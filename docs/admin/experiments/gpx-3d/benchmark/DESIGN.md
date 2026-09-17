# Controlled renderer comparison

Inherit ../DESIGN.md typography, colors and borders. A 1280 × 800 viewport has
a fixed 1280 × 720 rendering area and an 80 px status strip. Pixel ratio is
explicit and identical. No sidebar, basemap, grid, replay, selection animation,
hillshade, or synchronized second map is active during timing. A source GPX
line, its original nodes and DEM height colors are the shared scene layers.

The comparison uses the full prepared DEM pixels in both engines. Three.js
triangulates the pixel grid; MapLibre uses its native raster-dem terrain and
color-relief path at one checked tile LOD with the same visible mesh spacing.
Terrain and color sources use the same bytes in separate native source objects.
These are equal input detail and grid spacing, not equal total triangle counts.
Tile culling and native mesh reuse remain implementation differences.
This is a renderer comparison, not a complete Dashboard performance claim.

The status strip always identifies the engine, validation state and
visualization_only / candidate_only authority. Errors invalidate measurements;
no fallback can be counted as a successfully rendered 3D benchmark.
