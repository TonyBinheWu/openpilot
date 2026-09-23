from __future__ import annotations

from opendbc.car.hyundai.values import CANFD_CAR, HyundaiFlags, HyundaiSafetyFlags
from opendbc.car.structs import CarParams


def supports_low_speed_torque(CP: CarParams | None) -> bool:
  """Return whether the detected vehicle is eligible for the HKG dynamic torque profile."""
  if CP is None:
    return False

  torque_steering = CP.steerControlType == CarParams.SteerControlType.torque or str(CP.steerControlType) == "torque"
  canfd_safety = bool(CP.safetyConfigs) and (
    CP.safetyConfigs[-1].safetyModel == CarParams.SafetyModel.hyundaiCanfd or
    str(CP.safetyConfigs[-1].safetyModel) == "hyundaiCanfd"
  )
  return bool(CP.brand == "hyundai" and CP.carFingerprint in CANFD_CAR and
              CP.flags & HyundaiFlags.CANFD and not CP.flags & (HyundaiFlags.ALT_LIMITS | HyundaiFlags.ALT_LIMITS_2) and
              torque_steering and not CP.dashcamOnly and canfd_safety)


def configure_low_speed_torque(CP: CarParams, enabled: bool) -> None:
  """Configure controller and Panda safety before CarInterface constructs CarController."""
  if CP.brand != "hyundai":
    return

  CP.flags &= ~HyundaiFlags.CANFD_DYNAMIC_TORQUE.value
  for config in CP.safetyConfigs:
    config.safetyParam &= ~HyundaiSafetyFlags.CANFD_DYNAMIC_TORQUE.value

  if enabled and supports_low_speed_torque(CP):
    CP.flags |= HyundaiFlags.CANFD_DYNAMIC_TORQUE.value
    CP.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CANFD_DYNAMIC_TORQUE.value
