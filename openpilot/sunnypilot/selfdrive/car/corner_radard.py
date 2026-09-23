#!/usr/bin/env python3
import time

from opendbc.car.hyundai.values import CAR
from opendbc.car.structs import car

from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.sunnypilot.selfdrive.car.corner_radar import (
  CornerRadarTracker,
  OemFrontTargetTracker,
  RESEARCH_COMMIT,
)


def boot_time_ns() -> int:
  return time.clock_gettime_ns(getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC))


def ev6_oem_front_enabled() -> bool:
  cp_bytes = Params().get("CarParams")
  if cp_bytes is None:
    return False
  try:
    cp = messaging.log_from_bytes(cp_bytes, car.CarParams)
    return cp.brand == "hyundai" and cp.carFingerprint == CAR.KIA_EV6
  except Exception:
    return False


def main() -> None:
  can_sock = messaging.sub_sock("can", timeout=20)
  pm = messaging.PubMaster(["cornerRadarStateSP"])
  tracker = CornerRadarTracker()
  oem_front_tracker = OemFrontTargetTracker()
  use_oem_front = ev6_oem_front_enabled()
  rk = Ratekeeper(20)

  while True:
    for event in messaging.drain_sock(can_sock, wait_for_one=True):
      for frame in event.can:
        timestamp_nanos = int(event.logMonoTime)
        source_bus = int(frame.src)
        address = int(frame.address)
        data = bytes(frame.dat)
        tracker.ingest(timestamp_nanos, source_bus, address, data)
        if use_oem_front:
          oem_front_tracker.ingest(timestamp_nanos, source_bus, address, data)

    now_nanos = boot_time_ns()
    tracker.expire(now_nanos)
    oem_front_tracker.expire(now_nanos)
    msg = messaging.new_message("cornerRadarStateSP", valid=True)
    state = msg.cornerRadarStateSP
    state.researchSource = RESEARCH_COMMIT
    state.observedBuses = sorted(tracker.observed_buses)
    state.candidateFrames = tracker.candidate_frames
    state.rejectedLength = tracker.rejected_length
    state.timestampErrors = tracker.timestamp_errors
    state.droppedRawFrames = tracker.dropped_raw_frames

    raw_targets = list(tracker.targets.values())
    oem_targets = list(oem_front_tracker.targets.values()) if use_oem_front else []
    targets = state.init("targets", len(raw_targets) + len(oem_targets))

    output_index = 0
    for target in raw_targets:
      output = targets[output_index]
      output_index += 1
      record = target.record
      output.trackId = target.track_id
      output.sensorGroup = record.sensor_group
      output.sourceBus = record.source_bus
      output.address = record.address
      output.slot = record.slot
      output.candidateActive = record.candidate_active
      output.statusValidated = record.status_validated
      output.distance = record.distance_m
      output.encodedAngle = record.encoded_angle_deg
      output.correctedAngle = record.corrected_angle_deg
      output.longitudinal = record.longitudinal_m
      output.lateral = record.lateral_m
      output.relativeSpeedValid = False
      output.targetIdentityValidated = False
      output.mountingValidated = False
      output.ageSec = max((now_nanos - record.timestamp_nanos) / 1e9, 0.0)
      if target.estimated_radial_speed_mps is not None:
        output.estimatedRadialSpeed = target.estimated_radial_speed_mps
        output.estimatedRadialSpeedValid = True

    # Original OEM-calculated ADRV 0x1EA LF/RF slots. The layout is still an
    # EV6 research candidate, so the validation flags intentionally remain
    # false even though the source frame itself must pass the HKG checksum.
    for target in oem_targets:
      output = targets[output_index]
      output_index += 1
      output.trackId = target.track_id
      output.sensorGroup = target.sensor_group
      output.sourceBus = target.source_bus
      output.address = 0x1EA
      output.slot = target.slot
      output.candidateActive = True
      output.statusValidated = False
      output.distance = target.distance_m
      output.encodedAngle = 0.0
      output.correctedAngle = 0.0
      output.longitudinal = target.longitudinal_m
      output.lateral = target.lateral_m
      output.relativeSpeedValid = False
      output.estimatedRadialSpeedValid = False
      output.targetIdentityValidated = False
      output.mountingValidated = False
      output.ageSec = max((now_nanos - target.timestamp_nanos) / 1e9, 0.0)

    raw_frames = tracker.pop_raw_frames()
    raw = state.init("rawFrames", len(raw_frames))
    for output, frame in zip(raw, raw_frames, strict=True):
      output.timestampNanos = frame.timestamp_nanos
      output.sourceBus = frame.source_bus
      output.address = frame.address
      output.data = frame.data
      output.acceptedLength = frame.accepted_length
      output.timestampAccepted = frame.timestamp_accepted

    pm.send("cornerRadarStateSP", msg)
    rk.keep_time()


if __name__ == "__main__":
  main()
