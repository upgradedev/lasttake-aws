import {useState} from 'react';
import {decisionFor,roles,words} from './model';
import {Evidence} from './Inspector';
import type {Document,Finding,Role,RunState,Scene} from './types';
type Act=(path:string,extra?:Document)=>Promise<boolean>;
export function DecisionForm({finding,scene,state,role,busy,act,index=0,compact=false}:{finding:Finding;scene:Scene;state:RunState;role:Role;busy:boolean;act:Act;index?:number;compact?:boolean}) {
  const [action,setAction]=useState('confirm');
  const current=decisionFor(finding,state.decisions);
  const allowed=scene.authority[finding.check_type];
  return <article className="panel decision-card" data-check={finding.check_type} data-review={current.decision && !current.stale?'recorded':'open'} style={{animationDelay:`${Math.min(index,4)*60}ms`}} aria-label={`${words(finding.check_type)} ${finding.requirement_id ?? 'advisory'}`}>
    {compact?<><p className="eyebrow">{words(finding.check_type)} decision</p><h3>{finding.requirement_id ?? 'Shot plan advisory'}</h3><p className="fine">{finding.finding_id}</p></>:<Evidence finding={finding} scene={scene}/>}
    {current.decision && <div className={current.stale?'warning':'decision-note'}>{current.stale ? 'Earlier decision no longer applies: the evidence has changed. Review it again.' : `Recorded: ${words(current.decision.action)} by ${current.decision.actor}. The original finding remains visible.`}</div>}
    {allowed.may_confirm.includes(role) ? <form onSubmit={async e=>{e.preventDefault();const form=e.currentTarget;const data=new FormData(form);if(await act('decide',{finding_id:finding.finding_id,finding_sha256:finding.record_sha256,role,action,actor:String(data.get('actor')),reason:String(data.get('reason'))}))form.reset();}}><fieldset disabled={busy}>
      <div className="form-grid"><label>Your name in this demo<input name="actor" required maxLength={100}/></label><label>Decision<select aria-label="Decision" value={action} onChange={e=>setAction(e.target.value)}><option value="confirm">Confirm the finding</option><option value="reject_false_positive">Reject as false positive</option>{allowed.may_accept.includes(role) && <option value="accept_exception">Accept the documented exception</option>}</select></label></div>
      <label>Reason for this exact evidence<textarea name="reason" required maxLength={2000}/></label>
      <button className="primary" type="submit">Record decision</button>
      {!allowed.may_accept.includes(role) && <p className="fine">This role cannot accept away a missing release. Supply the record or route the decision to production and counsel.</p>}
    </fieldset></form> : <p className="fine">Decision belongs to {roles[finding.required_role]}.</p>}
  </article>;
}
export function ApprovalConsole({state,role,busy,act}:{state:RunState;role:Role;busy:boolean;act:Act}) {
  const pending=state.pending_approval;
  return <><section className="panel approvals" aria-labelledby="approval-title" data-state={state.wrap_approved?'recorded':pending?'waiting':'review'}><div className="approval-heading"><div><p className="eyebrow">Human authority</p><h2 id="approval-title">Pickup & wrap approvals</h2></div><span className="authority-label">1st AD · final decision</span></div>
    <ol className="approval-stages" aria-label="Wrap decision stages"><li data-complete={Boolean(state.counts)}><span>01</span> Evidence {state.counts?'assessed':'not assessed'}</li><li data-complete={Boolean(state.counts)&&state.eligible}><span>02</span> Gate {!state.counts?'not assessed':state.eligible?'eligible':'not eligible'}</li><li data-complete={state.wrap_approved}><span>03</span> Wrap {state.wrap_approved?'recorded':'not approved'}</li></ol>
    {state.wrap_approved && <div className="approval-record" role="status"><span className="approval-check" aria-hidden="true"><svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="m5 12 4 4L19 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg></span><div><strong>Wrap decision saved by the server</strong><p>Human sign-off recorded. This is not a certificate of creative or legal clearance.</p></div></div>}
    {pending ? <><h3>{pending.reason.kind==='pickup'?`Pickup requested: ${pending.reason.slug ?? pending.reason.beat_id}`:'Wrap approval requested'}</h3><p>{pending.reason.justification ?? pending.reason.note}</p><p className="fine">The real Strands run is interrupted. This request is saved on the server.</p>
      {pending.evidence_changed && <p className="warning">Evidence has changed since this request. {pending.reason.kind==='wrap'?'Decline this request, review the new evidence, then request a fresh wrap approval.':'Review the current scene before answering.'}</p>}
      {pending.reason.kind==='wrap' && <div className="wrap-decision-scope" data-testid="wrap-decision-scope"><h3>Your exact wrap decision</h3><p>For {state.scene_id}, script {state.revision}: approving records the 1st AD's decision for the evidence in this saved request. It enables publication of the editorial turnover; it does not publish it.</p><p>Declining leaves wrap unapproved. Accepted exceptions remain in the handoff for editorial to review.</p><p className="fine">The request ID below and package fingerprint identify the reviewed request and evidence. If evidence changes, decline this request and request a fresh decision.</p></div>}
      <p className="fine">Request {pending.id}</p>
      {role==='first_ad' && pending.reason.required_role==='first_ad' ? <div className="toolbar"><button className="primary" disabled={busy || !pending.id || (pending.reason.kind==='wrap' && (pending.evidence_changed || !state.counts || !state.eligible))} onClick={()=>void act(pending.reason.kind==='wrap'?'wrap':'approve',{interrupt_id:pending.id,approve:true,role})}>Approve {pending.reason.kind}</button><button disabled={busy || !pending.id} onClick={()=>void act(pending.reason.kind==='wrap'?'wrap':'approve',{interrupt_id:pending.id,approve:false,role})}>Decline {pending.reason.kind}</button></div> : <p className="warning">Waiting for the 1st AD. Select that demo role to review and answer this request.</p>}
    </> : <p>No approval is currently waiting. {state.wrap_approved?'The 1st AD wrap decision is on record.':'A wrap decision requires current eligibility and a separate 1st AD approval.'}</p>}
    <div className="toolbar"><button disabled={busy || !state.counts} onClick={()=>void act('evaluate')}>Review wrap readiness</button>{state.counts && state.eligible && !pending && !state.wrap_approved && role==='first_ad' && <button className="primary" disabled={busy} onClick={()=>void act('wrap',{role})}>Request wrap approval</button>}</div>
    {!state.counts && <p className="fine">Run a checkpoint first to assess readiness.</p>}
    {state.counts && <p className={state.eligible?'verified-text':'warning'}>{state.eligible?'The evidence gate reports eligible. Only the 1st AD can approve wrap.':`${state.causes.length} open cause(s) prevent wrap eligibility.`}</p>}
    <details className="approval-proof"><summary>Current package fingerprint · SHA-256</summary><code>{state.package_revision_digest}</code><p>This identifies the current package revision reported by the server. It is not a Merkle proof or an independent browser verification.</p></details>
  </section></>;
}
export function Actions({scene,state,role,busy,act}:{scene:Scene;state:RunState;role:Role;busy:boolean;act:Act}) {
  const mine=state.exceptions.filter(f=>scene.authority[f.check_type].may_confirm.includes(role));
  const others=state.exceptions.filter(f=>!scene.authority[f.check_type].may_confirm.includes(role));
  return <><ApprovalConsole state={state} role={role} busy={busy} act={act}/><div className="section-heading"><h2>Assigned to {roles[role]}</h2><span>{mine.length} recorded exceptions</span></div>
    {mine.length ? mine.map((f,index)=><DecisionForm key={`${f.finding_id}-${role}`} finding={f} scene={scene} state={state} role={role} busy={busy} act={act} index={index}/>) : <div className="panel empty">No finding is assigned to this role. Other roles may still have open work.</div>}
    <section className="panel"><h2>Waiting on other roles</h2>{others.length ? <ul className="action-list">{others.map(f=><li key={f.finding_id}><strong>{roles[f.required_role]}</strong><span>{f.next_action}</span><small>{f.requirement_id ? scene.locations[f.requirement_id] ?? f.requirement_id : 'Shot plan advisory'}</small></li>)}</ul> : <p>No other role has a recorded exception.</p>}</section>
  </>;
}
