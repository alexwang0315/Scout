[out:json][timeout:60];
(
  way["highway"~"^(path|footway|track|steps|pedestrian|cycleway|service|residential|unclassified|tertiary|secondary|primary)$"](25.0585,121.6505,25.0730,121.6705);
  way["route"="hiking"](25.0585,121.6505,25.0730,121.6705);
  relation["route"="hiking"](25.0585,121.6505,25.0730,121.6705);
);
out tags geom(25.0580,121.6500,25.0735,121.6710);
