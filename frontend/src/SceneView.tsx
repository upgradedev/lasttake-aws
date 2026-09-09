import {useState} from 'react';
import {aboutBeat,link,roles,words} from './model';
import type {Finding,RunState,Scene,Take} from './types';
export function Evidence({finding,scene}:{finding:Finding;scene:Scene}) {
  return <div className="evidence">
    <p className="eyebrow">{words(finding.check_type)} · {words(finding.truth_state)}</p>
    <h3>{finding.requirement_id ? scene.locations[finding.requirement_id] ?? finding.requirement_id : 'Shot plan advisory'}</h3>
    <p>{finding.observation}</p>
    {finding.inference && <div className="inference"><span className="eyebrow">Bounded interpretation</span><p>{finding.inference}</p></div>}
    <p><strong>Next action:</strong> {finding.next_action}</p>
    <p className="fine">Responsible: {roles[finding.required_role]}</p>
    <details><summary>Source records & digests</summary>{finding.sources.map(s=><p key={s.artifact_id}><strong>{s.artifact_id}</strong><code>{s.sha256}</code></p>)}<p>Finding digest<code>{finding.record_sha256}</code></p></details>
  </div>;
}
function Inspector({take}:{take:Take}) {
  return <details className="take"><summary><span>Slate {take.slate}</span><span className="fine">{take.preferred?'Preferred':'Recorded'} · {take.lens_mm} mm</span></summary>
    <p>{take.note || 'No supervisor note supplied.'}</p>
    <div className="table-scroll"><table><caption>Take sidecar and camera report</caption><thead><tr><th>Field</th><th>Sidecar</th><th>Camera report</th></tr></thead><tbody>{(['media_id','camera_roll','lens_mm'] as const).map(key=><tr key={key} className={take.camera_report?.[key]!==take[key]?'mismatch':''}><th>{words(key)}</th><td>{take[key]}</td><td>{take.camera_report?.[key] ?? 'Missing'}</td></tr>)}</tbody></table></div>
    <dl className="metadata"><dt>Sound roll</dt><dd>{take.sound_roll}</dd><dt>Timecode</dt><dd>{take.timecode_in} to {take.timecode_out}</dd><dt>Take</dt><dd>{take.take_id}</dd><dt>Usable flag</dt><dd>{take.usable?'Yes, in the supplied record':'No'}</dd></dl>
  </details>;
}
export function SceneView({scene,state,selected}:{scene:Scene;state:RunState;selected:string|null}) {
  const [filter,setFilter]=useState('all');
  const [search,setSearch]=useState('');
  const beat=scene.beats.find(b=>b.beat_id===selected);
  const findings=beat ? state.exceptions.filter(f=>aboutBeat(f,beat)) : state.exceptions;
  const outcomes=new Map((state.counts ? state.beats : []).map(b=>[b.beat_id,b]));
  const shown=scene.beats.filter(b=>(filter==='all'||state.exceptions.some(f=>aboutBeat(f,b))) && `${b.slug} ${b.beat_id}`.toLowerCase().includes(search.toLowerCase()));
  return <><div className="toolbar"><label className="grow">Find a beat<input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search script or beat identifier"/></label><label>Show<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All script beats</option><option value="exceptions">Beats with exceptions</option></select></label></div>
  <div className="scene-layout"><section className="script" aria-label="Lined script"><div className="script-title"><p className="eyebrow">The Last Ferry · scene 42</p><h2>{scene.scene_heading}</h2><p>{scene.revision} · {scene.take_count} supplied takes</p></div>
    {shown.length===0 && <p className="empty">No beats match this filter. Try another search or show all beats.</p>}
    {shown.map(b=>{const outcome=outcomes.get(b.beat_id); return <article key={b.beat_id} id={`beat-${b.beat_id}`} className={`beat ${selected===b.beat_id?'selected':''}`}>
      <a className="beat-link" href={link('scene',state.run_id,b.beat_id)} aria-current={selected===b.beat_id?'location':undefined}><span className="page-line">{b.page}:{b.line}</span><span><span className="beat-slug">{b.slug}</span><span className={`badge ${outcome?.status==='covered_with_evidence'?'verified':''}`}>{outcome?words(outcome.status):'Not assessed'}</span></span></a>
      <p className="script-text">{b.description}</p><p className="fine">{b.beat_id} · {b.required?'Required beat':'Optional insert'} · {b.planned_shot ?? 'No planned shot'}</p>
      {b.takes.length ? b.takes.map(t=><Inspector key={t.take_id} take={t}/>) : <p className="missing">No take supplied for this beat.</p>}
    </article>;})}
  </section><aside className="panel findings" aria-label="Evidence and exceptions"><div className="section-heading"><h2>{beat?'Selected beat':'Scene exceptions'}</h2>{beat && <a href={link('scene',state.run_id)}>Show all</a>}</div>
    {beat && <p>{beat.slug}</p>}
    {!state.counts ? <p className="empty">Run a checkpoint to reconcile the records. Unchecked records are not a pass.</p> : findings.length===0 ? <p className="empty">No exception is associated with this selection. Review the rest of the scene before requesting wrap.</p> : findings.map(f=><Evidence key={f.finding_id} finding={f} scene={scene}/>)}
    <a className="button" href={link('actions',state.run_id)}>Review actions & approvals</a>
  </aside></div></>;
}
