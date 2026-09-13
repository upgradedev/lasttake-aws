import { link, roles, words } from './model';
import { metrics, recentEvents, uniqueBy } from './projection';
import { ProductionCharts } from './ProductionCharts';
import type { EventRow, RunState, Scene, Session } from './types';

export function Dashboard({
  scene,
  state,
  events,
  session,
  busy,
  checkpoint
}: {
  scene: Scene;
  state: RunState;
  events: EventRow[];
  session: Session | null;
  busy: boolean;
  checkpoint: () => void;
}) {
  const recent = recentEvents(events).slice(0, 5);
  const run = session?.runs.find(r => r.run_id === state.run_id);
  const causes = uniqueBy(state.causes, c => `${c.finding_id}:${c.requirement_id}:${c.reason}`);

  return (
    <>
      <section className="summary panel">
        <div>
          <p className="eyebrow">Current saved run</p>
          <h2>{scene.scene_heading}</h2>
          <p>{scene.scene_id} · {scene.revision}</p>
          <p className="fine">
            Run {state.run_id}<br />
            {run ? <>Created <time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString()}</time></> : 'Run date unavailable'}
          </p>
        </div>
        <div className="summary-action">
          <span className="badge">{state.counts ? 'Checkpoint saved' : 'Not assessed'}</span>
          <p>
            {state.counts
              ? 'Review the current evidence and recorded decisions before requesting wrap.'
              : 'These records have not been assessed yet. Start the checkpoint to reconcile the evidence.'}
          </p>
          {state.counts ? (
            <a className="button primary" href={link('scene', state.run_id)}>Continue wrap review</a>
          ) : (
            <button className="primary" disabled={busy} onClick={checkpoint}>Run wrap checkpoint</button>
          )}
        </div>
      </section>

      <p className="scope-note">
        Current scene and selected run only. Saved runs repeat the same fictional corpus; they are not a production portfolio. Dates shown in your browser’s local time.
      </p>

      <ProductionCharts scene={scene} state={state} />

      <section className="metrics" aria-label="Current run metrics">
        {metrics(scene, state).map(m => (
          <a className="metric" key={m.id} data-testid={`metric-${m.id}`} href={m.href}>
            <span>{m.label}</span>
            <strong>{m.value}</strong>
            <small>{m.detail}</small>
            <span className="metric-drill">Inspect records <span aria-hidden="true">↗</span></span>
          </a>
        ))}
      </section>

      <div className="dashboard-grid">
        <section className="panel" aria-labelledby="priority-title">
          <div className="section-heading">
            <h2 id="priority-title">Priority work</h2>
            <a href={link('scene', state.run_id)}>Open workspace</a>
          </div>
          {state.pending_approval && (
            <a className="priority-request" href={link('scene', state.run_id, undefined, { filter: 'approval' })}>
              <strong>{state.pending_approval.reason.kind === 'pickup' ? 'Pickup request waiting' : 'Wrap request waiting'}</strong>
              <span>{roles[state.pending_approval.reason.required_role]} · {state.pending_approval.evidence_changed ? 'Evidence changed; review again' : 'Saved interrupt ready to resume'}</span>
            </a>
          )}
          {!state.counts ? (
            <p className="empty">Not assessed. A checkpoint establishes the current exceptions and their owners.</p>
          ) : causes.length ? (
            <ul className="action-list">
              {causes.slice(0, 6).map(c => (
                <li key={`${c.finding_id}:${c.requirement_id}:${c.reason}`}>
                  <a href={link('scene', state.run_id, undefined, c.finding_id ? { finding: c.finding_id } : { filter: 'approval' })}>
                    <strong>{roles[c.required_role]}</strong>
                    <p>{scene.locations[c.requirement_id] ?? c.requirement_id}</p>
                    <span>{c.reason}</span>
                  </a>
                </li>
              ))}
            </ul>
          ) : state.eligible ? (
            <p className="empty">No current eligibility blockers. Review the separate human wrap decision before turnover.</p>
          ) : (
            <p className="warning">The gate is not satisfied and returned no causes. Refresh saved state; do not infer eligibility from an empty list.</p>
          )}
          {causes.length > 6 && (
            <a href={link('scene', state.run_id, undefined, { filter: 'approval' })}>Review all {causes.length} eligibility causes</a>
          )}
        </section>

        <section className="panel" aria-labelledby="recent-title">
          <div className="section-heading">
            <h2 id="recent-title">Recent activity</h2>
            <a href={link('history', state.run_id)}>View history</a>
          </div>
          {recent.length ? (
            <ol className="timeline">
              {recent.map(e => (
                <li key={e.event_id}>
                  <strong>{words(e.event_type.replaceAll('.', ' '))}</strong>
                  <time dateTime={e.occurred_at}>{new Date(e.occurred_at).toLocaleString()}</time>
                  <code>{e.event_id}</code>
                </li>
              ))}
            </ol>
          ) : (
            <p className="empty">No events recorded for this run yet. Start a checkpoint or add evidence.</p>
          )}
        </section>
      </div>

      <details className="panel">
        <summary>Advanced: observed session outcomes</summary>
        <h2>Observed session outcomes</h2>
        <p>
          {session?.runs.length ?? 0} saved runs on the loaded history page; {session?.runs.filter(r => r.checked).length ?? 0} with findings; {session?.runs.filter(r => r.wrap_approved).length ?? 0} currently wrap-approved; {session?.runs.filter(r => r.turnover_published).length ?? 0} with a stored turnover. These are page counts, not session totals. Open History to load older runs.
        </p>
        <p>
          Selected run: {state.decisions.length} recorded decisions, including {state.decisions.length - new Set(state.decisions.map(d => d.finding_id)).size} later decisions on previously reviewed findings. Storage is not downstream delivery.
        </p>
        <p>Human-active time: unknown. Measured time or financial benefit: unknown.</p>
      </details>
    </>
  );
}
