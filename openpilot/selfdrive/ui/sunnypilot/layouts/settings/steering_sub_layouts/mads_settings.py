"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from collections.abc import Callable
import pyray as rl

from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.sunnypilot.car.tesla.values import MadsScreenButtonType, TeslaFlagsSP
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.mads.helpers import MadsLongitudinalAssistMode, MadsSteeringModeOnBrake
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.sunnypilot.widgets.list_view import multiple_button_item_sp, toggle_item_sp

MADS_STEERING_MODE_OPTIONS = [
  (tr("Remain Active"), tr_noop("Remain Active: ALC will remain active when the brake pedal is pressed.")),
  (tr("Pause"), tr_noop("Pause: ALC will pause when the brake pedal is pressed.")),
  (tr("Disengage"), tr_noop("Disengage: ALC will disengage when the brake pedal is pressed.")),
]

MADS_LONGITUDINAL_MODE_OPTIONS = [
  ("關閉", "關閉：MADS 僅控制橫向轉向，油門與煞車完全由駕駛控制。"),
  ("前車距離維持", "前車距離維持：平時由駕駛控制車速；接近有效前車時，sunnypilot 可依現有 MPC 與跟車人格設定介入滑行／減速／煞車，但絕不主動正加速。踩油門或煞車會立即覆寫此輔助。"),
  ("完整縱向控制", "完整縱向控制：MADS 保持橫向能力，使用 SET／RES 可進入既有的完整 openpilot 縱向控制；取消縱向後仍可保留 MADS 橫向控制。"),
]

MADS_MAIN_CRUISE_BASE_DESC = tr("Note: For vehicles without LFA/LKAS button, disabling this will prevent lateral control engagement.")
MADS_UNIFIED_ENGAGEMENT_MODE_BASE_DESC = "{engage}<br><h4>{note}</h4>".format(
  engage=tr("Engage lateral and longitudinal control with cruise control engagement."),
  note=tr("Note: Once lateral control is engaged via UEM, it will remain engaged until it is manually disabled via the MADS button or car shut off."),
)

STATUS_CHECK_COMPATIBILITY = tr("Start the vehicle to check vehicle compatibility.")
DEFAULT_TO_OFF = tr("This feature defaults to OFF, and does not allow selection due to vehicle limitations.")
DEFAULT_TO_ON = tr("This feature defaults to ON, and does not allow selection due to vehicle limitations.")
STATUS_DISENGAGE_ONLY = tr("This platform only supports Disengage mode due to vehicle limitations.")
FOLLOW_CANFD_ONLY = "前車距離維持目前僅支援已啟用 openpilot 縱向控制的 Hyundai／Kia／Genesis CAN-FD 車系。"


class MadsSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)
    self._initialize_items()
    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._main_cruise_toggle = toggle_item_sp(
      title=lambda: tr("Toggle with Main Cruise"),
      description=MADS_MAIN_CRUISE_BASE_DESC,
      param="MadsMainCruiseAllowed",
    )
    self._unified_engagement_toggle = toggle_item_sp(
      title=lambda: tr("Unified Engagement Mode (UEM)"),
      description=MADS_UNIFIED_ENGAGEMENT_MODE_BASE_DESC,
      param="MadsUnifiedEngagementMode"
    )
    self._longitudinal_assist_mode = multiple_button_item_sp(
      param="MadsLongitudinalAssistMode",
      title=lambda: "縱向輔助",
      description="",
      buttons=[opt[0] for opt in MADS_LONGITUDINAL_MODE_OPTIONS],
      inline=False,
      button_width=350,
      callback=self._update_longitudinal_assist_description,
    )
    self._steering_mode = multiple_button_item_sp(
      param="MadsSteeringMode",
      title=lambda: tr("Steering Mode on Brake Pedal"),
      description="",
      buttons=[opt[0] for opt in MADS_STEERING_MODE_OPTIONS],
      inline=False,
      button_width=350,
      callback=self._update_steering_mode_description,
    )

    self.items = [
      self._main_cruise_toggle,
      self._unified_engagement_toggle,
      self._longitudinal_assist_mode,
      self._steering_mode,
    ]

  def _update_state(self):
    super()._update_state()
    self._update_toggles()

  def _render(self, rect):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    # subtract button
    content_rect = rl.Rectangle(rect.x, rect.y + self._back_button.rect.height + 40, rect.width, rect.height - self._back_button.rect.height - 40)
    self._scroller.render(content_rect)

  def show_event(self):
    self._scroller.show_event()

  @staticmethod
  def _mads_limited_settings() -> bool:
    brand = ""
    if ui_state.is_offroad():
      bundle = ui_state.params.get("CarPlatformBundle")
      if bundle:
        brand = bundle.get("brand", "")
    if not brand:
      brand = ui_state.CP.brand if ui_state.CP is not None else ""

    if brand == "rivian":
      return True
    elif brand == "tesla":
      if ui_state.CP_SP is None or not ui_state.CP_SP.flags & TeslaFlagsSP.HAS_VEHICLE_BUS:
        return True
      screen_button = int(ui_state.params.get("TeslaMadsScreenButton", return_default=True))
      return screen_button == MadsScreenButtonType.OFF
    return False

  @staticmethod
  def _follow_assist_supported() -> bool:
    cp = ui_state.CP
    return bool(cp is not None and cp.brand == "hyundai" and cp.flags & HyundaiFlags.CANFD and cp.openpilotLongitudinalControl)

  def _update_steering_mode_description(self, button_index: int):
    base_desc = tr("Choose how Automatic Lane Centering (ALC) behaves after the brake pedal is manually pressed in sunnypilot.")
    result = base_desc + "<br><br>"
    for opt in MADS_STEERING_MODE_OPTIONS:
      desc = "<b>" + opt[1] + "</b>" if button_index == MADS_STEERING_MODE_OPTIONS.index(opt) else opt[1]
      result += desc + "<br>"
    self._steering_mode.set_description(result)
    self._steering_mode.show_description(True)

  def _update_longitudinal_assist_description(self, button_index: int):
    button_index = max(MadsLongitudinalAssistMode.OFF, min(button_index, MadsLongitudinalAssistMode.FULL))
    result = "MADS 啟動時的縱向控制方式。<br><br>"
    for index, opt in enumerate(MADS_LONGITUDINAL_MODE_OPTIONS):
      desc = "<b>" + opt[1] + "</b>" if button_index == index else opt[1]
      result += desc + "<br>"
    if not self._follow_assist_supported():
      result += "<br><b>" + FOLLOW_CANFD_ONLY + "</b>"
    self._longitudinal_assist_mode.set_description(result)
    self._longitudinal_assist_mode.show_description(True)

  def _update_toggles(self):
    self._update_steering_mode_description(self._steering_mode.action_item.get_selected_button())
    self._update_longitudinal_assist_description(self._longitudinal_assist_mode.action_item.get_selected_button())

    if self._follow_assist_supported():
      self._longitudinal_assist_mode.action_item.set_enabled(True)
      self._longitudinal_assist_mode.action_item.set_enabled_buttons(None)
    else:
      # OFF and FULL remain selectable on other platforms; brake-only lead following is CAN-FD HKG only for now.
      if self._longitudinal_assist_mode.action_item.get_selected_button() == MadsLongitudinalAssistMode.FOLLOW:
        ui_state.params.put("MadsLongitudinalAssistMode", MadsLongitudinalAssistMode.OFF)
        self._longitudinal_assist_mode.action_item.set_selected_button(MadsLongitudinalAssistMode.OFF)
      self._longitudinal_assist_mode.action_item.set_enabled_buttons({MadsLongitudinalAssistMode.OFF, MadsLongitudinalAssistMode.FULL})

    if self._mads_limited_settings():
      ui_state.params.remove("MadsMainCruiseAllowed")
      ui_state.params.put_bool("MadsUnifiedEngagementMode", True)
      ui_state.params.put("MadsSteeringMode", MadsSteeringModeOnBrake.DISENGAGE)

      self._main_cruise_toggle.action_item.set_enabled(False)
      self._main_cruise_toggle.action_item.set_state(False)
      self._main_cruise_toggle.set_description("<b>" + DEFAULT_TO_OFF + "</b><br>" + MADS_MAIN_CRUISE_BASE_DESC)

      self._unified_engagement_toggle.action_item.set_enabled(False)
      self._unified_engagement_toggle.action_item.set_state(True)
      self._unified_engagement_toggle.set_description("<b>" + DEFAULT_TO_ON + "</b><br>" + MADS_UNIFIED_ENGAGEMENT_MODE_BASE_DESC)

      self._steering_mode.set_description(STATUS_DISENGAGE_ONLY)
      self._steering_mode.action_item.set_selected_button(MadsSteeringModeOnBrake.DISENGAGE)
      self._steering_mode.action_item.set_enabled_buttons({MadsSteeringModeOnBrake.DISENGAGE})
    else:
      self._main_cruise_toggle.action_item.set_enabled(True)
      self._main_cruise_toggle.set_description(MADS_MAIN_CRUISE_BASE_DESC)

      self._unified_engagement_toggle.action_item.set_enabled(True)
      self._unified_engagement_toggle.set_description(MADS_UNIFIED_ENGAGEMENT_MODE_BASE_DESC)

      self._steering_mode.action_item.set_enabled(True)
      self._steering_mode.action_item.set_enabled_buttons(None)
