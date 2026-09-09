import {aboutBeat,decisionFor,link} from './model';
import type {Beat,EventRow,Finding,RunState,Scene,Selection} from './types';

// Identity deduplication prevents a repeated transport row from inflating a count.
// This is a projection of the server response, not verification of source bytes.
export function uniqueBy<T>(rows:T[],id:(row:T)=>string):T[] {
  return [...new Map(rows.map(row=>[id(row),row])).values()];
}
export function count(value:unknown):number|null {
  return typeof value==='number' && Number.isSafeInteger(value) && value>=0 ? value : null;
}
export function exceptions(state:RunState) {
  return state.counts ? uniqueBy(state.exceptions,f=>f.finding_id) : [];
}
export function recentEvents(events:EventRow[]) {
  return uniqueBy(events,e=>e.event_id).sort((a,b)=>b.occurred_at.localeCompare(a.occurred_at) || a.event_id.localeCompare(b.event_id));
}
export function beatsFor(scene:Scene,finding:Finding) {
  return uniqueBy(scene.beats.filter(b=>aboutBeat(finding,b)),b=>b.beat_id);
}
export function beatMatches(beat:Beat,state:RunState,filter:string) {
  if(!['covered','exceptions','missing-releases'].includes(filter))return true;
  if(!state.counts)return false;
  const outcome=state.beats.find(b=>b.beat_id===beat.beat_id);
  if(filter==='covered')return beat.required && outcome?.status==='covered_with_evidence';
  if(filter==='missing-releases')return beat.required && outcome?.status==='no_release_record';
  return exceptions(state).some(f=>aboutBeat(f,beat));
}
export function selectEvidence(scene:Scene,state:RunState,selection:Selection) {
  const all=exceptions(state);
  const beat=scene.beats.find(b=>b.beat_id===selection.beat);
  const requested=all.find(f=>f.finding_id===selection.finding);
  const conflicting=requested && state.exceptions.some(f=>f.finding_id===requested.finding_id && f.record_sha256!==requested.record_sha256);
  const invalid=Boolean(conflicting || (selection.beat && !beat)||(selection.finding && !requested)||(beat && requested && !aboutBeat(requested,beat)));
  const filtered=all.filter(f=>(!beat || aboutBeat(f,beat)) && (selection.filter!=='missing-releases'||f.check_type==='rights'));
  const finding=invalid?undefined:requested ?? filtered[0];
  return {beat,finding,findings:filtered,invalid,related:finding?beatsFor(scene,finding):[]};
}
export function metrics(scene:Scene,state:RunState) {
  const assessed=Boolean(state.counts);
  const c=state.counts;
  const value=(n:unknown)=>count(n)===null?'Not assessed':String(n);
  return [
    {id:'coverage',label:'Beats covered with evidence',value:value(c?.covered_with_evidence),detail:`${count(c?.required_beats) ?? scene.required_beats} required beats · current assessment`,href:link('scene',state.run_id,undefined,{filter:'covered'})},
    {id:'exceptions',label:'Retained exceptions',value:assessed?String(exceptions(state).length):'Not assessed',detail:'Unique findings; reviewed exceptions remain visible',href:link('scene',state.run_id,undefined,{filter:'exceptions'})},
    {id:'releases',label:'Beats missing release records',value:value(c?.without_release_record),detail:'Required beats; not a count of people or legal clearance',href:link('scene',state.run_id,undefined,{filter:'missing-releases'})},
    {id:'takes',label:'Supplied takes',value:count(scene.take_count)===null?'Unavailable':String(scene.take_count),detail:'Capture records, not assessed audio or footage',href:link('records',state.run_id,undefined,{filter:'takes'})},
    {id:'eligibility',label:'Wrap eligibility',value:assessed?(state.eligible?'Eligible':'Blocked'):'Not assessed',detail:'Deterministic evidence gate',href:link('scene',state.run_id,undefined,{filter:'approval'})},
    {id:'approval',label:'Human wrap approval',value:state.wrap_approved?'Recorded':state.pending_approval?.reason.kind==='wrap'?(state.pending_approval.evidence_changed?'Needs new review':'Pending 1st AD'):'Not approved',detail:'A separate decision on the reviewed package',href:link('scene',state.run_id,undefined,{filter:'approval'})},
  ];
}
export function reviewLabel(finding:Finding,state:RunState) {
  const current=decisionFor(finding,state.decisions);
  return current.stale?'Review changed evidence':current.decision?'Decision recorded · exception retained':'Needs review';
}
