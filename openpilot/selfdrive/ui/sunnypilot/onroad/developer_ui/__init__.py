"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from enum import IntEnum

import pyray as rl
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.onroad.torque_debug import TorqueDebugState
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui.elements import (
  UiElement, RelDistElement, RelSpeedElement, SteeringAngleElement,
  DesiredLateralAccelElement, ActualLateralAccelElement, DesiredSteeringAngleElement,
  AEgoElement, LeadSpeedElement, FrictionCoefficientElement, LatAccelFactorElement,
  SteeringTorqueEpsElement, BearingDegElement, AltitudeElement, DesiredSteeringPIDElement
)
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


def get_bottom_dev_ui_offset():
  if ui_state.developer_ui in (DeveloperUiState.BOTTOM, DeveloperUiState.BOTH):
    return 60
  return 0


class DeveloperUiState(IntEnum):
  OFF = 0
  BOTTOM = 1
  RIGHT = 2
  BOTH = 3


class DeveloperUiRenderer(Widget):
  def __init__(self):
    super().__init__()
    self._font_bold: rl.Font = gui_app.font(FontWeight.BOLD)
    self._font_semi_bold: rl.Font = gui_app.font(FontWeight.SEMI_BOLD)
    self.dev_ui_mode = DeveloperUiState.OFF
    self.torque_debug = TorqueDebugState()

    self.rel_dist_elem = RelDistElement()
    self.rel_speed_elem = RelSpeedElement()
    self.steering_angle_elem = SteeringAngleElement()
    self.desired_lat_accel_elem = DesiredLateralAccelElement()
    self.actual_lat_accel_elem = ActualLateralAccelElement()
    self.desired_steer_elem = DesiredSteeringAngleElement()
    self.desired_pid_steer_elem = DesiredSteeringPIDElement()
    self.a_ego_elem = AEgoElement()
    self.lead_speed_elem = LeadSpeedElement()
    self.friction_elem = FrictionCoefficientElement()
    self.lat_accel_factor_elem = LatAccelFactorElement()
    self.steering_torque_elem = SteeringTorqueEpsElement()
    self.bearing_elem = BearingDegElement()
    self.altitude_elem = AltitudeElement()

  def _update_state(self) -> None:
    self.dev_ui_mode = ui_state.developer_ui
    self.torque_debug.update(ui_state.sm, ui_state.started_frame,
                             ui_state.started and self.dev_ui_mode in (DeveloperUiState.BOTTOM, DeveloperUiState.RIGHT, DeveloperUiState.BOTH))

  def _render(self, rect: rl.Rectangle) -> None:
    if self.dev_ui_mode not in (DeveloperUiState.BOTTOM, DeveloperUiState.RIGHT, DeveloperUiState.BOTH):
      return

    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      return

    if self.dev_ui_mode == DeveloperUiState.BOTTOM:
      self._draw_bottom_dev_ui(rect)
    elif self.dev_ui_mode == DeveloperUiState.RIGHT:
      self._draw_right_dev_ui(rect)
    elif self.dev_ui_mode == DeveloperUiState.BOTH:
      self._draw_right_dev_ui(rect)
      self._draw_bottom_dev_ui(rect)

    self._draw_torque_debug(rect)
    self._draw_vehicle_diagnostics(rect)

  def _draw_vehicle_diagnostics(self, rect: rl.Rectangle) -> None:
    if rect.width <= 0 or rect.height <= 0:
      return
    scale = min(1.0, rect.width / 1920, rect.height / 1080)
    # Keep the lower-left driver-monitoring indicator unobstructed.
    x, y = rect.x + 270 * scale, rect.y + 650 * scale
    width = 700 * scale
    lines = ui_state.developer_diagnostics.lines()
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, width, (16 + 27 * len(lines)) * scale),
                               0.1, 8, rl.Color(0, 0, 0, 170))
    for i, line in enumerate(lines):
      font_size = 23 * scale
      measured = measure_text_cached(self._font_semi_bold, line, font_size, 0).x
      font_size *= min(1.0, (width - 24 * scale) / max(1.0, measured))
      color = rl.ORANGE if line.startswith('*') else rl.WHITE
      rl.draw_text_ex(self._font_semi_bold, line, rl.Vector2(x + 12 * scale, y + (8 + i * 27) * scale), font_size, 0, color)

  def _draw_torque_debug(self, rect: rl.Rectangle) -> None:
    # Left of the road, below the speed-limit ahead sign. Alerts render above HUD.
    if rect.width <= 0 or rect.height <= 0:
      return
    scale = min(1.0, rect.width / 1920, rect.height / 1080)
    x, y = rect.x + 30 * scale, rect.y + 470 * scale
    width, height = min(700 * scale, rect.width - 60 * scale), 170 * scale
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, width, height), 0.1, 8, rl.Color(0, 0, 0, 150))
    lines = self.torque_debug.lines(ui_state.is_metric)
    for i, line in enumerate(lines):
      font_size = 28 * scale
      measured = measure_text_cached(self._font_semi_bold, line, font_size, 0).x
      font_size *= min(1.0, (width - 24 * scale) / max(1.0, measured))
      color = rl.ORANGE if i == 2 and self.torque_debug.last_saturation is not None else rl.WHITE
      rl.draw_text_ex(self._font_semi_bold, line, rl.Vector2(x + 12 * scale, y + (12 + i * 38) * scale),
                      font_size, 0, color)

  def _draw_right_dev_ui(self, rect: rl.Rectangle) -> None:
    sm = ui_state.sm
    controls_state = sm['controlsState']

    UI_BORDER_SIZE = 20
    container_width = 184
    x = int(rect.x + rect.width - container_width - UI_BORDER_SIZE * 2)
    y = int(rect.y + UI_BORDER_SIZE * 1.5)

    elements = [
      self.rel_dist_elem.update(sm, ui_state.is_metric),
      self.rel_speed_elem.update(sm, ui_state.is_metric),
      self.steering_angle_elem.update(sm, ui_state.is_metric),
    ]
    if controls_state.lateralControlState.which() == 'torqueState':
      elements.append(self.desired_lat_accel_elem.update(sm, ui_state.is_metric))
    elif controls_state.lateralControlState.which() == 'angleState':
      elements.append(self.desired_steer_elem.update(sm, ui_state.is_metric))
    elif controls_state.lateralControlState.which() == 'pidState':
      elements.append(self.desired_pid_steer_elem.update(sm, ui_state.is_metric))

    elements.append(self.actual_lat_accel_elem.update(sm, ui_state.is_metric))

    current_y = y
    for element in elements:
      current_y += self._draw_right_dev_ui_element(x, current_y, element)

  def _draw_right_dev_ui_element(self, x: int, y: int, element: UiElement) -> int:
    x += 0
    y += 230
    container_width = 184
    label_size = 28
    value_size = 60
    unit_size = 28
    label_width = measure_text_cached(self._font_bold, element.label, label_size, 0).x
    centered_label_x = x + (container_width - label_width) / 2
    rl.draw_text_ex(self._font_bold, element.label, rl.Vector2(centered_label_x, y), label_size, 0, rl.WHITE)

    y += 45
    value_width = measure_text_cached(self._font_bold, element.value, value_size, 0).x
    centered_value_x = x + (container_width - value_width) / 2
    rl.draw_text_ex(self._font_bold, element.value, rl.Vector2(centered_value_x, y), value_size, 0, element.color)

    if element.unit:
      units_height = measure_text_cached(self._font_bold, element.unit, unit_size, 0).x

      units_x = x + container_width
      units_y = y + (value_size / 2) + (units_height / 2)

      rl.draw_text_pro(self._font_bold, element.unit, rl.Vector2(units_x, units_y), rl.Vector2(0, 0), -90.0, unit_size, 0, rl.WHITE)

    return 130

  def _draw_bottom_dev_ui(self, rect: rl.Rectangle) -> None:
    sm = ui_state.sm
    bar_height = 61
    y = int(rect.y + rect.height - bar_height)

    rl.draw_rectangle(int(rect.x), y, int(rect.width), bar_height,
                      rl.Color(0, 0, 0, 100))

    elements = [
      self.a_ego_elem.update(sm, ui_state.is_metric),
      self.lead_speed_elem.update(sm, ui_state.is_metric),
    ]

    # Add torque-specific elements if using torque control
    if sm['controlsState'].lateralControlState.which() == 'torqueState':
      override_active = ui_state.enforce_torque_control and ui_state.custom_torque_params and ui_state.torque_override_enabled
      if sm.valid['lateralTorqueParameters'] or override_active:
        elements.extend([
          self.friction_elem.update(sm, ui_state.is_metric),
          self.lat_accel_factor_elem.update(sm, ui_state.is_metric),
        ])
    else:
      # Non-torque: show steering torque and GPS data
      elements.append(self.steering_torque_elem.update(sm, ui_state.is_metric))

      if sm.valid['gpsLocationExternal'] or sm.valid['gpsLocation']:
        elements.append(self.bearing_elem.update(sm, ui_state.is_metric))

    # Add altitude if GPS available
    if sm.valid['gpsLocationExternal'] or sm.valid['gpsLocation']:
      elements.append(self.altitude_elem.update(sm, ui_state.is_metric))

    if not elements:
      return

    font_size = 38
    element_widths = []
    for element in elements:
      element.measure(self._font_bold, font_size)
      element_widths.append(element.total_width)

    total_element_width = sum(element_widths)
    num_gaps = len(elements) + 1
    available_width = rect.width
    gap_width = (available_width - total_element_width) / num_gaps

    center_y = y + bar_height // 2
    current_x = rect.x + gap_width

    for i, element in enumerate(elements):
      element_center_x = int(current_x + element_widths[i] / 2)
      self._draw_bottom_dev_ui_element(element_center_x, center_y, element)
      current_x += element_widths[i] + gap_width

  def _draw_bottom_dev_ui_element(self, center_x: int, y: int, element: UiElement) -> None:
    font_size = 38
    start_x = center_x - element.total_width / 2

    rl.draw_text_ex(self._font_bold, element.label_text, rl.Vector2(start_x, y - font_size // 2), font_size, 0, rl.WHITE)
    rl.draw_text_ex(self._font_bold, element.val_text, rl.Vector2(start_x + element.label_width, y - font_size // 2), font_size, 0, element.color)

    if element.unit:
      rl.draw_text_ex(self._font_bold, element.unit_text, rl.Vector2(start_x + element.label_width + element.val_width, y - font_size // 2),
                      font_size, 0, rl.WHITE)
