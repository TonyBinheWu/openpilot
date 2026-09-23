import unittest
from types import SimpleNamespace as NS

import numpy as np

from openpilot.selfdrive.ui.sunnypilot.onroad.blue_path import predicted_stop, read_blue_path_state, chevron_ribbons, ribbon_sections


def model(velocity=(10, 9, 8, 7, 6, 5), should_stop=False):
  t = np.arange(len(velocity)) * 0.5
  x = np.cumsum(np.asarray(velocity) * 0.5)
  return NS(position=NS(x=x, t=t), velocity=NS(x=velocity, t=t), action=NS(shouldStop=should_stop))


class Messages(dict):
  def __init__(self):
    super().__init__(carState=NS(aEgo=-1.2, vEgo=8.0), modelV2=model())
    self.valid = dict.fromkeys(self, True)
    self.alive = dict.fromkeys(self, True)
    self.recv_frame = dict.fromkeys(self, 20)
    self.recv_time = dict.fromkeys(self, 10.0)


class TestStopIntent(unittest.TestCase):
  def test_slowing_for_bend_does_not_claim_stop(self):
    self.assertEqual(predicted_stop(model()), (False, None))

  def test_sustained_future_stop_has_predicted_position(self):
    m = model((8, 5, 0.4, 0.2, 0.1, 0))
    self.assertEqual(predicted_stop(m), (True, m.position.x[2]))

  def test_one_low_velocity_sample_is_not_stop(self):
    self.assertEqual(predicted_stop(model((8, 5, 0, 4, 3, 2))), (False, None))

  def test_launch_from_standstill_does_not_claim_stop(self):
    self.assertEqual(predicted_stop(model((0, 0, 0.1, 1, 3, 5))), (False, None))

  def test_action_can_hold_stop_without_position(self):
    self.assertEqual(predicted_stop(model((), should_stop=True)), (True, None))

  def test_bad_or_unaligned_trajectory_does_not_invent_position(self):
    for mutate in (lambda m: setattr(m.position, 'x', [0, 1]),
                   lambda m: setattr(m.velocity, 'x', [5, 3, float('nan'), 0, 0, 0]),
                   lambda m: setattr(m.velocity, 't', [0, 0, 0, 0, 0, 0]),
                   lambda m: setattr(m.position, 't', m.position.t + 1)):
      m = model((8, 5, 0.4, 0.2, 0.1, 0))
      mutate(m)
      self.assertEqual(predicted_stop(m), (False, None))

  def test_model_confidence_colors_are_not_traffic_lights(self):
    for confidence in ('red', 'yellow', 'green'):
      m = model()
      m.confidence = confidence
      self.assertEqual(predicted_stop(m), (False, None))


class TestLiveInputs(unittest.TestCase):
  def test_acceleration_is_measured_not_model_request(self):
    sm = Messages()
    sm['modelV2'].action.desiredAcceleration = 2.0
    state = read_blue_path_state(sm, 10.1, 5)
    self.assertAlmostEqual(state.acceleration, -1.2)
    self.assertFalse(state.stopping)

  def test_stale_invalid_or_previous_drive_data_is_hidden(self):
    for service in ('carState', 'modelV2'):
      for field, value in (('valid', False), ('alive', False), ('recv_frame', 5), ('recv_time', 9.0), ('recv_time', 11.0)):
        with self.subTest(service=service, field=field, value=value):
          sm = Messages()
          getattr(sm, field)[service] = value
          self.assertIsNone(read_blue_path_state(sm, 10.1, 5))

  def test_nonfinite_vehicle_data_is_hidden(self):
    for field in ('aEgo', 'vEgo'):
      sm = Messages()
      setattr(sm['carState'], field, float('nan'))
      self.assertIsNone(read_blue_path_state(sm, 10.1, 5))


class TestBluePathGeometry(unittest.TestCase):
  def setUp(self):
    self.path = np.array([[100, 500], [170, 300], [235, 150], [260, 150], [240, 300], [300, 500]], dtype=np.float32)

  def test_chevrons_follow_offset_viewport_on_both_displays(self):
    original = chevron_ribbons(self.path, 0.25, 1)
    offset = np.array([310, 70])
    translated = chevron_ribbons(self.path + offset, 0.25, 1)
    self.assertEqual(len(original), 7)
    for (a, alpha), (b, other_alpha) in zip(original, translated, strict=True):
      np.testing.assert_allclose(a + offset, b, atol=0.001)
      self.assertEqual(alpha, other_alpha)

  def test_reverse_direction_changes_chevron_orientation(self):
    forward = chevron_ribbons(self.path, 0.2, 1)[0][0]
    reverse = chevron_ribbons(self.path, 0.2, -1)[0][0]
    self.assertLess(forward[1, 1], reverse[1, 1])

  def test_degenerate_paths_are_skipped(self):
    for points in (np.empty((0, 2)), np.ones((6, 2)), self.path[:3], self.path * float('nan')):
      self.assertIsNone(ribbon_sections(points))
      self.assertEqual(chevron_ribbons(points, 0, 1), [])


if __name__ == '__main__':
  unittest.main()
