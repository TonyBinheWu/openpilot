#!/usr/bin/env python3
"""Pre-build diagnostics. No cereal, Params, openpilot UI or CAN imports.

The optional screen uses pyray's built-in ASCII font, so missing translated
fonts or unbuilt extensions cannot break error formatting. No OS version,
partition, Panda firmware or safety setting is changed by this helper.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import textwrap
import time

MAX_LOG = 2 * 1024 * 1024
LFS_MAGIC = b"version https://git-lfs.github.com/spec/v1"


def read_text(path):
  try:
    return Path(path).read_text(errors="replace").strip().strip("\x00")
  except OSError:
    return "unknown"


def device_type(model):
  name = model.lower().strip().strip("\x00")
  if name in ("comma mici", "comma four", "mici"):
    return "mici"
  if name in ("comma tizi", "comma 3x", "tizi"):
    return "tizi"
  if name in ("comma tici", "comma three", "tici"):
    return "tici"
  return "unknown"


class Journal:
  def __init__(self, directory):
    self.directory = Path(directory)
    self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    self.log = self.directory / "boot.log"
    self.state = self.directory / "state.json"

  def append(self, data):
    if isinstance(data, str):
      data = data.encode("utf-8", "replace")
    try:
      if self.log.exists() and self.log.stat().st_size + len(data) > MAX_LOG:
        self.log.replace(self.directory / "boot.log.1")
      with self.log.open("ab") as stream:
        stream.write(data[-MAX_LOG:])
    except OSError as error:
      print(f"HKG_BOOT: cannot persist log: {error}", file=sys.stderr)

  def get(self):
    try:
      return json.loads(self.state.read_text())
    except (OSError, ValueError):
      return {}

  def set(self, stage, detail="", **extra):
    state = self.get()
    state.update(stage=stage, detail=detail, timestamp=time.time(), **extra)  # noqa: TID251 - journal wall-clock only
    tmp = self.state.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=True))
    tmp.replace(self.state)

  def tail(self, count=12):
    try:
      with self.log.open("rb") as stream:
        stream.seek(max(0, self.log.stat().st_size - 8192))
        return stream.read().decode("utf-8", "replace").splitlines()[-count:]
    except OSError:
      return []


def validate_updater(path, pointer):
  """Compare with this checkout's own LFS pointer; do not assume ELF."""
  path = Path(path)
  if not path.is_file():
    raise ValueError("UPDATER_MISSING: " + str(path))
  with path.open("rb") as stream:
    head = stream.read(160)
  if head.startswith(LFS_MAGIC):
    raise ValueError("UPDATER_LFS_POINTER: large file was not downloaded")
  if not os.access(path, os.X_OK):
    raise ValueError("UPDATER_NOT_EXECUTABLE")
  fields = dict(line.split(" ", 1) for line in pointer.splitlines() if " " in line)
  oid = fields.get("oid", "")
  if not oid.startswith("sha256:") or "size" not in fields:
    raise ValueError("UPDATER_POINTER_METADATA_UNAVAILABLE")
  if path.stat().st_size != int(fields["size"]):
    raise ValueError("UPDATER_SIZE_MISMATCH")
  with path.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
  if digest != oid.removeprefix("sha256:"):
    raise ValueError("UPDATER_HASH_MISMATCH")


def run_command(journal, stage, command, heartbeat=30.0):
  """Record output/exit codes. Never time out or kill an OS flash or build."""
  started = time.monotonic()
  journal.set(stage, "command starting", elapsed=0, exit_code=None)
  journal.append(f"\n[HKG_BOOT] {stage} start\n")
  try:
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  except OSError as error:
    code = 127 if isinstance(error, FileNotFoundError) else 126
    journal.append(f"{type(error).__name__}: {error}\n")
    journal.set(stage, str(error), exit_code=code)
    return code

  old_handlers = {}
  def forward(signum, _frame):
    # Forward service shutdown; do not create a new process group or orphan it.
    if proc.poll() is None:
      proc.send_signal(signum)
  for sig in (signal.SIGTERM, signal.SIGINT):
    old_handlers[sig] = signal.signal(sig, forward)
  selector = selectors.DefaultSelector()
  try:
    selector.register(proc.stdout, selectors.EVENT_READ)
    last_update = started
    while selector.get_map():
      for key, _ in selector.select(timeout=1.0):
        data = os.read(key.fd, 4096)
        if not data:
          selector.unregister(key.fileobj)
          continue
        journal.append(data)
        try:
          sys.stdout.buffer.write(data)
          sys.stdout.buffer.flush()
        except (BrokenPipeError, AttributeError, OSError):
          pass
      now = time.monotonic()
      if now - last_update >= heartbeat:
        elapsed = int(now - started)
        journal.set(stage, "still running; elapsed time is not an error", elapsed=elapsed, pid=proc.pid)
        journal.append(f"\n[HKG_BOOT] {stage}: alive {elapsed}s\n")
        last_update = now
    code = proc.wait()
    code = code if code >= 0 else 128 - code
    journal.set(stage, "command returned", exit_code=code, elapsed=int(time.monotonic() - started))
    journal.append(f"\n[HKG_BOOT] {stage} exit={code}\n")
    return code
  finally:
    selector.close()
    proc.stdout.close()
    for sig, handler in old_handlers.items():
      signal.signal(sig, handler)


def screen(journal, seconds=0):
  """Only called before handoff or after a failed pre-manager step.

  No watchdog is left running while manager/UI/vehicle controls are active.
  Screen availability still depends on the installed pyray/display driver.
  """
  if not Path("/AGNOS").exists():
    return
  import pyray as rl  # Intentionally the only non-stdlib import, deferred.
  state = journal.get()
  small = state.get("device") not in ("tici", "tizi")
  width, height = (536, 240) if small else (2160, 1080)
  size, spacing = (20, 25) if small else (52, 64)
  running = True
  def stop(_sig, _frame):
    nonlocal running
    running = False
  signal.signal(signal.SIGTERM, stop)
  signal.signal(signal.SIGINT, stop)
  rl.init_window(width, height, "HKG bootstrap diagnostic")
  started = time.monotonic()
  page = 0
  try:
    rl.set_target_fps(10)
    while running and not rl.window_should_close():
      state = journal.get()
      summary = [
        "HKG BOOT: " + state.get("stage", "unknown"),
        "Device: " + state.get("device", "unknown") + "  " + state.get("commit", "unknown")[:8],
        "AGNOS " + state.get("os_version", "unknown") + " -> " + state.get("required", "unknown"),
        state.get("detail", ""),
        "Log: " + str(journal.log),
        "Tap for log / summary. No auto reboot.",
      ]
      lines = summary if page == 0 else ["BOOT LOG (tap to return)", *journal.tail(16)]
      wrapped = []
      for line in lines:
        clean = line.encode("ascii", "replace").decode().replace("\x1b", "?")
        wrapped.extend(textwrap.wrap(clean, width=46 if small else 70) or [""])
      count = (height - 16) // spacing
      # Error tail pages auto-page so a long traceback is not hidden.
      pages = max(1, (len(wrapped) + count - 1) // count)
      offset = int((time.monotonic() - started) / 7) % pages * count
      rl.begin_drawing()
      rl.clear_background(rl.BLACK)
      for i, line in enumerate(wrapped[offset:offset + count]):
        rl.draw_text(line, 8, 8 + spacing * i, size, rl.WHITE)  # noqa: TID251 - built-in font, before app UI
      rl.end_drawing()
      if rl.is_mouse_button_pressed(0):  # noqa: TID251 - standalone screen, no Widget dependency
        page = 1 - page
        started = time.monotonic()
      if seconds > 0 and time.monotonic() - started >= seconds:
        break
  finally:
    rl.close_window()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--directory", default="/data/hkg_boot")
  sub = parser.add_subparsers(dest="action", required=True)
  init = sub.add_parser("init")
  init.add_argument("root")
  init.add_argument("required")
  mark = sub.add_parser("mark")
  mark.add_argument("stage")
  mark.add_argument("detail", nargs="?", default="")
  execute = sub.add_parser("run")
  execute.add_argument("stage")
  execute.add_argument("command", nargs=argparse.REMAINDER)
  check = sub.add_parser("check-updater")
  check.add_argument("root")
  view = sub.add_parser("screen")
  view.add_argument("--seconds", type=float, default=0)
  args = parser.parse_args()
  journal = Journal(args.directory)
  if args.action == "init":
    if journal.log.exists():
      journal.log.replace(journal.directory / "previous-boot.log")
    result = subprocess.run(["git", "-C", args.root, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
    journal.set("BOOTSTRAP_READY", "launcher reached; checking upstream requirements",
                device=device_type(read_text("/sys/firmware/devicetree/base/model")),
                os_version=read_text("/VERSION"), required=args.required,
                commit=result.stdout.strip(), pid=os.getppid())
    journal.append(json.dumps(journal.get()) + "\n")
  elif args.action == "mark":
    journal.set(args.stage, args.detail)
    journal.append(f"[HKG_BOOT] {args.stage}: {args.detail}\n")
  elif args.action == "run":
    if not args.command:
      parser.error("run needs a command")
    return run_command(journal, args.stage, args.command)
  elif args.action == "check-updater":
    relative = "openpilot/common/hardware/comma/updater"
    result = subprocess.run(["git", "-C", args.root, "show", f"HEAD:{relative}"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
      raise ValueError("UPDATER_POINTER_METADATA_UNAVAILABLE")
    validate_updater(Path(args.root) / relative, result.stdout)
    journal.append("[HKG_BOOT] upstream updater LFS size/hash/executable verified\n")
  elif args.action == "screen":
    screen(journal, args.seconds)
  return 0


if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception as error:
    print(f"HKG_BOOT_DIAGNOSTIC_ERROR: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
    sys.exit(1)
