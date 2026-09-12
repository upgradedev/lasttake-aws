import {useState} from 'react';
import {saveJson,saveText} from './api';
import {roles} from './model';
import type {Document,Role,RunState} from './types';

const value=(v:unknown)=>typeof v==='string'?v:'Unknown';
const rows=(v:unknown):Document[]=>Array.isArray(v)?v.filter((item):item is Document=>!!item && typeof item==='object' && !Array.isArray(item)):[];
const roleLabel=(v:unknown)=>roles[value(v) as Role] ?? value(v);
export function turnoverIsCurrent(state:RunState) {
  return !!state.turnover && state.turnover_current!==false && state.turnover.package_revision_digest===state.package_revision_digest && state.wrap_approved && state.eligible;
}
export function turnoverSummary(state:RunState) {
  const manifest=state.turnover!;
  const approval=rows([manifest.wrap_approved_by])[0];
  const findings=rows(manifest.outstanding_and_accepted_exceptions);
  return [
    'LASTTAKE | EDITORIAL HANDOFF',
    turnoverIsCurrent(state)?'Current saved turnover for the observed run.':'HISTORICAL: evidence or approval is no longer current. Do not use this record to approve the changed package.',
    `Run: ${value(manifest.run_id)} | Scene: ${value(manifest.scene_id)} | Script: ${value(manifest.script_revision)}`,
    `Generated: ${value(manifest.generated_at)} | Policy: ${value(manifest.policy_version)} | Schema: ${value(manifest.schema)}`,
    `Recorded wrap decision: ${value(approval?.actor)} (${value(approval?.role)})`,
    `Package SHA-256: ${value(manifest.package_revision_digest)}`,
    `Saved manifest SHA-256: ${value(manifest.record_sha256)}`,
    'Summary derived from the saved manifest by this browser. The summary is not separately sealed or independently verified.',
    '', 'RETAINED EXCEPTIONS (accepted exceptions remain visible)',
    ...findings.map(f=>`${value(f.requirement_id)} | ${value(f.required_role)} | ${value(f.observation)} | Next: ${value(f.recommended_action)}`),
    '', 'BEAT TO TAKE MAP',
    ...rows(manifest.beat_to_take_map).map(b=>`${value(b.beat_id)} ${value(b.slug)}: ${rows(b.takes).map(t=>`${value(t.take_id)} / slate ${value(t.slate)} / media ${value(t.media_id)} / ${value(t.timecode_in)}`).join('; ') || 'No supplied take'}`),
    '', 'SOURCE DIGESTS',
    ...rows(manifest.source_manifest).map(s=>`${value(s.artifact_id)} | ${value(s.sha256)}`),
    '', value(manifest.synthetic_corpus_notice),value(manifest.rights_disclaimer),
    'Scripted demo roles are not authenticated staff. Storage or event-bus acceptance does not establish editorial receipt or downstream completion.',
    'No footage/audio analysis, creative clearance or legal clearance. A hash identifies bytes, not truth.',
  ].join('\n');
}

export function CopyText({text,label}:{text:string;label:string}) {
  const [notice,setNotice]=useState('');
  return <><button onClick={async()=>{try {await navigator.clipboard.writeText(text);setNotice('Copied. Review the text and its limits before sharing.');}catch{setNotice('Clipboard unavailable. Select and copy the text below, or download it.');}}}>{label}</button>{notice && <div role="status"><p>{notice}</p><label>Selectable copy text<textarea readOnly value={text} rows={6} onFocus={e=>e.currentTarget.select()}/></label></div>}</>;
}

export function Turnover({state,busy,publish}:{state:RunState;busy:boolean;publish:()=>void}) {
  const [query,setQuery]=useState('');
  const current=turnoverIsCurrent(state);
  const summary=state.turnover?turnoverSummary(state):'';
  const manifest=state.turnover;
  const approval=rows([manifest?.wrap_approved_by])[0];
  const exceptions=rows(manifest?.outstanding_and_accepted_exceptions);
  const takes=rows(manifest?.beat_to_take_map);
  const matching=takes.filter(b=>[b.beat_id,b.slug,...rows(b.takes).flatMap(t=>[t.take_id,t.slate,t.media_id])].some(v=>typeof v==='string' && v.toLowerCase().includes(query.trim().toLowerCase())));
  return <section className="panel handoff-provenance" aria-label="Turnover for this run"><p className="eyebrow">Production to post</p><h2>Turnover for this run</h2>
    {state.turnover?<><p className="verified-text">A sealed turnover is saved for this run.</p>{!current && <p className="warning">Evidence has changed since this turnover, or its approval/review is no longer current. This is the historical record; it does not approve the changed package. Start a new run for a new turnover.</p>}
      <p>For the assistant editor: the manifest contains the beat-to-take map, technical report, source digests, human decisions and retained exceptions. Review these before accepting the handoff.</p>
      <dl className="metadata" data-testid="editorial-decision"><dt>Record status</dt><dd>{current?'Current for observed evidence and approval':'Historical record'}</dd><dt>Scene / script</dt><dd>{value(state.turnover.scene_id)} / {value(state.turnover.script_revision)}</dd><dt>Recorded wrap decision</dt><dd>{value(approval?.actor)} · {roleLabel(approval?.role)}</dd><dt>Turnover saved</dt><dd>{value(state.turnover.generated_at)}</dd></dl>
      <section className="editorial-exceptions" aria-label="Retained exceptions for editorial"><h3>What editorial still needs to know</h3><p>Accepted exceptions stay in the handoff. Read the observation and next action before accepting the turnover.</p>{exceptions.length?<ul className="action-list">{exceptions.map((f,i)=><li key={value(f.finding_id)+i}><strong>{value(f.requirement_id)} · {roleLabel(f.required_role)}</strong><p>{value(f.observation)}</p><p><strong>Next:</strong> {value(f.recommended_action)}</p></li>)}</ul>:<p>No exception entries were supplied in this manifest. This is not creative or legal clearance.</p>}</section>
      <section aria-label="Editorial take map"><h3>Find the take for a script beat</h3><label>Find beat or take in turnover<input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Beat, description, slate or media ID"/></label><p className="fine" role="status">{matching.length} of {takes.length} beat entries match. {matching.length>3?'Showing the first 3; narrow your search or download the complete handoff.':'All matching entries shown.'}</p>{matching.length?<div className="table-scroll" tabIndex={0} aria-label="Saved turnover take map"><table><caption>Saved beat-to-take map</caption><thead><tr><th>Script beat</th><th>Supplied take / media</th></tr></thead><tbody>{matching.slice(0,3).map((b,i)=><tr key={value(b.beat_id)+i}><th>{value(b.beat_id)} · {value(b.slug)}</th><td>{rows(b.takes).length?rows(b.takes).map((t,j)=><p key={value(t.take_id)+j}>{value(t.take_id)} · slate {value(t.slate)}<br/>{value(t.media_id)} · {value(t.timecode_in)}</p>):'No supplied take. Check the retained exceptions.'}</td></tr>)}</tbody></table></div>:<p className="empty">{takes.length?'No saved beat or take matches this search.':'No beat-to-take map was supplied. Inspect the manifest before handoff.'}</p>}{query && <button onClick={()=>setQuery('')}>Clear turnover search</button>}</section>
      <p className="fine">Hashes identify saved bytes, not truth or independent verification. Download preserves the server manifest; the text summary is derived in this browser. Storage is not delivery to editorial.</p>
      <div className="toolbar"><button className="primary" onClick={()=>saveJson(`${state.run_id}-turnover.json`,state.turnover)}>Download turnover</button><button onClick={()=>saveText(`${state.run_id}-handoff.txt`,summary)}>Download handoff summary</button><CopyText key={summary} text={summary} label="Copy handoff summary"/></div>
      <details><summary>Read editorial handoff summary</summary><pre>{summary}</pre></details><details><summary>Source fingerprints</summary><dl className="metadata"><dt>Package SHA-256</dt><dd>{value(state.turnover.package_revision_digest)}</dd><dt>Saved manifest SHA-256</dt><dd>{value(state.turnover.record_sha256)}</dd></dl></details><details><summary>Inspect saved manifest</summary><pre>{JSON.stringify(state.turnover,null,2)}</pre></details>
    </>:<><p>No turnover has been published for this run.</p><button disabled={busy || !state.wrap_approved || !state.eligible} onClick={publish}>Publish approved turnover</button>{(!state.wrap_approved || !state.eligible) && <p className="fine">Publishing requires current eligibility and the 1st AD's wrap approval.</p>}</>}
  </section>;
}
