import json
import tempfile
import unittest
from pathlib import Path

from opendbc.car.hyundai.hyundaicanfd import hkg_can_fd_checksum
from tools.hkg_factory_cluster.ev6_factory_cluster import (
  ReplayMode,
  ScenarioInput,
  analyze,
  build_replay_plan,
  file_sha256,
)


def hkg_frame(address: int, length: int, counter: int, marker: int = 0) -> bytes:
  data = bytearray(length)
  data[2] = counter
  data[3] = marker
  data[:2] = hkg_can_fd_checksum(address, None, data).to_bytes(2, "little")
  return bytes(data)


def write_jsonl(path: Path, rows: list[dict]) -> None:
  path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class TestEv6FactoryClusterAnalysis(unittest.TestCase):
  def test_three_scenarios_report_replacement_and_never_authorize(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      baseline = root / "baseline.jsonl"
      exp_off = root / "exp_off.jsonl"
      exp_on = root / "exp_on.jsonl"
      write_jsonl(baseline, [
        {"timestamp_nanos": 1_000_000_000 + index * 50_000_000, "direction": "rx", "bus": 1,
         "address": "0x1EA", "data": hkg_frame(0x1EA, 32, index, marker=index).hex(), "video_time_s": index * 0.05}
        for index in range(5)
      ])
      write_jsonl(exp_off, [
        {"timestamp_nanos": 2_000_000_000 + index * 50_000_000, "direction": "tx", "bus": 1,
         "address": "0x1EA", "data": hkg_frame(0x1EA, 32, index).hex()}
        for index in range(5)
      ])
      write_jsonl(exp_on, [
        {"timestamp_nanos": 3_000_000_000 + index * 50_000_000, "direction": "tx", "bus": 1,
         "address": "0x1EA", "data": hkg_frame(0x1EA, 32, index).hex()}
        for index in range(5)
      ])
      scenarios = [
        ScenarioInput("baseline", baseline, file_sha256(baseline)),
        ScenarioInput("sp_long_exp_off", exp_off, file_sha256(exp_off)),
        ScenarioInput("sp_long_exp_on", exp_on, file_sha256(exp_on)),
      ]
      report = analyze(scenarios)
      self.assertTrue(report["observed_0x1ea_replacement_candidate"])
      self.assertFalse(report["compatibility_verified"])
      self.assertFalse(report["production_transmission_authorized"])
      baseline_stream = next(stream for stream in report["candidate_streams"]
                             if stream["scenario"] == "baseline" and stream["address"] == "0x1EA")
      self.assertEqual(baseline_stream["valid_hkg_checksums"], 5)
      self.assertEqual(baseline_stream["counter_gaps"], 0)
      self.assertEqual(baseline_stream["video_labeled_frames"], 5)

  def test_navigation_plan_is_byte_exact_but_not_authorized_without_evidence(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "navigation.jsonl"
      rows = [
        {"timestamp_nanos": 1_000_000_000, "direction": "rx", "bus": 2, "address": "0x4A3", "data": "0102030405060708"},
        {"timestamp_nanos": 1_100_000_000, "direction": "rx", "bus": 2, "address": "0x4A3", "data": "1122334455667788"},
      ]
      write_jsonl(path, rows)
      source = ScenarioInput("stock_navigation", path, file_sha256(path))
      plan = build_replay_plan(source, "stock_navigation", {0x4A3}, ReplayMode.ORIGINAL_NAVIGATION, None)
      self.assertFalse(plan["bench_transmission_authorized"])
      self.assertFalse(plan["vehicle_transmission_authorized"])
      self.assertEqual(plan["frames"][1]["offset_nanos"], 100_000_000)
      self.assertEqual(plan["frames"][1]["data"], "1122334455667788")

  def test_complete_and_fixed_modes_reject_missing_evidence(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "navigation.jsonl"
      write_jsonl(path, [
        {"timestamp_nanos": 1, "direction": "rx", "bus": 2, "address": "0x4A3", "data": "00" * 8},
      ])
      source = ScenarioInput("stock_navigation", path, file_sha256(path))
      for mode in (ReplayMode.COMPLETE_NAVIGATION, ReplayMode.FIXED_HIGHWAY):
        with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "verified evidence manifest"):
          build_replay_plan(source, "stock_navigation", {0x4A3}, mode, None)

  def test_authorization_must_match_capture_and_exact_transport(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "navigation.jsonl"
      write_jsonl(path, [
        {"timestamp_nanos": 1, "direction": "rx", "bus": 2, "address": "0x4A3", "data": "00" * 8},
      ])
      source = ScenarioInput("stock_navigation", path, file_sha256(path))
      manifest = {
        "profile_id": "test-only",
        "capture_sha256": "wrong",
        "video_evidence_sha256": "a" * 64,
        "firmware": [{"ecu": "combinationMeter", "version": "test"}],
        "allowed_modes": [ReplayMode.ORIGINAL_NAVIGATION.value],
        "messages": [{"address": "0x4A3", "bus": 2, "length": 8}],
        "bench_isolated": True,
        "display_only_verified": True,
        "adas_control_unchanged_verified": True,
        "counter_checksum_verified": True,
        "receiver_ecu_verified": True,
        "bus_verified": True,
      }
      with self.assertRaisesRegex(ValueError, "capture_sha256"):
        build_replay_plan(source, "stock_navigation", {0x4A3}, ReplayMode.ORIGINAL_NAVIGATION, manifest)

  def test_synthetic_navigation_modes_require_mode_specific_proof(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "navigation.jsonl"
      write_jsonl(path, [
        {"timestamp_nanos": 1, "direction": "rx", "bus": 2, "address": "0x4A3", "data": "00" * 8},
      ])
      source = ScenarioInput("stock_navigation", path, file_sha256(path))
      manifest = {
        "profile_id": "test-only",
        "capture_sha256": source.sha256,
        "video_evidence_sha256": "a" * 64,
        "firmware": [{"ecu": "combinationMeter", "version": "test"}],
        "allowed_modes": [ReplayMode.COMPLETE_NAVIGATION.value, ReplayMode.FIXED_HIGHWAY.value],
        "messages": [{"address": "0x4A3", "bus": 2, "length": 8}],
        "bench_isolated": True,
        "display_only_verified": True,
        "adas_control_unchanged_verified": True,
        "counter_checksum_verified": True,
        "receiver_ecu_verified": True,
        "bus_verified": True,
      }
      with self.assertRaisesRegex(ValueError, "complete message sequence"):
        build_replay_plan(source, "stock_navigation", {0x4A3}, ReplayMode.COMPLETE_NAVIGATION, manifest)
      with self.assertRaisesRegex(ValueError, "vehicle-specific highway value"):
        build_replay_plan(source, "stock_navigation", {0x4A3}, ReplayMode.FIXED_HIGHWAY, manifest)


if __name__ == "__main__":
  unittest.main()
