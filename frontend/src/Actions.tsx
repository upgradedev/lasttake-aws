import {useState} from 'react';
import {decisionFor,roles,words} from './model';
import {Evidence} from './SceneView';
import type {Document,Finding,Role,RunState,Scene} from './types';
type Act=(path:string,extra?:Document)=>Promise<boolean>;
function DecisionForm({finding,scene,state,role,busy,act}:{finding:Finding;scene:Scene;state:RunState;role:Role;busy:boolean;act:Act}) {
  const [action,setAction]=useState('confirm');
  const current=decisionFor(finding,state.decisions);
  const allowed=scene.authority[finding.check_type];
  return <article className="panel decision-card" aria-label={`${words(finding.check_type)} ${finding.requirement_id ?? 'advisory'}`}>
    <Evidence finding={finding} scene={scene}/>
    {current.decision && <div className={current.stale?'warning':'decision-note'}>{current.stale ? 'Earlier decision no longer applies: the evidence has changed. Review it again.' : `Recorded: ${words(current.decision.action)} by ${current.decision.actor}. The original finding remains visible.`}</div>}
    {allowed.may_confirm.includes(role) ? <form onSubmit={async e=>{e.preventDefault();const form=e.currentTarget;const data=new FormData(form);if(await act('decide',{finding_id:finding.finding_id,finding_sha256:finding.record_sha256,role,action,actor:String(data.get('actor')),reason:String(data.get('reason'))}))form.reset();}}><fieldset disabled={busy}>
      <div className="form-grid"><label>Your name in this demo<input name="actor" required maxLength={100}/></label><label>Decision<select aria-label="Decision" value={action} onChange={e=>setAction(e.target.value)}><option value="confirm">Confirm the finding</option><option value="reject_false_positive">Reject as false positive</option>{allowed.may_accept.includes(role) && <option value="accept_exception">Accept the documented exception</option>}</select></label></div>
      <label>Reason for this exact evidence<textarea name="reason" required maxLength={2000}/></label>
      <button className="primary" type="submit">Record decision</button>
      {!allowed.may_accept.includes(role) && <p className="fine">This role cannot accept away a missing release. Supply the record or route the decision to production and counsel.</p>}
    </fieldset></form> : <p className="fine">Decision belongs to {roles[finding.required_role]}.</p>}
  </article>;
}
export function Actions({scene,state,role,busy,act}:{scene:Scene;state:RunState;role:Role;busy:boolean;act:Act}) {
  const mine=state.exceptions.filter(f=>scene.authority[f.check_type].may_confirm.includes(role));
  const others=state.exceptions.filter(f=>!scene.authority[f.check_type].may_confirm.includes(role));
  const pending=state.pending_approval;
  return <><section className="panel approvals" aria-labelledby="approval-title"><p className="eyebrow">Human authority</p><h2 id="approval-title">Pickup & wrap approvals</h2>
    {pending ? <><h3>{pending.reason.kind==='pickup'?`Pickup requested: ${pending.reason.slug ?? pending.reason.beat_id}`:'Wrap approval requested'}</h3><p>{pending.reason.justification ?? pending.reason.note}</p><p className="fine">The real Strands run is interrupted. This request is saved on the server.</p>
      {pending.evidence_changed && <p className="warning">Evidence has changed since this request. {pending.reason.kind==='wrap'?'Decline this request, review the new evidence, then request a fresh wrap approval.':'Review the current scene before answering.'}</p>}
      {role==='first_ad' ? <div className="toolbar"><button className="primary" disabled={busy || (pending.reason.kind==='wrap' && pending.evidence_changed)} onClick={()=>void act(pending.reason.kind==='wrap'?'wrap':'approve',{interrupt_id:pending.id,approve:true,role})}>Approve {pending.reason.kind}</button><button disabled={busy} onClick={()=>void act(pending.reason.kind==='wrap'?'wrap':'approve',{interrupt_id:pending.id,approve:false,role})}>Decline {pending.reason.kind}</button></div> : <p className="warning">Waiting for the 1st AD. Select that demo role to review and answer this request.</p>}
    </> : <p>No approval is currently waiting. {state.wrap_approved?'The 1st AD wrap decision is on record.':'A wrap decision requires current eligibility and a separate 1st AD approval.'}</p>}
    <div className="toolbar"><button disabled={busy || !state.counts} onClick={()=>void act('evaluate')}>Review wrap readiness</button>{state.eligible && !pending && !state.wrap_approved && role==='first_ad' && <button className="primary" disabled={busy} onClick={()=>void act('wrap',{role})}>Request wrap approval</button>}</div>
    {!state.counts && <p className="fine">Run a checkpoint first to assess readiness.</p>}
    {state.counts && <p className={state.eligible?'verified-text':'warning'}>{state.eligible?'The evidence gate reports eligible. Only the 1st AD can approve wrap.':`${state.causes.length} open cause(s) prevent wrap eligibility.`}</p>}
  </section><div className="section-heading"><h2>Assigned to {roles[role]}</h2><span>{mine.length} recorded exceptions</span></div>
    {mine.length ? mine.map(f=><DecisionForm key={`${f.finding_id}-${role}`} finding={f} scene={scene} state={state} role={role} busy={busy} act={act}/>) : <div className="panel empty">No finding is assigned to this role. Other roles may still have open work.</div>}
    <section className="panel"><h2>Waiting on other roles</h2>{others.length ? <ul className="action-list">{others.map(f=><li key={f.finding_id}><strong>{roles[f.required_role]}</strong><span>{f.next_action}</span><small>{f.requirement_id ? scene.locations[f.requirement_id] ?? f.requirement_id : 'Shot plan advisory'}</small></li>)}</ul> : <p>No other role has a recorded exception.</p>}</section>
  </>;
}
