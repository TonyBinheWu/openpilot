#!/usr/bin/env python3
import os
import sys
import time
import traceback
from pathlib import Path

BOOT_LOG = Path("/tmp/tonypilot_boot.log")
STAGE_FILE = Path("/tmp/tonypilot_boot_stage")


def _tail(path: Path, lines: int = 45) -> str:
  try:
    data = path.read_text(errors="replace").splitlines()
    return "\n".join(data[-lines:])
  except Exception as e:
    return f"<unable to read {path}: {e}>"


def _system_snapshot() -> str:
  out = []
  for path in (Path("/VERSION"), Path("/proc/meminfo")):
    try:
      if path.name == "meminfo":
        vals = path.read_text(errors="replace").splitlines()
        out.append("\n".join(vals[:5]))
      else:
        out.append(f"{path}: {path.read_text(errors='replace').strip()}")
    except Exception:
      pass
  try:
    st = os.statvfs("/data")
    free_gb = st.f_bavail * st.f_frsize / (1024 ** 3)
    total_gb = st.f_blocks * st.f_frsize / (1024 ** 3)
    out.append(f"/data free: {free_gb:.1f} GiB / {total_gb:.1f} GiB")
  except Exception:
    pass
  return "\n".join(out)


def show_error(title: str, detail: str) -> None:
  text = (
    f"{title}\n\n"
    f"{detail}\n\n"
    "System:\n"
    f"{_system_snapshot()}\n\n"
    "Last boot log:\n"
    f"{_tail(BOOT_LOG)}"
  )
  try:
    from openpilot.common.text_window import TextWindow
    with TextWindow(text) as window:
      window.wait_for_exit()
  except Exception:
    traceback.print_exc()
    print(text, flush=True)
    while True:
      time.sleep(60)


def watch(stage_path: str) -> None:
  stage_file = Path(stage_path)
  last_reported = ""
  while True:
    try:
      raw = stage_file.read_text(errors="replace").splitlines()
      if len(raw) >= 3:
        stage = raw[0].strip()
        started = int(raw[1].strip())
        timeout_s = int(raw[2].strip())
        if stage == "complete":
          return
        elapsed = int(time.time()) - started
        key = f"{stage}:{started}"
        if timeout_s > 0 and elapsed >= timeout_s and key != last_reported:
          last_reported = key
          show_error(
            "tonypilot startup appears stalled",
            f"Stage: {stage}\nElapsed: {elapsed}s\nExpected within: {timeout_s}s",
          )
    except Exception:
      pass
    time.sleep(5)


def main() -> None:
  if len(sys.argv) < 2:
    raise SystemExit("usage: boot_diagnostics.py watch <stage_file> | error <title> <detail>")

  if sys.argv[1] == "watch":
    watch(sys.argv[2] if len(sys.argv) > 2 else str(STAGE_FILE))
  elif sys.argv[1] == "error":
    title = sys.argv[2] if len(sys.argv) > 2 else "tonypilot startup error"
    detail = sys.argv[3] if len(sys.argv) > 3 else "Unknown startup error"
    show_error(title, detail)
  else:
    raise SystemExit(f"unknown command: {sys.argv[1]}")


if __name__ == "__main__":
  main()
