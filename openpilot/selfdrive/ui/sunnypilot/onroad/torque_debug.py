"""Read-only, UI-sampled controller telemetry; never estimates physical EPS limits."""
from dataclasses import dataclass
import math


SERVICES = ('carState', 'carControl', 'carOutput', 'controlsState')
MAX_SAMPLE_SKEW_NS = 250_000_000


@dataclass(frozen=True)
class TorqueSample:
  time_ns: int
  requested: float
  sent: float
  can_output: float
  speed: float
  angle: float
  active: bool
  overridden: bool
  saturated: bool


class TorqueDebugState:
  def __init__(self):
    self.session = None
    self.current: TorqueSample | None = None
    self.last_saturation: TorqueSample | None = None
    self.status = 'NO DATA'
    self._last_time = 0

  def update(self, sm, started_frame: int, enabled: bool) -> None:
    if self.session != started_frame or not enabled:
      self.current = self.last_saturation = None
      self._last_time = 0
      self.session = started_frame
    if not enabled:
      self.status = 'OFF'
      return

    self.current = None
    self.status = 'NO DATA'
    if any(not sm.valid[s] or not sm.alive[s] or sm.recv_frame[s] < started_frame for s in SERVICES):
      return
    times = [sm.logMonoTime[s] for s in SERVICES]
    if min(times) <= 0 or max(times) - min(times) > MAX_SAMPLE_SKEW_NS:
      return

    time_ns = sm.logMonoTime['controlsState']
    if time_ns < self._last_time:  # replay seek or process restart
      self.last_saturation = None
    self._last_time = time_ns

    lateral = sm['controlsState'].lateralControlState
    kind = lateral.which()
    if kind not in ('torqueState', 'pidState'):
      self.last_saturation = None
      self.status = 'NOT TORQUE CONTROL'
      return

    cs, cc = sm['carState'], sm['carControl']
    output = sm['carOutput'].actuatorsOutput
    values = (cc.actuators.torque, output.torque, output.torqueOutputCan, cs.vEgo, cs.steeringAngleDeg)
    if not all(math.isfinite(v) for v in values):
      return
    state = getattr(lateral, kind)
    saturated = bool(cc.latActive and state.active and not cs.steeringPressed and state.saturated)
    self.current = TorqueSample(time_ns, *values, cc.latActive, cs.steeringPressed, saturated)
    self.status = 'OVERRIDE' if cs.steeringPressed else ('ACTIVE' if cc.latActive else 'INACTIVE')
    if saturated:
      # Last observed saturated sample, not peak torque or physical motor limit.
      # Do not infer saturation from requested/sent differences (rate limits etc.).
      self.last_saturation = self.current

  def lines(self, is_metric: bool) -> list[str]:
    current, last = self.current, self.last_saturation
    title = 'CONTROL TORQUE (%) | ' + self.status
    live = 'REQ --   SENT --   CAN --'
    if current is not None:
      live = f'REQ {current.requested * 100:+.1f}   SENT {current.sent * 100:+.1f}   CAN {current.can_output:+.0f}'
    if last is None:
      return [title, live, 'LAST CONTROL SAT: --', 'No saturation observed in this UI session']
    age = f'{max(0, current.time_ns - last.time_ns) / 1e9:.0f}s ago' if current is not None else 'age unavailable'
    unit, factor = ('km/h', 3.6) if is_metric else ('mph', 2.2369362921)
    return [title, live,
            f'LAST CONTROL SAT: {last.sent * 100:+.1f}% | CAN {last.can_output:+.0f} | {age}',
            f'AT {last.speed * factor:.1f} {unit} | STEER {last.angle:+.1f} deg']
