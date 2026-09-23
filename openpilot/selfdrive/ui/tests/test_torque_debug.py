import unittest
from types import SimpleNamespace as NS

from openpilot.selfdrive.ui.sunnypilot.onroad.torque_debug import SERVICES, TorqueDebugState


class FakeSM(dict):
  def __init__(self, saturated=False, kind='torqueState'):
    super().__init__({
      'carState': NS(vEgo=12.0, steeringAngleDeg=-35.0, steeringPressed=False),
      'carControl': NS(latActive=True, actuators=NS(torque=-1.0)),
      'carOutput': NS(actuatorsOutput=NS(torque=-0.8, torqueOutputCan=-240.0)),
      'controlsState': NS(lateralControlState=NS(which=lambda: kind,
                                                **{kind: NS(active=True, saturated=saturated)})),
    })
    self.valid = dict.fromkeys(SERVICES, True)
    self.alive = dict.fromkeys(SERVICES, True)
    self.recv_frame = dict.fromkeys(SERVICES, 20)
    self.logMonoTime = dict.fromkeys(SERVICES, 10_000_000_000)

  def advance(self, seconds):
    self.logMonoTime = {s: t + int(seconds * 1e9) for s, t in self.logMonoTime.items()}


class TestTorqueDebug(unittest.TestCase):
  def test_signed_commands_and_units(self):
    state, sm = TorqueDebugState(), FakeSM(True)
    state.update(sm, 10, True)
    self.assertEqual(state.current.requested, -1.0)
    self.assertIn('SENT -80.0', state.lines(True)[1])
    self.assertIn('CAN -240', state.lines(True)[1])
    self.assertIn('43.2 km/h', state.lines(True)[3])
    self.assertIn('26.8 mph', state.lines(False)[3])

  def test_clipping_does_not_imply_saturation(self):
    state = TorqueDebugState()
    state.update(FakeSM(), 10, True)
    self.assertIsNone(state.last_saturation)

  def test_retains_last_observed_saturation_not_peak(self):
    state, sm = TorqueDebugState(), FakeSM(True)
    state.update(sm, 10, True)
    sm.advance(1)
    sm['carOutput'].actuatorsOutput.torque = -0.7
    state.update(sm, 10, True)
    sm.advance(5)
    sm['controlsState'].lateralControlState.torqueState.saturated = False
    state.update(sm, 10, True)
    self.assertEqual(state.last_saturation.sent, -0.7)
    self.assertIn('5s ago', state.lines(True)[2])

  def test_inactive_or_override_does_not_record(self):
    for field in ('latActive', 'steeringPressed', 'active'):
      with self.subTest(field=field):
        state, sm = TorqueDebugState(), FakeSM(True)
        if field == 'latActive':
          sm['carControl'].latActive = False
        elif field == 'steeringPressed':
          sm['carState'].steeringPressed = True
        else:
          sm['controlsState'].lateralControlState.torqueState.active = False
        state.update(sm, 10, True)
        self.assertIsNone(state.last_saturation)

  def test_bad_streams_hide_live_data_preserve_history(self):
    for service in SERVICES:
      for flag, value in (('valid', False), ('alive', False), ('recv_frame', 9), ('logMonoTime', 1)):
        with self.subTest(service=service, flag=flag):
          state, sm = TorqueDebugState(), FakeSM(True)
          state.update(sm, 10, True)
          previous = state.last_saturation
          getattr(sm, flag)[service] = value
          state.update(sm, 10, True)
          self.assertIsNone(state.current)
          self.assertEqual(state.last_saturation, previous)
          self.assertIn('age unavailable', state.lines(True)[2])

  def test_nonfinite_data_rejected(self):
    for bad in (float('nan'), float('inf'), -float('inf')):
      state, sm = TorqueDebugState(), FakeSM(True)
      sm['carOutput'].actuatorsOutput.torque = bad
      state.update(sm, 10, True)
      self.assertIsNone(state.current)
      self.assertIsNone(state.last_saturation)

  def test_off_new_drive_and_replay_seek_reset_history(self):
    for reset in ('off', 'drive', 'seek'):
      with self.subTest(reset=reset):
        state, sm = TorqueDebugState(), FakeSM(True)
        state.update(sm, 10, True)
        sm['controlsState'].lateralControlState.torqueState.saturated = False
        if reset == 'seek':
          sm.advance(-1)
        state.update(sm, 11 if reset == 'drive' else 10, reset != 'off')
        self.assertIsNone(state.last_saturation)

  def test_only_torque_and_pid_supported(self):
    for kind in ('angleState', 'curvatureState', 'debugState', 'pidState'):
      with self.subTest(kind=kind):
        state = TorqueDebugState()
        state.update(FakeSM(True, kind), 10, True)
        self.assertEqual(state.current is not None, kind == 'pidState')


if __name__ == '__main__':
  unittest.main()
