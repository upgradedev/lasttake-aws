// Source-only measurement records; no product code or browser side effects here.
import {mkdirSync,openSync,writeFileSync,fsyncSync,closeSync,renameSync,readFileSync,readdirSync,existsSync} from 'node:fs';
import {join,dirname,resolve} from 'node:path';
import {createHash} from 'node:crypto';
export const N=20;
export const stages=['trigger','live','sponsor','evidence','close'];
export const sha256=bytes=>createHash('sha256').update(bytes).digest('hex');
export const readJSON=file=>JSON.parse(readFileSync(file,'utf8'));
export function durableJSON(file,data){
  const temporary=file+'.next';
  const fd=openSync(temporary,'w');
  try{writeFileSync(fd,JSON.stringify(data,null,2)+'\n');fsyncSync(fd);}finally{closeSync(fd);}
  renameSync(temporary,file);
}
export function slotPath(root,index){
  if(!Number.isInteger(index)||index<1||index>N)throw new Error('Invalid fixed slot');
  return join(root,`slot-${String(index).padStart(2,'0')}.json`);
}
export function preallocate(root,identity){
  mkdirSync(dirname(root),{recursive:true});
  mkdirSync(root,{recursive:false}); // Refuse replacing any earlier cohort.
  durableJSON(join(root,'identity.json'),identity);
  for(let index=1;index<=N;index++)durableJSON(slotPath(root,index),{
    index,viewport:index<=10?'desktop':'mobile',status:'NOT_RUN',started_at:null,ended_at:null,
    elapsed_ms:null,failed_elapsed_ms:null,stage:null,failure:null,requests:[],
    stages:stages.map(id=>({id,status:'NOT_RUN',start_ms:null,end_ms:null,elapsed_ms:null})),
    offline_verified:false,model_calls:null,model_cost_usd:null,guard_before:null,guard_after:null,
  });
}
export function beginSlot(root,index){
  const slot=readJSON(slotPath(root,index));
  if(slot.status!=='NOT_RUN')throw new Error('Retries and replacements are forbidden');
  slot.status='RUNNING';slot.started_at=new Date().toISOString();
  durableJSON(slotPath(root,index),slot);return slot;
}
export function quantiles(values){
  if(values.some(v=>!Number.isFinite(v)||v<0))throw new Error('Invalid measured duration');
  const sorted=[...values].sort((a,b)=>a-b),n=sorted.length;
  return {successful_n:n,p50_ms:n?(n%2?sorted[(n-1)/2]:(sorted[n/2-1]+sorted[n/2])/2):null,
    p95_ms:n?sorted[Math.ceil(.95*n)-1]:null,max_ms:n?sorted[n-1]:null};
}
export function verifyOffline(before,after,commit){
  for(const evidence of [before,after]){
    if(!evidence||evidence.commit!==commit||evidence.guards_active!==true||
      evidence.run_state_store!=='local-files'||evidence.interpreter!=='offline-lexical/1.0.0'||
      evidence.planner!=='offline-scripted/1.0.0'||evidence.blocked_outbound!==0||evidence.blocked_clients!==0||
      !Number.isInteger(evidence.scripted_stream_calls)||!Number.isInteger(evidence.offline_run_builds))return false;
  }
  return before.pid===after.pid && after.scripted_stream_calls>before.scripted_stream_calls &&
    after.offline_run_builds>before.offline_run_builds;
}
export function summarize(slots){
  if(slots.length!==N||new Set(slots.map(s=>s.index)).size!==N)throw new Error('Fixed denominator lost');
  const counts={PASSED:0,FAILED:0,INCOMPLETE:0,NOT_RUN:0};
  for(const slot of slots){
    if(!(slot.status in counts))throw new Error('Unfinalized outcome');
    counts[slot.status]++;
    if(slot.status==='PASSED'&&(!slot.offline_verified||!Number.isFinite(slot.elapsed_ms)||slot.elapsed_ms<=0||
      slot.stages.some(s=>s.status!=='PASSED')||!slot.receipt))throw new Error('Incomplete success evidence');
  }
  const successful=slots.filter(s=>s.status==='PASSED');
  return {scope:'SOURCE_CI_ONLY',denominator:N,counts,overall:quantiles(successful.map(s=>s.elapsed_ms)),
    by_viewport:Object.fromEntries(['desktop','mobile'].map(v=>[v,quantiles(successful.filter(s=>s.viewport===v).map(s=>s.elapsed_ms))])),
    by_stage:Object.fromEntries(stages.map(id=>[id,quantiles(slots.flatMap(s=>s.stages.filter(x=>x.id===id&&x.status==='PASSED').map(x=>x.elapsed_ms)))])),
    model_cost_usd:slots.every(s=>s.status==='PASSED'&&s.offline_verified&&s.model_calls===0&&s.model_cost_usd===0)?0:null,infrastructure_cost_usd:null,runner_cost_usd:null,
    limits:'Descriptive scripted source-CI cohort only. Successful-duration quantiles exclude failures, which remain raw. body_bytes measures request bodies only; response-body bytes UNKNOWN, not captured. No total-network-byte, AWS/production/human-time/statistical advantage or total-zero-cost claim. Human NOT_RUN; video NOT_CONFIGURED.'};
}
export function finalize(root,reason){
  const slots=Array.from({length:N},(_,i)=>readJSON(slotPath(root,i+1)));
  for(const slot of slots)if(slot.status==='RUNNING'){
    slot.status='INCOMPLETE';slot.failure=reason;slot.ended_at=new Date().toISOString();
    slot.elapsed_observation='LAST_DURABLE_BOUND_NOT_COMPLETED_DURATION';
    durableJSON(slotPath(root,slot.index),slot);
  }
  const summary=summarize(slots);durableJSON(join(root,'summary.json'),summary);
  const escape=text=>String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  writeFileSync(join(root,'summary.html'),`<!doctype html><html lang="en"><meta charset="utf-8"><title>LastTake source hero measurement</title><h1>Source-only hero cohort</h1><p>${escape(summary.limits)}</p><p>p50: middle value/mean of two middle values. p95: nearest-rank ceil(.95 * successful_n). Infra and runner cost unknown.</p><pre>${escape(JSON.stringify(summary,null,2))}</pre><h2>All20 scheduled slots</h2><table><tr><th>Slot</th><th>Viewport</th><th>Status</th><th>Completed ms</th><th>Failed/partial ms</th></tr>${slots.map(s=>`<tr><td>${s.index}</td><td>${s.viewport}</td><td>${s.status}</td><td>${s.elapsed_ms??'unknown'}</td><td>${s.failed_elapsed_ms??'unknown'}</td></tr>`).join('')}</table></html>`);
  writeManifest(root);
  return summary;
}
function writeManifest(root){
  const hashes=Object.fromEntries(fileNames(root).filter(f=>f!=='manifest.json'&&!f.endsWith('.next')).map(f=>[f,sha256(readFileSync(join(root,f)))]));
  durableJSON(join(root,'manifest.json'),{schema:'lasttake/source-measurement-files/v1',sha256:hashes});
}
function fileNames(root,prefix=''){
  return readdirSync(join(root,prefix),{withFileTypes:true}).flatMap(entry=>{
    const path=prefix?`${prefix}/${entry.name}`:entry.name;
    if(entry.isDirectory())return fileNames(root,path);
    if(!entry.isFile())throw new Error('Unexpected non-regular evidence file');
    return [path];
  }).sort();
}
// Only this isolated destination is uploaded. A surviving producer knows the live root,
// never this destination; all derivation uses buffers captured once, not later live reads.
export function sealSnapshot(root,destination,reason){
  root=resolve(root);destination=resolve(destination);
  if(dirname(root)!==dirname(destination)||root===destination||existsSync(destination))throw new Error('Snapshot must be a new sibling');
  const staging=destination+'.next';mkdirSync(staging,{recursive:false});
  const started_at=new Date().toISOString();
  const captured=new Map(readdirSync(root,{withFileTypes:true}).filter(e=>!e.name.endsWith('.next')).map(entry=>{
    if(!entry.isFile())throw new Error('Unexpected producer evidence entry');
    return [entry.name,readFileSync(join(root,entry.name))];
  }));
  const ended_at=new Date().toISOString();
  mkdirSync(join(staging,'captured'));
  for(const [name,bytes] of captured){
    writeFileSync(join(staging,'captured',name),bytes,{flag:'wx'});
    if(!['manifest.json','summary.json','summary.html'].includes(name))writeFileSync(join(staging,name),bytes,{flag:'wx'});
  }
  durableJSON(join(staging,'capture.json'),{schema:'lasttake/source-measurement-capture/v1',started_at,ended_at,reason,
    consistency:'Per-file atomic observations, not a cross-file transaction. Captured bytes are retained unchanged; RUNNING slots become INCOMPLETE only in the derived view.',
    sha256:Object.fromEntries([...captured].map(([name,bytes])=>[name,sha256(bytes)]))});
  let summary,failure;
  try{
    // Preserve all available bytes BEFORE refusing a missing/corrupt denominator.
    for(let index=1;index<=N;index++){
      const name=`slot-${String(index).padStart(2,'0')}.json`;
      if(JSON.parse(captured.get(name)?.toString()??'null')?.index!==index)throw new Error('Captured denominator lost');
    }
    summary=finalize(staging,reason);
  }catch(error){
    failure=new Error('Captured evidence validation refused; raw bytes retained');
    durableJSON(join(staging,'validation-error.json'),{schema:'lasttake/source-measurement-refusal/v1',status:'REFUSED',
      reason:'CAPTURED_EVIDENCE_INVALID',error_class:error instanceof Error?error.name:'UNKNOWN',
      scheduled_denominator:N,observed_outcomes:null,summary_status:'NOT_PRODUCED',
      captured_slot_files:[...captured.keys()].filter(name=>/^slot-\d\d\.json$/.test(name)).sort()});
    writeManifest(staging);
  }
  renameSync(staging,destination); // Publish success OR refusal evidence once; never update in place.
  if(failure)throw failure; // Workflow fails, but its always-upload can retain the sealed evidence.
  return summary;
}
