export const EARTH_RADIUS = 6378137;
export const VISUAL_RAISE_M = 12;

// Approximate anchors read from the user's hypsometric-map JPEG, not an
// assertion of the original QGIS classification settings. Colors interpolate
// in sRGB between anchors across Scout's actual DEM range, before visual offset.
export const ELEVATION_COLOR_STOPS = [
  {fraction: 0, token: "terrain-low", label: "青綠"},
  {fraction: .2, token: "terrain-green", label: "亮綠"},
  {fraction: .4, token: "terrain-yellow", label: "黃色"},
  {fraction: .6, token: "terrain-orange", label: "橙色"},
  {fraction: .8, token: "terrain-brown", label: "棕色"},
  {fraction: 1, token: "terrain-high", label: "深灰"},
];

export function mercator(lon, lat) {
  return [EARTH_RADIUS * lon * Math.PI / 180,
    EARTH_RADIUS * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360))];
}

// Use precisely the same two triangles as the visible mesh; this is visual
// draping only, never a substitute for a GPX height or a source DEM sample.
export function meshElevation(mesh, lon, lat) {
  if (mesh?.status !== "ready") return null;
  const [x, y] = mercator(lon, lat);
  const column = (x - mesh.x0) / mesh.step_m, row = (mesh.y0 - y) / mesh.step_m;
  if (column < 0 || row < 0 || column >= mesh.width - 1 || row >= mesh.height - 1) return null;
  const c = Math.floor(column), r = Math.floor(row), u = column - c, v = row - r;
  const a = mesh.elevations[r * mesh.width + c], b = mesh.elevations[r * mesh.width + c + 1];
  const d = mesh.elevations[(r + 1) * mesh.width + c], e = mesh.elevations[(r + 1) * mesh.width + c + 1];
  if (![a, b, d, e].every(h => typeof h === "number" && Number.isFinite(h))) return null;
  return u >= v ? a * (1 - u) + b * (u - v) + e * v : a * (1 - v) + e * u + d * (v - u);
}
