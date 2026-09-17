# Third-party source attribution

## God's Eye View

- Project: <https://github.com/bilawalsidhu/gods-eye-view>
- Reviewed and adopted commit: `759652207fd1279ece97f0f19af566feb9a82146`.
- Original module: `src/data/contextStore.js`.
- Local copy: `vendor/gods-eye-view/contextStore.mjs`. File bytes are unchanged;
  only the extension changes for ES-module tests in this CommonJS repository.
- Module SHA-256: `e302125b7fc01f857f311751a8e983e7f234fec5aaaa44301a3059dfcf26c422`.
- Copyright (c) 2026 Bilawal Sidhu. Full upstream MIT License and its notices are
  retained in `vendor/gods-eye-view/LICENSE`.

Actual calls, via `selection.mjs`: `registerEntityContext`,
`selectEntityContext`, `getSelectedEntityContext`,
`removeEntityContextsForLayer`; the `gev:entity-selected` event updates both
the scene and sidebar. One isolated layer owns these records. Playback never
calls the selection API. The module does not import Cesium, external feeds,
AI chat, or any provider credentials.

The rest of God's Eye View is not ported. Its third-party datasets, models,
photorealistic assets, provider configuration, UI and live-data layers are not
included. The previous hosted Scout demo was not used as source code or GPX data.
The MIT license covers upstream source code, not its third-party datasets.

## Three.js

- Version: `0.180.0`, source <https://github.com/mrdoob/three.js/tree/r180>.
- Package: <https://registry.npmjs.org/three/-/three-0.180.0.tgz>.
- Tarball SHA-256: `ad66d724565ee29a2467277fa84daa5ed0211d6b8d446e9ef29f6bae0cd14144`.
- Local files: `three.core.js`, `three.module.js`, OrbitControls, Line2,
  LineGeometry, LineMaterial, LineSegments2 and LineSegmentsGeometry.
- Full MIT notice retained in `vendor/three/LICENSE`.
- Only modification: addon `from 'three'` imports changed to
  `from '../../three.module.js'` so all scripts load locally without a build
  system, CDN, or inline import map. Core and license bytes are unchanged.

## MapLibre (isolated benchmark only)

- Version: the existing Scout vendor copy of MapLibre GL JS `6.2.0`.
- Source: <https://github.com/maplibre/maplibre-gl-js/tree/v6.2.0>.
- The benchmark host serves `docs/admin/vendor/maplibre-gl/6.2.0/` unchanged,
  including its complete `LICENSE.txt` with MapLibre, Mapbox and bundled
  dependency notices. No new CDN or provider is used.
- The adapter calls the native raster-dem terrain and color-relief renderer,
  `jumpTo`, `setSourceTileLodParams`, `queryTerrainElevation` and `project`.
  Benchmark diagnostics read the pinned native terrain mesh/tile metadata.

## Scout data

These code licenses do not grant publication rights to the operator's GPX, CP,
or terrain data. Those remain in the selected local Workspace. The viewer
performs no external data requests or publication. Evidence screenshots and
reports under `outputs/evals/scout-gpx-3d/` are local ignored artifacts.
