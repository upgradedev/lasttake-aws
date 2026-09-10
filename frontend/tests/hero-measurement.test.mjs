import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {preallocate,beginSlot,slotPath,readJSON,durableJSON,finalize,quantiles,verifyOffline,summarize,sha256} from '../scripts/hero-measurement.mjs';
import {supervise,preregistration} from '../scripts/run-hero-benchmark.mjs';
function fixture(t){const parent=mkdtempSync(join(tmpdir(),'lasttake-measurement-fixture-'));t.after(()=>rmSync(parent,{recursive:true}));return join(parent,'cohort');}
test('all20 slots exist durably before any attempt, including failures and unrun denominators',t=>{
  const root=fixture(t);preallocate(root,{fixture:true});
  assert.equal(readdirSync(root).filter(f=>f.startsWith('slot-')).length,20);
  assert.equal(readJSON(slotPath(root,11)).viewport,'mobile');
  assert.equal(readJSON(slotPath(root,20)).status,'NOT_RUN');
  assert.throws(()=>preallocate(root,{}));
  const first=beginSlot(root,1);assert.equal(readJSON(slotPath(root,1)).status,'RUNNING');
  assert.throws(()=>beginSlot(root,1));
  first.status='FAILED';first.failed_elapsed_ms=12.375;durableJSON(slotPath(root,1),first);
  const summary=finalize(root,'FIXTURE');
  assert.deepEqual(summary.counts,{PASSED:0,FAILED:1,INCOMPLETE:0,NOT_RUN:19});
  assert.equal(summary.overall.p50_ms,null);assert.equal(summary.model_cost_usd,null);
  assert.equal(readJSON(slotPath(root,1)).failed_elapsed_ms,12.375);
  assert.match(readFileSync(join(root,'summary.html'),'utf8'),/Infra and runner cost unknown/);
});
test('atomic snapshots retain raw stage/request observations and actual file hashes',t=>{
  const root=fixture(t);preallocate(root,{});const slot=beginSlot(root,7);
  slot.stage='sponsor';slot.failed_elapsed_ms=5.125;slot.requests=[{body_bytes:null,status:null}];
  durableJSON(slotPath(root,7),slot);assert.equal(readJSON(slotPath(root,7)).stage,'sponsor');
  const summary=finalize(root,'PROCESS_TIMEOUT');
  assert.equal(summary.counts.INCOMPLETE,1);assert.equal(summary.counts.NOT_RUN,19);
  assert.equal(readJSON(slotPath(root,7)).failure,'PROCESS_TIMEOUT');
  assert.equal(readJSON(slotPath(root,7)).requests[0].body_bytes,null);
  assert.equal(readJSON(join(root,'manifest.json')).sha256['slot-07.json'],sha256(readFileSync(slotPath(root,7))));
  assert.ok(!readdirSync(root).some(f=>f.endsWith('.next')));
});
test('hard timeout kills a hung child and still finalizes every preallocated slot',async t=>{
  const root=fixture(t);preallocate(root,{});beginSlot(root,3);
  const result=await supervise(process.execPath,['-e','setInterval(()=>{},1000)'],{root,timeoutMs:120,cwd:process.cwd(),env:process.env});
  assert.equal(result.reason,'PROCESS_TIMEOUT');assert.notEqual(result.exit,0);
  assert.equal(result.summary.denominator,20);assert.equal(result.summary.counts.INCOMPLETE,1);
  assert.equal(result.summary.counts.NOT_RUN,19);assert.equal(readJSON(slotPath(root,3)).elapsed_ms,null);
});
test('failed child launch also preserves all unrun slots',async t=>{
  const root=fixture(t);preallocate(root,{});
  const result=await supervise(join(root,'nonexistent'),[],{root,timeoutMs:500,cwd:root,env:process.env});
  assert.notEqual(result.exit,0);assert.equal(result.summary.counts.NOT_RUN,20);
});
test('p50 and nearest-rank p95 use actual successful_n, without outlier trimming',()=>{
  assert.deepEqual(quantiles([4,1,3,2]),{successful_n:4,p50_ms:2.5,p95_ms:4,max_ms:4});
  assert.equal(quantiles(Array.from({length:20},(_,i)=>i+1)).p95_ms,19);
  assert.equal(quantiles([1,2,100]).p50_ms,2);assert.equal(quantiles([]).p95_ms,null);
  for(const value of [NaN,Infinity,-1])assert.throws(()=>quantiles([value]));
});
test('missing evidence, outbound attempts, wrong mode/revision and unchanged counters never claim model0',()=>{
  const before={commit:'fixture',pid:42,guards_active:true,run_state_store:'local-files',interpreter:'offline-lexical/1.0.0',planner:'offline-scripted/1.0.0',blocked_clients:0,blocked_outbound:0,scripted_stream_calls:1,offline_run_builds:2};
  const after={...before,scripted_stream_calls:2,offline_run_builds:3};
  assert.equal(verifyOffline(before,after,'fixture'),true);
  for(const patch of [{guards_active:false},{blocked_clients:1},{blocked_outbound:1},{pid:43},{commit:'wrong'},
    {interpreter:'bedrock'},{planner:'unknown'},{run_state_store:'s3'},{scripted_stream_calls:1},{offline_run_builds:2}])assert.equal(verifyOffline(before,{...after,...patch},'fixture'),false);
  assert.equal(verifyOffline(null,after,'fixture'),false);
});
test('partial or forged success cannot enter a completed-duration statistic',t=>{
  const root=fixture(t);preallocate(root,{});
  const slots=Array.from({length:20},(_,i)=>readJSON(slotPath(root,i+1)));
  assert.throws(()=>summarize(slots.slice(1)));slots[0].status='PASSED';slots[0].elapsed_ms=0;
  assert.throws(()=>summarize(slots));slots[0].status='RUNNING';assert.throws(()=>summarize(slots));
  for(const index of [0,21,-1,1.2,'1'])assert.throws(()=>slotPath(root,index));
});
test('mixed successful and failed cohorts retain20 while quantiles name their smaller denominator',t=>{
  const root=fixture(t);preallocate(root,{});
  const slots=Array.from({length:20},(_,i)=>readJSON(slotPath(root,i+1)));
  for(const [i,slot] of slots.entries()){
    slot.offline_verified=true;
    if(i<10){
      Object.assign(slot,{status:'PASSED',elapsed_ms:31+i,receipt:{fixture:true},model_calls:0,model_cost_usd:0});
      slot.stages.forEach(stage=>Object.assign(stage,{status:'PASSED',elapsed_ms:2}));
    }else Object.assign(slot,{status:'FAILED',failed_elapsed_ms:99});
  }
  const summary=summarize(slots);
  assert.deepEqual(summary.counts,{PASSED:10,FAILED:10,INCOMPLETE:0,NOT_RUN:0});
  assert.equal(summary.overall.successful_n,10);assert.equal(summary.overall.p50_ms,35.5);
  assert.equal(summary.overall.p95_ms,40);assert.equal(summary.by_viewport.mobile.p50_ms,null);
  assert.equal(summary.by_stage.close.successful_n,10);assert.equal(summary.model_cost_usd,null);
});
test('benchmark is manual-only after source verification and preserves the declared fixed budget',()=>{
  const protocol=readJSON('../docs/hero-measurement-protocol.json');
  assert.equal(protocol.sampling.n,20);assert.equal(protocol.sampling.process_timeout_ms,1200000);
  assert.match(protocol.supersedes.reason,/not a truthful commit timestamp/);
  assert.match(preregistration,/^[a-f0-9]{40}$/);
  const workflow=readFileSync('../.github/workflows/frontend-ci.yml','utf8');
  assert.match(workflow,/source-hero-benchmark:[\s\S]*needs: verify[\s\S]*if: github.event_name == 'workflow_dispatch' && inputs.run_source_benchmark == true/);
  const config=readFileSync('playwright.benchmark.config.ts','utf8');
  assert.match(config,/workers:1,retries:0,repeatEach:10/);assert.match(config,/globalTimeout:1140000/);
  assert.match(config,/trace:'off',screenshot:'off',video:'off'/);
});
test('LT-HISTORY has matching dated testbook evidence and current AWS pointer',()=>{
  const book=readJSON('UAT.testbook.json'),entry=book.cases.find(row=>row.id==='LT-HISTORY');
  assert.ok(entry);assert.equal(entry.human_signoff,'NOT_RUN');
  assert.match(entry.observed_result_evidence,/2026-09-10.*a3e3d390489382708f4b32a020ea4c9c5293e576/);
  assert.match(entry.expected_outcome,/DSQL.*200.*fallback.*409/);
  const html=readFileSync('UAT.testbook.html','utf8');assert.match(html,/id="LT-HISTORY"/);
  assert.match(html,/34476984764/);assert.match(html,/href="\/acceptance.html"/);
});
