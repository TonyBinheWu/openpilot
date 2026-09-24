"""Display-only visual options for the comma four (mici) settings."""
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigParamControl
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller import NavScroller


class VisualsLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()
    self._rainbow = BigParamControl("Tesla Rainbow Mode", "RainbowMode", toggle_callback=self._set_rainbow)
    self._style = BigButton("Tesla Rainbow Mode Style")
    self._style.set_click_callback(self._toggle_style)
    self._stop_marker = BigParamControl("Model Predicted Stop Position", "PredictedStopMarker",
                                        toggle_callback=self._set_stop_marker)
    self._scroller.add_widgets([self._rainbow, self._style, self._stop_marker])
    self._refresh()

  @staticmethod
  def _set_rainbow(enabled: bool):
    ui_state.rainbow_path = enabled

  @staticmethod
  def _set_stop_marker(enabled: bool):
    ui_state.predicted_stop_marker = enabled

  def _toggle_style(self):
    if not ui_state.params.get_bool("RainbowMode"):
      return
    new_style = 1 - int(ui_state.params.get("RainbowModeStyle", return_default=True))
    ui_state.params.put("RainbowModeStyle", new_style, block=True)
    ui_state.rainbow_mode_style = new_style
    self._refresh()

  def _refresh(self):
    self._rainbow.refresh()
    self._stop_marker.refresh()
    style = int(ui_state.params.get("RainbowModeStyle", return_default=True))
    self._style.set_value(tr("Dynamic Blue Bars") if style == 1 else tr("Rainbow Road"))
    self._style.set_enabled(ui_state.params.get_bool("RainbowMode"))

  def show_event(self):
    super().show_event()
    self._refresh()

  def _update_state(self):
    super()._update_state()
    self._style.set_enabled(ui_state.params.get_bool("RainbowMode"))
