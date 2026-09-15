#!/usr/bin/env node
// Recompute statistics from immutable Mac frame samples without changing the
// measured browser workload or treating Linux execution as Mac measurement.
import fs from "node:fs";
import path from "node:path";
import {createHash} from "node:crypto";
import {summarizeIntervals} from "../docs/admin/experiments/gpx-3d/benchmark/common.mjs";
import {validateParity,summarizeRuns} from "./scout_gpx_3d_benchmark_metrics.cjs";

const [input,output]=process.argv.slice(2);
if(!input||!output||path.resolve(input)===path.resolve(output))throw Error("Supply original report.json and a different analysis.json output path");
const bytes=fs.readFileSync(input),report=JSON.parse(bytes);
if(report.status!=="PASS"||report.machine.platform!=="darwin"||report.phase!=="measurement")throw Error("A successful actual Mac measurement capture is required");
report.parity=validateParity(report.runs);
if(report.parity.status!=="PASS")throw Error("Captured parity checks failed");
for(const row of report.runs) {
  const measure=row.measurement;
  measure.rotation=summarizeIntervals(measure.renderIntervalsMs,measure.refreshIntervalMs);
  measure.raf=summarizeIntervals(measure.rafIntervalsMs,measure.refreshIntervalMs);
}
report.summary=summarizeRuns(report.runs);
report.analysis={version:"scout.renderer_benchmark_analysis.v1",analyzedAt:new Date().toISOString(),
  captureSha256:createHash("sha256").update(bytes).digest("hex"),
  method:"Whole-window update deficit; raw frame samples, load times and memory observations unchanged",
  captureReport:path.resolve(input),browserRerun:false};
fs.writeFileSync(output,JSON.stringify(report,null,2));
console.log(JSON.stringify({status:report.status,parity:report.parity,summary:report.summary,analysis:report.analysis},null,2));
