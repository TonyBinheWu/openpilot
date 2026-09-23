"""Bounded, read-only telemetry for one Developer UI session."""
from collections import OrderedDict, deque
from itertools import islice
import math
import time

WATCH_FIELDS = ('leftBlinker', 'rightBlinker', 'gasPressed', 'brakePressed', 'regenBraking',
                'steeringPressed', 'doorOpen', 'seatbeltUnlatched', 'parkingBrake',
                'leftBlindspot', 'rightBlindspot', 'gearShifter')
MAX_IDS = 256
MAX_FRAMES = 256
STALE_SECONDS = 2.0


class DeveloperDiagnostics:
  def __init__(self):
    self._can_sock = self._gpu_sock = None
    self.session = None
    self.enabled = False
    self._retry_at = 0.0
    self.reset()

  def reset(self):
    self.temperature = self.peak = self.memory_temperature = self.memory_peak = None
    self.gpu_seen = self.can_seen = self.cs_seen = None
    self.values = {}
    self.events = deque(maxlen=6)
    self.frames = OrderedDict()
    self.sample_count = self.capped_batches = 0
    self._cs_timestamp = None
    self.error = False
    self.started_at = None

  def set_session(self, enabled, session, now):
    if enabled != self.enabled or session != self.session:
      # msgq sockets release their native handles when references are dropped.
      self._can_sock = self._gpu_sock = None
      self.reset()
      self.started_at = now if enabled else None
      self._retry_at = 0.0
    self.enabled, self.session = enabled, session

  def ingest_temperature(self, state, valid, now):
    self.temperature = self.memory_temperature = None
    if not valid:
      self.gpu_seen = None
      return
    self.gpu_seen = now
    # A bridge-only message has zero-valued GPU fields, not a 0 C GPU reading.
    for source, current, peak in (('tempC', 'temperature', 'peak'), ('memoryTempC', 'memory_temperature', 'memory_peak')):
      value = float(getattr(state, source))
      if math.isfinite(value) and 0 < value < 200:
        setattr(self, current, value)
        previous = getattr(self, peak)
        setattr(self, peak, value if previous is None else max(previous, value))

  def ingest_car_state(self, cs, timestamp, now):
    self.cs_seen = now
    if timestamp == self._cs_timestamp:
      return
    self._cs_timestamp = timestamp
    values = {name: str(cs.gearShifter) if name == 'gearShifter' else ('ON' if getattr(cs, name) else 'OFF')
              for name in WATCH_FIELDS}
    for name, value in values.items():
      if name in self.values and self.values[name] != value:
        self.events.appendleft((now, f'{name}: {self.values[name]} -> {value}'))
    self.values = values
    for button in cs.buttonEvents:
      self.events.appendleft((now, f'button.{button.type}: {"PRESS" if button.pressed else "RELEASE"}'))

  def ingest_can(self, frames, now):
    self.can_seen = now
    self.capped_batches += int(len(frames) > MAX_FRAMES)
    for frame in islice(frames, MAX_FRAMES):
      if frame.src >= 128:  # transmitted-message echoes are not received bus data
        continue
      key = (int(frame.src), int(frame.address))
      data = bytes(frame.dat)
      previous = self.frames.pop(key, None)
      changed = previous is not None and previous[0] != data
      self.frames[key] = (data, now, now if changed else (previous[2] if previous else None))
      self.sample_count += 1
      if len(self.frames) > MAX_IDS:
        self.frames.popitem(last=False)

  def update(self, sm, enabled, session, now=None, messaging_module=None):
    now = time.monotonic() if now is None else now
    self.set_session(enabled, session, now)
    if not enabled:
      return
    if sm.valid['carState'] and sm.alive['carState'] and sm.recv_frame['carState'] >= session:
      self.ingest_car_state(sm['carState'], sm.logMonoTime['carState'], now)
    else:
      self.cs_seen = None
      self.values = {}  # restart baseline after a gap; do not invent transitions
    if now < self._retry_at:
      return
    try:
      if messaging_module is None:
        from openpilot.cereal import messaging as messaging_module
      if self._can_sock is None:
        self._can_sock = messaging_module.sub_sock('can', conflate=True)
        self._gpu_sock = messaging_module.sub_sock('chestnutState', conflate=True)
      # One non-blocking batch per service/frame: never drain the CAN backlog.
      can = messaging_module.recv_one_or_none(self._can_sock)
      gpu = messaging_module.recv_one_or_none(self._gpu_sock)
      if can is not None and can.valid:
        self.ingest_can(can.can, now)
      if gpu is not None:
        self.ingest_temperature(gpu.chestnutState, gpu.valid, now)
      self.error = False
    except Exception:
      # Diagnostics must not terminate the driving UI; show failure and retry slowly.
      self.error = True
      self.temperature = self.memory_temperature = None
      self._can_sock = self._gpu_sock = None
      self._retry_at = now + 2.0

  def lines(self, now=None):
    now = time.monotonic() if now is None else now
    def temperature_text(value):
      return '--' if value is None else f'{value:.1f}'
    gpu_fresh = self.gpu_seen is not None and now - self.gpu_seen <= STALE_SECONDS
    lines = [f'eGPU HOTSPOT {temperature_text(self.temperature if gpu_fresh else None)} C | MAX {temperature_text(self.peak)} C',
             f'eGPU MEMORY {temperature_text(self.memory_temperature if gpu_fresh else None)} C | MAX {temperature_text(self.memory_peak)} C']
    valid_cs = self.cs_seen is not None and now - self.cs_seen <= STALE_SECONDS
    def value(name):
      return self.values.get(name, '--') if valid_cs else '--'
    lines += [f'BLINK L {value("leftBlinker")} R {value("rightBlinker")} | GEAR {value("gearShifter")}',
              f'GAS {value("gasPressed")} BRAKE {value("brakePressed")} REGEN {value("regenBraking")}',
              f'DOOR {value("doorOpen")} BELT UNLATCH {value("seatbeltUnlatched")} STEER {value("steeringPressed")}']
    for i in range(3):
      lines.append(f'{now - self.events[i][0]:.0f}s {self.events[i][1]}' if i < len(self.events) else 'EVENT --')
    keys = sorted(self.frames)
    pages = max(1, math.ceil(len(keys) / 3))
    page = int((now - (self.started_at if self.started_at is not None else now)) / 3) % pages
    status = 'ERROR' if self.error else ('LIVE' if self.can_seen is not None and now - self.can_seen <= STALE_SECONDS else 'NO DATA')
    lines.append(f'CAN RX SAMPLED {status} | IDs {len(keys)} | PAGE {page + 1}/{pages}')
    for key in keys[page * 3:page * 3 + 3]:
      data, seen, changed = self.frames[key]
      marker = '*' if changed is not None and now - changed < 2 else ' '
      # Prefix only: CAN FD payloads can be 64 bytes. Length and age are explicit.
      lines.append(f'{marker}B{key[0]} 0x{key[1]:X} [{len(data)}] {data[:8].hex().upper()}{".." if len(data) > 8 else ""} {now - seen:.1f}s')
    return lines
