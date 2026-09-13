import {link,roles} from './model';
import {uniqueBy} from './projection';
import {turnoverIsCurrent} from './Turnover';
import type {Page,RunState,Scene} from './types';

export function wrapHeadline(state:RunState,requiresRefresh=false) {
  if(requiresRefresh)return 'Refresh before deciding';
  if(state.needs_checkpoint)return 'Evidence needs a fresh checkpoint';
  if(!state.counts)return 'Wrap has not been assessed';
  if(state.pending_approval?.reason.kind==='wrap' && state.pending_approval.evidence_changed)return 'Evidence changed: wrap request is out of date';
  if(!state.eligible)return 'Wrap blocked by the supplied evidence';
  if(!state.wrap_approved)return 'Eligible for a human wrap decision';
  return 'Human wrap approval recorded';
}

export function nextStep(state:RunState) {
  if(state.turnover)return {title:'Read the turnover before handing it to editorial',detail:'Download the saved manifest and copy its handoff summary. Check whether this record still matches the current evidence and approval.',page:'history' as const};
  if(state.pending_approval)return {title:`Review the saved ${state.pending_approval.reason.kind} request`,detail:state.pending_approval.evidence_changed?'The evidence changed. Review the current sources; a changed wrap request must be declined before a fresh request.':`Select ${roles[state.pending_approval.reason.required_role]} in Demo role, inspect the sources, then explicitly approve or decline. A pickup decision is separate from wrap.`,page:'scene' as const};
  if(state.needs_checkpoint || !state.counts)return {title:'Start with the wrap checkpoint',detail:'Use Run wrap checkpoint below. It compares the supplied script, takes, camera reports and releases and saves the exceptions for review.',page:'scene' as const};
  if(state.wrap_approved && state.eligible)return {title:'Prepare the editorial handoff',detail:'The server has saved the human wrap decision. Publish the approved turnover in Handoff, then inspect and download the record.',page:'history' as const};
  if(state.eligible)return {title:'Ask the 1st AD for a separate wrap decision',detail:'Select 1st AD in Demo role, request wrap approval, review the saved request and choose whether to approve. Eligibility alone does not approve wrap.',page:'scene' as const};
  return {title:'Resolve the evidence gaps and review the exceptions',detail:'Use Add take or release for missing records. Select each remaining finding and record a reasoned decision in its named role. Then review wrap readiness.',page:'scene' as const};
}

export function WorkflowNext({state,scene,requiresRefresh=false,detailed=false,currentPage}:{state:RunState;scene?:Scene;requiresRefresh?:boolean;detailed?:boolean;currentPage?:Page}) {
  const next=nextStep(state);
  // A card that says "Open review workspace" while you are on the workspace is
  // a second, competing call to action. When the next step lives on this page,
  // the control points at the pane that holds it, or steps aside for the
  // primary button already on screen.
  const samePage=currentPage!==undefined && (next.page===currentPage || (next.page==='scene' && currentPage==='actions'));
  const paneJump=(e:React.MouseEvent)=>{e.preventDefault();const pane=document.getElementById('decision-pane');pane?.focus({preventScroll:true});pane?.scrollIntoView({block:'start'});};
  const causes=uniqueBy(state.causes,c=>`${c.finding_id}:${c.requirement_id}:${c.reason}`);
  return <section className={'workflow-next'+(detailed?' decision-brief':' compact')} aria-label="Next step" data-testid="workflow-next">
    {detailed && <div className="decision-context"><p className="eyebrow">Before the set comes down</p><h2 data-testid="decision-headline">{wrapHeadline(state,requiresRefresh)}</h2>
      <p>{requiresRefresh?'The saved view may be out of date. Use Refresh saved state before any decision.':state.counts?state.headline:'Start the checkpoint to find missing coverage, conflicting reports and missing releases before asking the 1st AD to wrap.'}</p>
      {state.counts && !requiresRefresh && <p>{state.eligible?'The evidence gate permits a wrap request; it does not approve wrap or erase accepted exceptions.':'Resolve the named evidence gaps, then review readiness. A pickup approval alone never approves wrap.'}</p>}
      <dl className="decision-stages"><div><dt>1 · Evidence</dt><dd>{requiresRefresh?'Refresh required':state.needs_checkpoint?'Checkpoint required':state.counts?'Assessed records':'Not assessed'}</dd></div><div><dt>2 · Human wrap decision</dt><dd>{requiresRefresh?'Recheck saved decision':state.wrap_approved?'1st AD approval on record':'Not approved'}</dd></div><div><dt>3 · Editorial turnover</dt><dd>{state.turnover?requiresRefresh?'Saved record; currency unknown':turnoverIsCurrent(state)?'Saved for current evidence':'Historical; do not use for changed evidence':'Not published'}</dd></div></dl>
      {state.counts && !state.eligible && !requiresRefresh && <div className="decision-reasons"><h3>Why wrap is blocked</h3>{causes.length?<ul>{causes.slice(0,3).map(c=>{
        const finding=state.exceptions.find(f=>f.finding_id===c.finding_id);
        return <li key={`${c.finding_id}:${c.requirement_id}:${c.reason}`}><a href={link('scene',state.run_id,undefined,c.finding_id?{finding:c.finding_id}:{filter:'approval'})}>{scene?.locations[c.requirement_id] ?? c.requirement_id}</a><p>{finding?.observation ?? c.reason}</p>{finding && <p><strong>Blocks wrap:</strong> {c.reason}</p>}<p><strong>{roles[c.required_role]}:</strong> {finding?.next_action ?? 'Review this cause in the workspace.'}</p></li>;
      })}</ul>:<p>No blocking explanation was returned. Refresh saved state; do not infer eligibility from an empty list.</p>}{causes.length>3 && <a href={link('scene',state.run_id,undefined,{filter:'approval'})}>Review all {causes.length} blocking causes</a>}</div>}
    </div>}{!detailed && <ol className="stage-rail" aria-label="Stages">
      <li data-state={requiresRefresh?'unknown':state.counts?'done':'open'}><span>1</span>Evidence<small>{requiresRefresh?'refresh first':state.needs_checkpoint?'checkpoint required':state.counts?'assessed':'not assessed'}</small></li>
      <li data-state={requiresRefresh?'unknown':state.wrap_approved?'done':state.pending_approval?.reason.kind==='wrap'?'waiting':'open'}><span>2</span>Human decision<small>{requiresRefresh?'recheck':state.wrap_approved?'1st AD approved':state.pending_approval?.reason.kind==='wrap'?'waiting for the 1st AD':'not approved'}</small></li>
      <li data-state={state.turnover?(turnoverIsCurrent(state)?'done':'historical'):'open'}><span>3</span>Turnover<small>{state.turnover?(requiresRefresh?'currency unknown':turnoverIsCurrent(state)?'saved':'historical'):'not published'}</small></li>
    </ol>}<div className="decision-next">{detailed?<p className="eyebrow">Next step</p>:<p className="eyebrow" data-testid="decision-headline">{wrapHeadline(state,requiresRefresh)}</p>}<h2>{next.title}</h2><p>{requiresRefresh?'Refresh saved state above. Existing sources and downloads remain available for inspection.':state.turnover && !turnoverIsCurrent(state)?'Keep this historical handoff for reference. Start a new shoot-day run for a new turnover; the old record cannot approve changed evidence.':next.detail}</p></div>{samePage
      ? (next.page==='scene' && state.counts ? <a className="button" href="#decision-pane" onClick={paneJump}>Go to the decision</a> : null)
      : <a className="button" href={link(next.page,state.run_id,undefined,next.page==='scene' && (state.pending_approval || state.eligible)?{filter:'approval'}:undefined)}>{next.page==='history'?'Open turnover & receipts':'Open review workspace'}</a>}
  </section>;
}
