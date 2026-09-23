"""Bootstrap regression tests: fake OS/updater/manager, never flash hardware."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools/hkg_bootstrap.py"
spec = importlib.util.spec_from_file_location("hkg_bootstrap_test_target", HELPER)
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class TestDiagnostic(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.root = Path(self.temp.name)
    self.journal = boot.Journal(self.root / "logs")

  def tearDown(self):
    self.temp.cleanup()

  def test_device_detection_uses_codename_and_product_name(self):
    for text, expected in [("comma mici\x00", "mici"), ("comma four", "mici"),
                           ("comma tizi\x00", "tizi"), ("comma 3X", "tizi"),
                           ("comma tici", "tici"), ("unknown", "unknown")]:
      self.assertEqual(boot.device_type(text), expected)

  def test_helper_imports_without_compiled_openpilot(self):
    modules = {n.names[0].name.split('.')[0] for n in ast.walk(ast.parse(HELPER.read_text())) if isinstance(n, ast.Import)}
    self.assertFalse(modules & {"openpilot", "cereal", "opendbc"})
    self.assertNotIn("TextWindow", HELPER.read_text())

  def test_journal_retains_os_metadata(self):
    self.journal.set("FIRST", "start", device="mici", os_version="18.4", required="19.7")
    self.journal.set("SECOND", "next", exit_code=126)
    data = self.journal.get()
    self.assertEqual(data['required'], '19.7')
    self.assertEqual(data['os_version'], '18.4')
    self.assertEqual(data['stage'], 'SECOND')

  def test_bounded_log_rotation(self):
    with patch.object(boot, 'MAX_LOG', 100):
      for _ in range(10):
        self.journal.append(b'x' * 70)
      self.assertLessEqual(self.journal.log.stat().st_size, 100)
      self.assertLessEqual((self.journal.directory / 'boot.log.1').stat().st_size, 100)

  def test_run_captures_stderr_and_preserves_exit_code(self):
    result = boot.run_command(self.journal, 'BUILD', [sys.executable, '-c',
                              'import sys; print("import failed", file=sys.stderr); sys.exit(23)'])
    self.assertEqual(result, 23)
    self.assertIn('import failed', self.journal.log.read_text())
    self.assertEqual(self.journal.get()['exit_code'], 23)

  def test_run_missing_executable(self):
    self.assertEqual(boot.run_command(self.journal, 'UPDATER', [str(self.root / 'missing')]), 127)

  def test_run_nonexecutable(self):
    f = self.root / 'noexec'
    f.write_text('#!/bin/sh\nexit 0\n')
    self.assertEqual(boot.run_command(self.journal, 'UPDATER', [str(f)]), 126)

  def test_long_command_is_not_killed_or_treated_as_failure(self):
    result = boot.run_command(self.journal, 'AGNOS_UPDATE', [sys.executable, '-c', 'import time; time.sleep(1.1)'], heartbeat=0.05)
    self.assertEqual(result, 0)
    self.assertIn('alive', self.journal.log.read_text())

  def _payload(self, data=b'#!/usr/bin/env python3\nprint("zipapp or script")\n'):
    f = self.root / 'updater'
    f.write_bytes(data)
    f.chmod(0o755)
    pointer = f'version https://git-lfs.github.com/spec/v1\noid sha256:{hashlib.sha256(data).hexdigest()}\nsize {len(data)}\n'
    return f, pointer

  def test_updater_python_payload_is_valid_not_necessarily_elf(self):
    f, pointer = self._payload()
    boot.validate_updater(f, pointer)

  def test_updater_lfs_pointer_rejected(self):
    f, pointer = self._payload(boot.LFS_MAGIC + b'\noid sha256:123\nsize 1\n')
    with self.assertRaisesRegex(ValueError, 'UPDATER_LFS_POINTER'):
      boot.validate_updater(f, pointer)

  def test_updater_hash_mismatch(self):
    f, pointer = self._payload()
    f.write_bytes(b'x' * f.stat().st_size)
    with self.assertRaisesRegex(ValueError, 'UPDATER_HASH_MISMATCH'):
      boot.validate_updater(f, pointer)

  def test_updater_size_mismatch(self):
    f, pointer = self._payload()
    f.write_bytes(b'x')
    with self.assertRaisesRegex(ValueError, 'UPDATER_SIZE_MISMATCH'):
      boot.validate_updater(f, pointer)

  def test_updater_bad_metadata(self):
    f, _ = self._payload()
    with self.assertRaisesRegex(ValueError, 'UPDATER_POINTER_METADATA'):
      boot.validate_updater(f, 'not a pointer')

  def test_updater_missing_and_nonexecutable(self):
    with self.assertRaisesRegex(ValueError, 'UPDATER_MISSING'):
      boot.validate_updater(self.root / 'absent', '')
    f, pointer = self._payload()
    f.chmod(0o644)
    with self.assertRaisesRegex(ValueError, 'UPDATER_NOT_EXECUTABLE'):
      boot.validate_updater(f, pointer)


class TestLauncher(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.base = Path(self.temp.name)
    self.root = self.base / 'checkout'
    self.root.mkdir()
    self.data = self.base / 'data'
    self.data.mkdir()
    self.marker = self.base / 'AGNOS'
    self.version = self.base / 'VERSION'
    self.version.write_text('19.7\n')
    (self.root / 'tools').mkdir()
    (self.root / 'tools/hkg_bootstrap.py').write_bytes(HELPER.read_bytes())
    # Only sandbox literals are replaced; tested production control flow is unchanged.
    script = (ROOT / 'launch_chffrplus.sh').read_text()
    script = script.replace('/data/', str(self.data) + '/').replace('/VERSION', str(self.version)).replace('/AGNOS', str(self.marker))
    # Stop the existing post-manager idle loop in the sandbox only.
    script = script.replace('  while true; do sleep 1; done', '  return 0')
    self.launcher = self.root / 'launch_chffrplus.sh'
    self.launcher.write_text(script)
    (self.root / 'launch_env.sh').write_text('export AGNOS_VERSION=19.7\nexport STAGING_ROOT="' + str(self.data / 'safe_staging') + '"\n')
    for p in ('msgq_repo/msgq', 'opendbc_repo/opendbc', 'rednose_repo/rednose', 'teleoprtc_repo/teleoprtc', 'tinygrad_repo/tinygrad'):
      (self.root / p).mkdir(parents=True)
    self.manager_dir = self.root / 'openpilot/system/manager'
    self.manager_dir.mkdir(parents=True)
    self.bin = self.base / 'bin'
    self.bin.mkdir()
    self.calls = self.base / 'calls'
    self.env = {**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'], 'CALLS': str(self.calls)}
    self._exe(self.bin / 'sudo', 'echo "sudo $*" >> "$CALLS"\nexit 0')
    self._exe(self.bin / 'tmux', 'exit 0')
    self._exe(self.bin / 'sleep', 'exit 0')
    self._exe(self.bin / 'git', 'if [ "$3" = show ]; then cat "' + str(self.root / 'updater.pointer') + '"; else echo sandboxcommit; fi')
    self._exe(self.manager_dir / 'build.py', 'echo "build:${HKG_BOOTSTRAP_CAPTURE:-none}" >> "$CALLS"\nexit 0')
    self._exe(self.manager_dir / 'manager.py', 'echo "manager:${HKG_BOOTSTRAP_CAPTURE:-none}" >> "$CALLS"\nexit 0')
    self._exe(self.root / 'openpilot/common/hardware/comma/agnos.py', 'echo verify >> "$CALLS"\nexit 1')
    self._updater(1)
    manifest = self.root / 'openpilot/system/hardware/comma/agnos.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[]')

  def tearDown(self):
    self.temp.cleanup()

  def _exe(self, p, body):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('#!/usr/bin/env bash\n' + body + '\n')
    p.chmod(0o755)

  def _updater(self, code):
    p = self.root / 'openpilot/common/hardware/comma/updater'
    self._exe(p, f'echo update >> "$CALLS"\necho "Updater error: simulated graphics failure" >&2\nexit {code}')
    content = p.read_bytes()
    (self.root / 'updater.pointer').write_text('version https://git-lfs.github.com/spec/v1\n' +
           f'oid sha256:{hashlib.sha256(content).hexdigest()}\nsize {len(content)}\n')

  def _run(self):
    result = subprocess.run(['bash', str(self.launcher)], cwd=self.base, env=self.env, capture_output=True, text=True, timeout=15)
    self.output = result.stdout + result.stderr
    self.call_text = self.calls.read_text() if self.calls.exists() else ''
    self.state = json.loads((self.data / 'hkg_boot/state.json').read_text())
    return result.returncode

  def test_equal_version_does_not_run_updater(self):
    self.marker.touch()
    self.assertEqual(self._run(), 0, self.output)
    self.assertNotIn('verify', self.call_text)
    self.assertNotIn('update\n', self.call_text)
    self.assertIn('build:1', self.call_text)
    self.assertIn('manager:none', self.call_text)

  def test_caller_cwd_does_not_change_package_links(self):
    self.assertEqual(self._run(), 0, self.output)
    self.assertEqual((self.data / 'pythonpath').resolve(), self.root)
    self.assertEqual((self.root / 'opendbc').resolve(), self.root / 'opendbc_repo/opendbc')

  def test_build_failure_never_starts_manager(self):
    self._exe(self.manager_dir / 'build.py', 'echo "build failed" >&2\nexit 23')
    self.assertNotEqual(self._run(), 0)
    self.assertNotIn('manager', self.call_text)
    self.assertEqual(self.state['stage'], 'SUNNYPILOT_BUILD_FAILED')
    self.assertIn('build failed', (self.data / 'hkg_boot/boot.log').read_text())

  def test_missing_submodule_stops_before_build(self):
    (self.root / 'opendbc_repo/opendbc').rmdir()
    self.assertNotEqual(self._run(), 0)
    self.assertEqual(self.state['stage'], 'SUBMODULE_MISSING_opendbc')
    self.assertNotIn('build', self.call_text)

  def test_updater_failure_runs_once_and_never_starts_build(self):
    self.marker.touch()
    self.version.write_text('18.4\n')
    self.assertNotEqual(self._run(), 0)
    self.assertEqual(self.call_text.count('update\n'), 1)
    self.assertNotIn('build:', self.call_text)
    self.assertNotIn('manager:', self.call_text)
    self.assertEqual(self.state['stage'], 'AGNOS_UPDATER_FAILED')

  def test_zero_exit_updater_cannot_bypass_os_requirement(self):
    self.marker.touch()
    self.version.write_text('18.4\n')
    self._updater(0)
    self.assertNotEqual(self._run(), 0)
    self.assertEqual(self.call_text.count('update\n'), 1)
    self.assertEqual(self.state['stage'], 'AGNOS_UPDATER_RETURNED_WITHOUT_REBOOT')
    self.assertNotIn('build:', self.call_text)

  def test_verified_target_requests_reboot_without_build(self):
    self.marker.touch()
    self.version.write_text('18.4\n')
    self._exe(self.root / 'openpilot/common/hardware/comma/agnos.py', 'echo verify >> "$CALLS"\nexit 0')
    self.assertNotEqual(self._run(), 0)
    self.assertIn('sudo reboot', self.call_text)
    self.assertNotIn('update\n', self.call_text)
    self.assertNotIn('build:', self.call_text)

  def test_updater_pointer_stops_before_any_flash(self):
    self.marker.touch()
    self.version.write_text('18.4\n')
    (self.root / 'openpilot/common/hardware/comma/updater').write_text((self.root / 'updater.pointer').read_text())
    self.assertNotEqual(self._run(), 0)
    self.assertEqual(self.state['stage'], 'AGNOS_UPDATER_INVALID')
    self.assertNotIn('verify', self.call_text)
    self.assertIn('UPDATER_LFS_POINTER', (self.data / 'hkg_boot/boot.log').read_text())

  def test_version_file_missing_never_bypasses_requirement(self):
    self.marker.touch()
    self.version.unlink()
    self.assertNotEqual(self._run(), 0)
    self.assertEqual(self.state['stage'], 'AGNOS_VERSION_UNREADABLE')
    self.assertNotIn('build:', self.call_text)

  def test_no_watchdog_after_manager_handoff(self):
    self.assertEqual(self._run(), 0, self.output)
    self.assertEqual(self.state['stage'], 'MANAGER_EXITED_CLEANLY')
    script = self.launcher.read_text()
    self.assertNotIn('watchdog', script.split('  ./manager.py')[1])
    self.assertNotIn('watch ', script)


if __name__ == '__main__':
  unittest.main()
