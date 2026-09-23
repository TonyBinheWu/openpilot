"""OEM-prioritized HKG side-object visualization; display only."""
import math
import time

import pyray as rl

from openpilot.common.constants import CV
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.onroad.corner_radar_layout import (
  DisplayCornerTarget,
  rear_bsm_position,
  scene_position,
  select_display_targets,
)
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.text_measure import measure_text_cached

MOTION_HORIZON_SEC = 0.60
CENTER_MAX_DISTANCE_M = 100.0
SCENE_MARKER_MIN_SIZE = 28.0
SCENE_MARKER_MAX_SIZE = 58.0


class CornerRadarIndicators:
  def __init__(self):
    self._font = gui_app.font(FontWeight.SEMI_BOLD)

  def update(self) -> None:
    # Select at render time so a frozen message cannot leave stale objects.
    pass

  @staticmethod
  def _speed_conversion() -> float:
    return CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH

  @staticmethod
  def _marker_size(distance_m: float) -> float:
    scale = 1.0 - min(max(distance_m / CENTER_MAX_DISTANCE_M, 0.0), 1.0)
    return SCENE_MARKER_MIN_SIZE + (SCENE_MARKER_MAX_SIZE - SCENE_MARKER_MIN_SIZE) * scale

  @staticmethod
  def _motion_color(speed_mps: float, ego_speed_mps: float) -> rl.Color:
    if speed_mps < max(ego_speed_mps - 1.0, 0.0):
      return rl.Color(255, 82, 82, 230)
    if speed_mps > ego_speed_mps + 1.0:
      return rl.Color(76, 220, 120, 230)
    return rl.Color(245, 245, 245, 220)

  def _draw_speed_text(self, x: float, y: float, speed_mps: float, color: rl.Color) -> None:
    if not math.isfinite(speed_mps) or speed_mps < 0.0:
      return
    label = str(int(round(speed_mps * self._speed_conversion())))
    font_size = 31
    measured = measure_text_cached(self._font, label, font_size)
    pad_x, pad_y = 9.0, 4.0
    bg = rl.Rectangle(x - measured.x / 2 - pad_x, y - measured.y / 2 - pad_y,
                      measured.x + pad_x * 2, measured.y + pad_y * 2)
    rl.draw_rectangle_rounded(bg, 0.25, 6, rl.Color(0, 0, 0, 175))
    rl.draw_rectangle_rounded_lines_ex(bg, 0.25, 6, 2.0, color)
    rl.draw_text_ex(self._font, label, rl.Vector2(x - measured.x / 2, y - measured.y / 2), font_size, 0, rl.WHITE)

  def _draw_tag(self, x: float, y: float, label: str, color: rl.Color) -> None:
    font_size = 24
    measured = measure_text_cached(self._font, label, font_size)
    pad_x, pad_y = 7.0, 3.0
    box = rl.Rectangle(x - measured.x / 2 - pad_x, y - measured.y / 2 - pad_y,
                       measured.x + pad_x * 2, measured.y + pad_y * 2)
    rl.draw_rectangle_rounded(box, 0.25, 6, rl.Color(0, 0, 0, 165))
    rl.draw_rectangle_rounded_lines_ex(box, 0.25, 6, 2.0, color)
    rl.draw_text_ex(self._font, label, rl.Vector2(x - measured.x / 2, y - measured.y / 2), font_size, 0, rl.WHITE)

  def _draw_scene_marker(self, rect: rl.Rectangle, longitudinal_m: float, lateral_m: float,
                         color: rl.Color, label: str, speed_mps: float | None = None,
                         future_longitudinal_m: float | None = None,
                         future_lateral_m: float | None = None,
                         ego_speed_mps: float = 0.0) -> tuple[float, float] | None:
    position = scene_position(longitudinal_m, lateral_m, rect.x, rect.y, rect.width, rect.height)
    if position is None:
      return None

    x, y = position
    distance_m = math.hypot(longitudinal_m, lateral_m)
    size = self._marker_size(distance_m)
    box = rl.Rectangle(x - size * 0.55, y - size * 0.72, size * 1.10, size * 0.82)
    rl.draw_rectangle_rounded(box, 0.22, 6, rl.Color(0, 0, 0, 55))
    rl.draw_rectangle_rounded_lines_ex(box, 0.22, 6, 3.0, color)
    rl.draw_circle_v(rl.Vector2(x, y), 5.0, color)

    if (future_longitudinal_m is not None and future_lateral_m is not None and
        math.isfinite(future_longitudinal_m) and math.isfinite(future_lateral_m)):
      future = scene_position(future_longitudinal_m, future_lateral_m, rect.x, rect.y, rect.width, rect.height)
      if future is not None:
        line_color = self._motion_color(speed_mps if speed_mps is not None else ego_speed_mps, ego_speed_mps)
        rl.draw_line_ex(rl.Vector2(x, y), rl.Vector2(*future), 4.0, line_color)
        rl.draw_circle_v(rl.Vector2(*future), 7.0, line_color)

    self._draw_tag(x, y + size * 0.62, label, color)
    if speed_mps is not None:
      self._draw_speed_text(x, y - size - 10.0, speed_mps, color)
    return position

  def _render_center_radar(self, rect: rl.Rectangle, sm) -> list[tuple[float, float]]:
    service = "radarState"
    if (not sm.valid[service] or not sm.alive[service] or
        sm.recv_frame[service] <= ui_state.started_frame):
      return []

    radar_state = sm[service]
    ego_speed = float(sm["carState"].vEgo) if sm.valid["carState"] else 0.0
    occupied: list[tuple[float, float]] = []
    center_color = rl.Color(255, 175, 3, 240)

    for lead in (radar_state.leadOne, radar_state.leadTwo):
      if not bool(getattr(lead, "present", False)) or not bool(getattr(lead, "radar", False)):
        continue
      d_rel = float(lead.dRel)
      y_rel = float(lead.yRel)
      speed = float(lead.vLeadK)
      if (not math.isfinite(d_rel) or not math.isfinite(y_rel) or not math.isfinite(speed) or
          not 2.5 <= d_rel <= CENTER_MAX_DISTANCE_M):
        continue

      future_d = d_rel + max(speed, 0.0) * MOTION_HORIZON_SEC
      position = self._draw_scene_marker(
        rect, d_rel, y_rel, center_color, "F", speed,
        future_longitudinal_m=future_d,
        future_lateral_m=y_rel,
        ego_speed_mps=ego_speed,
      )
      if position is not None:
        occupied.append((d_rel, y_rel))
    return occupied

  @staticmethod
  def _duplicates_center(target: DisplayCornerTarget, center_objects: list[tuple[float, float]]) -> bool:
    return any(abs(target.longitudinal_m - d_rel) < 4.0 and abs(target.lateral_m - y_rel) < 1.5
               for d_rel, y_rel in center_objects)

  def _render_oem_front(self, rect: rl.Rectangle, targets: list[DisplayCornerTarget],
                        center_objects: list[tuple[float, float]]) -> None:
    color = rl.Color(255, 215, 0, 235)
    for target in targets:
      if not target.oem_front or self._duplicates_center(target, center_objects):
        continue
      label = "FL" if target.sensor_group == 0 else "FR"
      self._draw_scene_marker(rect, target.longitudinal_m, target.lateral_m, color, label)

  def _render_oem_rear_bsm(self, rect: rl.Rectangle, sm) -> None:
    if not sm.valid["carState"] or sm.recv_frame["carState"] <= ui_state.started_frame:
      return
    car_state = sm["carState"]
    color = rl.Color(255, 145, 40, 245)
    for side, active, label in (
      (-1, bool(car_state.leftBlindspot), "RL"),
      (1, bool(car_state.rightBlindspot), "RR"),
    ):
      if not active:
        continue
      position = rear_bsm_position(side, rect.x, rect.y, rect.width, rect.height)
      if position is None:
        continue
      x, y = position
      size = 52.0
      box = rl.Rectangle(x - size * 0.60, y - size * 0.70, size * 1.20, size * 0.90)
      rl.draw_rectangle_rounded(box, 0.22, 6, rl.Color(0, 0, 0, 70))
      rl.draw_rectangle_rounded_lines_ex(box, 0.22, 6, 4.0, color)
      rl.draw_circle_v(rl.Vector2(x, y), 6.0, color)
      self._draw_tag(x, y + size * 0.70, label, color)

  def render(self, rect: rl.Rectangle) -> None:
    if not ui_state.hkg_corner_radar:
      return

    sm = ui_state.sm
    center_objects = self._render_center_radar(rect, sm)

    service = "cornerRadarStateSP"
    targets: list[DisplayCornerTarget] = []
    if (sm.valid[service] and sm.alive[service] and
        sm.recv_frame[service] > ui_state.started_frame):
      targets = select_display_targets(sm[service].targets, time.monotonic() - sm.recv_time[service])

    self._render_oem_front(rect, targets, center_objects)
    self._render_oem_rear_bsm(rect, sm)
