"""Display-only blind-spot edge light bars."""
import math
import time

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state


class BlindSpotEdgeRenderer:
  def render(self, rect: rl.Rectangle) -> None:
    if not getattr(ui_state, "blindspot_edge_bars", False):
      return
    sm = ui_state.sm
    if sm.recv_frame["carState"] < ui_state.started_frame:
      return

    car_state = sm["carState"]
    left = bool(car_state.leftBlindspot)
    right = bool(car_state.rightBlindspot)
    if not left and not right:
      return

    # Pulse at roughly 1.5 Hz. Keep a non-zero floor so the warning remains visible
    # through the entire cycle instead of fully disappearing between flashes.
    pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(time.monotonic() * math.tau * 1.5))
    alpha = int(255 * pulse)
    inner_alpha = int(120 * pulse)
    bar_w = max(26, int(rect.width * 0.018))
    bar_h = int(rect.height * 0.58)
    y = int(rect.y + (rect.height - bar_h) / 2)

    if left:
      x = int(rect.x + 4)
      rl.draw_rectangle_gradient_h(x, y, bar_w * 3, bar_h,
                                   rl.Color(255, 70, 20, alpha), rl.Color(255, 120, 30, 0))
      rl.draw_rectangle(x, y, bar_w, bar_h, rl.Color(255, 70, 20, inner_alpha))

    if right:
      x = int(rect.x + rect.width - bar_w * 3 - 4)
      rl.draw_rectangle_gradient_h(x, y, bar_w * 3, bar_h,
                                   rl.Color(255, 120, 30, 0), rl.Color(255, 70, 20, alpha))
      rl.draw_rectangle(int(rect.x + rect.width - bar_w - 4), y, bar_w, bar_h,
                        rl.Color(255, 70, 20, inner_alpha))
