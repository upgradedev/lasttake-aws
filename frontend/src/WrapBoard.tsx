import {count} from './projection';
import type {RunState,Scene} from './types';

// The count, typeset like a slate. This is the number the whole entry leads
// with: of the required beats, how many have evidence behind them, how many
// raise an exception with a named source, and how many have nobody's release on
// file. Before a checkpoint every tile says so rather than showing a zero,
// because a zero here would read as "nothing wrong".
//
// Eligibility and the wrap decision sit beside the numbers and stay distinct:
// the gate can be satisfied while no human has approved anything, and a judge
// should be able to see both states at once without reading a paragraph.

function tile(value:unknown,assessed:boolean) {
  return assessed?String(count(value) ?? 'Unknown'):'Not assessed';
}

export function WrapBoard({state,scene}:{state:RunState;scene:Scene}) {
  const c=state.counts;
  const assessed=Boolean(c);
  return <section className="wrap-board" data-testid="wrap-board" aria-label="Wrap board">
    <div className="wrap-tiles">
      <div className="tile"><span>Required beats</span><strong>{assessed?tile(c?.required_beats,true):String(scene.required_beats)}</strong></div>
      <div className="tile tile-ok"><span>Covered with evidence</span><strong>{tile(c?.covered_with_evidence,assessed)}</strong></div>
      <div className="tile tile-warn"><span>Raising exceptions</span><strong>{tile(c?.raising_exceptions,assessed)}</strong></div>
      <div className="tile tile-legal"><span>No release record</span><strong>{tile(c?.without_release_record,assessed)}</strong></div>
    </div>
    <dl className="wrap-verdicts">
      <div><dt>Evidence gate</dt><dd className={assessed?(state.eligible?'verified-text':'blocked-text'):''}>{!assessed?'Not assessed':state.eligible?'Eligible':'Blocked'}</dd></div>
      <div><dt>Human wrap decision</dt><dd className={state.wrap_approved?'verified-text':''}>{state.wrap_approved?'Recorded by the 1st AD':state.pending_approval?.reason.kind==='wrap'?'Waiting for the 1st AD':'Not approved'}</dd></div>
      <div><dt>Turnover</dt><dd>{state.turnover?'Saved':'Not published'}</dd></div>
    </dl>
  </section>;
}
