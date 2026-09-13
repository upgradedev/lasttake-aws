import {useState} from 'react';
import {count} from './projection';
import type {RunState,Scene} from './types';

// The beat matrix: every required beat as one cell, coloured only by what the
// checkpoint actually said about it. Before a checkpoint every cell is grey and
// says "not assessed", because a take on file is not coverage; whether a take
// covers a beat is exactly the question the checkpoint exists to answer.
//
// The earlier version of this file carried a hard-coded ten-beat scene, a fake
// event stream with invented event types, a "Simulate Live Ingest Cycle" button
// and a readiness gauge over made-up numbers. All of that is gone. This renders
// from the run the API returned and from nothing else.

const STATUS_LABEL:Record<string,string>={covered_with_evidence:'covered',no_viable_coverage:'no coverage',continuity_conflict:'continuity conflict',media_identity_exception:'metadata exception',no_release_record:'no release record',not_assessed:'not assessed'};

export function ProductionCharts({scene,state}:{scene:Scene;state:RunState}) {
  const [selected,setSelected]=useState<string|null>(null);
  const assessed=Boolean(state.counts);
  const outcomes=new Map(assessed?state.beats.map(b=>[b.beat_id,b]):[]);
  const required=scene.beats.filter(b=>b.required);
  const covered=count(state.counts?.covered_with_evidence);
  const chosen=selected?scene.beats.find(b=>b.beat_id===selected):undefined;
  const chosenOutcome=chosen?outcomes.get(chosen.beat_id):undefined;
  return <section className="panel beat-matrix" aria-label="Beat coverage matrix">
    <div className="section-heading"><div><p className="eyebrow">Required beats, one cell each</p><h2>{assessed?`${covered ?? 'Unknown'} of ${required.length} required beats have evidence behind them`:`${required.length} required beats, not assessed yet`}</h2></div><span className="fine">{assessed?'Colour is the checkpoint\'s finding for the beat, nothing else.':'Run the wrap checkpoint to assess them. A take on file is not coverage.'}</span></div>
    <div className="matrix-grid">
      {required.map(b=>{
        const o=outcomes.get(b.beat_id);
        const status=assessed?(o?.status ?? 'not_assessed'):'not_assessed';
        return <button key={b.beat_id} type="button" className={'matrix-cell'+(selected===b.beat_id?' selected':'')} data-status={status} aria-pressed={selected===b.beat_id} onClick={()=>setSelected(selected===b.beat_id?null:b.beat_id)} title={`${b.beat_id} · ${b.slug}`}>
          <span className="matrix-id">{b.beat_id}</span>
          <span className="matrix-slug">{b.slug}</span>
          <span className="matrix-status">{STATUS_LABEL[status] ?? status.replaceAll('_',' ')}</span>
        </button>;
      })}
    </div>
    {chosen && <div className="matrix-detail" role="status"><strong>{chosen.beat_id} · page {chosen.page}, line {chosen.line}</strong><p>{chosen.description}</p><p className="fine">{chosen.takes.length?`${chosen.takes.length} supplied take${chosen.takes.length===1?'':'s'}: ${chosen.takes.map(t=>'slate '+t.slate).join(', ')}.`:'No take supplied for this beat.'} {assessed?`Checkpoint: ${STATUS_LABEL[chosenOutcome?.status ?? 'not_assessed'] ?? chosenOutcome?.status}${chosenOutcome?.basis?`, basis ${chosenOutcome.basis.replaceAll('_',' ')}`:''}.`:'Not assessed.'}</p></div>}
  </section>;
}
