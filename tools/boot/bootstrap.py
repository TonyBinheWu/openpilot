#!/usr/bin/env python3
"""Pre-build diagnostics. Standard library only; never imports vehicle/UI modules."""
import argparse
from collections import deque
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time

LIMIT = 2 * 1024 * 1024
LFS_MAGIC = b"version https://git-lfs.github.com/spec/v1"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SECRET = re.compile(r"(?i)((?:access[_-]?token|authorization|password|secret)\s*[=:]\s*)[^\s,}]+")


def scrub(text):
  text = ANSI.sub("", text)
  text = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[redacted]@", text)
  return SECRET.sub(r"\1[redacted]", text)


def atomic_json(path, value):
  tmp = path.with_name(path.name + ".new")
  try:
    tmp.write_text(json.dumps(value, ensure_ascii=True) + "\n")
    tmp.replace(path)
  except OSError as error:
    print(f"[hkg-boot] Cannot save diagnostic status: {error}", flush=True)


def read_text(path):
  try:
    return path.read_text(errors="replace").strip("\x00\n ")
  except OSError:
    return "unavailable"


def device_type(path=Path("/sys/firmware/devicetree/base/model")):
  # Kernel names are 'comma mici'/'comma tizi', not the retail product names.
  return read_text(path).removeprefix("comma ")


def executable_problem(path, elf=False):
  try:
    with path.open("rb") as f:
      header = f.read(64)
  except OSError as error:
    return f"Missing/unreadable executable: {path}: {error}"
  if header.startswith(LFS_MAGIC):
    return f"Unresolved Git LFS pointer (not a binary): {path}"
  if not os.access(path, os.X_OK):
    return f"Executable permission missing: {path}"
  if elf and header[:4] != b"\x7fELF":
    return f"Invalid updater: expected an ELF binary: {path}"
  if elf and (len(header) < 20 or header[4:6] != b"\x02\x01" or int.from_bytes(header[18:20], "little") != 183):
    return f"Invalid updater: expected a 64-bit little-endian AArch64 ELF: {path}"
  return None


def preflight(root, agnos, version):
  problems = []
  for relative in ("launch_chffrplus.sh", "openpilot/system/manager/build.py", "openpilot/system/manager/manager.py"):
    problem = executable_problem(root / relative)
    if problem:
      problems.append(problem)
  if agnos:
    if not version or version == "unavailable":
      problems.append("Cannot read /VERSION; refusing to guess the running AGNOS version")
    # Check the binary when the launcher requests an OS update, not on every boot.
  return problems


class BootLog:
  """Bounded local logs: current + two rotated files, no network uploads."""
  def __init__(self, folder, limit=LIMIT):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    self.path = folder / "boot.log"
    self.limit = limit
    self.stream = None
    self.size = 0
    self.lines = deque(maxlen=12)
    self.rotate()

  def rotate(self):
    if self.stream:
      self.stream.close()
    old = self.path.with_name("boot.log.1")
    if old.exists():
      old.replace(self.path.with_name("boot.log.2"))
    if self.path.exists():
      self.path.replace(old)
    self.stream = self.path.open("wb")
    os.chmod(self.path, 0o600)
    self.size = 0

  def write(self, text):
    text = scrub(text)
    self.lines.extend(text.splitlines())
    raw = text.encode("utf-8", "replace")
    try:
      if self.stream is None:
        return
      if self.size + len(raw) > self.limit:
        self.rotate()
      raw = raw[-self.limit:]
      self.stream.write(raw)
      self.stream.flush()
      self.size += len(raw)
    except OSError as error:
      # Diagnostic storage failure must never interrupt an active OS update.
      print(f"[hkg-boot] Log storage unavailable: {error}", flush=True)
      try:
        self.stream.close()
      except OSError:
        pass
      self.stream = None

  def close(self):
    if self.stream:
      self.stream.close()


def show_screen(report_path, root, seconds=0):
  if not Path("/AGNOS").exists():
    return
  cmd = [sys.executable, str(root / "tools/boot/screen.py"), str(report_path)]
  if seconds:
    cmd += ["--seconds", str(seconds)]
  try:
    # No openpilot imports, downloaded fonts, params, or compiled extensions.
    proc = subprocess.Popen(cmd)
    if seconds:
      try:
        proc.wait(timeout=seconds + 5)
      except subprocess.TimeoutExpired:
        proc.terminate()
        try:
          proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
          proc.kill()
          proc.wait()
    else:
      proc.wait()
  except (OSError, KeyboardInterrupt) as error:
    print(f"[hkg-boot] Diagnostic display unavailable: {error}", flush=True)


def capture(command, cwd, env, log, state_file, report_path):
  """Capture early errors without imposing a timeout on flashing or compilation."""
  child = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  stopped = []
  previous = {}
  def forward(signum, _frame):
    stopped.append(signum)
    if child.poll() is None:
      child.send_signal(signum)
  for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    previous[sig] = signal.signal(sig, forward)
  poller = selectors.DefaultSelector()
  poller.register(child.stdout, selectors.EVENT_READ)
  pending = b""
  stage = "launcher"
  manager_since = None
  try:
    while True:
      state = read_text(state_file)
      if state != "unavailable":
        stage = state.splitlines()[0][:160]
      # No manager timeout or automatic error window while a manager is running.
      if stage == "manager" and manager_since is None:
        manager_since = time.monotonic()
      save_output = manager_since is None or time.monotonic() - manager_since < 60
      for key, _mask in poller.select(timeout=0.25):
        chunk = os.read(key.fd, 8192)
        if not chunk:
          poller.unregister(key.fileobj)
          continue
        try:
          sys.stdout.buffer.write(chunk)
          sys.stdout.buffer.flush()
        except (BrokenPipeError, OSError):
          pass
        pending += chunk
        while b"\n" in pending or len(pending) > 16384:
          if b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
          else:
            line, pending = pending[:16384], pending[16384:]
          if save_output:
            log.write(line.decode("utf-8", "replace") + "\n")
      result = child.poll()
      if result is not None:
        # A descendant holding the pipe must not make diagnostics hang forever.
        if not poller.get_map():
          break
        readable = poller.select(timeout=0.1)
        if not readable:
          break
    if pending:
      log.write(pending.decode("utf-8", "replace"))
    result = child.wait()
    log.write(f"\n[hkg-boot] stage={stage} launcher_exit={result}\n")
    report = {"stage": stage, "exit_code": result, "interrupted": bool(stopped),
              "agnos": read_text(Path("/VERSION")), "required_agnos": env.get("AGNOS_VERSION", "see launch_env.sh"),
              "model": device_type(), "log": str(log.path), "tail": list(log.lines)}
    atomic_json(report_path, report)
    return result, bool(stopped)
  finally:
    poller.close()
    child.stdout.close()
    for sig, handler in previous.items():
      signal.signal(sig, handler)


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("root", type=Path)
  parser.add_argument("--log-dir", type=Path, default=Path("/data/boot-diagnostics"))
  parser.add_argument("--check-updater", type=Path)
  args = parser.parse_args()
  if args.check_updater:
    problem = executable_problem(args.check_updater, elf=True)
    if problem:
      print(problem, flush=True)
      return 42
    return 0
  root = args.root.resolve()
  try:
    log = BootLog(args.log_dir)
  except OSError:
    try:
      log = BootLog(Path("/tmp/hkg-boot-diagnostics"))
    except OSError:
      print("[hkg-boot] Diagnostic storage unavailable; continuing with the launcher", flush=True)
      os.execv("/bin/bash", ["bash", str(root / "launch_chffrplus.sh")])
  report = log.path.parent / "status.json"
  state = log.path.parent / "stage"
  state.write_text("preflight\n")
  env = dict(os.environ, PYTHONUNBUFFERED="1", HKG_BOOT_STAGE=str(state), HKG_BOOT_ACTIVE="1")
  version = read_text(Path("/VERSION"))
  log.write(f"[hkg-boot] root={root}\nmodel={device_type()}\nAGNOS={version}\n")
  try:
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], timeout=5, text=True).strip()
    log.write(f"commit={revision}\n")
  except (OSError, subprocess.SubprocessError):
    pass
  problems = preflight(root, Path("/AGNOS").exists(), version)
  if problems:
    for problem in problems:
      log.write(problem + "\n")
    atomic_json(report, {"stage": "preflight", "exit_code": 42, "agnos": version,
                         "log": str(log.path), "tail": list(log.lines)})
    show_screen(report, root)
    log.close()
    return 42
  atomic_json(report, {"stage": "preflight", "exit_code": None, "agnos": version,
                       "required_agnos": env.get("AGNOS_VERSION", "see launch_env.sh"),
                       "log": str(log.path), "tail": list(log.lines)})
  show_screen(report, root, seconds=1)
  try:
    result, interrupted = capture(["bash", str(root / "launch_chffrplus.sh")], root, env, log, state, report)
    if result and not interrupted:
      show_screen(report, root)
    return result if result >= 0 else 128 - result
  except OSError as error:
    log.write(f"launcher OS error: {error}\n")
    atomic_json(report, {"stage": "launcher", "exit_code": 127, "agnos": version,
                         "log": str(log.path), "tail": list(log.lines)})
    show_screen(report, root)
    return 127
  finally:
    log.close()


if __name__ == "__main__":
  sys.exit(main())
