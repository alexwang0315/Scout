# Scout 3D renderer comparison on the user's Mac

Status: **WORKING PROTOTYPE — Mac measurement completed**, 2026-09-09.

2026-09-10：普通展示與對照頁共用的高程色帶已依使用者參考圖更新；見
[配色與高度分布](scout-gpx-3d-hypsometric-reference.md)。下列量測及截圖維持
09-09 當時的配色與條件，原始紀錄未改動，尚未以新色帶重跑 Mac 效能量測。

同一台 Mac、相同可見網格間距與圖層下，目前 MapLibre 對照頁的旋轉更新率、
載入時間與記憶體結果都優於目前 Three.js 完整密度展示。這不支持直接把
Dashboard 的體感差異歸因於引擎；普通 demo 使用更粗的網格，場景負擔也較少。

MacBookPro14,1 · Intel i5-7360U / Iris Plus 640 · 8 GiB RAM · macOS 13.7.8 ·
Chrome 152.0.7977.83 · ANGLE Metal hardware renderer · AC power, battery 100%.
Capture: 2026-09-09 14:27:16–14:31:56 Asia/Taipei. Three trials per engine;
the following values are medians across those trials.

| 指標 | Three.js 展示 | MapLibre 原生地形對照 |
| --- | ---: | ---: |
| 旋轉平均更新率 | 47.56 FPS | 60.00 FPS |
| 幀間隔 p95 | 23.60 ms | 19.50 ms |
| 相對刷新週期的更新缺口估計 | 20.61% | 0.41% |
| 首次完整 3D 畫面，含共同資料傳輸 | 6.184 s | 5.174 s |
| 其中引擎建立階段 | 1.402 s | 0.645 s |
| Chrome 程序樹峰值 RSS | 1,450.6 MiB | 907.4 MiB |
| 畫面就緒時主頁 JavaScript heap | 295.5 MiB | 9.4 MiB |

更新缺口是從 Mac 的實際 render 時間樣本估算，**不是 compositor 確認的實體
螢幕掉幀率**。RSS 含共享頁，heap 也不涵蓋所有 native／worker／GPU 記憶體。
完整定義與條件在下方；數字不能直接當成整個 Dashboard 的效能。

| 輪次 | 引擎 | 首次 3D (s) | 平均 FPS | p95 (ms) | 更新缺口估計 | 峰值 RSS (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Three | 6.376 | 48.03 | 23.8 | 20.22% | 1,131.1 |
| 2 | MapLibre | 5.764 | 57.36 | 26.9 | 4.17% | 814.0 |
| 3 | MapLibre | 5.173 | 60.00 | 19.2 | 0.00% | 913.8 |
| 4 | Three | 5.904 | 47.56 | 23.3 | 20.61% | 1,455.2 |
| 5 | Three | 6.184 | 46.96 | 23.6 | 22.02% | 1,450.6 |
| 6 | MapLibre | 5.085 | 60.00 | 19.5 | 0.41% | 907.4 |

Six-trial parity: PASS; maximum height difference 0.462 m, maximum screen
projection difference 0.050 px. All observed native terrain tiles remained at
Z14 with 128 cells per tile. All six trials had zero console errors, warnings,
HTTP errors, failed requests, external application requests or mutations.

Local evidence, intentionally ignored by Git:

- [Analyzed results and all raw samples](../../outputs/evals/scout-gpx-3d/benchmark/mac-2026-09-09/analysis.json).
- [Immutable original capture](../../outputs/evals/scout-gpx-3d/benchmark/mac-2026-09-09/measurement-3/report.json).
- Mac screenshots: [Three.js](../../outputs/evals/scout-gpx-3d/benchmark/mac-2026-09-09/measurement-3/1-three-ready.png),
  [MapLibre](../../outputs/evals/scout-gpx-3d/benchmark/mac-2026-09-09/measurement-3/2-maplibre-ready.png).
- [Source integrity](../../outputs/evals/scout-gpx-3d/benchmark/source-integrity.json)
  and [ordinary demo browser regression](../../outputs/evals/scout-gpx-3d/benchmark/demo-regression/browser-report.json).

## What is compared

The experiment compares the GPX demo's Three.js 0.180.0 renderer with the
Dashboard's existing, unmodified MapLibre GL JS 6.2.0 native raster-dem terrain
renderer. Both run on the same Mac, sequentially, through an isolated read-only
test service. It does not measure the complete Dashboard's UI or multi-map
synchronization overhead, and does not modify its production runtime.

Both scenes use:

- The explicitly selected Workspace's GPX `839bf9fac6f2fd73995a71ed`, SHA-256
  `5f0ff2993d561d8f3c5b108db215d312d85d703e51e1fd93743940768df916db`.
  All 5,768 points and the original segment are retained; two endpoint markers,
  no source waypoint and no provenance-matched CP. Source type remains `unknown`.
- The same 54 prepared local Terrain RGB PNGs, Z13, 256 × 256 pixels, with every
  tile's hash checked before rendering. DEM source fingerprint:
  `5bf9edd54b7ac4fc21dbd51cb74e7af1d6b117ef4e4a788245d4a701eb30e498`.
  The original DEM source cell size is 20 m; the prepared pixel grid is about
  17.53 m at the test center. Resampling adds no source resolution. Vertical
  datum remains `unknown`.
- DEM elevation colors, a 3 px GPX line, and source endpoint/node layers. No
  basemap, hillshade, coordinate grid, replay animation or synchronized second
  map is active. Heights are visual draping only, exaggeration 1, with no
  additional demo-only 12 m lift. Original GPX elevations are untouched.
- A 1280 × 800 viewport, 1280 × 720 drawing buffer, pixel ratio 1, pitch 45°,
  zoom 14, identical route-midpoint center, and a 360° orbit over 12 seconds.

Three.js triangulates all 2,304 × 1,536 source pixels: 3,538,944 vertices. This
intentionally removes the ordinary demo's coarse stride-16 mesh advantage.
MapLibre is constrained through `setSourceTileLodParams(1, 16, sourceId)` to one
LOD in the bounded viewport. Its actual terrain tiles are checked for Z14 with
128 mesh cells per tile: the same ground spacing as the Z13 256-pixel source.
The check continues during rotation and fails on coarser or finer spacing.
Terrain geometry and color relief use separate native DEM sources backed by the
same checked PNG bytes, following the native renderer's source separation rule.

MapLibre retains native tile culling and mesh reuse. Equal visible mesh spacing
does not mean identical total triangle counts, interpolation or line raster
coverage. Its native terrain implementation is pinned in the existing vendor
directory; see [MapLibre 6.2.0 terrain source](https://github.com/maplibre/maplibre-gl-js/blob/v6.2.0/src/render/terrain.ts).

## Measurement definitions

Each engine runs three times, in the order Three / MapLibre / MapLibre / Three /
Three / MapLibre. Each trial launches a separate installed Chrome instance with
a fresh Playwright profile, closes only that instance, disables HTTP cache,
checks the actual WebGL GPU, viewport and foreground visibility, then performs
a 4-second warm-up rotation before recording a 12-second rotation. Existing
Chrome profiles and other applications are not changed. OS, disk and server
caches are not flushed, and this is not a thermally controlled laboratory test.

First complete 3D time starts at page navigation and ends after the common input
load, renderer setup, initial GPU finish, and two animation frames. It includes
the private SSH data transfer and full common input decoding. Engine setup is
reported separately. These are controlled test-page timings, not the ordinary
demo's or complete Dashboard's real-world startup latency.

Frame intervals are recorded from actual render callbacks on the Mac. Refresh
period is calibrated from 90 idle requestAnimationFrame callbacks. Expected
updates are `round(sum(intervals) / refreshPeriod)`. The update deficit is
`max(0, expected - observed)` divided by `observed + deficit`. Rounding over the
whole observation window preserves cumulative deficits: for example, a steady
50 FPS stream on a 60 Hz cadence cannot be counted as zero missed updates.
Frame p95, mean FPS, raw intervals and
the corresponding rAF timings are retained. **These are render-submission timing
estimates, not compositor-confirmed physical display drop counts.**

The first capture's per-interval rounding underestimated cumulative deficits.
A failing 50 FPS / 60 Hz test reproduced this analysis bug. The corrected
whole-window estimator passed the test and recomputed all six trials from their
unchanged raw samples. `analysis.json` is authoritative for summaries;
`measurement-3/report.json` preserves the original bytes and old derived counts.
No browser timing, load-time or memory sample was rewritten or rerun for that
statistics correction. Capture SHA-256:
`f7a0c6edd9c6f7c992a8663386683e5627185fd3a51e6c0b6ee5f4737093b6cb`.

Chrome process-tree RSS is sampled every 500 ms from the owned browser PID and
its descendants, with blank-page, scene-ready and final samples. Peak RSS may
double-count shared pages; it is not dedicated GPU VRAM. CDP JS heap usage is
reported separately and excludes much of native/WebGL memory.

All trials must have matching GPX/CP/DEM fingerprints and configuration. Six
terrain and screen-position probes at each of bearings 0° and 90° check the
actual adapter outputs, with maximum tolerances of 1 m and 5 px. Nonfinite
samples, missing probes, viewport changes, software GPU, network failures or
renderer errors invalidate the comparison. Actual mesh size and every observed
native tile LOD are also checked, rather than trusting equal source hashes alone.
There is no successful flat fallback.

## Reproduce without starting Dashboard

On Scout, from the repository root:

```sh
./venv/bin/python tools/scout_gpx_3d_benchmark_app.py \
  --project-root /home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --port 9128
```

Forward a private loopback port to that service from the Mac, then run on the Mac
with its existing Node, Playwright and installed Chrome:

```sh
node tools/scout_gpx_3d_benchmark.cjs \
  --playwright /Users/alexwang0315/scout-fusion/node_modules/playwright \
  --url http://127.0.0.1:19128 \
  --gpx 839bf9fac6f2fd73995a71ed \
  --output /tmp/scout-renderer-comparison
```

The runner and adjacent `scout_gpx_3d_benchmark_metrics.cjs` must both be present.
Use `--preflight` for only the source/camera/GPU checks. Each trial produces a
screenshot and incremental `report.json`; a failed run cannot be summarized as
a successful comparison. Page entrypoints are
`/benchmark?engine=three&gpx=839bf9fac6f2fd73995a71ed` and
`/benchmark?engine=maplibre&gpx=839bf9fac6f2fd73995a71ed` on the test origin.

All requests stay on the allowed loopback origin through the user's SSH link.
GPX/CP data is not sent to a public demo or terrain provider. This test remains
`visualization_only`, `candidate_only`, and never `runtime_safety_truth`.

To reproduce the statistics from the retained actual Mac capture on either
machine, without launching another browser:

```sh
node tools/scout_gpx_3d_benchmark_analyze.mjs \
  outputs/evals/scout-gpx-3d/benchmark/mac-2026-09-09/measurement-3/report.json \
  /tmp/scout-renderer-analysis.json
```

## Changed scope and validation

| Files | Purpose |
| --- | --- |
| `docs/admin/experiments/gpx-3d/benchmark/{index.html,style.css,common.mjs,run.mjs,three-adapter.mjs,maplibre-adapter.mjs,DESIGN.md}` | Independent normalized scene and measurement entrypoint |
| `docs/admin/experiments/gpx-3d/renderer.mjs` | Optional benchmark-only grid/shading/pixel-ratio controls, ordinary defaults preserved |
| `tools/scout_gpx_3d_benchmark_app.py` | Separate read-only host |
| `tools/scout_gpx_3d_benchmark.cjs` | Isolated actual-Mac Chrome capture |
| `tools/scout_gpx_3d_benchmark_metrics.cjs` | Cross-trial parity/detail validation and summaries |
| `tools/scout_gpx_3d_benchmark_analyze.mjs` | Reproducible statistics over retained Mac samples |
| `tests/scout_gpx_3d_benchmark.test.mjs`, `tests/test_scout_gpx_3d.py` | Focused timing, parity and read-only-boundary checks |
| This report, `scout-gpx-3d-experiment.md`, `experiments/gpx-3d/THIRD_PARTY.md` | Results, current-versus-historical terrain batch, retained attribution |

- Added the isolated benchmark page/adapters, read-only host and Mac runner.
- Added optional pixel-ratio/grid/shading controls to the experimental demo's
  renderer; its ordinary defaults remain unchanged.
- Added focused frame/parity validation tests and benchmark HTTP-boundary tests.
- Dashboard HTML, its shared MapLibre adapter, existing vendor modules, layer
  contract, Workspace artifacts and production runtime are outside this change.

Validation completed:

- Python GPX/HTTP-boundary tests: 7 passed.
- Node GPX tests: 10 passed; benchmark statistics/parity tests: 6 passed.
- Existing `pnpm lint`, `pnpm typecheck` and `pnpm test`: PASS (typecheck 1,
  test 17). The existing AnyIO BlockingPortal deprecation warning remains.
- Actual ordinary-demo browser regression: 14 checks passed on Scout Chromium
  148, including desktop 1440 × 1000, mobile 390 × 844 with touch, and tablet
  768 × 1024. Normal console/network errors: zero. Injected terrain 503 and
  renderer ERR_FAILED errors correctly produced explicit degradation. These
  Linux browser checks are functional evidence only; Mac performance values
  come exclusively from the Mac capture.
- Eleven shared Dashboard/vendor/contract/dependency files and sixteen selected
  Workspace GPX/project/CP/manifest files retained their original SHA-256 hashes.
  All 54 DEM tile hashes and the source fingerprint also matched afterward.
- Freeze guard: `INVALID_BASELINE`, not PASS. The checkout has no guard/baseline;
  the sibling checkout's guard, run against this root before and after the work
  in report-only mode, reports the missing `qualification/navigation-freeze-baseline.json`.
  No guard or baseline was created, updated or bypassed. The independent hash
  comparisons above cover the named shared files.

Earlier attempts were retained and excluded from these statistics: one wrong
MapLibre module import, one closed SSH forward before navigation, and one
benchmark diagnostic using the old `map.transform` interface. The final adapter
uses the pinned version's public camera getters. These were new benchmark-tool
problems, not repairs to existing Navigation.

God's Eye View supplies the original demo's actual `contextStore` selection
module, not either 3D engine; selection is idle during measurement. Its adopted
commit, unchanged module hash and MIT notice are in
[THIRD_PARTY.md](experiments/gpx-3d/THIRD_PARTY.md). The benchmark serves the
existing MapLibre vendor directory with its retained license.

Follow-up completed 2026-09-10: [Dashboard layers and synchronization cost](dashboard-3d-cost-benchmark.md)
records 18 actual Mac trials using the original Dashboard functions. It observed
extra peer-map rendering during fixed-center rotation; CPU throttling and swap
limit causal timing interpretation. The next bounded experiment is skipping
unchanged-center synchronization under steadier system conditions. This earlier
engine comparison remains one bounded view on one Mac with three trials, not a product SLO or
a general claim about all Three.js and MapLibre applications. No production
activation, source GPX/CP update, commit, push, deployment or paid API was used.
The temporary benchmark server and SSH forward were closed after capture; its
Mac temporary directory was removed after copying and verifying the capture
hash. The previously authorized ordinary demo on Scout loopback port 9127
remains active.
