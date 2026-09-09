import {Evidence,Inspector} from './Inspector';
import {aboutBeat,link,words} from './model';
import {exceptions,reviewLabel,uniqueBy} from './projection';
import type {RunState,Scene,Selection} from './types';

const filters={takes:'Supplied takes',script:'Script beats',findings:'Retained findings',releases:'Release subjects'};
export function Records({scene,state,selection}:{scene:Scene;state:RunState;selection:Selection}) {
  const kind=Object.hasOwn(filters,selection.filter ?? '')?selection.filter as keyof typeof filters:'takes';
  const search=selection.q ?? '';
  const setSearch=(q:string)=>location.replace(link('records',state.run_id,selection.beat ?? undefined,{...selection,filter:kind,q}));
  const allFindings=exceptions(state);
  const takes=uniqueBy(scene.beats.flatMap(b=>b.takes),t=>t.take_id);
  const entries=kind==='takes'?takes.map(t=>({id:t.take_id,label:'Slate '+t.slate,detail:t.media_id})):kind==='script'?uniqueBy(scene.beats,b=>b.beat_id).map(b=>({id:b.beat_id,label:b.slug,detail:'Page '+b.page+', line '+b.line})):kind==='releases'?uniqueBy(scene.subjects,s=>s.subject_id).map(s=>({id:s.subject_id,label:s.subject_id,detail:s.released?'Executed status supplied':'No executed status supplied'})):allFindings.map(f=>({id:f.finding_id,label:words(f.check_type)+' · '+(f.requirement_id ?? 'Shot plan advisory'),detail:reviewLabel(f,state)}));
  const shown=entries.filter(e=>(e.id+' '+e.label+' '+e.detail).toLowerCase().includes(search.toLowerCase()));
  const selected=entries.find(e=>e.id===selection.record);
  const take=takes.find(t=>t.take_id===selected?.id);
  const beat=scene.beats.find(b=>b.beat_id===selected?.id);
  const finding=allFindings.find(f=>f.finding_id===selected?.id);
  const subject=scene.subjects.find(s=>s.subject_id===selected?.id);
  return <><div className="toolbar records-controls"><label>Record type<select value={kind} onChange={e=>{location.hash=link('records',state.run_id,selection.beat ?? undefined,{filter:e.target.value,finding:selection.finding});}}>{Object.entries(filters).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><label className="grow">Search records<input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Identifier, slate, source or location"/></label></div>
    <div className="records-layout"><section className="panel record-list" aria-label="Source records"><h2>{filters[kind]}</h2><p>{shown.length} shown in the current scene.</p>{kind==='takes' && <p className="fine">{scene.take_count} takes reported by the API; {takes.length} distinct takes linked to script beats are inspectable here. Unlinked takes are not projected by this endpoint.</p>}
      {kind==='releases' && <p className="fine">Supplied execution status alone does not establish expiry, scope or legal sufficiency. Inspect the assessed rights findings.</p>}
      {kind==='findings' && !state.counts && <p className="empty">Not assessed. Run a checkpoint to obtain findings.</p>}
      {shown.length?<ul>{shown.map(e=><li key={e.id}><a aria-current={selected?.id===e.id?'true':undefined} href={link('records',state.run_id,selection.beat ?? undefined,{filter:kind,record:e.id,finding:selection.finding,q:search})}><strong>{e.label}</strong><code>{e.id}</code><span>{e.detail}</span></a></li>)}</ul>:<p className="empty">No records match this search.</p>}
    </section><section className="panel record-detail" aria-label="Record inspector">{!selected?<p className={selection.record?'warning':'empty'}>{selection.record?'This source is unavailable in the current record category. Choose a listed record.':'Select a record to inspect its supplied fields and linked workspace context.'}</p>:<><p className="eyebrow">Source inspector</p><h2>{selected.label}</h2><code>{selected.id}</code>
      {kind==='takes' && take && <><Inspector key={take.take_id} take={take} open/><h3>Linked script beats</h3>{scene.beats.filter(b=>b.takes.some(t=>t.take_id===take.take_id)).map(b=><a className="button" key={b.beat_id} href={link('scene',state.run_id,b.beat_id)}>{b.beat_id} · Page {b.page}, line {b.line}</a>)}</>}
      {kind==='script' && beat && <><p className="script-text">{beat.description}</p><p>Page {beat.page}, line {beat.line} · {beat.required?'Required':'Optional'}</p><p>Planned shot: {beat.planned_shot ?? 'Not supplied'}</p><p>Continuity reference: {beat.continuity_ref ?? 'Not supplied'}</p><a className="button primary" href={link('scene',state.run_id,beat.beat_id)}>Review beat & findings</a></>}
      {kind==='findings' && finding && <><Evidence finding={finding} scene={scene}/><a className="button primary" href={link('scene',state.run_id,undefined,{finding:finding.finding_id})}>Review this finding</a></>}
      {kind==='releases' && subject && <><p>{subject.released?'An executed status is present in the supplied ledger.':'No executed status is present in the supplied ledger.'}</p><p className="fine">Release documents and dates are not exposed by this scene projection. Current rights findings carry any assessed missing, conflicting, unknown or expired record concerns.</p>{allFindings.filter(f=>f.check_type==='rights' && f.requirement_id===subject.subject_id).map(f=><div key={f.finding_id}><Evidence finding={f} scene={scene}/><a className="button" href={link('scene',state.run_id,undefined,{finding:f.finding_id})}>Review rights finding</a></div>)}{!state.counts && <p className="warning">Not assessed. No clearance can be inferred.</p>}</>}
      {kind==='script' && beat && <p className="fine">{state.counts?allFindings.filter(f=>aboutBeat(f,beat)).length+' retained findings associated with this beat.':'Findings not assessed.'}</p>}
    </>}</section></div></>;
}
