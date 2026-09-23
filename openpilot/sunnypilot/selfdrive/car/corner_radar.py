"""Conservative decoders for HKG corner-radar display research.

The raw 0x300/0x400/0x500/0x600 wire format comes from
commaai/openpilot#24221 at abcc844. It is not a Kia specification. In
particular, activity/status bits, sensor mounting, and directly measured
relative speed remain unknown.

For the EV6 HDA2 display path we also decode the stock ADRV 0x1EA left/right
front object slots already documented in the local opendbc research helper.
Those objects are accepted only from an original checksum-valid OEM frame and
are display-only; they never feed controls or sensor fusion.
"""
from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import asdict, dataclass, field

from opendbc.sunnypilot.car.hyundai.factory_cluster import (
  ADRV_1EA_CANDIDATE_LAYOUT,
  ADRV_OBJECTS_ADDRESS,
  TargetSlot,
  valid_hkg_frame,
)

RESEARCH_COMMIT = "commaai/openpilot#24221@abcc844c00bddba9105d868d2ee40749e5ed2741"
CANDIDATE_ADDRESSES = frozenset(address for base in (0x300, 0x400, 0x500, 0x600) for address in range(base, base + 8))
PAYLOAD_BYTES = 64
RECORD_BYTES = 8
TRACK_TIMEOUT_NS = 350_000_000
MAX_RAW_FRAMES = 256

OEM_FRONT_TARGET_TIMEOUT_NS = 350_000_000
OEM_FRONT_ACTIVE_DETECT_VALUES = (3, 4)
OEM_FRONT_TRACK_ID_BASE = 0x10000
OEM_FRONT_SLOTS = (
  (TargetSlot.LEFT_FRONT, 0, 1.0, 0),
  (TargetSlot.RIGHT_FRONT, 1, -1.0, 1),
)


@dataclass(frozen=True)
class CornerRadarRecord:
  timestamp_nanos: int
  source_bus: int
  address: int
  slot: int
  sensor_group: int
  raw: bytes
  candidate_active: bool
  status_validated: bool
  distance_m: float
  encoded_angle_deg: float
  corrected_angle_deg: float
  longitudinal_m: float
  lateral_m: float


@dataclass
class CornerRadarTarget:
  track_id: int
  record: CornerRadarRecord
  estimated_radial_speed_mps: float | None = None
  history: deque[tuple[int, float, int, int]] = field(default_factory=lambda: deque(maxlen=4))


@dataclass(frozen=True)
class RawCornerRadarFrame:
  timestamp_nanos: int
  source_bus: int
  address: int
  data: bytes
  accepted_length: bool
  timestamp_accepted: bool


@dataclass(frozen=True)
class OemFrontTarget:
  timestamp_nanos: int
  source_bus: int
  track_id: int
  sensor_group: int
  slot: int
  detect_state: int
  distance_m: float
  longitudinal_m: float
  lateral_m: float


def is_candidate_address(address: int) -> bool:
  return address in CANDIDATE_ADDRESSES


def decode_oem_adrv_front_targets(timestamp_nanos: int, source_bus: int, address: int, data: bytes) -> list[OemFrontTarget]:
  """Decode OEM-calculated LF/RF side objects from a checksum-valid stock 0x1EA.

  The bit layout is still an EV6 research candidate, so this function is
  intentionally fail-closed: only the object-present states already used by the
  local factory-cluster helper and physically sane position values are exposed.
  """
  if timestamp_nanos <= 0 or not 0 <= source_bus < 128 or address != ADRV_OBJECTS_ADDRESS:
    return []
  if not valid_hkg_frame(address, data, ADRV_1EA_CANDIDATE_LAYOUT.length):
    return []

  targets = []
  for target_slot, sensor_group, lateral_sign, slot_index in OEM_FRONT_SLOTS:
    fields = ADRV_1EA_CANDIDATE_LAYOUT.fields[target_slot]
    if fields.distance is None or fields.lateral is None:
      continue

    detect_state = int(round(fields.detect.decode(data)))
    if detect_state not in OEM_FRONT_ACTIVE_DETECT_VALUES:
      continue

    longitudinal = float(fields.distance.decode(data))
    lateral_magnitude = abs(float(fields.lateral.decode(data)))
    lateral = lateral_sign * lateral_magnitude
    if (not math.isfinite(longitudinal) or not math.isfinite(lateral) or
        not 0.5 <= longitudinal <= 120.0 or lateral_magnitude > 8.0):
      continue

    targets.append(OemFrontTarget(
      timestamp_nanos=timestamp_nanos,
      source_bus=source_bus,
      track_id=OEM_FRONT_TRACK_ID_BASE + sensor_group,
      sensor_group=sensor_group,
      slot=slot_index,
      detect_state=detect_state,
      distance_m=math.hypot(longitudinal, lateral),
      longitudinal_m=longitudinal,
      lateral_m=lateral,
    ))
  return targets


class OemFrontTargetTracker:
  """Latch only fresh OEM LF/RF objects; a valid clear frame clears immediately."""

  def __init__(self):
    self.targets: dict[int, OemFrontTarget] = {}

  def ingest(self, timestamp_nanos: int, source_bus: int, address: int, data: bytes) -> bool:
    if address != ADRV_OBJECTS_ADDRESS or timestamp_nanos <= 0 or not 0 <= source_bus < 128:
      return False
    if not valid_hkg_frame(address, data, ADRV_1EA_CANDIDATE_LAYOUT.length):
      return False

    decoded = decode_oem_adrv_front_targets(timestamp_nanos, source_bus, address, data)
    present_groups = {target.sensor_group for target in decoded}
    for target in decoded:
      self.targets[target.sensor_group] = target
    for group in (0, 1):
      if group not in present_groups:
        self.targets.pop(group, None)
    return True

  def expire(self, now_nanos: int) -> None:
    self.targets = {
      group: target for group, target in self.targets.items()
      if 0 <= now_nanos - target.timestamp_nanos <= OEM_FRONT_TARGET_TIMEOUT_NS
    }


def decode_frame(timestamp_nanos: int, source_bus: int, address: int, data: bytes) -> list[CornerRadarRecord]:
  """Decode one 64-byte candidate frame. No target identity is inferred here."""
  if timestamp_nanos <= 0:
    raise ValueError("timestamp must be positive")
  if source_bus < 0 or source_bus >= 128:
    raise ValueError("source bus must identify a received CAN bus")
  if address not in CANDIDATE_ADDRESSES:
    raise ValueError(f"unsupported candidate address: {address:#x}")
  if len(data) != PAYLOAD_BYTES:
    raise ValueError(f"candidate frame must contain {PAYLOAD_BYTES} bytes")

  group = address // 0x100 - 3
  records = []
  for slot in range(PAYLOAD_BYTES // RECORD_BYTES):
    raw = data[slot * RECORD_BYTES:(slot + 1) * RECORD_BYTES]
    # This is only the placeholder heuristic used by the closed research PR.
    # It must not be treated as a decoded validity/status bit.
    candidate_active = not raw.startswith(b"\x80\x80")
    distance = (256 * raw[3] + raw[4]) / 256.0
    encoded_angle = (256 * raw[5] + raw[6]) / 256.0
    corrected_angle = (165.0 if group in (0, 1) else 175.0) - encoded_angle
    lateral_sign = 1.0 if group in (0, 2) else -1.0
    longitudinal_sign = 1.0 if group in (0, 1) else -1.0
    angle_radians = math.radians(corrected_angle)
    records.append(CornerRadarRecord(
      timestamp_nanos=timestamp_nanos,
      source_bus=source_bus,
      address=address,
      slot=slot,
      sensor_group=group,
      raw=raw,
      candidate_active=candidate_active,
      status_validated=False,
      distance_m=distance,
      encoded_angle_deg=encoded_angle,
      corrected_angle_deg=corrected_angle,
      longitudinal_m=longitudinal_sign * math.cos(angle_radians) * distance,
      lateral_m=lateral_sign * math.sin(angle_radians) * distance,
    ))
  return records


class CornerRadarTracker:
  """Assign ephemeral tracks and estimate radial speed from tightly gated history."""

  def __init__(self):
    self.targets: dict[int, CornerRadarTarget] = {}
    self.observed_buses: set[int] = set()
    self.raw_frames: deque[RawCornerRadarFrame] = deque(maxlen=MAX_RAW_FRAMES)
    self.candidate_frames = 0
    self.rejected_length = 0
    self.timestamp_errors = 0
    self.dropped_raw_frames = 0
    self._next_track_id = 1
    self._latest_timestamp_nanos = 0

  def ingest(self, timestamp_nanos: int, source_bus: int, address: int, data: bytes) -> bool:
    if not is_candidate_address(address) or not 0 <= source_bus < 128:
      return False
    accepted_length = len(data) == PAYLOAD_BYTES
    timestamp_accepted = timestamp_nanos > 0 and timestamp_nanos >= self._latest_timestamp_nanos
    if len(self.raw_frames) == self.raw_frames.maxlen:
      self.dropped_raw_frames += 1
    self.raw_frames.append(RawCornerRadarFrame(timestamp_nanos, source_bus, address, bytes(data), accepted_length, timestamp_accepted))
    if not timestamp_accepted:
      self.timestamp_errors += 1
    if not accepted_length:
      self.rejected_length += 1
    if not timestamp_accepted or not accepted_length:
      return False

    self._latest_timestamp_nanos = timestamp_nanos

    self.candidate_frames += 1
    self.observed_buses.add(source_bus)
    matched_this_timestamp: set[int] = set()
    for record in decode_frame(timestamp_nanos, source_bus, address, data):
      if not record.candidate_active:
        continue
      match = self._match(record, matched_this_timestamp)
      if match is None:
        match = CornerRadarTarget(self._next_track_id, record)
        self._next_track_id += 1
        self.targets[match.track_id] = match
      self._update_track(match, record)
      matched_this_timestamp.add(match.track_id)
    self.expire(timestamp_nanos)
    return True

  def _match(self, record: CornerRadarRecord, excluded: set[int]) -> CornerRadarTarget | None:
    candidates: list[tuple[float, CornerRadarTarget]] = []
    for target in self.targets.values():
      previous = target.record
      dt = (record.timestamp_nanos - previous.timestamp_nanos) / 1e9
      if (target.track_id in excluded or previous.source_bus != record.source_bus or
          previous.sensor_group != record.sensor_group or not 0.01 <= dt <= 0.20):
        continue
      distance_delta = abs(record.distance_m - previous.distance_m)
      angle_delta = abs(record.encoded_angle_deg - previous.encoded_angle_deg)
      distance_gate = 0.5 + 25.0 * dt
      if distance_delta > distance_gate or angle_delta > 4.0:
        continue
      score = distance_delta / distance_gate + angle_delta / 4.0
      candidates.append((score, target))
    candidates.sort(key=lambda candidate: candidate[0])
    if not candidates:
      return None
    # Do not force an association when two old targets are similarly plausible.
    if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < 0.25:
      return None
    return candidates[0][1]

  @staticmethod
  def _update_track(target: CornerRadarTarget, record: CornerRadarRecord) -> None:
    if target.history and record.timestamp_nanos <= target.history[-1][0]:
      target.history.clear()
      target.estimated_radial_speed_mps = None
    target.record = record
    target.history.append((record.timestamp_nanos, record.distance_m, record.address, record.slot))
    target.estimated_radial_speed_mps = None
    if len(target.history) == target.history.maxlen:
      # Address + slot are not treated as a permanent sensor target ID. They are
      # only an additional continuity requirement before estimating speed.
      if len({(address, slot) for _, _, address, slot in target.history}) != 1:
        return
      slopes = []
      for (t1, r1, _, _), (t2, r2, _, _) in zip(target.history, list(target.history)[1:], strict=False):
        dt = (t2 - t1) / 1e9
        if not 0.01 <= dt <= 0.20:
          return
        speed = (r2 - r1) / dt
        if abs(speed) > 25.0:
          return
        slopes.append(speed)
      if max(slopes) - min(slopes) <= 4.0:
        # Negative means closing. This is an estimate from range differences,
        # never a radar-decoded REL_SPEED or target absolute speed.
        target.estimated_radial_speed_mps = statistics.median(slopes)

  def expire(self, now_nanos: int) -> None:
    self.targets = {track_id: target for track_id, target in self.targets.items()
                    if 0 <= now_nanos - target.record.timestamp_nanos <= TRACK_TIMEOUT_NS}

  @property
  def latest_timestamp_nanos(self) -> int:
    return self._latest_timestamp_nanos

  def pop_raw_frames(self) -> list[RawCornerRadarFrame]:
    frames = list(self.raw_frames)
    self.raw_frames.clear()
    return frames

  def json_records(self, now_nanos: int) -> list[dict]:
    self.expire(now_nanos)
    output = []
    for target in self.targets.values():
      record = asdict(target.record)
      record["raw"] = target.record.raw.hex()
      record.update({
        "track_id": target.track_id,
        "target_identity_source": "temporal_nearest_neighbor_estimate",
        "distance_source": "experimental_pr_24221",
        "angle_source": "experimental_pr_24221_mounting_unverified",
        "relative_speed_mps": None,
        "relative_speed_source": "unknown_not_decoded",
        "estimated_radial_speed_mps": target.estimated_radial_speed_mps,
        "estimated_radial_speed_source": "range_difference_temporal_track" if target.estimated_radial_speed_mps is not None else None,
      })
      output.append(record)
    return output
