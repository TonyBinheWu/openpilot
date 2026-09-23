# Developer UI steering telemetry

The existing Developer UI (bottom, right, or both) now shows a compact panel
on the left below the speed-limit ahead sign in the standard sunnypilot UI.
It is hidden when Developer UI is off. The separate mici HUD does not use
this Developer UI renderer and is not changed here.

- `REQ`: `carControl.actuators.torque`, signed normalized command × 100.
- `SENT`: `carOutput.actuatorsOutput.torque`, signed normalized command × 100,
  after vehicle-controller limits. This is not measured motor torque or proof
  that the EPS accepted the command.
- `CAN`: `carOutput.actuatorsOutput.torqueOutputCan`, native command units
  reported by the vehicle port; availability depends on the port.
- `LAST CONTROL SAT`: the most recent valid UI sample with an active torque
  or PID controller reporting `saturated`, without driver override. Shows
  sent torque, native CAN command, sample age, speed, and steering angle.

The driving model plans curvature; the lateral controller computes torque.
Normalized percentages and native CAN units must not be labeled Nm.
Controller saturation is **not** the vehicle's physical torque limit. The
existing saturation flag can also reflect curvature limiting, has a timer
and speed gates, and does not describe every vehicle-side limiting event.
Requested/sent differences are deliberately not treated as saturation.

This is an on-screen, UI-rate sample history, not a complete control-rate
event recorder or GPS location marker. Short events between UI updates can
be missed. History resets on a new drive, disabling Developer UI, a backward
log timestamp, or an unsupported controller. Invalid, dead, pre-drive or
time-skewed streams hide live values; the last valid event is retained with
its age marked unavailable. It is not persisted across UI restarts.

## Other requested features: prerequisites remain unresolved

The current model runners do not feed OSM road geometry into inference.
An OSM-aware turn intention needs route/road matching and a model trained
for a defined navigation input. A turn signal alone cannot distinguish a
lane change from one of several turns. This change does not inject map data
into unrelated tensor inputs or restore the removed offline OSM experiment.

The model messages do not expose a red/green traffic-light classification.
Braking or stopping predictions cannot supply that classification. A real
signal detector with lane relevance, confidence and stale/unknown handling
is needed before adding a Visuals toggle and a signal icon below the
experimental-mode button. Neither that toggle nor a fabricated signal icon
is added here.

## Validation

`python -m unittest discover -s openpilot/selfdrive/ui/tests -p test_torque_debug.py`
checks signed values, units, history, invalid/stale streams, replay/session
resets, override/inactive behavior and unsupported controller types.
No model, control, CAN, safety or process configuration is modified.
Device rendering and on-road behavior still require validation.
