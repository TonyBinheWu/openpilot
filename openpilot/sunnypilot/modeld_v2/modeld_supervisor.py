#!/usr/bin/env python3
from __future__ import annotations

import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import openpilot.cereal.messaging as messaging
from openpilot.common.basedir import BASEDIR
from openpilot.common.file_chunker import get_chunk_name, get_manifest_path
from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.modeld.helpers import chestnut_present
from openpilot.sunnypilot.models.helpers import get_selected_bundle
from openpilot.sunnypilot.models.model_name import DEFAULT_MODEL_REF

STARTUP_TIMEOUT = 75.0
HEARTBEAT_TIMEOUT = 5.0
HEALTHY_FRAMES = 5
BAD_POSE_FRAMES = 5

_child: subprocess.Popen | None = None
_shutdown_requested = False


def _signal_handler(signum, _frame):
  global _shutdown_requested
  _shutdown_requested = True
  if _child is not None and _child.poll() is None:
    try:
      _child.send_signal(signum)
    except ProcessLookupError:
      pass


def _terminate_child() -> None:
  global _child
  if _child is None or _child.poll() is not None:
    return
  try:
    _child.terminate()
    _child.wait(timeout=2.0)
  except subprocess.TimeoutExpired:
    _child.kill()
    _child.wait(timeout=2.0)
  except ProcessLookupError:
    pass


def _queue_bundle_ref(params: Params, ref: str | None) -> None:
  if ref and params.get("ModelManager_DownloadRef") is None:
    params.put("ModelManager_DownloadRef", ref, block=True)


def _bundle_files_present(bundle) -> tuple[bool, str]:
  if bundle is None or not bundle.models:
    return False, "bundle is not selected"

  root = Paths.model_root()
  for model in bundle.models:
    artifact = model.artifact
    if not artifact.fileName:
      continue
    base_path = os.path.join(root, artifact.fileName)
    if len(artifact.chunks) > 0:
      manifest = get_manifest_path(base_path)
      if not os.path.isfile(manifest):
        return False, f"missing manifest: {artifact.fileName}"
      count = len(artifact.chunks)
      for i in range(count):
        chunk_path = get_chunk_name(base_path, i, count)
        if not os.path.isfile(chunk_path):
          return False, f"missing chunk {i + 1}/{count}: {artifact.fileName}"
    elif not os.path.isfile(base_path):
      return False, f"missing model artifact: {artifact.fileName}"
  return True, "ok"


def _preflight(params: Params) -> tuple[bool, str]:
  has_chestnut = chestnut_present()
  if has_chestnut:
    big_bundle = get_selected_bundle(params, "chestnut")
    ok, reason = _bundle_files_present(big_bundle)
    if not ok:
      _queue_bundle_ref(params, big_bundle.ref if big_bundle is not None else None)
      return False, f"chestnut preflight failed: {reason}"

    # modeld_v2 always prepares a QCOM fallback while Chestnut is active.
    # If this fallback is missing, the old code crashes after the big model loads
    # and manager restarts modeld_tinygrad forever, leaving ChestnutLoading stuck.
    small_bundle = get_selected_bundle(params, "qcom")
    ok, reason = _bundle_files_present(small_bundle)
    if not ok:
      if small_bundle is not None:
        _queue_bundle_ref(params, small_bundle.ref)
      else:
        _queue_bundle_ref(params, DEFAULT_MODEL_REF)
      return False, f"qcom fallback preflight failed: {reason}"
  else:
    small_bundle = get_selected_bundle(params, "qcom")
    ok, reason = _bundle_files_present(small_bundle)
    if not ok:
      if small_bundle is not None:
        _queue_bundle_ref(params, small_bundle.ref)
      else:
        _queue_bundle_ref(params, DEFAULT_MODEL_REF)
      return False, f"qcom preflight failed: {reason}"

  return True, "ok"


def _finite_pose(sm: messaging.SubMaster) -> bool:
  if not sm.seen["cameraOdometry"]:
    return False
  vals = list(sm["cameraOdometry"].trans)
  return len(vals) >= 3 and all(math.isfinite(float(v)) for v in vals[:3])


def _run_attempt(entry: Path, label: str, argv: list[str]) -> tuple[str, str]:
  global _child

  sm = messaging.SubMaster(["modelV2", "cameraOdometry"])
  cmd = [sys.executable, str(entry), *argv]
  cloudlog.warning(f"modeld supervisor starting {label}: {' '.join(cmd)}")
  _child = subprocess.Popen(cmd, cwd=BASEDIR)

  start = time.monotonic()
  last_model_msg: float | None = None
  healthy = False
  healthy_frames = 0
  bad_pose_frames = 0

  while True:
    sm.update(100)
    now = time.monotonic()

    if _shutdown_requested:
      _terminate_child()
      return "shutdown", "manager requested shutdown"

    rc = _child.poll()
    if rc is not None:
      phase = "runtime" if healthy else "startup"
      return f"{phase}_failed", f"{label} exited with code {rc}"

    if sm.updated["modelV2"]:
      last_model_msg = now

    if sm.updated["cameraOdometry"]:
      if _finite_pose(sm) and sm.seen["modelV2"]:
        healthy_frames += 1
        bad_pose_frames = 0
      else:
        bad_pose_frames += 1
        healthy_frames = 0

      if bad_pose_frames >= BAD_POSE_FRAMES:
        _terminate_child()
        phase = "runtime" if healthy else "startup"
        return f"{phase}_failed", f"{label} published non-finite cameraOdometry"

    if not healthy and healthy_frames >= HEALTHY_FRAMES:
      healthy = True
      cloudlog.event("modeld_tinygrad_supervisor_healthy", attempt=label)

    if not healthy and now - start > STARTUP_TIMEOUT:
      _terminate_child()
      return "startup_failed", f"{label} did not publish finite model output within {STARTUP_TIMEOUT:.0f}s"

    if healthy and last_model_msg is not None and now - last_model_msg > HEARTBEAT_TIMEOUT:
      _terminate_child()
      return "runtime_failed", f"{label} modelV2 heartbeat lost for {HEARTBEAT_TIMEOUT:.0f}s"


def _fallback_to_stock(params: Params, reason: str) -> None:
  # Runner.stock is @2 in custom.capnp. Keep this as an int because Params stores
  # ModelRunnerTypeCache as an integer and process_config re-evaluates it every loop.
  params.put("ModelRunnerTypeCache", 2, block=True)
  params.put_bool("ChestnutLoading", False, block=True)
  params.put_bool("ChestnutActive", False, block=True)
  params.put_bool("ChestnutModelError", True, block=True)
  cloudlog.event("modeld_tinygrad_supervisor_fallback", reason=reason, error=True)


def main() -> int:
  for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, _signal_handler)

  params = Params()
  ok, reason = _preflight(params)
  if not ok:
    _fallback_to_stock(params, reason)
    return 0

  modeld_dir = Path(__file__).resolve().parent
  normal_entry = modeld_dir / "modeld.py"
  compat_entry = modeld_dir / "modeld_compat_entry.py"
  argv = sys.argv[1:]

  outcome, reason = _run_attempt(normal_entry, "native-unpickler", argv)
  if outcome == "shutdown":
    return 0
  if outcome == "runtime_failed":
    _fallback_to_stock(params, reason)
    return 1

  # If startup failed before any valid model output, retry once with the
  # cross-tinygrad compatibility unpickler. This covers devices whose submodule
  # checkout or downloaded PKL is one tinygrad ABI behind/ahead of the branch.
  cloudlog.warning(f"modeld supervisor retrying with compatibility loader: {reason}")
  outcome2, reason2 = _run_attempt(compat_entry, "compat-unpickler", argv)
  if outcome2 == "shutdown":
    return 0
  if outcome2 in ("startup_failed", "runtime_failed"):
    _fallback_to_stock(params, f"{reason}; retry: {reason2}")
    return 1

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
