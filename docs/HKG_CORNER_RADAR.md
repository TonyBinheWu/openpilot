# HKG CAN-FD corner-radar research display

This implementation passively records and displays candidate Kia EV6 corner-radar frames. It does not transmit CAN, change Panda safety policy, or use the output for steering, longitudinal control, or lane-change decisions.

## Evidence and pinned revisions

| Source | Revision checked | Supported conclusion |
|---|---|---|
| [commaai/openpilot PR #24221](https://github.com/commaai/openpilot/pull/24221) | head `abcc844c00bddba9105d868d2ee40749e5ed2741` | Candidate IDs, 64-byte records, and experimental range/angle formulas |
| `TonyBinheWu/sunnypilot` | `hkg-enhanced` base `934b4e899270389770286e01cb56bc373c8fdfae` | Integration point for this implementation |
| `TonyBinheWu/opendbc` submodule | `fa4874935666a796fb4dcb0f4afa4056c105216f` | Existing CAN-FD BSM state comes from `ADAS_CMD_50_50ms` (`0x1BA`) |
| [dhvms/carrotpilot](https://github.com/dhvms/carrotpilot) | `be766a9dad2b6d4b56827e621bdd05cfc04373c0` | BSM indicators and front-radar lane classification do not decode four corner radars |

PR #24221 is closed and unmerged. Its TODO list leaves validity/status, relative speed, and DBC work unfinished. The formulas below are research candidates, not Kia specifications.

## Passive receive rules

- Candidate CAN IDs: `0x300–0x307`, `0x400–0x407`, `0x500–0x507`, and `0x600–0x607`.
- A candidate frame must contain exactly 64 bytes. Each frame is split into eight 8-byte records.
- Every received Panda bus (`src` from 0 through 127) is inspected. The implementation discovers and logs buses that actually carry accepted 64-byte frames; it does not hardcode bus 9.
- `src >= 128` is a transmitted echo and is ignored by the live receiver.
- Wrong-length candidate frames are retained and counted, but never decoded. This prevents 8-byte front-radar frames on overlapping IDs such as `0x500–0x507` from being treated as corner-radar records.
- No bitrate, harness routing, Panda mode, or CAN forwarding assumption is added.

The public research used bus 9 for its recording setup. That number is not evidence for Hyundai P harness routing. If no accepted frames appear, the private radar network may not be physically exposed by the installed harness; software scanning cannot recover a network that never reaches Panda.

## Candidate decoding

For bytes `b[0]` through `b[7]` in one record:

```text
distance_m = (256 * b[3] + b[4]) / 256
encoded_angle_deg = (256 * b[5] + b[6]) / 256
```

The old research subtracts the encoded angle from 165° for groups `0x3xx` and `0x4xx`, and from 175° for groups `0x5xx` and `0x6xx`. It assigns groups 0/2 to the left, groups 1/3 to the right, groups 0/1 to the front, and groups 2/3 to the rear. The HUD uses this experimental grouping; physical mounting, coordinate origin, and these offsets remain unvalidated.

The Visuals `HkgCornerRadarDetection` switch enables independent panels on both sides of the sunnypilot speedometer. These are device-screen graphics, not factory-cluster CAN output. Existing blind-spot icons remain separate. The panels reserve space for both standard central blind-spot widgets and mici edge icons; a viewport too narrow to fit them hides the panels.

Each group contributes up to three nearest fresh candidates (at most six per side). Yellow dots represent unclassified returns, not confirmed vehicles. Front-group dots are above the speed center and rear-group dots below it, using the unvalidated mapping above. Radial distance controls vertical displacement and marker size. Horizontal columns only separate dots; they do not indicate measured lateral position. Ordering can change when candidates enter or leave and is not a claim of stable physical identity.

`RADAR*` identifies experimental data, and `~12.3 m` shows the nearest candidate range on that side. Unknown speed and object class are not displayed. Bus, group, raw frames and every accepted record remain available in logs and JSONL. Target age plus elapsed message-receipt time must not exceed 350 ms, so stopped publishers cannot leave frozen dots. Invalid, absent, inactive and stale data produce no marker. Turning this option off removes only the radar panels.

This change builds on main commit `5699249f015a4415ebe88897c1bfc5b7b325c9cc`, with opendbc `03f4ba63901497df0fe4d6aa01cfd3504fe7aa69`. It changes no radar decoding, CAN transmission, safety policy or driving decisions. Offline tests cover multiple targets, invalid data, stale publishers, layout clearance and range-based motion. Actual Hyundai P reception and physical mounting remain to be verified from passive vehicle logs.

The old `record[0:2] != 0x8080` activity heuristic is retained as `candidateActive`, with `statusValidated=false`. It must not be interpreted as a decoded Kia validity bit.

## Target association and speed

CAN ID plus record slot is not exposed as a permanent target ID. The runtime assigns an ephemeral ID using same-bus, same-group temporal nearest-neighbor gates. Ambiguous associations, jumps, stale data, and timestamps outside the accepted order do not update an old track.

There is no supported direct relative-speed decode. Live schema field `relativeSpeedValid` stays false, and JSONL writes `relative_speed_mps: null` with source `unknown_not_decoded`.

An estimated radial speed may be published separately only after four samples pass all of these checks:

- same received bus and candidate sensor group;
- one unambiguous temporal track;
- same address and slot across the estimate window, used only as a continuity check;
- 10–200 ms between samples;
- range and angle gates pass;
- every range slope is at most 25 m/s in magnitude and their spread is at most 4 m/s.

The calculation is `(r2 - r1) / (t2 - t1)`. A negative value means the measured range is closing. This remains an **estimated radial speed**, not radar-decoded relative speed, ego longitudinal speed, or target absolute speed. A slot change clears the estimate even when visual tracking continues.

## Traceable output

When `HkgCornerRadarDetection` is enabled on an HKG CAN-FD car, `corner_radard` publishes and logs `cornerRadarStateSP` at 20 Hz. It includes:

- raw candidate frames, source bus, CAN ID, timestamps, length acceptance, and timestamp acceptance;
- counters for accepted candidates, wrong lengths, timestamp errors, and raw-buffer drops;
- candidate distance, encoded/corrected angle, experimental coordinates, ephemeral track ID, and estimate-valid flags;
- the exact public research revision in `researchSource`.

For standalone analysis, use:

```bash
python tools/corner_radar/ev6_corner_radar.py tools/corner_radar/public_sample_frame.jsonl decoded.jsonl
```

The JSONL output keeps raw frames, decoded records, track snapshots, explicit source labels, rejection reasons, and a final summary. The sample's bus 9 is preserved only for reproducibility of the public recording and is not a device configuration.
