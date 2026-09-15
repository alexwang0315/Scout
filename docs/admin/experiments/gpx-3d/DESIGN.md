# GPX 3D experiment design

## 1. Identity

Inherit the root Scout Design System: a quiet field console with source identity
and failure state visible. The terrain is the main work surface.

## 2. Color

Application colors inherit root `DESIGN.md`. Cyan is the supported route and
selection; green/yellow identify start/end; accent-2 dashed geometry identifies
planar locations without DEM coverage. This experiment adds a continuous DEM
elevation scale based on the user's Manicaland hypsometric-map reference:

| Token | Value | Fraction of the displayed DEM range |
| --- | --- | --- |
| `--terrain-low` (青綠) | `#00bfbf` | 0% |
| `--terrain-green` (亮綠) | `#00ff00` | 20% |
| `--terrain-yellow` (黃色) | `#ffff00` | 40% |
| `--terrain-orange` (橙色) | `#ff7f00` | 60% |
| `--terrain-brown` (棕色) | `#bf7f3f` | 80% |
| `--terrain-high` (深灰) | `#141414` | 100% |

These are approximate color anchors reconstructed from the supplied JPEG's
legend, not recovered QGIS settings. The reference labels only 313–1,843 m;
its internal numerical breaks and stretch method are not documented. Use a
continuous color ramp, interpolating in sRGB between six evenly spaced anchors
over Scout's actual current DEM range: height = min + fraction × (max − min).
Do not copy the Zimbabwe endpoints, use quantile/Jenks classification, or imply
that each color covers the same map area. Between anchors colors interpolate.

The renderer and legend share the same stops. Scale raw DEM mesh elevations,
before the visual base/route offset; do not use GPX elevation. The legend labels
the current DEM minimum, midpoint, maximum (metres) and vertical datum; an
expandable color-distribution list shows each anchor's actual DEM height and
percentage. Use a single anchor for a uniform elevation surface. White relief
light (`--terrain-light: #ffffff`) comes from the northwest at 45°; ambient
intensity 0.15, directional intensity 3.0. This approximates the reference's
strong relief shading without changing mesh geometry or claiming its exact
hillshade parameters. State that shadows affect brightness. Missing DEM is never
assigned a terrain color. Hide the legend on loading, empty data or fallback.
These colors encode elevation only, not vegetation, snow, land cover or risk.

## 3. Type

Use root system sans, 18/17/14/12 px hierarchy and system monospace for progress.
No remote fonts or icons. Preserve readable wrapping for source identifiers.

## 4. Layout

Independent desktop page: 336 px source/selection column (300 px below 1024),
flexible scene, controls and replay beneath the scene. Below 768 px: source
chooser, 400 px scene, replay, nodes, provenance in one scrolling column.
The desktop scene scrolls when the expanded legend exceeds its available
height; its non-map panels do not shrink and clip playback controls.
Controls use at least 40 px hit areas; node rows are 44 px on mobile.

## 5. Components

Source chooser, read-only provenance list, searchable source-node list, shared
selected-node detail, scene camera controls, explicit terrain status, playback
range and separate cursor. A compact elevation legend sits below the scene,
outside its pointer surface, and wraps on mobile. Its native details/summary
disclosure has a 40 px target. Color-anchor rows use a responsive 3/2/1-column
grid (12 px text, 16 px swatches, 8/12 px gaps); heights remain text labels.
No chat, dashboard navigation,
promotion, or runtime controls appear on this page.

## 6. Interaction

Manual camera and node selection stay independent of replay. OrbitControls:
single drag rotates, right drag pans, wheel/pinch zooms. Arrow keys rotate/tilt,
plus/minus zoom, F fits. No autoplay. Hidden tabs pause replay. No continuous
idle rendering; controls and replay request frames. Reduced motion removes
button translation; camera controls move directly without animated flights.

## 7. Depth

Root borders-only panel style. The scene is an actual bounded 3D mesh with
vertical exaggeration 1. A grid represents schematic horizontal positions,
explicitly without terrain elevation outside coverage. Desktop/mobile visual
proof and screenshots are in the accompanying browser report.
