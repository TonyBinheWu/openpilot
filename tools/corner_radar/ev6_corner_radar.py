#!/usr/bin/env python3
"""Convert EV6 corner-radar candidate CAN frames to traceable JSONL."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
  sys.path.insert(0, str(REPO_ROOT))

from openpilot.sunnypilot.selfdrive.car.corner_radar import (
  CANDIDATE_ADDRESSES,
  PAYLOAD_BYTES,
  CornerRadarTracker,
  RESEARCH_COMMIT,
  decode_frame,
)


def _first(row: dict, names: tuple[str, ...]):
  for name in names:
    if name in row:
      return row[name]
  raise KeyError(f"missing one of: {', '.join(names)}")


def _parse_int(value) -> int:
  return value if isinstance(value, int) else int(str(value), 0)


def _parse_timestamp_nanos(row: dict) -> int:
  for key in ("timestamp_nanos", "timestampNanos", "logMonoTime", "mono_time_nanos"):
    if key in row:
      return _parse_int(row[key])
  if "timestamp_sec" in row:
    return round(float(row["timestamp_sec"]) * 1e9)
  raise KeyError("missing nanosecond timestamp or timestamp_sec")


def _parse_data(value) -> bytes:
  if isinstance(value, list):
    return bytes(value)
  if not isinstance(value, str):
    raise TypeError("payload must be a hexadecimal string or byte list")
  value = value.strip().lower().removeprefix("0x")
  for separator in (" ", ":", "-", "_"):
    value = value.replace(separator, "")
  return bytes.fromhex(value)


def _write(output: TextIO, record: dict) -> None:
  output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def convert_stream(input_file: TextIO, output_file: TextIO) -> None:
  tracker = CornerRadarTracker()
  input_lines = 0
  candidate_lines = 0
  parse_errors = 0

  for line_number, line in enumerate(input_file, 1):
    if not line.strip():
      continue
    input_lines += 1
    try:
      source = json.loads(line)
      timestamp_nanos = _parse_timestamp_nanos(source)
      source_bus = _parse_int(_first(source, ("source_bus", "bus", "src")))
      address = _parse_int(_first(source, ("address", "can_id", "id")))
      data = _parse_data(_first(source, ("data", "dat", "payload")))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
      parse_errors += 1
      _write(output_file, {
        "record_type": "input_error",
        "input_line": line_number,
        "error": str(error),
        "raw_input": line.rstrip("\n"),
      })
      continue

    if address not in CANDIDATE_ADDRESSES:
      continue
    candidate_lines += 1
    prior_timestamp = tracker.latest_timestamp_nanos
    accepted_length = len(data) == PAYLOAD_BYTES
    timestamp_accepted = timestamp_nanos > 0 and timestamp_nanos >= prior_timestamp
    received_bus = 0 <= source_bus < 128
    ingested = tracker.ingest(timestamp_nanos, source_bus, address, data)
    # Raw data is already written below; keep the track state without retaining
    # a second bounded copy during long offline conversions.
    tracker.pop_raw_frames()

    rejection = None
    if not received_bus:
      rejection = "not_a_received_can_bus"
    elif not timestamp_accepted:
      rejection = "non_positive_or_out_of_order_timestamp"
    elif not accepted_length:
      rejection = f"wrong_payload_length:{len(data)}"

    raw_hex = data.hex()
    _write(output_file, {
      "record_type": "raw_frame",
      "input_line": line_number,
      "timestamp_nanos": timestamp_nanos,
      "source_bus": source_bus,
      "address": f"0x{address:03X}",
      "payload_length": len(data),
      "data": raw_hex,
      "accepted_length": accepted_length,
      "timestamp_accepted": timestamp_accepted,
      "received_bus": received_bus,
      "decoder_accepted": ingested,
      "rejection": rejection,
      "input_source": source.get("source"),
      "research_source": RESEARCH_COMMIT,
    })

    if not (received_bus and timestamp_accepted and accepted_length):
      continue

    for decoded in decode_frame(timestamp_nanos, source_bus, address, data):
      record = asdict(decoded)
      record["record_type"] = "decoded_record"
      record["input_line"] = line_number
      record["address"] = f"0x{decoded.address:03X}"
      record["raw"] = decoded.raw.hex()
      record["distance_source"] = "experimental_pr_24221"
      record["angle_source"] = "experimental_pr_24221_mounting_unverified"
      record["relative_speed_mps"] = None
      record["relative_speed_source"] = "unknown_not_decoded"
      record["target_identity_validated"] = False
      record["research_source"] = RESEARCH_COMMIT
      _write(output_file, record)

    if ingested:
      for record in tracker.json_records(timestamp_nanos):
        if record["timestamp_nanos"] != timestamp_nanos:
          continue
        record["record_type"] = "track_snapshot"
        record["input_line"] = line_number
        record["address"] = f"0x{record['address']:03X}"
        record["target_identity_validated"] = False
        record["mounting_validated"] = False
        record["research_source"] = RESEARCH_COMMIT
        _write(output_file, record)

  _write(output_file, {
    "record_type": "summary",
    "input_lines": input_lines,
    "candidate_lines": candidate_lines,
    "parse_errors": parse_errors,
    "accepted_candidate_frames": tracker.candidate_frames,
    "rejected_length": tracker.rejected_length,
    "timestamp_errors": tracker.timestamp_errors,
    "observed_64_byte_buses": sorted(tracker.observed_buses),
    "direct_relative_speed_source": "unknown_not_decoded",
    "research_source": RESEARCH_COMMIT,
  })


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("input", type=Path, help="input JSONL containing raw CAN frames")
  parser.add_argument("output", nargs="?", type=Path, help="output JSONL (stdout when omitted)")
  args = parser.parse_args()

  with args.input.open(encoding="utf-8") as input_file:
    if args.output is None:
      convert_stream(input_file, sys.stdout)
    else:
      with args.output.open("w", encoding="utf-8") as output_file:
        convert_stream(input_file, output_file)


if __name__ == "__main__":
  main()
