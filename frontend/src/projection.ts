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
  const filtered=all.filter(f=>(!beat || aboutBeat(f,beat)) && (selection.filter!=='missing-releases'||f.check_type==='rights'));
  const candidate=requested ?? filtered[0];
  const conflicting=candidate && state.exceptions.some(f=>f.finding_id===candidate.finding_id && f.record_sha256!==candidate.record_sha256);
  const invalid=Boolean(conflicting || (selection.beat && !beat)||(selection.finding && !requested)||(beat && requested && !aboutBeat(requested,beat)));
  const finding=invalid?undefined:candidate;
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
    {id:'approval',label:'Human wrap approval',value:state.wrap_approved?'Approved':state.pending_approval?.reason.kind==='wrap'?(state.pending_approval.evidence_changed?'Needs new review':'Pending 1st AD'):'Not approved',detail:'A separate decision on the reviewed package',href:link('scene',state.run_id,undefined,{filter:'approval'})},
  ];
}
export function reviewLabel(finding:Finding,state:RunState) {
  const current=decisionFor(finding,state.decisions);
  if(current.stale)return 'Review changed evidence';
  if(current.decision)return 'Decision recorded · exception retained';
  // The gate in policy.py skips a finding with no requirement id, so it can
  // never block wrap. Say so instead of leaving it open as "Needs review".
  return finding.requirement_id===null || finding.requirement_id===undefined?'Advisory, not a wrap blocker':'Needs review';
}
function field(value:unknown,key:string):unknown {
  return typeof value==='object' && value!==null ? (value as Record<string,unknown>)[key] : undefined;
}
// An approved pickup is saved as a pickup.requested delivery whose payload names
// the beat. Only a bus-accepted row counts: a pending, unknown or rejected
// outcome is not established, and the server does not call it approved either.
export function hasApprovedPickup(finding:Finding,state:RunState) {
  if(finding.check_type!=='coverage' || typeof finding.requirement_id!=='string' || !finding.requirement_id)return false;
  return (state.delivery_outcomes ?? []).some(row=>row.event_type==='pickup.requested' && row.status==='accepted' && row.accepted===true && field(field(row,'payload'),'beat_id')===finding.requirement_id);
}
