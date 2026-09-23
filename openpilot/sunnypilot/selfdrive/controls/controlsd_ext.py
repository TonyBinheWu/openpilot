"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import time

import openpilot.cereal.messaging as messaging
from openpilot.cereal import log, custom

from opendbc.car import structs
from opendbc.car.hyundai.values import HyundaiFlags
from openpilot.common.params import Params
from openpilot.common.constants import CV
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot import PARAMS_UPDATE_PERIOD
from openpilot.sunnypilot.livedelay.helpers import get_lat_delay
from openpilot.sunnypilot.modeld_v2.modeld_base import ModelStateBase
from openpilot.sunnypilot.selfdrive.controls.lib.blinker_pause_lateral import BlinkerPauseLateral
from openpilot.sunnypilot.selfdrive.controls.lib.latcontrol_torque_v0 import LatControlTorque as LatControlTorqueV0
from openpilot.selfdrive.controls.lib.desire_helper import CREEP_LANE_CHANGE_SPEED_MAX, creep_lane_change_context_safe

CREEP_LANE_CHANGE_ACTIVE_SPEED_MAX = 30. * CV.KPH_TO_MS


class ControlsExt(ModelStateBase):
  def __init__(self, CP: structs.CarParams, params: Params):
    ModelStateBase.__init__(self)
    self.CP = CP
    self.params = params
    self._param_update_time: float = 0.0
    self.blinker_pause_lateral = BlinkerPauseLateral()

    cloudlog.info("controlsd_ext is waiting for CarParamsSP")
    self.CP_SP = messaging.log_from_bytes(params.get("CarParamsSP", block=True), custom.CarParamsSP)
    cloudlog.info("controlsd_ext got CarParamsSP")

    self.sm_services_ext = ['radarState', 'selfdriveStateSP', 'modelDataV2SP']
    self.pm_services_ext = ['carControlSP']

  def initialize_lateral_control(self, lac, CI, dt):
    enforce_torque_control = self.params.get_bool("EnforceTorqueControl")
    torque_versions = self.params.get("TorqueControlTune")
    if not enforce_torque_control:
      if self.CP.lateralTuning.which() == 'torque':
        return LatControlTorqueV0(self.CP, self.CP_SP, CI, dt)  # FIXME-SP: revert when upstream fixes tuning issues with v1
      return lac

    if torque_versions == 0.0:  # v0
      return LatControlTorqueV0(self.CP, self.CP_SP, CI, dt)
    else:
      return lac

  def get_params_sp(self, sm: messaging.SubMaster) -> None:
    if time.monotonic() - self._param_update_time > PARAMS_UPDATE_PERIOD:
      self.blinker_pause_lateral.get_params()

      if self.CP.lateralTuning.which() == 'torque':
        self.lat_delay = get_lat_delay(self.params, sm["lateralDelay"].lateralDelay)

      self._param_update_time = time.monotonic()

  def get_lat_active(self, sm: messaging.SubMaster) -> bool:
    pause_for_blinker = self.blinker_pause_lateral.update(sm['carState'])
    creep_candidate = self.creep_lane_change_candidate(self.CP, sm['carState'], sm['modelV2'], sm.valid['modelV2'])
    creep_active = self.creep_lane_change_active(self.CP, sm['carState'], sm['modelV2'], sm.valid['modelV2'],
                                                sm['modelDataV2SP'].creepLaneChangeActive, sm.valid['modelDataV2SP'])
    if pause_for_blinker and not (creep_candidate or creep_active):
      return False

    ss_sp = sm['selfdriveStateSP']
    if ss_sp.mads.available:
      return bool(ss_sp.mads.active)

    # MADS not available, use stock state to engage
    return bool(sm['selfdriveState'].active)

  @staticmethod
  def get_lead_data(_lead, src: log.RadarState.LeadData) -> None:
    _lead.dRel = src.dRel
    _lead.yRel = src.yRel
    _lead.vRel = src.vRel
    _lead.aRel = src.deprecated.aRel
    _lead.vLead = src.vLead
    _lead.dPath = src.deprecated.dPath
    _lead.vLat = src.deprecated.vLat
    _lead.vLeadK = src.vLeadK
    _lead.aLeadK = src.aLeadK
    _lead.fcw = src.deprecated.fcw
    _lead.status = src.present
    _lead.aLeadTau = src.aLeadTau
    _lead.modelProb = src.modelProb
    _lead.radar = src.radar
    _lead.radarTrackId = src.radarTrackId

  @staticmethod
  def creep_lane_change_candidate(CP: structs.CarParams, CS, model_v2, model_valid: bool,
                                  speed_max: float = CREEP_LANE_CHANGE_SPEED_MAX) -> bool:
    if not (CP.flags & HyundaiFlags.CANFD_CREEP_LANE_CHANGE and model_valid and CS.canValid):
      return False
    if not 0. <= CS.vEgoRaw <= speed_max:
      return False

    one_blinker = CS.leftBlinker != CS.rightBlinker
    signaled_blindspot = (CS.leftBlinker and CS.leftBlindspot) or (CS.rightBlinker and CS.rightBlindspot)
    if not one_blinker or signaled_blindspot:
      return False

    if len(model_v2.leadsV3) == 0:
      return False
    lead = model_v2.leadsV3[0]
    lead_distance = float(lead.x[0]) if len(lead.x) else float("nan")
    return creep_lane_change_context_safe(True, float(lead.prob), lead_distance)

  @classmethod
  def creep_lane_change_active(cls, CP: structs.CarParams, CS, model_v2, model_valid: bool,
                               request_active: bool, request_valid: bool) -> bool:
    if not (request_valid and request_active and not CS.brakePressed and
            cls.creep_lane_change_candidate(CP, CS, model_v2, model_valid, CREEP_LANE_CHANGE_ACTIVE_SPEED_MAX)):
      return False
    return model_v2.meta.laneChangeState == log.LaneChangeState.laneChangeStarting

  def state_control_ext(self, sm: messaging.SubMaster) -> custom.CarControlSP:
    CC_SP = custom.CarControlSP.new_message()
    CC_SP.creepLaneChangeActive = self.creep_lane_change_active(
      self.CP, sm['carState'], sm['modelV2'], sm.valid['modelV2'],
      sm['modelDataV2SP'].creepLaneChangeActive, sm.valid['modelDataV2SP'])

    self.get_lead_data(CC_SP.leadOne, sm['radarState'].leadOne)
    self.get_lead_data(CC_SP.leadTwo, sm['radarState'].leadTwo)

    # MADS state
    mads_src = sm['selfdriveStateSP'].mads
    CC_SP.mads.state = mads_src.state
    CC_SP.mads.enabled = mads_src.enabled
    CC_SP.mads.active = mads_src.active
    CC_SP.mads.available = mads_src.available

    # ICBM state
    icbm_src = sm['selfdriveStateSP'].intelligentCruiseButtonManagement
    CC_SP.intelligentCruiseButtonManagement.state = icbm_src.state
    CC_SP.intelligentCruiseButtonManagement.sendButton = icbm_src.sendButton
    CC_SP.intelligentCruiseButtonManagement.vTarget = icbm_src.vTarget

    return CC_SP

  @staticmethod
  def publish_ext(CC_SP: custom.CarControlSP, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    cc_sp_send = messaging.new_message('carControlSP')
    cc_sp_send.valid = sm['carState'].canValid
    cc_sp_send.carControlSP = CC_SP

    pm.send('carControlSP', cc_sp_send)

  def run_ext(self, sm: messaging.SubMaster, pm: messaging.PubMaster) -> None:
    CC_SP = self.state_control_ext(sm)
    self.publish_ext(CC_SP, sm, pm)
