"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.common.params import Params
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.sunnypilot.car.hyundai.factory_cluster import (
  FACTORY_SIDE_DISPLAY_PARAM,
  FACTORY_SIDE_DISPLAY_STATUS_PARAM,
  FactoryClusterStatus,
  configuration_status,
  is_ev6_hda2_candidate,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import multilang, tr
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, multiple_button_item_sp
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets import Widget


def vtr(english: str, traditional_chinese: str) -> str:
  """Keep Visuals usable in zh-CHT even before generated PO catalogs are refreshed."""
  return traditional_chinese if multilang.language == "zh-CHT" else tr(english)


CHEVRON_INFO_DESCRIPTION = {
  "enabled": ("Display useful metrics below the chevron that tracks the lead car only applicable to cars with sunnypilot longitudinal control.",
              "在前車追蹤箭頭下方顯示實用資訊；僅適用於使用 sunnypilot 縱向控制的車輛。"),
  "disabled": ("This feature requires sunnypilot longitudinal control to be available.",
               "此功能需要車輛支援 sunnypilot 縱向控制。"),
}

FACTORY_CLUSTER_STATUS_TEXT = {
  FactoryClusterStatus.OFF.value: ("Off", "關閉"),
  FactoryClusterStatus.UNAVAILABLE_VEHICLE.value: ("Unavailable: incompatible vehicle", "無法使用：車型不相容"),
  FactoryClusterStatus.UNAVAILABLE_UNVERIFIED_PROFILE.value: ("Unavailable: vehicle firmware and CAN profile not verified", "無法使用：車輛韌體與 CAN 設定檔尚未驗證"),
  FactoryClusterStatus.UNAVAILABLE_NO_STOCK_TEMPLATE.value: ("Unavailable: original target message not captured", "無法使用：尚未擷取原廠目標訊息"),
  FactoryClusterStatus.UNAVAILABLE_INVALID_STOCK_TEMPLATE.value: ("Unavailable: original target message failed validation", "無法使用：原廠目標訊息驗證失敗"),
  FactoryClusterStatus.UNAVAILABLE_STALE_STOCK_MESSAGE.value: ("Unavailable: original target message is stale", "無法使用：原廠目標訊息已過期"),
  FactoryClusterStatus.UNAVAILABLE_RADAR_DATA.value: ("Unavailable: real target data is stale or missing", "無法使用：實際目標資料過期或缺失"),
  FactoryClusterStatus.UNAVAILABLE_TARGET_ENCODING.value: ("Unavailable: real target cannot be encoded safely", "無法使用：實際目標無法安全編碼"),
  FactoryClusterStatus.UNAVAILABLE_UNSUPPORTED_MESSAGE.value: ("Unavailable: message is not authorized by Panda safety", "無法使用：Panda safety 未允許此訊息"),
  FactoryClusterStatus.BLOCKED_SENDER_CONFLICT.value: ("Blocked: another ECU is sending the same message", "已阻擋：其他 ECU 正在傳送相同訊息"),
  FactoryClusterStatus.ACTIVE_STOCK_PASSTHROUGH.value: ("Active: preserving original vehicle targets", "啟用：保留原廠車輛目標"),
  FactoryClusterStatus.ACTIVE_REAL_TARGETS.value: ("Active: displaying verified real targets", "啟用：顯示已驗證的實際目標"),
  FactoryClusterStatus.ACTIVE_BSM_REGION.value: ("Active: blind-spot region warning only", "啟用：僅顯示盲點區域警告"),
  FactoryClusterStatus.ACTIVE_NO_TARGETS.value: ("Active: no nearby targets", "啟用：附近沒有目標"),
}
FACTORY_CLUSTER_DESCRIPTION = (
  "Keep real left/right vehicle graphics on the Kia factory instrument cluster while sunnypilot longitudinal control or Experimental Mode is active. "
  "Display only: this does not enable Kia automatic lane changes or use side targets for driving decisions. "
  "Unsupported firmware, stale data, or a CAN sender conflict produces no added vehicle graphic. A restart is required after changing this setting.",
  "在 sunnypilot 縱向控制或實驗模式啟用時，保留 Kia 原廠儀表左右側實際車輛圖示。此功能僅供顯示，不會啟用 Kia 自動換道，也不會將側向目標用於駕駛決策。若韌體不支援、資料過期或 CAN 傳送端衝突，系統不會額外產生車輛圖示。變更此設定後需要重新啟動。",
)


class VisualsLayout(Widget):
  def __init__(self):
    super().__init__()

    self._params = Params()
    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._toggle_defs = {
      "AdjacentLaneObjectMarkers": (
        lambda: vtr("Adjacent Lane Object Markers", "相鄰車道物件標記"),
        lambda: vtr("Show yellow markers for high-confidence model lead candidates outside the current driving path. The driving model does not provide a complete object list, so some nearby vehicles may not appear.",
                     "在目前行駛路徑外，以黃色標記顯示模型高可信度的前車候選目標。駕駛模型並未提供完整物件清單，因此部分鄰近車輛可能不會顯示。"),
        None,
      ),
      "BlindSpot": (
        lambda: vtr("Show Blind Spot Warnings", "顯示盲點警告"),
        lambda: vtr("Display a warning when the vehicle reports an object in the left or right blind spot. Requires vehicle BSM support.",
                     "當車輛回報左側或右側盲點有物件時顯示警告。需要車輛支援 BSM 盲點偵測。"),
        None,
      ),
      "PredictedStopMarker": (
        lambda: vtr("Model Predicted Stop Position", "模型預計停止位置"),
        lambda: vtr("Draw a line at the model-predicted stopping position. The marker is latched through brief prediction dropouts and disappears after the vehicle has stopped and starts moving again. Display only; it does not affect braking or longitudinal control.",
                     "在畫面上以線條標示模型預計的停止位置。模型預測短暫消失時仍會保留標記，車輛完成停止並再次起步後才會清除。此功能僅供顯示，不會影響煞車或縱向控制。"),
        None,
      ),
      "HkgCornerRadarDetection": (
        lambda: vtr("HKG Corner Radar Detection (Experimental)", "HKG 角雷達偵測（實驗）"),
        lambda: vtr("Show yellow radar candidates beside the speedometer, separately from blind-spot icons. RADAR* means experimental: sensor mounting and validity still need vehicle validation. Display only; no control decisions.",
                     "在時速表兩側以黃色標記顯示角雷達候選目標，與盲點圖示分開顯示。RADAR* 代表實驗功能；感測器安裝位置與資料有效性仍需實車驗證。僅供顯示，不參與控制決策。"),
        None,
      ),
      FACTORY_SIDE_DISPLAY_PARAM: (
        lambda: vtr("Kia EV6 Factory Cluster Side Vehicles", "Kia EV6 原廠儀表側向車輛"),
        lambda: vtr(*FACTORY_CLUSTER_DESCRIPTION),
        self._on_factory_side_display,
      ),
      "TorqueBar": (
        lambda: vtr("Steering Arc", "方向盤轉向弧"),
        lambda: vtr("Display steering arc on the driving screen when lateral control is enabled.", "橫向控制啟用時，在行駛畫面顯示方向盤轉向弧。"),
        None,
      ),
      "RainbowMode": (
        lambda: vtr("Enable Tesla Rainbow Mode", "啟用 Tesla 彩虹模式"),
        lambda: vtr("Choose the original rainbow path or dynamic blue acceleration and deceleration bars below. Display only.",
                     "可在下方選擇原始彩虹路徑，或動態藍色加速／減速條。僅供顯示。"),
        None,
      ),
      "StandstillTimer": (
        lambda: vtr("Enable Standstill Timer", "啟用停車計時器"),
        lambda: vtr("Show a timer on the HUD when the car is at a standstill.", "車輛靜止時，在 HUD 顯示停車時間。"),
        None,
      ),
      "RoadNameToggle": (
        lambda: vtr("Display Road Name", "顯示道路名稱"),
        lambda: vtr("Displays the name of the road the car is traveling on.<br>The OpenStreetMap database of the location must be downloaded from the OSM panel to fetch the road name.",
                     "顯示目前行駛道路名稱。<br>必須先從 OSM 頁面下載所在地區的 OpenStreetMap 資料庫，才能取得道路名稱。"),
        None,
      ),
      "GreenLightAlert": (
        lambda: vtr("Green Traffic Light Alert (Beta)", "綠燈提醒（Beta）"),
        lambda: vtr("A chime and on-screen alert will play when the traffic light you are waiting for turns green and you have no vehicle in front of you.<br>Note: This chime is only designed as a notification. It is the driver's responsibility to observe their environment and make decisions accordingly.",
                     "等待中的號誌轉為綠燈且前方沒有車輛時，播放提示音並顯示畫面提醒。<br>注意：此提示僅供通知，駕駛仍須自行觀察環境並做出安全判斷。"),
        None,
      ),
      "LeadDepartAlert": (
        lambda: vtr("Lead Departure Alert (Beta)", "前車起步提醒（Beta）"),
        lambda: vtr("A chime and on-screen alert will play when you are stopped, and the vehicle in front of you start moving.<br>Note: This chime is only designed as a notification. It is the driver's responsibility to observe their environment and make decisions accordingly.",
                     "本車停止且前方車輛開始移動時，播放提示音並顯示畫面提醒。<br>注意：此提示僅供通知，駕駛仍須自行觀察環境並做出安全判斷。"),
        None,
      ),
      "TrueVEgoUI": (
        lambda: vtr("Speedometer: Always Display True Speed", "時速表：永遠顯示實際車速"),
        lambda: vtr("For applicable vehicles, always display the true vehicle current speed from wheel speed sensors.", "適用車型永遠使用輪速感測器資料顯示目前實際車速。"),
        None,
      ),
      "HideVEgoUI": (
        lambda: vtr("Speedometer: Hide from Onroad Screen", "時速表：從行駛畫面隱藏"),
        lambda: vtr("When enabled, the speedometer on the onroad screen is not displayed.", "啟用後，行駛畫面不顯示時速表。"),
        None,
      ),
      "ShowTurnSignals": (
        lambda: vtr("Display Turn Signals", "顯示方向燈"),
        lambda: vtr("When enabled, visual turn indicators are drawn on the HUD.", "啟用後，在 HUD 顯示方向燈指示。"),
        None,
      ),
      "RocketFuel": (
        lambda: vtr("Real-time Acceleration Bar", "即時加減速條"),
        lambda: vtr("Show an indicator on the left side of the screen to display real-time vehicle acceleration and deceleration. This displays what the car is currently doing, not what the planner is requesting.",
                     "在畫面左側顯示車輛即時加速與減速狀態。此資訊代表車輛目前實際動作，而不是規劃器要求的動作。"),
        None,
      ),
    }
    self._toggles = {}
    for param, (title, desc, callback) in self._toggle_defs.items():
      toggle = toggle_item_sp(
        title=title,
        description=desc,
        param=param,
        initial_state=ui_state.params.get_bool(param),
        callback=callback,
      )
      self._toggles[param] = toggle

    self._blindspot_style = multiple_button_item_sp(
      title=lambda: vtr("Blind Spot Warning Style", "盲點警告顯示樣式"),
      description=lambda: vtr("Choose the original small icons beside the speedometer or flashing light bars along the left/right screen edges.",
                               "選擇原本顯示在時速表左右側的小圖示，或改用螢幕左右邊緣閃爍光條顯示。"),
      buttons=[lambda: vtr("Original Icon", "原始小圖示"), lambda: vtr("Edge Light Bars", "側邊光條")],
      param="BlindSpotDisplayStyle",
      button_width=450,
      inline=False,
    )

    self._chevron_info = multiple_button_item_sp(
      title=lambda: vtr("Display Metrics Below Chevron", "前車箭頭下方資訊"),
      description="",
      buttons=[lambda: vtr("Off", "關閉"), lambda: vtr("Distance", "距離"), lambda: vtr("Speed", "速度"), lambda: vtr("Time", "時間"), lambda: vtr("All", "全部")],
      param="ChevronInfo",
      inline=False
    )
    self._dev_ui_info = multiple_button_item_sp(
      title=lambda: vtr("Developer UI", "開發者介面"),
      description=lambda: vtr("Display real-time parameters and metrics from various sources.", "顯示各種來源的即時參數與量測資訊。"),
      buttons=[lambda: vtr("Off", "關閉"), lambda: vtr("Bottom", "下方"), lambda: vtr("Right", "右側"), lambda: vtr("Right & Bottom", "右側與下方")],
      param="DevUIInfo",
      button_width=350,
      inline=False
    )

    self._rainbow_style = multiple_button_item_sp(
      title=lambda: vtr("Tesla Rainbow Mode Style", "Tesla 彩虹模式樣式"),
      description=lambda: vtr("Blue bars animate with actual vehicle acceleration and deceleration. A model-predicted stop is shown for any cause, including traffic lights or stop signs. The model does not identify light colors or sign types.",
                               "藍色動態條會依車輛實際加速與減速變化。模型預測需要停止時會顯示停止提示，不論原因可能是號誌、停止標誌或其他情況；模型本身不會辨識號誌顏色或標誌類型。"),
      buttons=[lambda: vtr("Rainbow Road", "彩虹路徑"), lambda: vtr("Dynamic Blue Bars", "動態藍色條")],
      param="RainbowModeStyle",
      button_width=450,
      inline=False,
    )
    items = list(self._toggles.values())
    items.insert(list(self._toggles).index("BlindSpot") + 1, self._blindspot_style)
    items.insert(items.index(self._toggles["RainbowMode"]) + 1, self._rainbow_style)
    items += [
      self._chevron_info,
      self._dev_ui_info,
    ]
    return items

  def _on_factory_side_display(self, state: bool):
    status = configuration_status(ui_state.CP, state)
    self._params.put(FACTORY_SIDE_DISPLAY_STATUS_PARAM, status.value)

  def _update_state(self):
    super()._update_state()

    for param in self._toggle_defs:
      self._toggles[param].action_item.set_state(self._params.get_bool(param))

    self._blindspot_style.action_item.set_selected_button(int(self._params.get("BlindSpotDisplayStyle", return_default=True)))
    self._blindspot_style.action_item.set_enabled(self._params.get_bool("BlindSpot"))

    hkg_canfd = (ui_state.CP is not None and ui_state.CP.brand == "hyundai" and
                 bool(ui_state.CP.flags & HyundaiFlags.CANFD))
    self._toggles["HkgCornerRadarDetection"].set_visible(hkg_canfd)

    factory_cluster_toggle = self._toggles[FACTORY_SIDE_DISPLAY_PARAM]
    factory_cluster_toggle.set_visible(is_ev6_hda2_candidate(ui_state.CP))
    status = self._params.get(FACTORY_SIDE_DISPLAY_STATUS_PARAM) or FactoryClusterStatus.OFF.value
    status_pair = FACTORY_CLUSTER_STATUS_TEXT.get(str(status), ("Unavailable: unknown state", "無法使用：未知狀態"))
    status_text = vtr(*status_pair)
    factory_cluster_toggle.set_right_value(status_text)
    base_description = vtr(*FACTORY_CLUSTER_DESCRIPTION)
    factory_cluster_toggle.set_description(f"<b>{status_text}</b><br><br>{base_description}")

    self._rainbow_style.action_item.set_selected_button(1 if self._params.get("RainbowModeStyle", return_default=True) == 1 else 0)
    self._rainbow_style.action_item.set_enabled(self._params.get_bool("RainbowMode"))

    self._dev_ui_info.action_item.set_selected_button(ui_state.params.get("DevUIInfo", return_default=True))

    if ui_state.has_longitudinal_control:
      self._chevron_info.set_description(vtr(*CHEVRON_INFO_DESCRIPTION["enabled"]))
      self._chevron_info.action_item.set_selected_button(ui_state.params.get("ChevronInfo", return_default=True))
      self._chevron_info.action_item.set_enabled(True)
    else:
      self._chevron_info.set_description(vtr(*CHEVRON_INFO_DESCRIPTION["disabled"]))
      self._chevron_info.action_item.set_enabled(False)
      ui_state.params.put("ChevronInfo", 0)

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
    if not ui_state.has_longitudinal_control:
      self._chevron_info.set_description(vtr(*CHEVRON_INFO_DESCRIPTION["disabled"]))
      self._chevron_info.show_description(True)
