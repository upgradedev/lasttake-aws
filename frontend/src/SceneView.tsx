import {useLayoutEffect,useRef,useState} from 'react';
import {ApprovalConsole,DecisionForm} from './Actions';
import {Evidence,Inspector} from './Inspector';
import {link,roles,words} from './model';
import {beatMatches,reviewLabel,selectEvidence,uniqueBy} from './projection';
import type {Document,Role,RunState,Scene,Selection} from './types';

export function SceneView({scene,state,selected,selection={},role='script_supervisor',busy=false,act}:{scene:Scene;state:RunState;selected:string|null;selection?:Selection;role?:Role;busy?:boolean;act?:(path:string,extra?:Document)=>Promise<boolean>}) {
  const [search,setSearch]=useState('');
  const [localFilter,setLocalFilter]=useState('all');
  const filter=selection.filter ?? localFilter;
  const {beat,finding,findings,invalid,related}=selectEvidence(scene,state,{...selection,beat:selected});
  const scriptList=useRef<HTMLDivElement>(null);
  const activeBeat=selected ?? related[0]?.beat_id;
  const previousBeat=useRef<string|undefined>(undefined);
  useLayoutEffect(()=>{
    const list=scriptList.current;
    const row=activeBeat?document.getElementById('beat-'+activeBeat):null;
    if(list && row && list.contains(row)){
      list.scrollTop=Math.max(0,list.scrollTop+row.getBoundingClientRect().top-list.getBoundingClientRect().top-10);
      // A new selection also brings the pane into the window, minimally, so
      // the row the pane just scrolled to is where the person is looking.
      if(previousBeat.current!==activeBeat)list.closest('section')?.scrollIntoView({block:'nearest'});
    }
    previousBeat.current=activeBeat;
  // A filter can replace the rows above the same selected beat. Reposition for
  // that layout change as well as a new selection, without moving focus.
  },[activeBeat,filter,search,scene,state.counts]);
  const outcomes=new Map((state.counts ? state.beats : []).map(b=>[b.beat_id,b]));
  const shown=uniqueBy(scene.beats,b=>b.beat_id).filter(b=>beatMatches(b,state,['covered','exceptions','missing-releases'].includes(filter)?filter:'all') && `${b.slug} ${b.beat_id} ${b.description} ${b.page} ${b.line}`.toLowerCase().includes(search.toLowerCase()));
  const updateFilter=(value:string)=>{setLocalFilter(value);if(selection.filter)location.hash=link('scene',state.run_id,undefined,{filter:value});};
  return <>
    <div className="workspace-jumps" aria-label="Workspace panels">{[['script-pane','01 Script & takes'],['evidence-pane','02 Evidence'],['decision-pane','03 Decision']].filter(([id])=>act || id!=='decision-pane').map(([id,label])=><a key={id} href={'#'+id} onClick={e=>{e.preventDefault();const pane=document.getElementById(id);pane?.focus({preventScroll:true});pane?.scrollIntoView({block:'start'});}}>{label}</a>)}</div>
    {invalid && <p className="warning" role="status">This selection is unavailable or does not match the current evidence. <a href={link('scene',state.run_id)}>Reset selection</a>. No finding decision is offered for an invalid link.</p>}
    <div className="scene-layout" data-testid="production-cockpit">
      <section id="script-pane" tabIndex={-1} className="script cockpit-pane" aria-label="Lined script"><div className="pane-heading"><span>01</span><h2>Scene & script beats</h2></div><div className="script-title"><div className="slate-index">{scene.scene_id}</div><div><h3>{scene.scene_heading}</h3><p>{scene.revision} · {scene.take_count} supplied takes</p></div></div>
        <div className="pane-controls"><label>Find a beat<input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Beat, script text, page or line"/></label><label>Show<select value={['covered','exceptions','missing-releases'].includes(filter)?filter:'all'} onChange={e=>updateFilter(e.target.value)}><option value="all">All script beats</option><option value="exceptions">Beats with exceptions</option><option value="covered">Covered required beats</option><option value="missing-releases">Beats missing release records</option></select></label></div>
        <div ref={scriptList} className="pane-scroll" tabIndex={0} aria-label="Script beat list"><p className="list-count">{shown.length} shown · {scene.required_beats} required in scene</p>{shown.length===0 && <p className="empty">No beats match this filter. Try another search or show all beats.{!state.counts?' Assessment is not available until a checkpoint.':''}</p>}
          {shown.map(b=>{const outcome=outcomes.get(b.beat_id);return <article key={b.beat_id} id={'beat-'+b.beat_id} className={'beat '+(selected===b.beat_id || related.some(r=>r.beat_id===b.beat_id)?'selected':'')}>
            <a className="beat-link" href={link('scene',state.run_id,b.beat_id)} aria-current={selected===b.beat_id?'location':undefined}><span className="page-line">{b.page}:{b.line}</span><span><span className="beat-slug">{b.slug}</span><span className={'badge '+(outcome?.status==='covered_with_evidence'?'verified':'')}>{outcome?words(outcome.status):!state.counts?'Not assessed':b.required?'Not assessed':'Optional · outside coverage count'}</span></span></a>
            <p className="script-text">{b.description}</p><p className="fine">{b.beat_id} · {b.required?'Required beat':'Optional insert'} · {b.planned_shot ?? 'No planned shot'}</p>
            {selected===b.beat_id && outcome && <p className="fine">Evidence basis: {words(outcome.basis)}</p>}
            {b.takes.length?uniqueBy(b.takes,t=>t.take_id).map(t=><Inspector key={t.take_id} take={t}/>):<p className="missing">No take supplied for this beat.</p>}
          </article>;})}
        </div>
      </section>
      <section id="evidence-pane" tabIndex={-1} className="cockpit-pane findings" aria-label="Evidence and exceptions"><div className="pane-heading"><span>02</span><h2>Discrepancy & sources</h2></div><div className="pane-scroll" tabIndex={0} aria-label="Finding inspection">
        <div className="section-heading"><h3>{beat?'Selected beat':'Scene exceptions'}</h3>{(beat||selection.finding||selection.filter) && <a href={link('scene',state.run_id)}>Show all</a>}</div>{beat && <p>{beat.slug}</p>}
        {!state.counts?<p className="empty">Run a checkpoint to reconcile the records. Unchecked records are not a pass.</p>:findings.length===0?<p className="empty">No exception is associated with this selection. Review the rest of the scene before requesting wrap.</p>:<>
          <div className="finding-picker" aria-label="Choose a finding">{findings.map(f=><a key={f.finding_id} className="finding-option" data-check={f.check_type} href={link('scene',state.run_id,beat?.beat_id,{finding:f.finding_id})} aria-current={finding?.finding_id===f.finding_id?'true':undefined}><span>{words(f.check_type)} · {f.requirement_id ?? 'Shot plan advisory'}</span><small>{words(f.truth_state)} · {reviewLabel(f,state)}</small></a>)}</div>
          {finding && <><Evidence finding={finding} scene={scene}/><div className="related-beats"><h3>Linked script beats</h3>{related.length?related.map(b=><a className="button" key={b.beat_id} href={link('scene',state.run_id,b.beat_id,{finding:finding.finding_id})}>{b.beat_id} · Page {b.page}, line {b.line}</a>):<p className="warning">Unmatched source: this finding has no linked beat in the current script. Its source records are shown above.</p>}</div><a className="button" href={link('records',state.run_id,beat?.beat_id,{finding:finding.finding_id,filter:'findings',record:finding.finding_id})}>Inspect in Records</a></>}
        </>}
      </div></section>
      {act && <section id="decision-pane" tabIndex={-1} className="cockpit-pane decision-console" aria-label="Role and decision console"><div className="pane-heading"><span>03</span><h2>Human decision</h2></div><div className="wrap-status" data-testid="wrap-status"><span>Eligibility <strong>{!state.counts?'Not assessed':state.eligible?'Eligible':'Blocked'}</strong></span><span>Wrap <strong>{state.wrap_approved?'Recorded':'Not approved'}</strong></span>{state.pending_approval && <a href={link('scene',state.run_id,undefined,{filter:'approval'})}>Review pending {state.pending_approval.reason.kind} · {roles[state.pending_approval.reason.required_role]}{state.pending_approval.evidence_changed?' · evidence changed':''}</a>}</div><div className="pane-scroll" key={filter==='approval'?'approval':'finding'} tabIndex={0} aria-label="Decision controls"><p className="console-role">Reviewing as {roles[role]}</p>
        {filter!=='approval' && (finding && !invalid?<DecisionForm key={finding.finding_id+':'+finding.record_sha256+':'+role} compact finding={finding} scene={scene} state={state} role={role} busy={busy} act={act}/>:<p className="empty">Select a current finding to review its decision. Approval controls remain separate below.</p>)}
        <ApprovalConsole state={state} role={role} busy={busy} act={act}/>
        {state.counts && state.causes.length>0 && <details><summary>All eligibility causes ({state.causes.length})</summary><ul className="action-list">{state.causes.map((c,i)=><li key={i}>{c.reason}<small>{roles[c.required_role]} · {scene.locations[c.requirement_id] ?? c.requirement_id}</small>{c.finding_id && state.exceptions.some(f=>f.finding_id===c.finding_id) && <a href={link('scene',state.run_id,undefined,{finding:c.finding_id})}>Review finding</a>}</li>)}</ul></details>}
        <a className="button" href={link('history',state.run_id,selected ?? undefined,{finding:selection.finding})}>Turnover & receipts</a>
      </div></section>}
    </div>
  </>;
}
