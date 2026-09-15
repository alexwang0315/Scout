"use strict";
const names={base:"基準：DEM ＋路線",hillshade:"＋山體陰影",rudy:"＋Rudy 底圖",full:"＋Dashboard 候選圖層",split_static:"＋第二張 2D 地圖（固定）",split_sync:"＋原有地圖同步"};
const units={rotationFps:"FPS",panFps:"FPS",rotationP95Ms:"ms",firstReadySeconds:"s",peakRssMiB:"MiB"};
const text=(id,value)=>document.getElementById(id).textContent=value;
(async()=>{
  try{
    const response=await fetch("result-data.json");if(!response.ok)throw Error("結果 HTTP "+response.status);
    const result=await response.json();if(result.status!=="PASS")throw Error("沒有通過驗證的完整量測");
    text("status","已完成 · "+result.parity.trials+" 次 Mac 實測 · 尚未更換引擎");
    text("measurement-limit",result.measurementCaveat||"系統負載未隔離：數值為方向性觀察，並非精確因果成本。");
    text("machine",result.machine.cpu+" · "+(result.machine.memoryBytes/2**30).toFixed(0)+" GiB RAM · Chrome "+result.browserVersion+" · "+result.gpu.renderer);
    text("conditions","各組相同：960 × 640 的 3D 畫布、Z14／俯角 45°、DEM 網格 128 cells／tile，實際地形 LOD "+result.parity.observedTerrainZooms.join(" / ")+"。既有投影路線 "+result.parity.preparedRoutePointCount+" 個展示取樣點、完整組增加 43 個 QGIS 節點。第二張 2D 地圖固定 320 × 640。");
    text("capture","資料擷取："+result.capturedFrom+" 至 "+result.capturedTo+" · 原始紀錄 SHA-256 "+result.captureSha256);
    for(const finding of result.findings||[]){const item=document.createElement("li");item.textContent=finding;document.getElementById("findings").append(item);}
    for(const [id,label]of Object.entries(names)){
      const a=document.createElement("a");a.textContent=label;a.href="/dashboard-cost?case="+id+"&projectId=dongqing_batongguan_historic_trail_newImport";document.getElementById("scenes").append(a);
    }
    const chart=()=>{
      const key=document.getElementById("metric").value,unit=units[key],maximum=Math.max(...Object.values(result.summary).map(s=>s.metrics[key].median));
      text("metric-note",(key.endsWith("Fps")?"越高越順暢":"越低越好")+" · 中位數〔三輪最小–最大〕");
      const host=document.getElementById("chart");host.replaceChildren();
      for(const [id,label]of Object.entries(names)){
        const s=result.summary[id].metrics[key],row=document.createElement("div");row.className="bar-row";
        const heading=document.createElement("div");heading.className="bar-label";const name=document.createElement("span");name.textContent=label;
        const value=document.createElement("strong");value.textContent=s.median.toFixed(2)+" "+unit+" ";
        const range=document.createElement("span");range.className="range";range.textContent="〔"+s.min.toFixed(2)+"–"+s.max.toFixed(2)+"〕";value.append(range);heading.append(name,value);
        const track=document.createElement("div");track.className="bar-track";track.setAttribute("aria-hidden","true");const fill=document.createElement("div");fill.className="bar-fill";fill.style.width=100*s.median/maximum+"%";track.append(fill);row.append(heading,track);host.append(row);
      }
    };
    document.getElementById("metric").addEventListener("change",chart);chart();
  }catch(error){text("status","量測結果尚未可用："+error.message);}
})();
