[out:json][timeout:40];
(
  way["highway"~"^(path|footway|track|steps|bridleway|pedestrian)$"](23.8726657,121.1772669,24.0539696,121.2816995);
  node["tourism"~"^(wilderness_hut|alpine_hut)$"](23.8726657,121.1772669,24.0539696,121.2816995);
  node["amenity"~"^(shelter|drinking_water|parking)$"](23.8726657,121.1772669,24.0539696,121.2816995);
  node["natural"~"^(spring|peak)$"](23.8726657,121.1772669,24.0539696,121.2816995);
);
out tags geom;
