# Kia EV6 factory-cluster side-vehicle evidence tools

This directory supports the evidence phase for the Kia EV6 factory instrument-cluster side-vehicle display. The analyzer is read-only. The replay command writes a JSON plan and never opens Panda, publishes `sendcan`, or transmits to a vehicle.

There is deliberately no production profile in `VERIFIED_PROFILES`. Turning on `HkgFactorySideVehicleDisplay` therefore reports `unavailable_unverified_profile` and does not add a CAN message until the exact EV6 firmware, installed Hyundai P bus visibility, fields, target source, timing, and display-only behavior have been verified.

## Required captures

Record all three scenarios on the same road section and in conditions where the factory cluster normally renders nearby vehicles. A parked test is not an acceptance test.

1. `baseline`: stock longitudinal control, Experimental Mode off.
2. `sp_long_exp_off`: sunnypilot longitudinal control active, Experimental Mode off.
3. `sp_long_exp_on`: sunnypilot longitudinal control active, Experimental Mode on.

For each capture:

- retain full `can` and `sendcan`, not a signal-only export;
- retain `carParams`, including fingerprint, flags, fuzzy-match state, and all firmware responses;
- record synchronized video of the factory cluster and label when a real vehicle appears/disappears at left-front, right-front, left-rear, and right-rear;
- note vehicle year/VIN build range, combination-meter software, head-unit software, ADAS ECU software, harness part number, and any non-stock bus wiring;
- include periods with no adjacent target and with targets entering/leaving each side;
- never create a target solely for the test.

Candidate IDs `0x1BA`, `0x161`, `0x162`, `0x1E0`, and `0x1EA` are inspected automatically. `0x4A3` is included only as a navigation/highway-state research candidate; the tool does not assign it a payload format.

## Analyze rlogs

```bash
python tools/hkg_factory_cluster/ev6_factory_cluster.py analyze \
  --scenario baseline=/path/to/baseline.rlog.zst \
  --scenario sp_long_exp_off=/path/to/sp-long-exp-off.rlog.zst \
  --scenario sp_long_exp_on=/path/to/sp-long-exp-on.rlog.zst \
  --output /tmp/ev6-cluster-evidence.json \
  --markdown /tmp/ev6-cluster-evidence.md
```

The report compares direction, observed bus, ID, length, median frequency, changed bytes, HKG checksum, counter continuity, and same-ID RX/TX conflicts. Candidate field decoding is labelled as a hypothesis and never changes `compatibility_verified` or `production_transmission_authorized` to true.

## JSONL input

JSONL can be used when a full rlog is unavailable. A frame row is:

```json
{"timestamp_nanos": 1234567890, "direction": "rx", "bus": 1, "address": "0x1EA", "data": "001122...", "event": "real_left_vehicle_appears", "video_time_s": 42.15}
```

An optional metadata row can precede the frames:

```json
{"record_type": "metadata", "metadata": {"car_fingerprint": "KIA_EV6", "cluster_version": "exact text", "head_unit_version": "exact text"}}
```

## Navigation and highway-state research

The only implemented navigation operation is a byte- and timing-exact, non-transmitting plan from received stock frames:

```bash
python tools/hkg_factory_cluster/ev6_factory_cluster.py replay-plan \
  --scenario stock_navigation=/path/to/stock-navigation.jsonl \
  --address 0x4A3 \
  --mode original_navigation \
  --output /tmp/ev6-navigation-replay-plan.json
```

Without an evidence manifest the plan is marked `bench_transmission_authorized=false`. `complete_navigation` additionally requires `complete_message_sequence_verified=true`; `fixed_highway` additionally requires `fixed_highway_value_verified=true`. Both modes require all of these manifest facts:

- exact capture SHA-256, video evidence SHA-256, firmware records, receiver ECU, bus, ID, and length;
- counter/checksum behavior verified;
- isolated bench validation;
- proof that steering, acceleration, braking, lane-change availability, and all other ADAS control states are unchanged;
- explicit mode authorization and an allowlist containing every replayed transport tuple.

Even with those facts, the generated plan always keeps `vehicle_transmission_authorized=false`. A separate reviewed sender and recovery sequence would be needed after bench validation. No highway value is inferred, no Mapbox image is encoded, and navigation replay never creates a vehicle target.

## Enabling a vehicle profile

Add a `VerifiedFactoryClusterProfile` only after the synchronized evidence establishes all of the following for one exact firmware set:

- the cluster-visible source ID and source bus through the installed Hyundai P harness;
- the destination bus, 32-byte `0x1EA` format, 20 Hz rate, HKG counter/checksum, target detection values, physical units, sign convention, neutral encoding, and timeouts;
- that every non-target bit can be preserved from a fresh original frame, or that a cached template is safe after the original sender is silenced;
- that the chosen `radarTracks` points represent verified real targets for the displayed slots;
- that a returning original sender is handled without two transmitters competing.

The current live path can only replace `0x1EA` on Panda bus 1 because that is the existing HDA2 longitudinal safety allowlist. It does not expand Panda authority for `0x161`, `0x162`, `0x4A3`, or any control message.
