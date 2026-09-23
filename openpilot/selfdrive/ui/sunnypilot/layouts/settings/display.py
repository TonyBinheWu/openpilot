"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from enum import IntEnum

from openpilot.common.hardware import HARDWARE
from openpilot.common.params import Params
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.multilang import multilang, tr
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, option_item_sp
from openpilot.sunnypilot.system.params_migration import ONROAD_BRIGHTNESS_TIMER_VALUES


_DISPLAY_ZH_CHT = {
  "Onroad Brightness": "行駛中螢幕亮度",
  "Onroad Brightness Delay": "行駛中亮度延遲",
  "Interactivity Timeout": "互動逾時時間",
  "Apply a custom timeout for settings UI.<br>This is the time after which settings UI closes automatically if user is not interacting with the screen.":
    "自訂設定介面的逾時時間。<br>若使用者未操作螢幕，超過此時間後會自動關閉設定介面。",
  "Screen Saver": "螢幕保護程式",
  "Show a screen saver when the device is offroad and idle, instead of turning the screen off.":
    "裝置離線且閒置時顯示螢幕保護程式，而不是直接關閉螢幕。",
  "Screen Saver Duration": "螢幕保護程式持續時間",
  "How long the screen saver runs before the screen turns off.": "螢幕保護程式顯示多久後關閉螢幕。",
  "Auto (Default)": "自動（預設）",
  "Auto (Dark)": "自動（較暗）",
  "Screen Off": "關閉螢幕",
  "Default": "預設",
  "Reduce Night Driving Glare": "降低夜間行駛光害",
  "C3X OLED only. After the selected delay, hide the road camera and model graphics and keep a mostly black screen with essential HUD and alerts. Touching the screen or receiving an alert restores the full display and restarts the delay.":
    "僅限 C3X OLED。啟用後，經過設定的延遲時間會隱藏道路相機與模型圖形，改以大面積黑底只保留必要 HUD 與警示。觸控螢幕或出現警示時會恢復完整畫面並重新計時。",
  "Night Low-Light Delay": "夜間低光害顯示延遲",
}


def display_tr(text: str) -> str:
  if multilang.language == "zh-CHT":
    return _DISPLAY_ZH_CHT.get(text, text)
  return tr(text)


class OnroadBrightness(IntEnum):
  AUTO = 0
  AUTO_DARK = 1
  SCREEN_OFF = 2
  # Internal sentinel used by the C3X/tizi-only night low-light toggle. Normal brightness values remain 3-22.
  NIGHT_LOW_LIGHT = 23


class DisplayLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._is_c3x = HARDWARE.get_device_type() == "tizi"
    self._brightness_before_night = OnroadBrightness.AUTO

    current_brightness = int(float(self._params.get("OnroadScreenOffBrightness", return_default=True)))
    if current_brightness != OnroadBrightness.NIGHT_LOW_LIGHT:
      self._brightness_before_night = current_brightness

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._onroad_brightness = option_item_sp(
      param="OnroadScreenOffBrightness",
      title=lambda: display_tr("Onroad Brightness"),
      description="",
      min_value=0,
      max_value=23 if self._is_c3x else 22,
      value_change_step=1,
      label_callback=lambda value: self.update_onroad_brightness(value),
      inline=True
    )
    self._onroad_brightness_timer = option_item_sp(
      param="OnroadScreenOffTimer",
      title=lambda: display_tr("Onroad Brightness Delay"),
      description="",
      min_value=0,
      max_value=15,
      value_change_step=1,
      value_map=ONROAD_BRIGHTNESS_TIMER_VALUES,
      label_callback=lambda value: f"{value} s" if value < 60 else f"{int(value/60)} m",
      inline=True
    )
    self._interactivity_timeout = option_item_sp(
      param="InteractivityTimeout",
      title=lambda: display_tr("Interactivity Timeout"),
      description=lambda: display_tr("Apply a custom timeout for settings UI.<br>This is the time after which settings UI closes automatically if user is not interacting with the screen."),
      min_value=0,
      max_value=120,
      value_change_step=10,
      label_callback=lambda value: (display_tr("Default") if not value or value == 0 else
                                    f"{value} s" if value < 60 else f"{int(value/60)} m"),
      inline=True
    )
    self._screensaver_toggle = toggle_item_sp(
      param="ScreenSaverEnabled",
      title=lambda: display_tr("Screen Saver"),
      description=lambda: display_tr("Show a screen saver when the device is offroad and idle, instead of turning the screen off."),
    )
    self._screensaver_timeout = option_item_sp(
      param="ScreenSaverTimeout",
      title=lambda: display_tr("Screen Saver Duration"),
      description=lambda: display_tr("How long the screen saver runs before the screen turns off."),
      min_value=60,
      max_value=600,
      value_change_step=60,
      label_callback=lambda value: f"{int(value/60)} m"
    )

    items = [
      self._onroad_brightness,
      self._onroad_brightness_timer,
    ]

    self._night_low_light_toggle = None
    self._night_low_light_delay = None
    if self._is_c3x:
      night_active = int(float(self._params.get("OnroadScreenOffBrightness", return_default=True))) == OnroadBrightness.NIGHT_LOW_LIGHT
      self._night_low_light_toggle = toggle_item_sp(
        title=lambda: display_tr("Reduce Night Driving Glare"),
        description=lambda: display_tr("C3X OLED only. After the selected delay, hide the road camera and model graphics and keep a mostly black screen with essential HUD and alerts. Touching the screen or receiving an alert restores the full display and restarts the delay."),
        initial_state=night_active,
        callback=self._set_night_low_light,
      )
      self._night_low_light_delay = option_item_sp(
        param="OnroadScreenOffTimer",
        title=lambda: display_tr("Night Low-Light Delay"),
        description="",
        min_value=6,
        max_value=15,
        value_change_step=1,
        value_map=ONROAD_BRIGHTNESS_TIMER_VALUES,
        label_callback=lambda value: f"{int(value/60)} m",
        inline=True,
      )
      items.extend([self._night_low_light_toggle, self._night_low_light_delay])

    items.extend([
      self._interactivity_timeout,
      self._screensaver_toggle,
      self._screensaver_timeout,
    ])
    return items

  def _set_night_low_light(self, enabled: bool) -> None:
    current = int(float(self._params.get("OnroadScreenOffBrightness", return_default=True)))
    if enabled:
      if current != OnroadBrightness.NIGHT_LOW_LIGHT:
        self._brightness_before_night = current if 0 <= current <= 22 else OnroadBrightness.AUTO
      self._params.put("OnroadScreenOffBrightness", int(OnroadBrightness.NIGHT_LOW_LIGHT), block=True)
    else:
      restore = int(self._brightness_before_night)
      self._params.put("OnroadScreenOffBrightness", restore if 0 <= restore <= 22 else int(OnroadBrightness.AUTO), block=True)

  @staticmethod
  def update_onroad_brightness(val):
    if val == OnroadBrightness.AUTO:
      return display_tr("Auto (Default)")

    if val == OnroadBrightness.AUTO_DARK:
      return display_tr("Auto (Dark)")

    if val == OnroadBrightness.SCREEN_OFF:
      return display_tr("Screen Off")

    if val == OnroadBrightness.NIGHT_LOW_LIGHT:
      return display_tr("Reduce Night Driving Glare")

    return f"{(val - 2) * 5} %"

  def _update_state(self):
    super()._update_state()

    brightness_val = int(float(self._params.get("OnroadScreenOffBrightness", return_default=True)))
    night_active = self._is_c3x and brightness_val == OnroadBrightness.NIGHT_LOW_LIGHT

    # Keep the custom toggle synchronized with the shared brightness mode parameter.
    if self._night_low_light_toggle is not None:
      self._night_low_light_toggle.action_item.toggle.set_state(night_active)
    if self._night_low_light_delay is not None:
      self._night_low_light_delay.set_visible(night_active)

    # Avoid presenting the normal brightness controls while the C3X-only night mode owns the same timer/mode params.
    self._onroad_brightness.set_visible(not night_active)
    self._onroad_brightness_timer.set_visible(not night_active)
    self._onroad_brightness_timer.action_item.set_enabled(
      brightness_val not in (OnroadBrightness.AUTO, OnroadBrightness.AUTO_DARK, OnroadBrightness.NIGHT_LOW_LIGHT)
    )

    self._screensaver_timeout.set_visible(self._screensaver_toggle.action_item.get_state())

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
