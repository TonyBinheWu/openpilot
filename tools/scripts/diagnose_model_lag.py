#!/usr/bin/env python3
"""Read-only model timing capture. Run on the device, or against a saved rlog.

No CAN/VisionIPC publishing, parameter writes, model loading or benchmark work.
The collector's observed message gaps are not modeld's frameDropPerc metric.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

if __package__ in (None, ""):
  sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


FIELDS = {
  "modelV2": ("frameId", "frameIdExtra", "frameDropPerc", "modelExecutionTime", "timestampEof", "big"),
  "narrowRoadCameraState": ("frameId", "timestampSof", "timestampEof", "sensor"),
  "wideRoadCameraState": ("frameId", "timestampSof", "timestampEof", "sensor"),
  "deviceState": ("deviceType", "started", "cpuUsagePercent", "gpuUsagePercent", "memoryUsagePercent",
                  "cpuTempC", "gpuTempC", "memoryTempC", "thermalStatus", "chestnutPresent"),
  "chestnutState": ("tempC", "memoryTempC", "powerDrawW", "powerLimitW", "gpuUsagePercent", "gpuClockMhz",
                    "fanSpeedRpm", "pcieLtssm", "supplyVoltage", "supplyCurrent", "supplyFault"),
}


def finite_json(value):
  if isinstance(value, float) and not math.isfinite(value):
    return None
  if isinstance(value, dict):
    return {k: finite_json(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [finite_json(v) for v in value]
  return value


def make_sample(service, data, mono_ns, valid, alive=None):
  values = {key: data.get(key) for key in FIELDS[service]}
  if service == "deviceState":
    # USB performance/topology only. Do not include serial numbers or network state.
    values["usbDevices"] = [{key: dev.get(key) for key in ("vendorId", "productId", "speedMbps", "linkErrorCount")}
                            for dev in data.get("usbState", {}).get("devices", [])]
  return finite_json({"type": "sample", "service": service, "logMonoTime": mono_ns,
                      "valid": bool(valid), "alive": alive, "values": values})


def distribution(values):
  values = sorted(v for v in values if isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v))
  if not values:
    return None
  return {"count": len(values), "median": statistics.median(values),
          "p95": values[math.ceil(len(values) * .95) - 1], "max": values[-1]}


class TimingSummary:
  def __init__(self):
    self.times = {service: [] for service in FIELDS}
    self.valid_counts = dict.fromkeys(FIELDS, 0)
    self.execution_ms = []
    self.drops = []
    self.big_count = 0
    self.model_count = 0

  def add(self, sample):
    service = sample["service"]
    self.times[service].append(sample["logMonoTime"] / 1e9)
    usable = sample["valid"] and sample.get("alive") is not False
    self.valid_counts[service] += int(usable)
    if service == "modelV2" and usable:
      values = sample["values"]
      execution = values.get("modelExecutionTime")
      if isinstance(execution, (int, float)) and math.isfinite(execution) and execution >= 0:
        self.execution_ms.append(execution * 1000)
      drop = values.get("frameDropPerc")
      if isinstance(drop, (int, float)) and math.isfinite(drop) and 0 <= drop <= 100:
        self.drops.append(drop)
      self.big_count += int(values.get("big") is True)
      self.model_count += 1

  def result(self):
    services = {}
    for name, times in self.times.items():
      intervals = [b - a for a, b in zip(times, times[1:], strict=False)]
      ordered = len(times) > 1 and all(dt > 0 for dt in intervals)
      services[name] = {"samples": len(times), "valid_samples": self.valid_counts[name],
                        "observed_hz": (len(times) - 1) / (times[-1] - times[0]) if ordered else None,
                        "observed_interval_ms": distribution([dt * 1000 for dt in intervals if dt > 0]),
                        "nonincreasing_timestamps": sum(dt <= 0 for dt in intervals)}
    return {"type": "summary", "services": services, "model_execution_ms": distribution(self.execution_ms),
            "reported_frame_drop_percent": distribution(self.drops),
            "execution_over_50ms_samples": sum(ms > 50 for ms in self.execution_ms),
            "valid_big_model_samples": self.big_count, "valid_model_samples": self.model_count,
            "note": "20 Hz has a 50 ms period. Execution time includes run() work, not just GPU kernels. " +
                    "Observed message gaps may include collector delay; inspect reported_frame_drop_percent separately."}


def local_metadata():
  from openpilot.common.params import Params
  from openpilot.common.hardware import HARDWARE
  params = Params()
  bundles = {}
  for key in ("ModelManager_ActiveBundle", "ModelManager_ActiveBundleChestnut"):
    bundle = params.get(key)
    bundles[key] = ({field: bundle.get(field) for field in ("internalName", "displayName", "ref", "runner")}
                    if isinstance(bundle, dict) else None)
  root = Path(__file__).resolve().parents[2]
  def revision(path):
    try:
      return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
      return None
  return {"type": "metadata", "mode": "live", "device_type": HARDWARE.get_device_type(),
          "commit": revision(root), "tinygrad_commit": revision(root / "tinygrad_repo"), "bundles": bundles,
          "model_runner": params.get("ModelRunnerTypeCache"), "chestnut_active": params.get_bool("ChestnutActive"),
          "chestnut_loading": params.get_bool("ChestnutLoading"), "chestnut_model_error": params.get_bool("ChestnutModelError")}


def live_samples(seconds):
  from openpilot.cereal import messaging
  sm = messaging.SubMaster(list(FIELDS), poll="modelV2")
  deadline = time.monotonic() + seconds
  while time.monotonic() < deadline:
    sm.update(1000)
    for service in FIELDS:
      if sm.updated[service]:
        yield make_sample(service, sm[service].to_dict(), sm.logMonoTime[service], sm.valid[service], sm.alive[service])


def log_samples(path):
  from openpilot.tools.lib.logreader import LogReader
  for msg in LogReader(path):
    service = msg.which()
    if service in FIELDS:
      yield make_sample(service, getattr(msg, service).to_dict(), msg.logMonoTime, msg.valid)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--seconds", type=int, default=60, help="live capture duration (1-600 seconds)")
  parser.add_argument("--rlog", help="saved rlog/route instead of live capture")
  parser.add_argument("--output", required=True, type=Path, help="new JSONL file (existing files are never overwritten)")
  args = parser.parse_args()
  if not 1 <= args.seconds <= 600:
    parser.error("--seconds must be between 1 and 600")
  summary = TimingSummary()
  with args.output.open("x") as output:
    def emit(record):
      output.write(json.dumps(finite_json(record), ensure_ascii=False, allow_nan=False) + "\n")
    emit({"type": "metadata", "mode": "rlog"} if args.rlog else local_metadata())
    try:
      for sample in log_samples(args.rlog) if args.rlog else live_samples(args.seconds):
        emit(sample)
        summary.add(sample)
    except KeyboardInterrupt:
      pass
    emit(summary.result())
  print(json.dumps(summary.result(), indent=2, allow_nan=False))
  print(f"Saved {args.output}")


if __name__ == "__main__":
  main()
