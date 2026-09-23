# CTM / CTMV2 lag on comma 3X

Investigation base: `TonyBinheWu/sunnypilot` `hkg-enhanced` at
`c398a6235af6e83c38bf9e967121c0b75868f2a4`. The comparison used current
sunnypilot `master` at `6135084c`, the requested `dev-chestnut` release commit
`0e51ecbb7efc004c81cb640500a4d886f3ebb9c5`, and that release's recorded source
commit `b255314f5ad9ff46f5561c7c2ef21c5b3c6585e7`.

No comma 3X capture was supplied, so an exact device-level root cause cannot be
claimed. The branch did, however, contain two concrete divergences capable of
making a model that is already near its 50 ms budget miss frames intermittently.

## Findings

- The requested `0e51ecb` commit is an orphaned, prebuilt `dev-chestnut` release,
  not a normal source commit. Its commit message records `b255314f` as the master
  source revision. Comparing that source with current master shows no hidden CTM
  scheduling or frame-drop fix; the relevant runtime difference is only a helper
  relocation.
- `hkg-enhanced` added a second taco2 navigation model and Mapbox renderer. When
  enabled, that model shared the Chestnut AMD/USB execution path with the 20 Hz
  driving model. Even at a lower navigation rate, resource contention can produce
  periodic driving-model misses. A per-frame navigation bridge was also inserted
  into both driving-model loops.
- The branch's custom model build change replaced upstream
  `TC_OCCUPANCY_OPT=1` with a backported `TC_MIN_GLOBALS=32` configuration and
  changed camera build selection. That is not the build path recorded by the
  requested release source. It also made locally rebuilt artifacts differ from
  the official sunnypilot path without device benchmarks proving an improvement.
- `modelV2.frameDropPerc` measures skipped consumed camera frame IDs. The
  `Driving Model Lagging` alert fires above 1%; hiding the alert or changing that
  threshold would not fix inference latency.

The pinned Chestnut v25 catalog gives another useful clue:

| Bundle | Reference | Build | Chunks |
|---|---|---|---:|
| Sad Model (`SM`) | `30de303d…` | `recompiled24`, 2026-09-01 | 17 |
| CTM | `68b5f8e4…` | `recompiled25`, 2026-09-05 | 18 |
| CTMV2 | `37bfa141…` | `recompiled25`, 2026-09-08 | 18 |

CTM and CTMV2 share 15 of 18 compiled chunk hashes; Sad Model shares none with
either. This strongly suggests CTM and CTMV2 use the same newer compiled execution
shape, distinct from Sad Model. Chunk identity is not a performance measurement,
so it cannot establish whether the remaining cost is in the model artifact,
USB transfer, warp, or host scheduling.

## Fix applied in this branch

- Removed Mapbox navigation, taco2, all navigation-model processes, services,
  parameters, UI paths, and the per-frame navigation bridge.
- Restored the original OSM page plus the upstream `mapd` / `mapd_manager` path.
- Restored stock and selected-model runtime/build files to current sunnypilot
  master, including `TC_OCCUPANCY_OPT=1` on the selected Chestnut build workflow.
- Kept the alert threshold, 20 Hz model rate, camera geometry, and model outputs
  unchanged. The change removes competing work instead of masking dropped frames.

## Read-only validation

After installing this branch, delete and redownload CTM/CTMV2 if the device holds
an artifact built locally by the old custom compile path. Then collect a 60-second
sample while parked; do not operate SSH while driving:

```bash
cd /data/openpilot
python tools/scripts/diagnose_model_lag.py --seconds 60 --output /data/ctm_c3x.jsonl
```

Use a new output filename for each run; the tool intentionally refuses to
overwrite a prior capture. To inspect a saved rlog instead:

```bash
python tools/scripts/diagnose_model_lag.py --rlog /path/to/rlog.zst --output /data/ctm_rlog.jsonl
```

Compare CTM, CTMV2, and Sad Model under the same device temperature and camera
conditions. Relevant fields are median/p95/max `modelExecutionTime`, samples over
50 ms, `frameDropPerc`, camera publication intervals, Chestnut clocks and
temperature, PCIe state, power/fault state, and USB speed/error counters.

If CTM still drops frames after the competing navigation path is gone, the next
decision needs that capture. The three main remaining risks are:

1. The official CTM/CTMV2 compiled artifact itself exceeds the c3x 50 ms budget
   intermittently and must be rebuilt upstream with measured compiler tuning.
2. Chestnut thermal, power, PCIe, USB-link, or cable behavior is causing stalls.
3. Camera synchronization or host load outside modeld is skipping input frames.

The diagnostic script is read-only: it does not load another model, change model
rate, suppress alerts, write Params, or send CAN.
