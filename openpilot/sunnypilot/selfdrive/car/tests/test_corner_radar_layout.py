from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.sunnypilot.onroad.corner_radar_layout import (
  OEM_ADRV_ADDRESS,
  DisplayCornerTarget,
  estimate_corner_object_velocity,
  marker_position,
  panel_bounds,
  rear_bsm_position,
  scene_position,
  select_display_targets,
)


def target(**values):
  defaults = {
    "sensorGroup": 0,
    "sourceBus": 1,
    "address": 0x300,
    "trackId": 1,
    "distance": 10.0,
    "longitudinal": 9.5,
    "lateral": 1.0,
    "ageSec": 0.05,
    "candidateActive": True,
    "estimatedRadialSpeed": 0.0,
    "estimatedRadialSpeedValid": False,
  }
  return SimpleNamespace(**(defaults | values))


def display_target(group=0, distance=10.0, longitudinal=9.5, lateral=1.0,
                   radial_speed: float | None = None, address: int = 0x300):
  return DisplayCornerTarget(group, 1, address, 1, distance, longitudinal, lateral, radial_speed)


def test_multiple_nearest_targets_per_group():
  records = [
    target(sensorGroup=group, trackId=i, distance=i + 1, longitudinal=i + 1)
    for group in range(4) for i in range(8)
  ]
  chosen = select_display_targets(list(reversed(records)))
  assert len(chosen) == 12
  for group in range(4):
    assert [t.distance_m for t in chosen if t.sensor_group == group] == [1, 2, 3]


def test_oem_front_is_identified_and_preferred_in_front_group():
  records = [
    target(sensorGroup=0, address=0x300, trackId=1, distance=5.0),
    target(sensorGroup=0, address=OEM_ADRV_ADDRESS, trackId=2, distance=20.0),
    target(sensorGroup=0, address=0x301, trackId=3, distance=6.0),
    target(sensorGroup=0, address=0x302, trackId=4, distance=7.0),
  ]
  chosen = select_display_targets(records)
  assert len(chosen) == 3
  assert chosen[0].oem_front
  assert chosen[0].address == OEM_ADRV_ADDRESS


@pytest.mark.parametrize('values', [
  {"distance": 0}, {"distance": float('nan')}, {"distance": 121},
  {"longitudinal": float('nan')}, {"lateral": float('nan')},
  {"ageSec": -1}, {"ageSec": float('nan')}, {"ageSec": 0.36},
  {"sourceBus": 128}, {"sensorGroup": 4}, {"candidateActive": False},
])
def test_invalid_targets_are_hidden(values):
  assert select_display_targets([target(**values)]) == []


def test_radial_speed_is_only_exposed_when_valid_and_finite():
  chosen = select_display_targets([target(estimatedRadialSpeed=-2.5, estimatedRadialSpeedValid=True)])
  assert chosen[0].estimated_radial_speed_mps == pytest.approx(-2.5)

  chosen = select_display_targets([target(estimatedRadialSpeed=float('nan'), estimatedRadialSpeedValid=True)])
  assert chosen[0].estimated_radial_speed_mps is None


def test_frozen_message_ages_out_without_new_receive():
  assert select_display_targets([target()], 0.1)
  assert not select_display_targets([target()], 0.31)
  assert not select_display_targets([target()], -0.1)
  assert not select_display_targets([target()], float('nan'))
  assert not select_display_targets([])


@pytest.mark.parametrize('width', [1080, 1440, 1920, 2160])
def test_panels_do_not_overlap_speed_or_either_blindspot_layout(width):
  for side in (-1, 1):
    bounds = panel_bounds(30, width, side)
    assert bounds is not None
    x, panel_width = bounds
    center = 30 + width / 2
    assert x >= 30 + 148
    assert x + panel_width <= 30 + width - 148
    assert x + panel_width <= center - 250 if side < 0 else x >= center + 250
    for group in ((0, 2) if side < 0 else (1, 3)):
      for column in range(3):
        position = marker_position(display_target(group=group, distance=120, longitudinal=20), column, 30, width)
        assert position is not None
        px, py = position
        assert x + 12 <= px <= x + panel_width - 12
        assert 85 <= py <= 265


def test_small_viewport_hides_panels_instead_of_overlapping():
  assert panel_bounds(0, 800, -1) is None
  assert marker_position(display_target(), 0, 0, 800) is None


def test_distance_moves_markers_in_separate_front_rear_regions():
  for group in range(4):
    near_position = marker_position(display_target(group=group, distance=1), 0, 0, 2160)
    far_position = marker_position(display_target(group=group, distance=120), 0, 0, 2160)
    assert near_position is not None and far_position is not None
    near = near_position[1]
    far = far_position[1]
    assert far < near < 180 if group < 2 else 180 < near < far


def test_scene_projection_uses_vehicle_left_positive_coordinates():
  left = scene_position(30.0, 2.0, 0.0, 0.0, 1920.0, 1080.0)
  center = scene_position(30.0, 0.0, 0.0, 0.0, 1920.0, 1080.0)
  right = scene_position(30.0, -2.0, 0.0, 0.0, 1920.0, 1080.0)
  assert left is not None and center is not None and right is not None
  assert left[0] < center[0] < right[0]


def test_scene_projection_rejects_rear_and_extreme_side_targets():
  assert scene_position(-5.0, 1.0, 0.0, 0.0, 1920.0, 1080.0) is None
  assert scene_position(30.0, 9.0, 0.0, 0.0, 1920.0, 1080.0) is None
  assert scene_position(101.0, 0.0, 0.0, 0.0, 1920.0, 1080.0) is None


def test_rear_bsm_positions_are_separated_and_low_in_scene():
  left = rear_bsm_position(-1, 30.0, 30.0, 1860.0, 1020.0)
  right = rear_bsm_position(1, 30.0, 30.0, 1860.0, 1020.0)
  assert left is not None and right is not None
  assert left[0] < 960 < right[0]
  assert left[1] == pytest.approx(right[1])
  assert left[1] > 700


def test_corner_speed_estimate_is_marked_as_approximate_input():
  tracked = display_target(distance=20.0, longitudinal=20.0, lateral=0.0, radial_speed=-2.0)
  velocity = estimate_corner_object_velocity(tracked, ego_speed_mps=12.0)
  assert velocity is not None
  abs_long, abs_lat, speed = velocity
  assert abs_long == pytest.approx(10.0)
  assert abs_lat == pytest.approx(0.0)
  assert speed == pytest.approx(10.0)


def test_corner_speed_estimate_requires_valid_range_rate():
  assert estimate_corner_object_velocity(display_target(radial_speed=None), 12.0) is None
