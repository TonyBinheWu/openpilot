#!/usr/bin/env python3
"""Analyze EV6 cluster CAN evidence and build non-transmitting replay plans.

The tool never opens Panda or publishes sendcan.  A replay plan becomes marked
as bench-authorized only when a separate evidence manifest passes every check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections.abc import Iterable, Iterator
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from opendbc.sunnypilot.car.hyundai.factory_cluster import (
  ADRV_OBJECTS_ADDRESS,
  BSM_ADDRESS,
  CANDIDATE_LAYOUTS,
  CCNC_OBJECTS_ADDRESS,
  CCNC_STATUS_ADDRESS,
  EXPECTED_LENGTHS,
  HDA_INFO_ADDRESS,
  LFAHDA_CLUSTER_ADDRESS,
  SignalSpec,
  valid_hkg_frame,
)
from openpilot.tools.lib.logreader import LogReader


CANDIDATE_ADDRESSES = (
  BSM_ADDRESS,
  CCNC_STATUS_ADDRESS,
  CCNC_OBJECTS_ADDRESS,
  LFAHDA_CLUSTER_ADDRESS,
  ADRV_OBJECTS_ADDRESS,
  HDA_INFO_ADDRESS,
)
BSM_SIGNALS = {
  "left": SignalSpec(31, 2, False),
  "right": SignalSpec(32, 2, True),
}
MAX_INTERVAL_SAMPLES = 10_000
MAX_UNIQUE_VALUES = 128


class ReplayMode(StrEnum):
  ORIGINAL_NAVIGATION = "original_navigation"
  COMPLETE_NAVIGATION = "complete_navigation"
  FIXED_HIGHWAY = "fixed_highway"


@dataclass(frozen=True)
class CaptureFrame:
  scenario: str
  direction: str
  timestamp_nanos: int
  bus: int
  address: int
  data: bytes
  event: str = ""
  video_time_s: float | None = None


@dataclass
class NumericSummary:
  minimum: float = math.inf
  maximum: float = -math.inf
  values: set[float] = field(default_factory=set)

  def add(self, value: float) -> None:
    self.minimum = min(self.minimum, value)
    self.maximum = max(self.maximum, value)
    if len(self.values) < MAX_UNIQUE_VALUES:
      self.values.add(value)

  def to_dict(self) -> dict[str, Any]:
    if self.minimum == math.inf:
      return {"minimum": None, "maximum": None, "unique_values": []}
    return {"minimum": self.minimum, "maximum": self.maximum, "unique_values": sorted(self.values)}


@dataclass
class StreamAccumulator:
  scenario: str
  direction: str
  bus: int
  address: int
  length: int
  count: int = 0
  first_nanos: int | None = None
  last_nanos: int | None = None
  previous_nanos: int | None = None
  intervals_s: list[float] = field(default_factory=list)
  previous_data: bytes | None = None
  changed_bytes: set[int] = field(default_factory=set)
  unique_payloads: set[str] = field(default_factory=set)
  checksum_valid: int = 0
  checksum_invalid: int = 0
  previous_counter: int | None = None
  counter_gaps: int = 0
  decoded: dict[str, NumericSummary] = field(default_factory=dict)
  video_labeled_frames: int = 0

  def add(self, frame: CaptureFrame) -> None:
    self.count += 1
    self.first_nanos = frame.timestamp_nanos if self.first_nanos is None else min(self.first_nanos, frame.timestamp_nanos)
    self.last_nanos = frame.timestamp_nanos if self.last_nanos is None else max(self.last_nanos, frame.timestamp_nanos)
    if self.previous_nanos is not None and frame.timestamp_nanos > self.previous_nanos and len(self.intervals_s) < MAX_INTERVAL_SAMPLES:
      self.intervals_s.append((frame.timestamp_nanos - self.previous_nanos) * 1e-9)
    self.previous_nanos = frame.timestamp_nanos
    if self.previous_data is not None and len(self.previous_data) == len(frame.data):
      self.changed_bytes.update(index for index, (before, after) in enumerate(zip(self.previous_data, frame.data, strict=True)) if before != after)
    self.previous_data = frame.data
    if len(self.unique_payloads) < MAX_UNIQUE_VALUES:
      self.unique_payloads.add(hashlib.sha256(frame.data).hexdigest()[:16])
    if frame.video_time_s is not None:
      self.video_labeled_frames += 1

    expected_length = EXPECTED_LENGTHS.get(frame.address)
    if expected_length == len(frame.data):
      if valid_hkg_frame(frame.address, frame.data, expected_length):
        self.checksum_valid += 1
      else:
        self.checksum_invalid += 1
      counter = frame.data[2]
      if self.previous_counter is not None and ((counter - self.previous_counter) & 0xFF) != 1:
        self.counter_gaps += 1
      self.previous_counter = counter

    if frame.address == BSM_ADDRESS and len(frame.data) == EXPECTED_LENGTHS[BSM_ADDRESS]:
      for name, signal in BSM_SIGNALS.items():
        self.decoded.setdefault(f"bsm.{name}", NumericSummary()).add(signal.decode(frame.data))
    layout = CANDIDATE_LAYOUTS.get(frame.address)
    if layout is not None and len(frame.data) == layout.length:
      for slot, fields in layout.fields.items():
        for name, signal in (("detect", fields.detect), ("distance", fields.distance), ("lateral", fields.lateral)):
          if signal is not None:
            self.decoded.setdefault(f"{slot.value}.{name}", NumericSummary()).add(signal.decode(frame.data))

  def median_frequency_hz(self) -> float | None:
    if not self.intervals_s:
      return None
    period = statistics.median(self.intervals_s)
    return 1.0 / period if period > 0 else None

  def to_dict(self) -> dict[str, Any]:
    return {
      "scenario": self.scenario,
      "direction": self.direction,
      "bus": self.bus,
      "address": f"0x{self.address:03X}",
      "length": self.length,
      "frames": self.count,
      "median_frequency_hz": self.median_frequency_hz(),
      "changed_byte_indices": sorted(self.changed_bytes),
      "sampled_unique_payloads": len(self.unique_payloads),
      "valid_hkg_checksums": self.checksum_valid,
      "invalid_hkg_checksums": self.checksum_invalid,
      "counter_gaps": self.counter_gaps,
      "video_labeled_frames": self.video_labeled_frames,
      "candidate_decoding": {name: summary.to_dict() for name, summary in sorted(self.decoded.items())},
      "candidate_decoding_is_compatibility_proof": False,
    }


@dataclass
class ScenarioInput:
  name: str
  path: Path
  sha256: str
  metadata: dict[str, Any] = field(default_factory=dict)


def parse_int(value: Any) -> int:
  return value if isinstance(value, int) else int(str(value), 0)


def parse_data(value: Any) -> bytes:
  if isinstance(value, list):
    return bytes(value)
  if not isinstance(value, str):
    raise TypeError("CAN data must be a hex string or byte list")
  compact = value.strip().lower().removeprefix("0x")
  for separator in (" ", ":", "-", "_"):
    compact = compact.replace(separator, "")
  return bytes.fromhex(compact)


def file_sha256(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def _jsonl_frames(path: Path, scenario: str, metadata: dict[str, Any]) -> Iterator[CaptureFrame]:
  with path.open(encoding="utf-8") as stream:
    for line_number, line in enumerate(stream, 1):
      if not line.strip():
        continue
      row = json.loads(line)
      if row.get("record_type") == "metadata":
        metadata.update(row.get("metadata", row))
        continue
      try:
        yield CaptureFrame(
          scenario=scenario,
          direction=str(row.get("direction", "rx")),
          timestamp_nanos=parse_int(next(row[key] for key in ("timestamp_nanos", "logMonoTime", "mono_time_nanos") if key in row)),
          bus=parse_int(next(row[key] for key in ("bus", "source_bus", "src") if key in row)),
          address=parse_int(next(row[key] for key in ("address", "can_id", "id") if key in row)),
          data=parse_data(next(row[key] for key in ("data", "dat", "payload") if key in row)),
          event=str(row.get("event", "")),
          video_time_s=float(row["video_time_s"]) if row.get("video_time_s") is not None else None,
        )
      except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise ValueError(f"{path}:{line_number}: invalid CAN row: {exc}") from exc


def _safe_fw_dict(fw: Any) -> dict[str, Any]:
  return {
    "ecu": str(fw.ecu),
    "address": f"0x{int(fw.address):X}",
    "sub_address": int(fw.subAddress),
    "response_address": f"0x{int(fw.responseAddress):X}",
    "bus": int(fw.bus),
    "firmware_hex": bytes(fw.fwVersion).hex(),
  }


def _rlog_frames(path: Path, scenario: str, metadata: dict[str, Any]) -> Iterator[CaptureFrame]:
  for message in LogReader(str(path), sort_by_time=True):
    which = message.which()
    if which == "carParams" and not metadata:
      CP = message.carParams
      metadata.update({
        "car_fingerprint": str(CP.carFingerprint),
        "fingerprint_source": str(CP.fingerprintSource),
        "fuzzy_fingerprint": bool(CP.fuzzyFingerprint),
        "flags": int(CP.flags),
        "openpilot_longitudinal_control": bool(CP.openpilotLongitudinalControl),
        "enable_bsm": bool(CP.enableBsm),
        "car_fw": [_safe_fw_dict(fw) for fw in CP.carFw],
      })
      continue
    if which not in ("can", "sendcan"):
      continue
    direction = "rx" if which == "can" else "tx"
    for frame in getattr(message, which):
      yield CaptureFrame(scenario, direction, int(message.logMonoTime), int(frame.src), int(frame.address), bytes(frame.dat))


def iter_frames(source: ScenarioInput) -> Iterator[CaptureFrame]:
  if source.path.suffix == ".jsonl":
    yield from _jsonl_frames(source.path, source.name, source.metadata)
  else:
    yield from _rlog_frames(source.path, source.name, source.metadata)


def parse_scenario(value: str) -> tuple[str, Path]:
  if "=" not in value:
    raise argparse.ArgumentTypeError("scenario must use NAME=PATH")
  name, raw_path = value.split("=", 1)
  path = Path(raw_path)
  if not name or not path.is_file():
    raise argparse.ArgumentTypeError(f"invalid scenario or missing file: {value}")
  return name, path


def _stream_key(frame: CaptureFrame) -> tuple[str, str, int, int, int]:
  return frame.scenario, frame.direction, frame.bus, frame.address, len(frame.data)


def _comparison_key(stream: StreamAccumulator) -> tuple[str, int, int, int]:
  return stream.direction, stream.bus, stream.address, stream.length


def _compare_scenarios(streams: dict[tuple[str, str, int, int, int], StreamAccumulator],
                       left: str, right: str) -> dict[str, Any]:
  left_streams = {_comparison_key(stream): stream for stream in streams.values() if stream.scenario == left}
  right_streams = {_comparison_key(stream): stream for stream in streams.values() if stream.scenario == right}
  lost, added, rate_changes = [], [], []
  for key in sorted(left_streams.keys() | right_streams.keys()):
    before, after = left_streams.get(key), right_streams.get(key)
    entry = {"direction": key[0], "bus": key[1], "address": f"0x{key[2]:03X}", "length": key[3]}
    if before is not None and before.count >= 3 and after is None:
      lost.append(entry)
    elif after is not None and after.count >= 3 and before is None:
      added.append(entry)
    elif before is not None and after is not None:
      before_hz, after_hz = before.median_frequency_hz(), after.median_frequency_hz()
      if before_hz and after_hz and (after_hz / before_hz < 0.75 or after_hz / before_hz > 1.25):
        rate_changes.append({**entry, "before_hz": before_hz, "after_hz": after_hz})
  return {"from": left, "to": right, "lost_streams": lost, "added_streams": added, "rate_changes": rate_changes}


def _sender_conflicts(streams: Iterable[StreamAccumulator], scenario: str) -> list[dict[str, Any]]:
  directions: dict[tuple[int, int, int], set[str]] = defaultdict(set)
  counts: Counter[tuple[str, int, int, int]] = Counter()
  for stream in streams:
    if stream.scenario == scenario:
      key = (stream.bus, stream.address, stream.length)
      directions[key].add(stream.direction)
      counts[(stream.direction, *key)] += stream.count
  return [{"bus": bus, "address": f"0x{address:03X}", "length": length,
           "rx_frames": counts[("rx", bus, address, length)], "tx_frames": counts[("tx", bus, address, length)]}
          for (bus, address, length), observed in sorted(directions.items()) if observed == {"rx", "tx"}]


def analyze(scenarios: list[ScenarioInput]) -> dict[str, Any]:
  streams: dict[tuple[str, str, int, int, int], StreamAccumulator] = {}
  for source in scenarios:
    for frame in iter_frames(source):
      key = _stream_key(frame)
      stream = streams.setdefault(key, StreamAccumulator(frame.scenario, frame.direction, frame.bus, frame.address, len(frame.data)))
      stream.add(frame)

  names = [scenario.name for scenario in scenarios]
  comparisons = []
  if "baseline" in names:
    comparisons.extend(_compare_scenarios(streams, "baseline", name) for name in names if name != "baseline")
  else:
    comparisons.extend(_compare_scenarios(streams, names[index - 1], name) for index, name in enumerate(names[1:], 1))
  if "sp_long_exp_off" in names and "sp_long_exp_on" in names:
    comparisons.append(_compare_scenarios(streams, "sp_long_exp_off", "sp_long_exp_on"))

  candidates = [stream.to_dict() for stream in streams.values() if stream.address in CANDIDATE_ADDRESSES]
  conflicts = {name: _sender_conflicts(streams.values(), name) for name in names}
  replacement_observed = any(
    item["address"] == "0x1EA" for comparison in comparisons
    for section in ("lost_streams", "added_streams") for item in comparison[section]
  )
  return {
    "schema_version": 1,
    "inputs": [{"scenario": source.name, "path": str(source.path), "sha256": source.sha256,
                "metadata": source.metadata} for source in scenarios],
    "candidate_streams": sorted(candidates, key=lambda item: (item["scenario"], item["direction"], item["bus"], item["address"])),
    "comparisons": comparisons,
    "same_id_rx_tx_conflicts": conflicts,
    "observed_0x1ea_replacement_candidate": replacement_observed,
    "compatibility_verified": False,
    "production_transmission_authorized": False,
    "missing_required_evidence": [
      "synchronized on-road factory-cluster video with event labels",
      "exact combination-meter and head-unit versions",
      "field-to-screen correlation for this EV6",
      "proof of physical bus visibility through the installed Hyundai P harness",
      "proof that any navigation/highway state changes display only and cannot enable ADAS control",
    ],
  }


def report_markdown(report: dict[str, Any]) -> str:
  lines = ["# Kia EV6 factory-cluster CAN evidence report", "",
           "This report is an offline transport comparison. It does not authorize vehicle transmission or prove cluster compatibility.", ""]
  for source in report["inputs"]:
    metadata = source["metadata"]
    lines += [f"## {source['scenario']}", "", f"- SHA-256: `{source['sha256']}`",
              f"- Vehicle fingerprint: `{metadata.get('car_fingerprint', 'not present')}`",
              f"- Firmware records: {len(metadata.get('car_fw', []))}", ""]
  lines += ["## Candidate streams", "",
            "| Scenario | Direction | Bus | ID | Length | Frames | Median Hz | CRC bad | Counter gaps |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
  for stream in report["candidate_streams"]:
    hz = "—" if stream["median_frequency_hz"] is None else f"{stream['median_frequency_hz']:.2f}"
    row = (stream["scenario"], stream["direction"], stream["bus"], stream["address"], stream["length"],
           stream["frames"], hz, stream["invalid_hkg_checksums"], stream["counter_gaps"])
    lines.append("| " + " | ".join(str(value) for value in row) + " |")
  lines += ["", "## Result", "",
            "- Compatibility: **unverified**",
            "- Production CAN transmission: **not authorized**",
            "- Candidate decoding is a correlation aid only; it is not proof that this EV6 uses those fields.", "",
            "## Evidence still required", ""]
  lines.extend(f"- {item}" for item in report["missing_required_evidence"])
  lines.append("")
  return "\n".join(lines)


def _load_authorization(path: Path | None) -> dict[str, Any] | None:
  if path is None:
    return None
  with path.open(encoding="utf-8") as stream:
    return json.load(stream)


def validate_authorization(manifest: dict[str, Any], source: ScenarioInput, mode: ReplayMode,
                           addresses: set[int], streams: list[CaptureFrame]) -> None:
  required_true = ("bench_isolated", "display_only_verified", "adas_control_unchanged_verified",
                   "counter_checksum_verified", "receiver_ecu_verified", "bus_verified")
  missing = [key for key in required_true if manifest.get(key) is not True]
  if missing:
    raise ValueError(f"authorization is missing true evidence flags: {', '.join(missing)}")
  if manifest.get("capture_sha256") != source.sha256:
    raise ValueError("authorization capture_sha256 does not match the replay source")
  if mode.value not in manifest.get("allowed_modes", []):
    raise ValueError(f"authorization does not allow replay mode {mode.value}")
  if not manifest.get("profile_id") or not manifest.get("video_evidence_sha256") or not manifest.get("firmware", []):
    raise ValueError("authorization requires a profile id, video evidence hash, and exact firmware records")
  if mode == ReplayMode.COMPLETE_NAVIGATION and manifest.get("complete_message_sequence_verified") is not True:
    raise ValueError("complete navigation mode requires a verified complete message sequence")
  if mode == ReplayMode.FIXED_HIGHWAY and manifest.get("fixed_highway_value_verified") is not True:
    raise ValueError("fixed highway mode requires a verified vehicle-specific highway value")
  allowed_messages = {(parse_int(item["address"]), int(item["bus"]), int(item["length"]))
                      for item in manifest.get("messages", [])}
  observed = {(frame.address, frame.bus, len(frame.data)) for frame in streams}
  if not addresses or not observed or not observed <= allowed_messages:
    raise ValueError("replay contains an address, bus, or length not authorized by the evidence manifest")


def build_replay_plan(source: ScenarioInput, scenario: str, addresses: set[int], mode: ReplayMode,
                      authorization: dict[str, Any] | None) -> dict[str, Any]:
  if mode != ReplayMode.ORIGINAL_NAVIGATION and authorization is None:
    raise ValueError(f"{mode.value} requires a verified evidence manifest; field values will not be guessed")
  frames = [frame for frame in iter_frames(source) if frame.scenario == scenario and frame.direction == "rx" and frame.address in addresses]
  frames.sort(key=lambda frame: frame.timestamp_nanos)
  if not frames:
    raise ValueError("no matching received frames were found")
  if any(frame.timestamp_nanos <= 0 for frame in frames):
    raise ValueError("replay source contains a non-positive timestamp")
  authorized = authorization is not None
  if authorization is not None:
    validate_authorization(authorization, source, mode, addresses, frames)
  start = frames[0].timestamp_nanos
  return {
    "schema_version": 1,
    "mode": mode.value,
    "source_sha256": source.sha256,
    "profile_id": authorization.get("profile_id") if authorization else None,
    "bench_transmission_authorized": authorized,
    "vehicle_transmission_authorized": False,
    "frames": [{"offset_nanos": frame.timestamp_nanos - start, "bus": frame.bus,
                "address": f"0x{frame.address:03X}", "data": frame.data.hex()} for frame in frames],
    "stop_behavior": "stop all replay frames immediately; restore only with a separately verified recovery sequence or receiving-ECU power cycle",
    "note": "This file is a replay plan only. This tool never sends CAN or opens Panda.",
  }


def write_json(path: Path, data: dict[str, Any]) -> None:
  path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  subparsers = parser.add_subparsers(dest="command", required=True)

  analyze_parser = subparsers.add_parser("analyze", help="compare labeled baseline/longitudinal/experimental captures")
  analyze_parser.add_argument("--scenario", action="append", type=parse_scenario, required=True, metavar="NAME=PATH")
  analyze_parser.add_argument("--output", type=Path, required=True)
  analyze_parser.add_argument("--markdown", type=Path)

  replay_parser = subparsers.add_parser("replay-plan", help="build a non-transmitting, byte-exact replay plan")
  replay_parser.add_argument("--scenario", type=parse_scenario, required=True, metavar="NAME=PATH")
  replay_parser.add_argument("--address", action="append", required=True, type=parse_int)
  replay_parser.add_argument("--mode", choices=[mode.value for mode in ReplayMode], default=ReplayMode.ORIGINAL_NAVIGATION.value)
  replay_parser.add_argument("--authorization", type=Path)
  replay_parser.add_argument("--output", type=Path, required=True)
  args = parser.parse_args()

  if args.command == "analyze":
    scenarios = [ScenarioInput(name, path, file_sha256(path)) for name, path in args.scenario]
    report = analyze(scenarios)
    write_json(args.output, report)
    if args.markdown is not None:
      args.markdown.write_text(report_markdown(report), encoding="utf-8")
  else:
    name, path = args.scenario
    source = ScenarioInput(name, path, file_sha256(path))
    plan = build_replay_plan(source, name, set(args.address), ReplayMode(args.mode), _load_authorization(args.authorization))
    write_json(args.output, plan)


if __name__ == "__main__":
  main()
