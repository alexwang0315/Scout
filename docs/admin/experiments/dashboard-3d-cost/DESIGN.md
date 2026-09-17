# Dashboard 3D cost replay

An isolated measurement surface over the actual Dashboard source and existing
Workspace artifacts. Retain Scout's local system fonts, dark panel colors and
candidate-only labeling. A fixed 1280 × 800 measurement viewport contains a
960 × 640 primary 3D map and a 320 × 640 secondary 2D map (blank when absent).
Keeping the primary map unchanged isolates the extra map from viewport changes.

The header names the ablation case and explicitly labels stale recorded data.
The footer exposes a manual measure button and progress. The normal Dashboard
DOM is retained for its real construction cost, but covered by this experiment;
unrelated API bootstrap and runtime controls are inaccessible. Native Dashboard
map controls remain usable. No new visual data or replacement renderer.

Browser profiling uses the desktop geometry above. Narrow screens may scroll;
this profiling surface is not a mobile Dashboard replacement. Results include
source hashes, actual layer/feature counts, rendering cadence, process memory
and original callback counts/timings. No external fonts or imagery requests.
Rudy imagery is explicitly capped at the existing prepared cache's Z14 because
the native higher-zoom cache is incomplete. This is a controlled cached replay,
not a claim of complete native/live Dashboard basemap coverage. DEM unchanged.
