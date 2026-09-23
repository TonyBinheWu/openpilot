"""Display helpers for the experimental HKG side-object visualization.

OEM front targets are accepted only from the stock ADRV 0x1EA path published by
corner_radard. Rear occupancy comes from the normal CarState blind-spot flags.
Legacy raw corner-radar targets remain available for diagnostics but no longer
define the OEM front/rear quadrant placement.
"""
import math
from dataclasses import dataclass

MAX_DISPLAY_AGE_SEC = 0.35
MAX_DISPLAY_DISTANCE_M = 120.0
MAX_SCENE_DISTANCE_M = 100.0
MAX_SCENE_ABS_LATERAL_M = 8.0
MAX_TARGETS_PER_GROUP = 3
OEM_ADRV_ADDRESS = 0x1EA
GROUP_POSITIONS = {0: (-1, 0), 1: (1, 0), 2: (-1, 1), 3: (1, 1)}


@dataclass(frozen=True)
class DisplayCornerTarget:
  sensor_group: int
  source_bus: int
  address: int
  track_id: int
  distance_m: float
  longitudinal_m: float
  lateral_m: float
  estimated_radial_speed_mps: float | None = None

  @property
  def oem_front(self) -> bool:
    return self.address == OEM_ADRV_ADDRESS and self.sensor_group in (0, 1)


def select_display_targets(targets, message_age: float = 0.0) -> list[DisplayCornerTarget]:
  if not math.isfinite(message_age) or not 0 <= message_age <= MAX_DISPLAY_AGE_SEC:
    return []

  groups: dict[int, list[DisplayCornerTarget]] = {group: [] for group in GROUP_POSITIONS}
  for target in targets:
    group, bus = int(target.sensorGroup), int(target.sourceBus)
    address = int(target.address)
    distance, age = float(target.distance), float(target.ageSec) + message_age
    longitudinal, lateral = float(target.longitudinal), float(target.lateral)
    radial_speed = None
    if bool(target.estimatedRadialSpeedValid):
      value = float(target.estimatedRadialSpeed)
      radial_speed = value if math.isfinite(value) else None

    if (group not in groups or not 0 <= bus < 128 or not target.candidateActive or
        not math.isfinite(distance) or not 0 < distance <= MAX_DISPLAY_DISTANCE_M or
        not math.isfinite(longitudinal) or not math.isfinite(lateral) or
        not math.isfinite(age) or not 0 <= age <= MAX_DISPLAY_AGE_SEC):
      continue

    groups[group].append(DisplayCornerTarget(
      sensor_group=group,
      source_bus=bus,
      address=address,
      track_id=int(target.trackId),
      distance_m=distance,
      longitudinal_m=longitudinal,
      lateral_m=lateral,
      estimated_radial_speed_mps=radial_speed,
    ))

  return [target for group in groups.values()
          for target in sorted(group, key=lambda t: (not t.oem_front, t.distance_m, t.source_bus, t.track_id))[:MAX_TARGETS_PER_GROUP]]


def scene_position(longitudinal_m: float, lateral_m: float, x: float, y: float,
                   width: float, height: float) -> tuple[float, float] | None:
  """Project a forward target into a stable camera-like HUD perspective."""
  if (not math.isfinite(longitudinal_m) or not math.isfinite(lateral_m) or
      not 2.5 <= longitudinal_m <= MAX_SCENE_DISTANCE_M or
      abs(lateral_m) > MAX_SCENE_ABS_LATERAL_M or width <= 0 or height <= 0):
    return None

  center_x = x + width * 0.5
  horizon_y = y + height * 0.40
  near_y = y + height * 0.90
  depth = math.sqrt(min(max(longitudinal_m / MAX_SCENE_DISTANCE_M, 0.0), 1.0))
  screen_y = near_y - depth * (near_y - horizon_y)

  near_scale = 92.0
  far_scale = 14.0
  scale_ratio = min(max((longitudinal_m - 2.5) / (MAX_SCENE_DISTANCE_M - 2.5), 0.0), 1.0)
  lateral_scale = near_scale + (far_scale - near_scale) * scale_ratio
  # Vehicle y is left-positive, screen x is right-positive.
  screen_x = center_x - lateral_m * lateral_scale

  margin = 24.0
  if not (x + margin <= screen_x <= x + width - margin and y + margin <= screen_y <= y + height - margin):
    return None
  return screen_x, screen_y


def rear_bsm_position(side: int, x: float, y: float, width: float, height: float) -> tuple[float, float] | None:
  """Fixed rear-left/rear-right quadrant positions for OEM BCW occupancy."""
  if side not in (-1, 1) or width <= 0 or height <= 0:
    return None
  return x + width * (0.31 if side < 0 else 0.69), y + height * 0.80


def estimate_corner_object_velocity(target: DisplayCornerTarget, ego_speed_mps: float) -> tuple[float, float, float] | None:
  """Return an approximate absolute velocity vector for legacy raw targets only."""
  radial_speed = target.estimated_radial_speed_mps
  if radial_speed is None or not math.isfinite(ego_speed_mps) or target.distance_m <= 0.1:
    return None

  ux = target.longitudinal_m / target.distance_m
  uy = target.lateral_m / target.distance_m
  rel_long = radial_speed * ux
  rel_lat = radial_speed * uy
  abs_long = ego_speed_mps + rel_long
  abs_lat = rel_lat
  speed = math.hypot(abs_long, abs_lat)
  if not all(math.isfinite(value) for value in (abs_long, abs_lat, speed)) or speed > 70.0:
    return None
  return abs_long, abs_lat, speed


def panel_bounds(x: float, width: float, side: int) -> tuple[float, float] | None:
  # Reserve speed and standard blind-spot widgets (+/-230 plus 20 clearance),
  # and mici edge blind-spot icons (148 including clearance).
  panel_width = min(150.0, width / 2 - 250 - 148)
  if panel_width < 72:
    return None
  center = x + width / 2
  return (center - 250 - panel_width if side < 0 else center + 250, panel_width)


def marker_position(target: DisplayCornerTarget, column: int, x: float, width: float) -> tuple[float, float] | None:
  side, rear = GROUP_POSITIONS[target.sensor_group]
  bounds = panel_bounds(x, width, side)
  if bounds is None:
    return None
  left, panel_width = bounds
  offset = 18 + 65 * min(target.distance_m / MAX_DISPLAY_DISTANCE_M, 1.0)
  return left + panel_width * (column + 0.5) / MAX_TARGETS_PER_GROUP, 180 + (offset if rear else -offset)
