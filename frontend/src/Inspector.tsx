import {decisionFor,roles,words} from './model';
import {uniqueBy} from './projection';
import type {Decision,Finding,Scene,Take} from './types';

export function Evidence({finding,scene,decisions}:{finding:Finding;scene:Scene;decisions?:Decision[]}) {
  // A decision by the named role about this exact reading is shown in words.
  // It replaces the check's next action ("reconcile before it is cleared") only
  // when policy.py _resolution treats it as closing the finding: a rejected
  // false positive, or an exception accepted by a role allowed to accept one.
  // A confirmation leaves the finding blocking wrap, so its next action stays.
  // A decision about changed evidence is not shown and leaves the action open.
  const current=decisionFor(finding,decisions ?? []);
  const outcome=current.decision && !current.stale?current.decision:undefined;
  const resolved=Boolean(outcome && (outcome.action==='reject_false_positive' || (outcome.action==='accept_exception' && scene.authority[finding.check_type]?.may_accept.includes(outcome.role))));
  return <div className="evidence" data-check={finding.check_type}>
    <p className="eyebrow">{words(finding.check_type)} · {words(finding.truth_state)}</p>
    <h3>{finding.requirement_id ? scene.locations[finding.requirement_id] ?? finding.requirement_id : 'Shot plan advisory'}</h3>
    <p>{finding.observation}</p>
    {finding.inference && <div className="inference"><span className="eyebrow">Bounded interpretation</span><p>{finding.inference}</p></div>}
    {outcome && <p><strong>Decision on record:</strong> {words(outcome.action)} by {outcome.actor} ({roles[outcome.role]}). The finding stays on the turnover.</p>}
    {!resolved && <p><strong>Next action:</strong> {finding.next_action}</p>}<p className="fine">Responsible: {roles[finding.required_role]}</p>
    <details><summary>Source records & digests</summary>
      {finding.sources.length?uniqueBy(finding.sources,s=>s.artifact_id+':'+s.sha256).map(s=><p key={s.artifact_id+':'+s.sha256}><strong>{s.artifact_id}</strong><code>{s.sha256}</code></p>):<p>No source artifact supplied for this finding.</p>}
      <h4>Source locations</h4>{finding.locators.length?<dl className="metadata">{finding.locators.map((l,i)=><div key={i}><dt>{words(l.kind)}</dt><dd>{l.value}</dd></div>)}</dl>:<p>No source locator supplied. Do not infer a page or take.</p>}
      <p>Finding {finding.finding_id}<code>{finding.record_sha256}</code></p>
    </details>
  </div>;
}
export function Inspector({take,open=false}:{take:Take;open?:boolean}) {
  return <details className="take" open={open || undefined}><summary><span>Slate {take.slate}</span><span className="fine">{take.preferred?'Preferred':'Recorded'} · {take.lens_mm} mm</span></summary>
    <p>{take.note || 'No supervisor note supplied.'}</p>
    <div className="table-scroll" tabIndex={0} aria-label={'Report comparison for '+take.take_id}><table><caption>Take sidecar and camera report</caption><thead><tr><th>Field</th><th>Sidecar</th><th>Camera report</th></tr></thead><tbody>{(['media_id','camera_roll','lens_mm'] as const).map(key=><tr key={key} className={take.camera_report?.[key]!==take[key]?'mismatch':''}><th>{words(key)}</th><td>{take[key]}</td><td>{take.camera_report?.[key] ?? 'Missing'}</td></tr>)}</tbody></table></div>
    <dl className="metadata"><dt>Sound roll</dt><dd>{take.sound_roll}</dd><dt>Timecode</dt><dd>{take.timecode_in} to {take.timecode_out}</dd><dt>Take</dt><dd>{take.take_id}</dd><dt>Captured</dt><dd>{take.captured_at}</dd><dt>Usable flag</dt><dd>{take.usable?'Yes, in the supplied record':'No'}</dd><dt>Visible people</dt><dd>{take.visible_people.join(', ') || 'None declared'}</dd><dt>Visible assets</dt><dd>{take.visible_assets.join(', ') || 'None declared'}</dd></dl>
    <p className="fine">Sound checks reconcile supplied metadata only. No audio-drop or waveform analysis is performed.</p>
  </details>;
}
