import math

from openpilot.cereal import log, custom
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.sunnypilot.selfdrive.controls.lib.auto_lane_change import AutoLaneChangeController, AutoLaneChangeMode
from openpilot.sunnypilot.selfdrive.controls.lib.lane_turn_desire import LaneTurnController

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection
TurnDirection = custom.ModelDataV2SP.TurnDirection

LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.
LANE_CHANGE_START_TIME = 0.5

CREEP_LANE_CHANGE_SPEED_MAX = 5. * CV.KPH_TO_MS
CREEP_LANE_CHANGE_LEAD_PROB = 0.5
CREEP_LANE_CHANGE_MIN_LEAD_DISTANCE = 5.0

TURN_DESIRES = {
  TurnDirection.none: log.Desire.none,
  TurnDirection.turnLeft: log.Desire.turnLeft,
  TurnDirection.turnRight: log.Desire.turnRight,
}


def creep_lane_change_context_safe(model_valid: bool, lead_prob: float, lead_distance: float) -> bool:
  if not model_valid:
    return False
  if lead_prob < CREEP_LANE_CHANGE_LEAD_PROB:
    return True
  return math.isfinite(lead_distance) and lead_distance >= CREEP_LANE_CHANGE_MIN_LEAD_DISTANCE


class DesireHelper:
  def __init__(self, creep_lane_change_enabled: bool = False):
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.prev_one_blinker = False
    self.desire = log.Desire.none
    self.creep_lane_change = False
    self.alc = AutoLaneChangeController(self, creep_lane_change_enabled)
    self.lane_turn_controller = LaneTurnController(self)
    self.lane_turn_direction = TurnDirection.none

  @staticmethod
  def get_lane_change_direction(CS):
    return LaneChangeDirection.left if CS.leftBlinker else LaneChangeDirection.right

  def reset_lane_change(self) -> None:
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.creep_lane_change = False

  def blindspot_detected(self, carstate, left_edge_detected: bool, right_edge_detected: bool) -> bool:
    return (((carstate.leftBlindspot or left_edge_detected) and self.lane_change_direction == LaneChangeDirection.left) or
            ((carstate.rightBlindspot or right_edge_detected) and self.lane_change_direction == LaneChangeDirection.right))

  def update(self, carstate, lateral_active, lane_change_prob, left_edge_detected=False, right_edge_detected=False,
             model_valid=True, lead_prob=0.0, lead_distance=math.inf):
    self.alc.update_params()
    self.lane_turn_controller.update_params()
    v_ego = carstate.vEgo
    one_blinker = carstate.leftBlinker != carstate.rightBlinker
    below_lane_change_speed = v_ego < LANE_CHANGE_SPEED_MIN
    creep_context_safe = creep_lane_change_context_safe(model_valid, lead_prob, lead_distance)
    creep_speed_valid = 0. <= v_ego <= CREEP_LANE_CHANGE_SPEED_MAX
    creep_entry_allowed = self.alc.creep_lane_change_enabled and creep_speed_valid and creep_context_safe

    # Lane turn controller update
    self.lane_turn_controller.update_lane_turn(blindspot_left=carstate.leftBlindspot, blindspot_right=carstate.rightBlindspot,
                                               left_blinker=carstate.leftBlinker, right_blinker=carstate.rightBlinker, v_ego=v_ego)
    self.lane_turn_direction = self.lane_turn_controller.get_turn_direction()

    normal_lane_change_disabled = self.alc.lane_change_set_timer == AutoLaneChangeMode.OFF
    active_normal_lane_change_disabled = self.lane_change_state != LaneChangeState.off and \
      not self.creep_lane_change and normal_lane_change_disabled

    if not lateral_active or self.lane_change_timer > LANE_CHANGE_TIME_MAX or active_normal_lane_change_disabled:
      self.reset_lane_change()
    else:
      if self.lane_change_state == LaneChangeState.off and one_blinker and not self.prev_one_blinker:
        normal_entry_allowed = not below_lane_change_speed and not normal_lane_change_disabled
        if normal_entry_allowed or creep_entry_allowed:
          self.lane_change_state = LaneChangeState.preLaneChange
          self.lane_change_timer = 0.0
          self.creep_lane_change = creep_entry_allowed and not normal_entry_allowed
          # Initialize lane change direction to prevent UI alert flicker
          self.lane_change_direction = self.get_lane_change_direction(carstate)

      elif self.lane_change_state == LaneChangeState.preLaneChange:
        if not one_blinker:
          self.reset_lane_change()
        else:
          # Update lane change direction
          self.lane_change_direction = self.get_lane_change_direction(carstate)

          torque_applied = carstate.steeringPressed and \
                           ((carstate.steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.left) or
                            (carstate.steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.right))

          blindspot_detected = self.blindspot_detected(carstate, left_edge_detected, right_edge_detected)
          creep_invalid = self.creep_lane_change and \
            (not creep_speed_valid or not creep_context_safe or blindspot_detected)

          if creep_invalid or (not self.creep_lane_change and below_lane_change_speed):
            self.reset_lane_change()
          elif self.creep_lane_change and carstate.brakePressed:
            # A stopped driver may signal while holding the brake. Start the delay after release.
            self.alc.lane_change_wait_timer = 0.0
          else:
            self.alc.update_lane_change(blindspot_detected, carstate.brakePressed, self.creep_lane_change)
            lane_change_triggered = self.alc.auto_lane_change_allowed if self.creep_lane_change else \
              torque_applied or self.alc.auto_lane_change_allowed
            if lane_change_triggered and not blindspot_detected:
              self.lane_change_state = LaneChangeState.laneChangeStarting
              self.lane_change_timer = 0.0

      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        blindspot_detected = self.blindspot_detected(carstate, left_edge_detected, right_edge_detected)
        creep_invalid = self.creep_lane_change and \
          (not one_blinker or not creep_context_safe or carstate.brakePressed or blindspot_detected)

        if creep_invalid:
          self.reset_lane_change()
        else:
          self.lane_change_timer += DT_MDL

          if lane_change_prob < 0.02 and self.lane_change_timer >= LANE_CHANGE_START_TIME:
            if self.creep_lane_change:
              # One signal edge authorizes one creep maneuver. Require signal cancellation before another request.
              self.reset_lane_change()
            else:
              self.lane_change_timer = 0.0
              if one_blinker:
                self.lane_change_state = LaneChangeState.preLaneChange
                self.lane_change_direction = self.get_lane_change_direction(carstate)
              else:
                self.reset_lane_change()

    self.prev_one_blinker = one_blinker and lateral_active

    if self.creep_lane_change:
      self.desire = log.Desire.none
      if self.lane_change_state == LaneChangeState.laneChangeStarting:
        self.desire = log.Desire.laneChangeLeft if self.lane_change_direction == LaneChangeDirection.left else log.Desire.laneChangeRight
    elif self.lane_turn_direction != TurnDirection.none:
      self.desire = TURN_DESIRES[self.lane_turn_direction]
    else:
      self.desire = log.Desire.none
      if self.lane_change_state == LaneChangeState.laneChangeStarting:
        if self.lane_change_direction == LaneChangeDirection.left:
          self.desire = log.Desire.laneChangeLeft
        elif self.lane_change_direction == LaneChangeDirection.right:
          self.desire = log.Desire.laneChangeRight

    self.alc.update_state()
