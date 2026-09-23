"""Host-only regression tests. OS, reboot, updater and manager calls are all mocked."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("boot", ROOT / "tools/boot/bootstrap.py")
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class DiagnosticTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)

  def binary(self, content, executable=True):
    path = self.root / "updater"
    path.write_bytes(content)
    path.chmod(0o700 if executable else 0o600)
    return path

  def test_missing_binary(self):
    self.assertIn("Missing", boot.executable_problem(self.root / "missing", elf=True))

  def test_lfs_pointer(self):
    self.assertIn("LFS pointer", boot.executable_problem(self.binary(boot.LFS_MAGIC + b"\n"), elf=True))

  def test_bad_mode(self):
    self.assertIn("permission", boot.executable_problem(self.binary(b"abc", False)))

  def test_invalid_elf(self):
    self.assertIn("ELF", boot.executable_problem(self.binary(b"not a binary"), elf=True))

  def test_arm64_elf(self):
    elf = bytearray(64)
    elf[:6] = b"\x7fELF\x02\x01"
    elf[18:20] = (183).to_bytes(2, "little")
    self.assertIsNone(boot.executable_problem(self.binary(elf), elf=True))

  def test_wrong_architecture(self):
    elf = bytearray(64)
    elf[:6] = b"\x7fELF\x02\x01"
    elf[18:20] = (62).to_bytes(2, "little")
    self.assertIn("AArch64", boot.executable_problem(self.binary(elf), elf=True))

  def test_kernel_device_name(self):
    path = self.root / "model"
    path.write_bytes(b"comma mici\0")
    self.assertEqual(boot.device_type(path), "mici")
    path.write_bytes(b"comma tizi\0")
    self.assertEqual(boot.device_type(path), "tizi")

  def test_redaction(self):
    result = boot.scrub("password=abc access_token=def https://name:secret@example.com/file")
    for value in ("abc", "def", "name:secret"):
      self.assertNotIn(value, result)

  def test_log_is_bounded(self):
    log = boot.BootLog(self.root, limit=64)
    for _ in range(12):
      log.write("x" * 60 + "\n")
    log.close()
    files = list(self.root.glob("boot.log*"))
    self.assertLessEqual(len(files), 3)
    self.assertTrue(all(p.stat().st_size <= 64 for p in files))

  def test_storage_failure_does_not_raise(self):
    log = boot.BootLog(self.root)
    self.addCleanup(log.close)
    with patch.object(log, "rotate", side_effect=OSError("disk full")):
      log.limit = 1
      log.write("still updating")
    self.assertIsNone(log.stream)

  def test_missing_os_version_is_rejected(self):
    errors = boot.preflight(self.root, True, "unavailable")
    self.assertTrue(any("/VERSION" in x for x in errors))

  def test_capture_reports_real_exit_and_stderr(self):
    log = boot.BootLog(self.root)
    self.addCleanup(log.close)
    state, report = self.root / "stage", self.root / "status.json"
    state.write_text("agnos-update\n")
    cmd = [sys.executable, "-c", "import sys; print('updater test failure',file=sys.stderr); sys.exit(7)"]
    result, interrupted = boot.capture(cmd, self.root, os.environ.copy(), log, state, report)
    self.assertEqual(result, 7)
    self.assertFalse(interrupted)
    data = json.loads(report.read_text())
    self.assertEqual(data["stage"], "agnos-update")
    self.assertIn("updater test failure", log.path.read_text())

  def test_capture_zero_is_not_an_error(self):
    log = boot.BootLog(self.root)
    self.addCleanup(log.close)
    result, _ = boot.capture([sys.executable, "-c", "pass"], self.root, os.environ.copy(), log,
                              self.root / "stage", self.root / "report")
    self.assertEqual(result, 0)

  def test_signal_handler_restored(self):
    log = boot.BootLog(self.root)
    self.addCleanup(log.close)
    before = signal.getsignal(signal.SIGTERM)
    boot.capture([sys.executable, "-c", "pass"], self.root, os.environ.copy(), log,
                 self.root / "stage", self.root / "report")
    self.assertEqual(signal.getsignal(signal.SIGTERM), before)

  def test_emergency_renderer_has_no_openpilot_imports(self):
    import ast
    for name in ("bootstrap.py", "screen.py"):
      tree = ast.parse((ROOT / "tools/boot" / name).read_text())
      for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
          self.assertFalse((node.module or "").startswith(("openpilot", "cereal", "opendbc")))


class LauncherTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)
    self.bin = self.root / "bin"
    self.bin.mkdir()
    self.calls = self.root / "calls"
    self.manager_dir = self.root / "openpilot/system/manager"
    self.manager_dir.mkdir(parents=True)
    self.agnos_dir = self.root / "openpilot/common/hardware/comma"
    self.agnos_dir.mkdir(parents=True)
    (self.root / "openpilot/system/hardware/comma").mkdir(parents=True)
    (self.root / "openpilot/system/hardware/comma/agnos.json").write_text("[]")
    (self.root / "AGNOS").touch()
    (self.root / "VERSION").write_text("19.7\n")
    (self.root / "data").mkdir()
    (self.root / "tmp").mkdir()
    (self.root / "launch_env.sh").write_text('export AGNOS_VERSION="19.7"\nexport STAGING_ROOT="' + str(self.root / "staging") + '"\n')
    source = (ROOT / "launch_chffrplus.sh").read_text()
    # Rewrite absolute test paths in a TEMPORARY copy, never in production.
    for old, new in (("/data/", str(self.root / "data") + "/"), ("/tmp/launch_log", str(self.root / "tmp/launch_log")),
                     ("/AGNOS", str(self.root / "AGNOS")), ("/VERSION", str(self.root / "VERSION"))):
      source = source.replace(old, new)
    self.script = self.root / "launch_chffrplus.sh"
    self.script.write_text(source)
    self.make(self.bin / "sudo", 'echo "sudo $*" >> "$CALLS"\n[ "$1" != reboot ]\n')
    self.make(self.bin / "tmux", 'exit 0\n')
    # ELF validation is independently tested above; fake updater here is a shell stub.
    self.make(self.bin / "python3", 'echo preflight >> "$CALLS"\nexit "${PREFLIGHT_EXIT:-0}"\n')
    self.make(self.agnos_dir / "agnos.py", 'echo verify >> "$CALLS"\nexit "${VERIFY_EXIT:-1}"\n')
    self.make(self.agnos_dir / "updater", 'echo updater >> "$CALLS"\nexit "${UPDATER_EXIT:-1}"\n')
    self.make(self.manager_dir / "build.py", 'echo build >> "$CALLS"\nexit "${BUILD_EXIT:-0}"\n')
    self.make(self.manager_dir / "manager.py", 'echo manager >> "$CALLS"\nexit 7\n')

  def make(self, path, code):
    path.write_text("#!/bin/bash\n" + code)
    path.chmod(0o700)

  def run_launcher(self, version="19.7", **settings):
    (self.root / "VERSION").write_text(version + "\n")
    env = dict(os.environ, CALLS=str(self.calls), PATH=str(self.bin) + ":" + os.environ["PATH"],
               HKG_BOOT_STAGE=str(self.root / "stage"), **settings)
    result = subprocess.run(["bash", str(self.script)], cwd="/", env=env, capture_output=True, text=True, timeout=4)
    calls = self.calls.read_text().splitlines() if self.calls.exists() else []
    return result, calls

  def test_current_os_does_not_call_updater(self):
    result, calls = self.run_launcher()
    self.assertEqual(result.returncode, 7)
    self.assertIn("build", calls)
    self.assertIn("manager", calls)
    self.assertNotIn("updater", calls)

  def test_build_failure_never_starts_manager(self):
    result, calls = self.run_launcher(BUILD_EXIT="3")
    self.assertEqual(result.returncode, 3)
    self.assertNotIn("manager", calls)

  def test_mismatch_does_not_bypass_os_requirement(self):
    result, calls = self.run_launcher("18.4", UPDATER_EXIT="9")
    self.assertEqual(result.returncode, 9)
    self.assertEqual(calls.count("updater"), 1)
    self.assertNotIn("build", calls)
    self.assertNotIn("manager", calls)

  def test_updater_success_without_verification_stops(self):
    result, calls = self.run_launcher("18.4", UPDATER_EXIT="0")
    self.assertEqual(result.returncode, 44)
    self.assertEqual(calls.count("verify"), 2)
    self.assertNotIn("build", calls)

  def test_verified_update_requests_reboot(self):
    result, calls = self.run_launcher("18.4", VERIFY_EXIT="0")
    self.assertIn("sudo reboot", calls)
    self.assertEqual(result.returncode, 43)  # mock intentionally rejects real reboot
    self.assertNotIn("updater", calls)
    self.assertNotIn("build", calls)

  def test_bad_updater_rejected_before_verify(self):
    result, calls = self.run_launcher("18.4", PREFLIGHT_EXIT="42")
    self.assertEqual(result.returncode, 42)
    self.assertNotIn("verify", calls)
    self.assertNotIn("updater", calls)

  def test_prebuilt_still_skips_compilation(self):
    (self.root / "prebuilt").touch()
    result, calls = self.run_launcher()
    self.assertEqual(result.returncode, 7)
    self.assertNotIn("build", calls)
    self.assertIn("manager", calls)


if __name__ == "__main__":
  unittest.main()
