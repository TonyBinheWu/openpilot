import json
import pytest

from tools.scripts.diagnose_model_lag import TimingSummary, distribution, finite_json, make_sample, main


def test_missing_metrics_stay_unknown():
  result = TimingSummary().result()
  assert result["model_execution_ms"] is None
  assert result["reported_frame_drop_percent"] is None
  assert result["services"]["modelV2"]["observed_hz"] is None
  assert distribution([None, float("nan"), float("inf")]) is None
  assert finite_json({"x": [float("nan"), 1]}) == {"x": [None, 1]}


def test_invalid_and_dead_samples_do_not_become_performance_evidence():
  stats = TimingSummary()
  for n, (valid, alive, execution) in enumerate(((False, True, 100), (True, False, 100), (True, True, .06))):
    stats.add(make_sample("modelV2", {"big": True, "modelExecutionTime": execution, "frameDropPerc": 2}, n * 50_000_000,
                          valid, alive))
  result = stats.result()
  assert result["valid_model_samples"] == result["valid_big_model_samples"] == 1
  assert result["model_execution_ms"]["max"] == 60
  assert result["execution_over_50ms_samples"] == 1
  assert result["reported_frame_drop_percent"]["median"] == 2


def test_timestamp_reset_does_not_produce_a_false_rate():
  stats = TimingSummary()
  for timestamp in (100_000_000, 50_000_000):
    stats.add(make_sample("modelV2", {}, timestamp, True))
  service = stats.result()["services"]["modelV2"]
  assert service["observed_hz"] is None
  assert service["nonincreasing_timestamps"] == 1


def test_device_capture_excludes_network_and_identifiers():
  sample = make_sample("deviceState", {"deviceType": "tizi", "networkInfo": {"imei": "private"},
                       "usbState": {"devices": [{"vendorId": 1, "productId": 2, "speedMbps": 5000,
                                                 "serial": "private", "manufacturer": "private"}]}}, 1, True)
  assert "private" not in json.dumps(sample)
  assert sample["values"]["usbDevices"][0]["speedMbps"] == 5000


def test_cli_saved_rlog_and_no_overwrite(tmp_path, monkeypatch):
  from openpilot.cereal import messaging
  source, output = tmp_path / "rlog", tmp_path / "metrics.jsonl"
  with source.open("wb") as stream:
    for n, execution in enumerate((.03, .04, .07)):
      msg = messaging.new_message("modelV2", valid=True)
      msg.logMonoTime = 1_000_000_000 + n * 50_000_000
      msg.modelV2.modelExecutionTime = execution
      msg.modelV2.frameDropPerc = float(n)
      msg.modelV2.big = True
      stream.write(msg.to_bytes())
  monkeypatch.setattr("sys.argv", ["diagnose", "--rlog", str(source), "--output", str(output)])
  main()
  rows = [json.loads(line) for line in output.read_text().splitlines()]
  assert rows[0] == {"type": "metadata", "mode": "rlog"}
  assert rows[-1]["valid_big_model_samples"] == 3
  assert rows[-1]["model_execution_ms"]["max"] == pytest.approx(70)
  assert rows[-1]["services"]["modelV2"]["observed_hz"] == pytest.approx(20)
  assert rows[-1]["services"]["chestnutState"]["samples"] == 0
  with pytest.raises(FileExistsError):
    main()
