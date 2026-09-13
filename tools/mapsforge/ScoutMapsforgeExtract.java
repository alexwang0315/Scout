// Optional local adapter for the official Mapsforge reader. No network or writes.
import java.io.File;
import java.util.*;
import org.mapsforge.core.model.*;
import org.mapsforge.map.datastore.*;
import org.mapsforge.map.reader.MapFile;
import org.mapsforge.map.reader.header.MapFileInfo;

class ScoutMapsforgeExtract {
    static int x(double lon, int z) { return (int)Math.floor((lon+180)/360*(1L<<z)); }
    static int y(double lat, int z) { double r=Math.toRadians(lat);return (int)Math.floor((1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*(1L<<z)); }
    static String json(Object value) {
        if (value==null) return "null";
        if (value instanceof Number || value instanceof Boolean) return value.toString();
        if (value instanceof Map<?,?> map) {
            List<String> rows=new ArrayList<>();for(var e:map.entrySet())rows.add(json(e.getKey().toString())+":"+json(e.getValue()));return "{"+String.join(",",rows)+"}";
        }
        if (value instanceof Iterable<?> list) {
            List<String> rows=new ArrayList<>();for(Object v:list)rows.add(json(v));return "["+String.join(",",rows)+"]";
        }
        StringBuilder s=new StringBuilder("\"");for(char c:value.toString().toCharArray()) {
            if(c=='"' || c=='\\')s.append('\\').append(c);
            else if(c<32)s.append(String.format("\\u%04x",(int)c));else s.append(c);
        }return s.append('"').toString();
    }
    public static void main(String[] args) {
        if(args.length!=5)throw new IllegalArgumentException("map south west north east required");
        double south=Double.parseDouble(args[1]),west=Double.parseDouble(args[2]),north=Double.parseDouble(args[3]),east=Double.parseDouble(args[4]);
        if(!(Double.isFinite(south)&&Double.isFinite(west)&&Double.isFinite(north)&&Double.isFinite(east)&&south<north&&west<east&&south>-85.051&&north<85.051&&west>=-180&&east<180))throw new IllegalArgumentException("Invalid nonempty WGS84 bbox");
        MapFile map=new MapFile(new File(args[0]));
        try {
            MapFileInfo info=map.getMapFileInfo();byte z=info.zoomLevelMax;
            Tile a=new Tile(x(west,z),y(north,z),z,256),b=new Tile(x(east,z),y(south,z),z,256);
            MapReadResult data=map.readMapData(a,b);
            if(data==null)throw new IllegalArgumentException("No Mapsforge data for area");
            data.deduplicate();List<Object> features=new ArrayList<>();
            for(Way way:data.ways) {
                Map<String,String> tags=new TreeMap<>();for(Tag tag:way.tags)tags.put(tag.key,tag.value);
                if((!tags.containsKey("highway")&&!"trk".equals(tags.get("gpx")))||"yes".equals(tags.get("area")))continue;
                List<Object> parts=new ArrayList<>();boolean intersects=false;
                for(LatLong[] coordinates:way.latLongs) {
                    if(coordinates.length<2)continue;double minLat=90,maxLat=-90,minLon=180,maxLon=-180;List<Object> points=new ArrayList<>();
                    for(LatLong point:coordinates) {
                        points.add(List.of(point.longitude,point.latitude));minLat=Math.min(minLat,point.latitude);maxLat=Math.max(maxLat,point.latitude);minLon=Math.min(minLon,point.longitude);maxLon=Math.max(maxLon,point.longitude);
                    }
                    if(maxLat>=south&&minLat<=north&&maxLon>=west&&minLon<=east)intersects=true;
                    parts.add(points);
                }
                if(!intersects||parts.isEmpty())continue;
                Map<String,Object> props=new LinkedHashMap<>();props.put("tags",tags);props.put("layer",way.layer);props.put("topology_available",false);props.put("timing_semantics","unknown_no_recorded_timestamps");
                features.add(Map.of("type","Feature","properties",props,"geometry",Map.of("type","MultiLineString","coordinates",parts)));
            }
            Map<String,Object> meta=new LinkedHashMap<>();meta.put("extractor","mapsforge-map-reader");meta.put("reader_version","0.25.0");meta.put("map_file_version",info.fileVersion);meta.put("map_date_unix_ms",info.mapDate);meta.put("comment",info.comment);meta.put("created_by",info.createdBy);meta.put("source_file_size",info.fileSize);meta.put("projection",info.projectionName);meta.put("query_zoom",z);meta.put("raw_way_count",data.ways.size());meta.put("candidate_count",features.size());meta.put("query_bbox_wgs84",Map.of("south",south,"west",west,"north",north,"east",east));meta.put("map_bbox_wgs84",Map.of("south",info.boundingBox.minLatitude,"west",info.boundingBox.minLongitude,"north",info.boundingBox.maxLatitude,"east",info.boundingBox.maxLongitude));meta.put("coordinate_policy","source_parts_preserved_no_join_no_simplification");meta.put("topology_available",false);
            System.out.println(json(Map.of("type","FeatureCollection","properties",meta,"features",features)));
        } finally { map.close(); }
    }
}
