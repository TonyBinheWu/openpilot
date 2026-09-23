# EV6 corner-radar JSONL converter

This tool preserves candidate raw frames and labels every derived value by source. Run it from any directory:

```bash
python tools/corner_radar/ev6_corner_radar.py input.jsonl decoded.jsonl
```

Accepted input aliases are `timestamp_nanos`/`logMonoTime`, `source_bus`/`bus`/`src`, `address`/`can_id`/`id`, and `data`/`dat`/`payload`. Addresses may be integers or `0x` strings. Data may be hexadecimal text or a byte list.

The output contains `raw_frame`, `decoded_record`, `track_snapshot`, and final `summary` rows. `relative_speed_mps` remains `null`; `estimated_radial_speed_mps` is separate and appears only after conservative temporal continuity checks. `public_sample_decoded.jsonl` is the reproducible output for the bundled public frame. See [HKG_CORNER_RADAR.md](../../docs/HKG_CORNER_RADAR.md) for evidence and limitations.
