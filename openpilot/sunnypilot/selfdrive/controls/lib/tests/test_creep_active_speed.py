"""Dependency-light tests of the production controlsd entry/active speed gates."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest


def load_controls():
  path = Path(__file__).resolve().parents[2] / 'controlsd_ext.py'
  tree = ast.parse(path.read_text())
  cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ControlsExt')
  cls.bases = []
  cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in
              ('get_lat_active', 'creep_lane_change_candidate', 'creep_lane_change_active')]
  constants = [n for n in tree.body if isinstance(n, ast.Assign) and
               any(isinstance(t, ast.Name) and t.id == 'CREEP_LANE_CHANGE_ACTIVE_SPEED_MAX' for t in n.targets)]
  scope = {'CREEP_LANE_CHANGE_SPEED_MAX': 5 / 3.6, 'CV': NS(KPH_TO_MS=1 / 3.6),
           'HyundaiFlags': NS(CANFD_CREEP_LANE_CHANGE=1 << 28),
           'log': NS(LaneChangeState=NS(laneChangeStarting=1)),
           'creep_lane_change_context_safe': lambda valid, prob, distance: valid and (prob < 0.5 or distance >= 5)}
  future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
  module = ast.fix_missing_locations(ast.Module(body=[future, *constants, cls], type_ignores=[]))
  exec(compile(module, str(path), 'exec'), scope)
  return scope['ControlsExt']


class TestCreepActiveSpeed(unittest.TestCase):
  def setUp(self):
    self.controls = load_controls()
    self.cp = NS(flags=1 << 28)
    self.cs = NS(vEgoRaw=0., canValid=True, leftBlinker=True, rightBlinker=False,
                 leftBlindspot=False, rightBlindspot=False, brakePressed=False)
    self.model = NS(leadsV3=[NS(prob=0.9, x=[10.])], meta=NS(laneChangeState=1))

  def active(self):
    return self.controls.creep_lane_change_active(self.cp, self.cs, self.model, True, True, True)

  def test_new_entry_remains_limited_to_five(self):
    for kph, allowed in ((0, True), (5, True), (5.1, False), (20, False), (30, False)):
      self.cs.vEgoRaw = kph / 3.6
      self.assertEqual(self.controls.creep_lane_change_candidate(self.cp, self.cs, self.model, True), allowed)

  def test_active_maneuver_can_follow_taper_until_thirty(self):
    for kph, allowed in ((-1, False), (5, True), (20, True), (21, True), (25.5, True), (30, True), (30.1, False)):
      self.cs.vEgoRaw = kph / 3.6
      self.assertEqual(self.active(), allowed)

  def test_active_still_requires_brake_signal_blindspot_and_perception_checks(self):
    self.cs.vEgoRaw = 20 / 3.6
    for name in ('brakePressed', 'leftBlindspot', 'rightBlinker'):
      setattr(self.cs, name, True)
      self.assertFalse(self.active())
      setattr(self.cs, name, False)
    self.model.leadsV3[0].x = [4.9]
    self.assertFalse(self.active())
    self.model.leadsV3[0].x = [10.]
    for args in ((False, True, True), (True, False, True), (True, True, False)):
      self.assertFalse(self.controls.creep_lane_change_active(self.cp, self.cs, self.model, *args))
    self.model.meta.laneChangeState = 0
    self.assertFalse(self.active())

  def test_blinker_pause_exception_requires_active_request_above_five(self):
    self.cs.vEgoRaw = 20 / 3.6
    obj = self.controls()
    obj.CP = self.cp
    obj.blinker_pause_lateral = NS(update=lambda cs: True)
    class SM(dict):
      valid = {'modelV2': True, 'modelDataV2SP': True}
    sm = SM(carState=self.cs, modelV2=self.model, modelDataV2SP=NS(creepLaneChangeActive=True),
            selfdriveStateSP=NS(mads=NS(available=False)), selfdriveState=NS(active=True))
    self.assertTrue(obj.get_lat_active(sm))
    sm['modelDataV2SP'].creepLaneChangeActive = False
    self.assertFalse(obj.get_lat_active(sm))


if __name__ == '__main__':
  unittest.main()
