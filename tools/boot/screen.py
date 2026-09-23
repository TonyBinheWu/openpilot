#!/usr/bin/env python3
"""Emergency display using pyray's embedded ASCII font, not the application UI."""
import argparse
import json
from pathlib import Path
import signal
import textwrap
import time


def pages(report, columns=61, rows=6):
  tail = report.get("tail", [])
  lines = []
  for line in tail:
    # ASCII fallback deliberately avoids any dependency on downloaded CJK fonts.
    ascii_line = str(line).encode("ascii", "replace").decode()
    lines.extend(textwrap.wrap(ascii_line, columns, replace_whitespace=True) or [""])
  return [lines[i:i + rows] for i in range(0, len(lines), rows)] or [["No console output was captured."]]


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("report", type=Path)
  parser.add_argument("--seconds", type=float, default=0)
  parser.add_argument("--large", action="store_true")
  args = parser.parse_args()
  # Import only at display time. No Params, cereal, model, CAN, or UI app imports.
  import pyray as rl
  report = json.loads(args.report.read_text())
  scale = 3 if args.large else 1
  rl.init_window(536 * scale, 240 * scale, "hkg-enhanced boot diagnostics")
  rl.set_target_fps(10)
  if not rl.is_window_ready():
    raise RuntimeError("pyray could not open the diagnostic display")
  running = True
  def stop(_sig, _frame):
    nonlocal running
    running = False
  signal.signal(signal.SIGTERM, stop)
  signal.signal(signal.SIGINT, stop)
  started = time.monotonic()
  chunks = pages(report)
  page = 0
  next_page = started + 8
  def text(value, y, size, color):
    rl.draw_text(str(value).encode("ascii", "replace").decode()[:76], 10 * scale, y * scale, size * scale, color)
  try:
    while running and not rl.window_should_close():
      now = time.monotonic()
      if args.seconds and now - started >= args.seconds:
        break
      if now >= next_page or rl.is_mouse_button_pressed(0):
        page = (page + 1) % len(chunks)
        next_page = now + 8
      rl.begin_drawing()
      rl.clear_background(rl.BLACK)
      error = report.get("exit_code") not in (None, 0)
      text("hkg-enhanced: STARTUP ERROR" if error else "hkg-enhanced: starting", 8, 23, rl.RED if error else rl.WHITE)
      text(f"Stage: {report.get('stage', 'unknown')} | exit: {report.get('exit_code', '-')}", 39, 16, rl.WHITE)
      text(f"AGNOS: {report.get('agnos', '?')} / required: {report.get('required_agnos', '?')}", 61, 15, rl.WHITE)
      for index, line in enumerate(chunks[page]):
        text(line, 84 + index * 17, 14, rl.WHITE)
      text(f"Page {page + 1}/{len(chunks)} - tap to advance; photograph errors", 192, 13, rl.WHITE)
      text(report.get("log", "/data/boot-diagnostics/boot.log"), 214, 12, rl.WHITE)
      rl.end_drawing()
  finally:
    rl.close_window()


if __name__ == "__main__":
  main()
