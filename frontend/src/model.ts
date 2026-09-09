import type { Beat, Decision, Finding, Page, Role, Selection } from './types';
export const roles: Record<Role,string> = {script_supervisor:'Script supervisor', first_ad:'1st AD', dit:'DIT / data manager', production_coordinator:'Production coordinator', editorial:'Assistant editor'};
export const pages: Record<Page,string> = {overview:'Dashboard', scene:'Workspace', records:'Records', history:'History', actions:'My actions'};
export function readRoute() {
  const [raw, query] = location.hash.slice(1).split('?');
  const page = raw==='dashboard'?'overview':raw==='workspace'?'scene':Object.hasOwn(pages, raw) ? raw as Page : 'overview';
  const params = new URLSearchParams(query);
  return {page, run:params.get('run'), beat:params.get('beat'), finding:params.get('finding'),filter:params.get('filter'),record:params.get('record'),q:params.get('q')};
}
export function link(page:Page, run?:string|null, beat?:string, selection:Selection={}) {
  const params = new URLSearchParams();
  if (run) params.set('run',run);
  if (beat) params.set('beat',beat);
  for(const [key,value] of Object.entries(selection))if(value)params.set(key,value);
  return `#${page}${params.size ? `?${params}` : ''}`;
}
export function aboutBeat(finding:Finding, beat:Beat) {
  const id=finding.requirement_id;
  if(typeof id!=='string' || !id.trim())return false;
  return id===beat.beat_id || (Boolean(beat.continuity_ref) && id===beat.continuity_ref) || beat.takes.some(t=>t.take_id===id || t.visible_people.includes(id) || t.visible_assets.includes(id)) || finding.locators.some(l=>l.kind==='take' && Boolean(l.value) && beat.takes.some(t=>t.take_id===l.value));
}
export function decisionFor(finding:Finding, decisions:Decision[]) {
  const decision=decisions.filter(d=>d.finding_id===finding.finding_id && d.role===finding.required_role).sort((a,b)=>a.at.localeCompare(b.at)||a.decision_id.localeCompare(b.decision_id)).at(-1);
  return {decision, stale:!!decision?.finding_sha256 && decision.finding_sha256!==finding.record_sha256};
}
export function words(value:string) { return value.replaceAll('_',' '); }
export function makeDocument(kind:'take'|'rights_record', form:FormData) {
  const text=(name:string)=>String(form.get(name) ?? '').trim();
  if(kind==='rights_record') return {record_id:text('record_id'), subject_id:text('subject_id'), subject_kind:text('subject_kind'), document_type:text('document_type'), scope:text('scope'), territory:text('territory'), status:text('status'), expires_on:text('expires_on') || null};
  const list=(name:string)=>text(name).split(',').map(s=>s.trim()).filter(Boolean);
  return {take_id:text('take_id'),shot_id:text('shot_id'),beat_ids:[text('beat_id')],slate:text('slate'),camera_roll:text('camera_roll'),sound_roll:text('sound_roll'),timecode_in:text('timecode_in'),timecode_out:text('timecode_out'),lens_mm:Number(text('lens_mm')),media_id:text('media_id'),preferred:form.has('preferred'),usable:form.has('usable'),note:text('note'),visible_people:list('visible_people'),visible_assets:list('visible_assets'),captured_at:text('captured_at'),camera_report_row:{take_id:text('take_id'),media_id:text('report_media_id'),lens_mm:Number(text('report_lens_mm')),camera_roll:text('report_camera_roll')}};
}
