import {link,roles} from './model';
import type {RunState} from './types';

export function nextStep(state:RunState) {
  if(state.turnover)return {title:'Read the turnover before handing it to editorial',detail:'Download the saved manifest and copy its handoff summary. Check whether this record still matches the current evidence and approval.',page:'history' as const};
  if(state.pending_approval)return {title:`Review the saved ${state.pending_approval.reason.kind} request`,detail:state.pending_approval.evidence_changed?'The evidence changed. Review the current sources; a changed wrap request must be declined before a fresh request.':`Select ${roles[state.pending_approval.reason.required_role]} in Demo role, inspect the sources, then explicitly approve or decline. A pickup decision is separate from wrap.`,page:'scene' as const};
  if(state.needs_checkpoint || !state.counts)return {title:'Start with the wrap checkpoint',detail:'Use Run wrap checkpoint below. It compares the supplied script, takes, camera reports and releases and saves the exceptions for review.',page:'scene' as const};
  if(state.wrap_approved && state.eligible)return {title:'Prepare the editorial handoff',detail:'The server has saved the human wrap decision. Publish the approved turnover in History, then inspect and download the record.',page:'history' as const};
  if(state.eligible)return {title:'Ask the 1st AD for a separate wrap decision',detail:'Select 1st AD in Demo role, request wrap approval, review the saved request and choose whether to approve. Eligibility alone does not approve wrap.',page:'scene' as const};
  return {title:'Resolve the evidence gaps and review the exceptions',detail:'Use Add take or release for missing records. Select each remaining finding and record a reasoned decision in its named role. Then review wrap readiness.',page:'scene' as const};
}

export function WorkflowNext({state}:{state:RunState}) {
  const next=nextStep(state);
  return <section className="workflow-next" aria-label="Next step" data-testid="workflow-next"><div><p className="eyebrow">Next step</p><h2>{next.title}</h2><p>{next.detail}</p></div><a className="button" href={link(next.page,state.run_id,undefined,next.page==='scene' && (state.pending_approval || state.eligible)?{filter:'approval'}:undefined)}>{next.page==='history'?'Open turnover & receipts':'Open review workspace'}</a></section>;
}
