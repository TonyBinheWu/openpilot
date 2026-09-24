"""Display-only blue path animation. Stop intent is not traffic-object classification."""
from dataclasses import dataclass
import math
import time

import numpy as np

MESSAGE_TIMEOUT = 0.5
STOP_SPEED = 0.5  # m/s, sustained in the model's future velocity trajectory


@dataclass(frozen=True)
class BluePathState:
  acceleration: float
  speed: float
  stopping: bool = False
  stop_distance: float | None = None


def predicted_stop(model) -> tuple[bool, float | None]:
  """Require a sustained future stop; slowing for a bend alone is not a stop.

  The model has no supported red/green-light or stop-sign classification output.
  Never infer those classes from confidence colors, braking, or greenLightAlert.
  """
  stopping = bool(model.action.shouldStop)
  x = np.asarray(model.position.x, dtype=float)
  t = np.asarray(model.velocity.t, dtype=float)
  v = np.asarray(model.velocity.x, dtype=float)
  position_t = np.asarray(model.position.t, dtype=float)
  if (len(x) < 3 or len(t) != len(x) or len(v) != len(x) or len(position_t) != len(x) or
      not all(np.isfinite(a).all() for a in (x, t, v, position_t)) or
      np.any(np.diff(x) < -0.1) or np.any(np.diff(t) <= 0) or not np.allclose(t, position_t)):
    return stopping, None

  for i in range(len(v) - 2):
    if t[i] >= 1.0 and x[i] >= 0 and np.all(np.abs(v[i:i + 3]) <= STOP_SPEED):
      return True, float(x[i])
  return stopping, None


def read_blue_path_state(sm, now: float, started_frame: int) -> BluePathState | None:
  # SubMaster defaults and data from the previous drive must never animate the path.
  for service in ('carState', 'modelV2'):
    if (not sm.valid[service] or not sm.alive[service] or sm.recv_frame[service] <= started_frame or
        not 0 <= now - sm.recv_time[service] <= MESSAGE_TIMEOUT):
      return None
  car_state = sm['carState']
  acceleration, speed = float(car_state.aEgo), float(car_state.vEgo)
  if not math.isfinite(acceleration) or not math.isfinite(speed):
    return None
  stopping, distance = predicted_stop(sm['modelV2'])
  return BluePathState(float(np.clip(acceleration, -4.0, 4.0)), max(0.0, speed), stopping, distance)


def ribbon_sections(points: np.ndarray):
  """Return near-to-far path edges indexed by normalized screen-space distance."""
  if points.ndim != 2 or points.shape[1] != 2 or len(points) < 4 or len(points) % 2 or not np.isfinite(points).all():
    return None
  count = len(points) // 2
  left, right = points[:count], points[count:][::-1]
  center = (left + right) * 0.5
  distances = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(center, axis=0), axis=1))]
  keep = np.r_[True, np.diff(distances) > 1e-3]
  distances, left, right = distances[keep], left[keep], right[keep]
  if len(distances) < 2 or distances[-1] < 2.0:
    return None
  return distances / distances[-1], left, right


def chevron_ribbons(points: np.ndarray, phase: float, direction: int):
  """Two-chain ribbons stay inside the projected path, including on curves."""
  sections = ribbon_sections(points)
  if sections is None:
    return []
  stations, left, right = sections

  def point(station, lateral):
    l = np.array([np.interp(station, stations, left[:, k]) for k in range(2)])
    r = np.array([np.interp(station, stations, right[:, k]) for k in range(2)])
    return l * (1 - lateral) + r * lateral

  ribbons = []
  for i in range(7):
    station = 0.07 + ((i + phase) % 7) / 7 * 0.80
    depth = 0.064 * (1 - station * 0.6)
    thickness = 0.026 * (1 - station * 0.6)
    # At steady speed the chevrons face forward but remain still.
    nose = station + (direction or 1) * depth
    back = [point(station, 0.07), point(nose, 0.5), point(station, 0.93)]
    front = [point(station + thickness, 0.93), point(nose + thickness, 0.5), point(station + thickness, 0.07)]
    # Match the path's winding so the GPU does not cull the chevron strips.
    ribbons.append((np.asarray(back + front, dtype=np.float32)[::-1], int(210 * (1 - station * 0.6))))
  return ribbons


class DynamicBluePath:
  def __init__(self):
    self.reset()

  def reset(self):
    self._last_time: float | None = None
    self._acceleration = 0.0
    self._phase = 0.0
    self._stop_since: float | None = None

  def draw(self, rect, path, sm, started_frame, project, z_offset, *, local_coordinates=False):
    now = time.monotonic()
    state = read_blue_path_state(sm, now, started_frame)
    if state is None:
      self.reset()
      return False
    return self.draw_state(rect, path, state, now, project, z_offset, local_coordinates=local_coordinates)

  def draw_state(self, rect, path, state, now, project, z_offset, *, local_coordinates=False):
    # Imports stay here so trajectory/geometry tests need no graphics context.
    import pyray as rl
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient
    from openpilot.system.ui.lib.multilang import tr
    from openpilot.system.ui.widgets.label import gui_label
    from openpilot.system.ui.lib.application import TextAlignment

    points = path.projected_points
    if ribbon_sections(points) is None:
      self.reset()
      return False
    offset = np.array([rect.x, rect.y], dtype=np.float32) if local_coordinates else np.zeros(2, dtype=np.float32)
    points = points + offset

    if self._last_time is None or not 0 <= now - self._last_time <= MESSAGE_TIMEOUT:
      self.reset()
      self._acceleration = state.acceleration
    dt = 0.0 if self._last_time is None else now - self._last_time
    self._last_time = now
    self._acceleration += (state.acceleration - self._acceleration) * (1 - math.exp(-dt / 0.2))
    direction = 0 if state.speed < 0.1 or abs(self._acceleration) < 0.15 else (1 if self._acceleration > 0 else -1)
    self._phase = (self._phase + direction * min(abs(self._acceleration), 3.0) * dt * 1.8) % 7

    gradient = Gradient(start=(0.0, 1.0), end=(0.0, 0.0),
                        colors=[rl.Color(25, 130, 255, 135), rl.Color(46, 155, 255, 90), rl.Color(65, 175, 255, 10)],
                        stops=[0.0, 0.55, 1.0])
    draw_polygon(rect, points, gradient=gradient)
    for ribbon, alpha in chevron_ribbons(points, self._phase, direction):
      draw_polygon(rect, ribbon, rl.Color(55, 170, 255, alpha))

    # The independent PredictedStopMarker owns stop-line persistence when enabled.
    # Keep the legacy transient marker only when that option is disabled.
    if state.stopping:
      if self._stop_since is None:
        self._stop_since = now
    else:
      self._stop_since = None
    if (not ui_state.predicted_stop_marker and self._stop_since is not None and
        now - self._stop_since >= 0.3):
      self._draw_stop_bar(rect, path, state.stop_distance, project, z_offset, offset)
      height = max(30.0, rect.height * 0.055)
      badge = rl.Rectangle(rect.x + rect.width * 0.30, rect.y + rect.height * 0.73, rect.width * 0.40, height)
      rl.draw_rectangle_rounded(badge, 0.35, 8, rl.Color(16, 29, 45, 225))
      gui_label(badge, tr("Model predicts stop"), font_size=int(height * 0.66),
                color=rl.Color(255, 207, 110, 255), alignment=TextAlignment.CENTER)
    return True

  @staticmethod
  def _draw_stop_bar(rect, path, distance, project, z_offset, offset):
    import pyray as rl

    raw = path.raw_points
    if distance is None or len(raw) < 2 or not np.isfinite(raw).all() or not raw[0, 0] <= distance <= raw[-1, 0]:
      return
    y, z = (float(np.interp(distance, raw[:, 0], raw[:, k])) for k in (1, 2))
    projected = [project(distance, y + side, z + z_offset) for side in (-0.7, 0.7)]
    if any(p is None for p in projected):
      return
    # A nearer lead or clipping can shorten the drawn path. Only mark within it.
    sections = ribbon_sections(path.projected_points)
    if sections is None:
      return
    _, left, right = sections
    center_y = (projected[0][1] + projected[1][1]) / 2
    if not min(left[:, 1].min(), right[:, 1].min()) <= center_y <= max(left[:, 1].max(), right[:, 1].max()):
      return
    a, b = (np.asarray(p) + offset for p in projected)
    if not all(rect.x <= p[0] <= rect.x + rect.width and rect.y <= p[1] <= rect.y + rect.height for p in (a, b)):
      return
    rl.draw_line_ex(rl.Vector2(*a), rl.Vector2(*b), max(3.0, rect.height * 0.006), rl.Color(255, 207, 110, 240))
