import {TerrainScene} from "../renderer.mjs";
import {meshElevation,mercator,VISUAL_RAISE_M} from "../terrain.mjs";
import {CIRCUMFERENCE} from "./common.mjs";

export async function createAdapter(host,common,onRender,onFailure) {
  class BenchmarkScene extends TerrainScene {
    position(lon,lat) {
      const point=super.position(lon,lat);
      if(meshElevation(this.mesh,lon,lat)!==null)point.y-=VISUAL_RAISE_M;
      return point;
    }
  }
  const scene=new BenchmarkScene(host,{onSelect:()=>{},onFailure,onCamera:onRender,pixelRatio:common.config.pixelRatio,drawGrid:false,shading:false});
  scene.setData(common.model,common.mesh);
  scene.lineMaterials.forEach(material=>{material.depthTest=false;});
  scene.camera.fov=common.config.fov;scene.camera.aspect=host.clientWidth/host.clientHeight;
  scene.camera.updateProjectionMatrix();
  const {center,pitch,zoom}=common.config;
  const [x,y]=mercator(...center),groundScale=Math.cos(center[1]*Math.PI/180);
  const height=meshElevation(common.mesh,...center);
  scene.controls.target.set((x-scene.origin[0])*scene.scale,height-scene.base,(scene.origin[1]-y)*scene.scale);
  const distance=host.clientHeight/(2*Math.tan(common.config.fov*Math.PI/360))*CIRCUMFERENCE*groundScale/(512*2**zoom);
  const pose=bearing=>{
    const theta=-bearing*Math.PI/180,phi=pitch*Math.PI/180;
    scene.camera.position.set(scene.controls.target.x+distance*Math.sin(phi)*Math.sin(theta),scene.controls.target.y+distance*Math.cos(phi),scene.controls.target.z+distance*Math.sin(phi)*Math.cos(theta));
    scene.controls.update();
  };
  pose(0);scene.draw();scene.renderer.getContext().finish();
  return {engine:"three",version:"0.180.0",pose,
    sample:point=>meshElevation(common.mesh,...point),
    project:point=>{const position=scene.position(...point);position.project(scene.camera);return [(position.x+1)*host.clientWidth/2,(1-position.y)*host.clientHeight/2];},
    diagnostics:()=>({meshVertices:scene.world.children.find(object=>object.type==="Mesh").geometry.attributes.position.count,
      renderer:scene.renderer.info.render,geometryCount:scene.renderer.info.memory.geometries,textureCount:scene.renderer.info.memory.textures}),
    dispose:()=>scene.dispose()};
}
