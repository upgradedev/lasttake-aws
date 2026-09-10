import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,readdirSync,rmSync,writeFileSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {setTimeout as delay} from 'node:timers/promises';
import {preallocate,beginSlot,slotPath,readJSON,durableJSON,finalize,sealSnapshot,quantiles,verifyOffline,summarize,sha256} from '../scripts/hero-measurement.mjs';
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
  const summary=sealSnapshot(root,root+'-final',result.reason);
  assert.equal(summary.denominator,20);assert.equal(summary.counts.INCOMPLETE,1);
  assert.equal(summary.counts.NOT_RUN,19);assert.equal(readJSON(slotPath(root,3)).status,'RUNNING');
  assert.equal(readJSON(slotPath(root+'-final',3)).elapsed_ms,null);
});
test('failed child launch also preserves all unrun slots',async t=>{
  const root=fixture(t);preallocate(root,{});
  const result=await supervise(join(root,'nonexistent'),[],{root,timeoutMs:500,cwd:root,env:process.env});
  assert.notEqual(result.exit,0);assert.equal(sealSnapshot(root,root+'-final',result.reason).counts.NOT_RUN,20);
});

test('killed driver leaves a real detached writer, but captured bytes and final hashes cannot drift',{timeout:10000},async t=>{
  const parent=mkdtempSync(join(tmpdir(),'lasttake-orphan-fixture-')),root=join(parent,'live'),destination=join(parent,'final');
  let driver,writerPid;
  t.after(()=>{try{driver?.kill('SIGKILL');}catch{}try{process.kill(writerPid,'SIGKILL');}catch{}rmSync(parent,{recursive:true,force:true});});
  preallocate(root,{});beginSlot(root,1);
  const writer=`const fs=require('node:fs'); const path=${JSON.stringify(slotPath(root,1))}; let revision=0; setInterval(()=>{const slot=JSON.parse(fs.readFileSync(path)); slot.revision=++revision; fs.writeFileSync(path+'.next',JSON.stringify(slot)); fs.renameSync(path+'.next',path);},5);`;
  const driverSource=`const {spawn}=require('node:child_process'); const child=spawn(process.execPath,['-e',${JSON.stringify(writer)}],{detached:true,stdio:'ignore'}); console.log(child.pid); setInterval(()=>{},1000);`;
  driver=spawn(process.execPath,['-e',driverSource],{stdio:['ignore','pipe','inherit']});
  writerPid=Number(String((await once(driver.stdout,'data'))[0]).trim());assert.ok(writerPid>0);
  const closed=once(driver,'close');driver.kill('SIGKILL');await closed;
  async function waitRevision(minimum){
    const deadline=Date.now()+3000;
    while(Date.now()<deadline){const revision=readJSON(slotPath(root,1)).revision??0;if(revision>minimum)return revision;await delay(10);}
    assert.fail('Detached writer stopped unexpectedly');
  }
  await waitRevision(2);
  const summary=sealSnapshot(root,destination,'OUTER_DRIVER_KILLED');
  const captured=readFileSync(join(destination,'captured','slot-01.json'));
  const manifestBytes=readFileSync(join(destination,'manifest.json'));
  await waitRevision(JSON.parse(captured).revision+5); // Writer is still alive after publication.
  assert.equal(summary.counts.INCOMPLETE,1);assert.equal(summary.counts.NOT_RUN,19);
  assert.equal(readJSON(slotPath(destination,1)).status,'INCOMPLETE');
  assert.equal(JSON.parse(captured).status,'RUNNING');
  assert.deepEqual(readFileSync(join(destination,'captured','slot-01.json')),captured);
  assert.deepEqual(readFileSync(join(destination,'manifest.json')),manifestBytes);
  for(const [file,hash] of Object.entries(JSON.parse(manifestBytes).sha256))assert.equal(sha256(readFileSync(join(destination,file))),hash);
  assert.throws(()=>sealSnapshot(root,destination,'REPLACEMENT'));
});

for(const kind of ['missing','malformed'])test(`${kind} captured slot seals available raw/error bytes and refuses a success summary`,t=>{
  const root=fixture(t),destination=root+'-final';preallocate(root,{fixture:true});beginSlot(root,1);
  if(kind==='missing')rmSync(slotPath(root,20));else writeFileSync(slotPath(root,20),'{broken JSON');
  const originals=Object.fromEntries(readdirSync(root).map(name=>[name,readFileSync(join(root,name))]));
  assert.throws(()=>sealSnapshot(root,destination,'FIXTURE'),/raw bytes retained/);
  const refusal=readJSON(join(destination,'validation-error.json'));
  assert.equal(refusal.status,'REFUSED');assert.equal(refusal.summary_status,'NOT_PRODUCED');
  assert.equal(refusal.observed_outcomes,null);assert.equal(refusal.scheduled_denominator,20);
  assert.equal(refusal.captured_slot_files.length,kind==='missing'?19:20);
  assert.equal(refusal.error_class,kind==='missing'?'Error':'SyntaxError');
  assert.equal(existsSync(join(destination,'summary.json')),false);
  assert.equal(existsSync(join(destination,'summary.html')),false);
  for(const [name,bytes] of Object.entries(originals))assert.deepEqual(readFileSync(join(destination,'captured',name)),bytes);
  const manifest=readFileSync(join(destination,'manifest.json'));
  durableJSON(slotPath(root,1),{changed_after_seal:true});
  for(const [file,hash] of Object.entries(JSON.parse(manifest).sha256))assert.equal(sha256(readFileSync(join(destination,file))),hash);
  assert.deepEqual(readFileSync(join(destination,'manifest.json')),manifest);
  assert.throws(()=>sealSnapshot(root,destination,'REPLACE'));
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
  assert.match(workflow,/timeout --signal=KILL 1200s node scripts\/run-hero-benchmark.mjs/);
  assert.match(workflow,/WORKFLOW_PROCESS_TERMINATED/);
  assert.match(workflow,/path: frontend\/test-results\/hero-benchmark-final\//);
  assert.doesNotMatch(workflow,/path: frontend\/test-results\/hero-benchmark\//);
  assert.match(workflow,/sealSnapshot\('test-results\/hero-benchmark','test-results\/hero-benchmark-final'/);
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
