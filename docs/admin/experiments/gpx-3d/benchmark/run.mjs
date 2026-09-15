import {loadCommon,summarizeIntervals} from "./common.mjs";

const start=performance.now(),query=new URLSearchParams(location.search),engine=query.get("engine"),source=query.get("gpx");
const state={status:"loading",engine,errors:[],phases:{},result:null};
let adapter,common,renderTimes=null;
const status=text=>document.querySelector("#bench-status").textContent=text;
const fail=error=>{const message=error.message||String(error);state.errors.push(message);state.status="failed";document.body.dataset.benchState="failed";status(message);};
const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));
document.querySelector("#bench-engine").textContent=engine==="maplibre"?"Dashboard MapLibre · 原生地形對照":"Three.js · 同密度地形對照";
window.addEventListener("error",event=>fail(event.error||event.message));
window.addEventListener("unhandledrejection",event=>fail(event.reason));

async function sweep(seconds,record=false) {
  if(document.visibilityState!=="visible")throw Error("Benchmark tab is not foreground");
  const dimensions=[innerWidth,innerHeight,devicePixelRatio],raf=[];
  const begin=await frame();
  if(record)renderTimes=[];
  await new Promise((resolve,reject)=>{
    const step=time=>{
      if(document.visibilityState!=="visible"||innerWidth!==dimensions[0]||innerHeight!==dimensions[1]||state.errors.length)return reject(Error("Foreground, dimensions or renderer changed during rotation"));
      if(time-begin>=seconds*1000)return resolve();
      raf.push(time);adapter.pose(360*(time-begin)/(seconds*1000));requestAnimationFrame(step);
    };requestAnimationFrame(step);
  });
  await frame();await frame();
  const rendered=renderTimes;renderTimes=null;
  return {raf,rendered};
}

async function measure() {
  if(state.status!=="ready")throw Error("Scene is not ready");
  const refresh=[];
  for(let i=0;i<90;i++)refresh.push(await frame());
  const delta=times=>times.slice(1).map((t,i)=>t-times[i]);
  const calibrated=delta(refresh).sort((a,b)=>a-b)[Math.floor((refresh.length-1)/2)];
  status("暖機旋轉…");await sweep(common.config.warmupSeconds);
  status("旋轉量測中，請保持此視窗在前景…");
  state.status="measuring";
  const rotation=await sweep(common.config.rotationSeconds,true);
  const intervals=delta(rotation.rendered);
  const result={engine,version:adapter.version,input:common.input,inputSha256:common.inputSha256,config:common.config,
    phases:state.phases,refreshIntervalMs:calibrated,rotation:summarizeIntervals(intervals,calibrated),
    raf:summarizeIntervals(delta(rotation.raf),calibrated),renderIntervalsMs:intervals,rafIntervalsMs:delta(rotation.raf),
    diagnostics:adapter.diagnostics(),errors:[...state.errors],authority:{visualization_only:true,candidate_only:true,runtime_safety_truth:false}};
  state.result=result;state.status="complete";status("本輪完成；完整記錄由測試工具保存。");return result;
}

window.scoutBenchmark={snapshot:()=>({...state}),measure,pose:angle=>adapter.pose(angle),
  probes:()=>{
    const [lon,lat]=common.config.center;
    return [[0,0],[.005,0],[-.005,0],[0,.005],[0,-.005],[.008,.008]].map(([x,y])=>{
      const point=[lon+x,lat+y];return {point,height:adapter.sample(point),screen:adapter.project(point)};
    });
  },dispose:()=>adapter?.dispose()};

try {
  if(!["three","maplibre"].includes(engine))throw Error("Select engine=three or engine=maplibre");
  common=await loadCommon(source);state.phases.commonDataMs=performance.now()-start;
  status("共同來源已驗證，建立完整密度 3D…");
  const {createAdapter}=await import(`./${engine}-adapter.mjs`);
  adapter=await createAdapter(document.querySelector("#bench-map"),common,()=>{if(renderTimes)renderTimes.push(performance.now());},fail);
  await frame();await frame();
  if(state.errors.length)throw Error(state.errors.join("; "));
  state.phases.firstComplete3dMs=performance.now();
  state.phases.engineSetupMs=performance.now()-start-state.phases.commonDataMs;
  state.input=common.input;state.inputSha256=common.inputSha256;state.config=common.config;
  state.diagnostics=adapter.diagnostics();
  state.status="ready";document.body.dataset.benchState="ready";status(`${common.input.pixelSpacingGroundM.toFixed(1)} m / DEM 像素 · 相同 GPX／來源節點 · 等待測試工具`);
} catch(error){fail(error);}
