"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.common.params import Params
from opendbc.car import structs
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.safety import ALTERNATIVE_EXPERIENCE
from opendbc.sunnypilot.car.hyundai.values import HyundaiFlagsSP, HyundaiSafetyFlagsSP
from opendbc.sunnypilot.car.tesla.values import MadsScreenButtonType, TeslaFlagsSP


MADS_NO_ACC_MAIN_BUTTON = ("rivian", "tesla")


class MadsSteeringModeOnBrake:
  REMAIN_ACTIVE = 0
  PAUSE = 1
  DISENGAGE = 2


class MadsLongitudinalAssistMode:
  OFF = 0
  FOLLOW = 1
  FULL = 2


MADS_LONGITUDINAL_ASSIST_MODES = (
  MadsLongitudinalAssistMode.OFF,
  MadsLongitudinalAssistMode.FOLLOW,
  MadsLongitudinalAssistMode.FULL,
)


def get_mads_limited_brands(CP: structs.CarParams, CP_SP: structs.CarParamsSP, params: Params) -> bool:
  if CP.brand == 'rivian':
    return True
  if CP.brand == 'tesla':
    if not CP_SP.flags & TeslaFlagsSP.HAS_VEHICLE_BUS:
      return True
    screen_button = int(params.get("TeslaMadsScreenButton", return_default=True))
    return screen_button == MadsScreenButtonType.OFF

  return False


def mads_follow_supported(CP: structs.CarParams) -> bool:
  """Brake-only MADS follow is initially scoped to Hyundai/Kia/Genesis CAN-FD with OP longitudinal."""
  return bool(CP.brand == "hyundai" and CP.flags & HyundaiFlags.CANFD and CP.openpilotLongitudinalControl)


def read_steering_mode_param(CP: structs.CarParams, CP_SP: structs.CarParamsSP, params: Params):
  if get_mads_limited_brands(CP, CP_SP, params):
    return MadsSteeringModeOnBrake.DISENGAGE

  return params.get("MadsSteeringMode", return_default=True)


def read_longitudinal_assist_mode(params: Params) -> int:
  try:
    mode = int(params.get("MadsLongitudinalAssistMode", return_default=True))
  except (TypeError, ValueError):
    return MadsLongitudinalAssistMode.OFF
  return mode if mode in MADS_LONGITUDINAL_ASSIST_MODES else MadsLongitudinalAssistMode.OFF


def set_alternative_experience(CP: structs.CarParams, CP_SP: structs.CarParamsSP, params: Params):
  enabled = params.get_bool("Mads")
  steering_mode = read_steering_mode_param(CP, CP_SP, params)
  longitudinal_assist_mode = read_longitudinal_assist_mode(params)

  if enabled:
    CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ENABLE_MADS

    if steering_mode == MadsSteeringModeOnBrake.DISENGAGE:
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.MADS_DISENGAGE_LATERAL_ON_BRAKE
    elif steering_mode == MadsSteeringModeOnBrake.PAUSE:
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.MADS_PAUSE_LATERAL_ON_BRAKE

    if longitudinal_assist_mode == MadsLongitudinalAssistMode.FOLLOW and mads_follow_supported(CP):
      CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.MADS_LONGITUDINAL_FOLLOW


def set_car_specific_params(CP: structs.CarParams, CP_SP: structs.CarParamsSP, params: Params):
  if CP.brand == "hyundai":
    # TODO-SP: This should be separated from MADS module for future implementations
    #          Use "HyundaiLongitudinalMainCruiseToggleable" param
    hyundai_cruise_main_toggleable = True
    if hyundai_cruise_main_toggleable:
      CP_SP.flags |= HyundaiFlagsSP.LONGITUDINAL_MAIN_CRUISE_TOGGLEABLE.value
      CP_SP.safetyParam |= HyundaiSafetyFlagsSP.LONG_MAIN_CRUISE_TOGGLEABLE

  # MADS Partial Support
  # MADS is currently partially supported for these platforms due to lack of consistent states to engage controls
  # Only MadsSteeringModeOnBrake.DISENGAGE is supported for these platforms
  # TODO-SP: To enable MADS full support for Rivian and most Tesla, identify consistent signals for MADS toggling
  mads_partial_support = get_mads_limited_brands(CP, CP_SP, params)
  if mads_partial_support:
    params.put("MadsSteeringMode", 2, block=True)
    params.put_bool("MadsUnifiedEngagementMode", True, block=True)

  # no ACC MAIN button for these brands
  if CP.brand in MADS_NO_ACC_MAIN_BUTTON:
    params.remove("MadsMainCruiseAllowed")
