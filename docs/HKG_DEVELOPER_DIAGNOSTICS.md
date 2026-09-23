# Developer UI: eGPU and vehicle signals

Enable any existing Developer UI mode in the standard sunnypilot UI.
The new panel appears below the torque panel, offset to leave the driver
monitoring indicator visible. The separate mici HUD is not changed here.

## Temperature

- eGPU HOTSPOT / MEMORY: `chestnutState.tempC` / `memoryTempC`, in Celsius.
  These are external GPU hotspot and memory readings, not `deviceState.gpuTempC`
  (the host GPU). MAX is the highest valid reading received this session.
- The current producer publishes at 10 Hz but refreshes its cached AMD metrics
  every 100 sends, approximately 10 seconds. This display does not poll the
  GPU hardware or change model execution. Brief thermal peaks may be missed.
- Invalid, zero/uninitialized, non-finite or stale values show `--`. Absence
  of the publisher, including some fallback/model-loading states, is not 0 C.
  Disconnects retain the session peak while the current value becomes unavailable.

## Vehicle signals

The current decoded state includes left/right indicators, gear, gas, brake,
regenerative braking, door, seatbelt and steering override. Changes also track
parking brake, blind spots and decoded button press/release events. An initial
snapshot establishes the baseline; it is not reported as a new operation.
The three newest events from a bounded six-event buffer are shown with age.
Missing carState data shows `--`; samples resume with a new baseline.

The CAN RX section independently samples the `can` service. It shows bus,
hexadecimal message ID, payload length, the first eight bytes and last-seen age.
`..` marks a longer payload and `*` marks a recently changed payload. Pages of
three IDs rotate every three seconds. Bus + ID uniquely identify an entry.
Transmit echoes (`src >= 128`) are excluded. Counters/checksums can change bytes
without any driver action: temporal proximity is not proof of signal meaning.

The subscriber conflates to the latest batch, reads one non-blocking batch per
UI update and processes at most 256 frames. The table retains at most 256 IDs.
This is not a full CAN logger, a complete DBC decoder, an exact frame-rate meter,
or a capture of all vehicle networks. UI sampling can miss short button events.
The UI sees only the buses exposed by the installed harness and vehicle port.

## How the existing direction indicators work

For the pinned Hyundai CAN FD port, `opendbc/car/hyundai/carstate.py` reads
`BLINKERS.LEFT_LAMP` and `BLINKERS.RIGHT_LAMP` (alternative lamp fields for
specific models), then uses `update_blinker_from_lamp(50, ...)` to maintain the
decoded indicator state through lamp blinking. It publishes `carState.leftBlinker`
and `rightBlinker`. `openpilot/selfdrive/ui/sunnypilot/onroad/turn_signal.py`
reads those flags and draws its own blinking animation. Blind-spot display can
take precedence over the direction indicator. This is not camera recognition
or a model prediction of the driver's intent.

## Lifecycle and validation

Subscriptions exist only while on-road with Developer UI enabled. The collector
runs in UI state updates, so switching the setting off in another screen also
clears temperatures, peaks, event history, ID table and baseline, and releases
both socket references. New drives and UI restarts also reset everything.
No diagnostic files or parameters persist the session. Standard driving logs
are not deleted or otherwise changed. Subscription failures show ERROR and
retry after two seconds; they do not terminate the driving UI.

Ten unit tests cover temperature validity/staleness, session peaks, signal
transitions, duplicate events, bounded memory/work, bus identity, payload
truncation, echoes, lifecycle and subscription failures. Existing torque tests
also pass. No hardware or on-road validation has been performed.
