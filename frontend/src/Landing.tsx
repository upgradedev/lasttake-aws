import { useEffect, useState } from 'react';
import { link } from './model';
import type { Page, SavedRun, ScenePreview, Session } from './types';

function runStatus(run: SavedRun) {
  return run.turnover_published
    ? 'Turnover saved'
    : run.wrap_approved
    ? 'Wrap approved, turnover not published'
    : run.checked
    ? 'Checkpoint saved, decisions open'
    : 'Created, not yet checked';
}

function validPreview(value: unknown): value is ScenePreview {
  if (!value || typeof value !== 'object') return false;
  const p = value as Record<string, unknown>;
  return (
    p.schema === 'lasttake/scene-preview/v1' &&
    Number.isInteger(p.required_beats) &&
    Number.isInteger(p.supplied_takes) &&
    Array.isArray(p.opening_beats) &&
    typeof p.scene_heading === 'string' &&
    typeof p.synthetic_notice === 'string'
  );
}

export function useScenePreview() {
  const [preview, setPreview] = useState<ScenePreview | null>(null);
  useEffect(() => {
    let active = true;
    fetch('/scene-preview.json', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (active && validPreview(data)) setPreview(data);
      })
      .catch(() => {
        /* the landing reads without it */
      });
    return () => {
      active = false;
    };
  }, []);
  return preview;
}

export function Landing({
  session,
  busy,
  page,
  start,
  onNavigate
}: {
  session: Session | null;
  busy: boolean;
  page: Page;
  start: () => void;
  onNavigate?: (page: Page) => void;
}) {
  const preview = useScenePreview();
  const saved = session?.runs ?? [];
  const newest = saved[0];
  const returning = Boolean(newest);

  const handleNav = (targetPage: Page) => (e: React.MouseEvent) => {
    if (onNavigate) {
      e.preventDefault();
      onNavigate(targetPage);
    }
  };

  return (
    <section className="landing" aria-label="Start a shoot-day review">
      <div
        className="landing-hero"
        style={{
          background: 'radial-gradient(ellipse at top right, rgba(14, 165, 233, 0.15), transparent 70%), var(--raised, #131b2e)',
          border: '1px solid rgba(56, 189, 248, 0.25)',
          borderRadius: '16px',
          padding: '36px',
          boxShadow: '0 20px 40px -15px rgba(0, 0, 0, 0.5)'
        }}
      >
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 14px', background: 'rgba(20, 184, 166, 0.15)', border: '1px solid #0d9488', borderRadius: '999px', marginBottom: '16px' }}>
          <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#14b8a6', boxShadow: '0 0 10px #14b8a6' }} />
          <span style={{ fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.08em', color: '#5eead4', textTransform: 'uppercase' }}>
            LIVE FILM PRODUCTION COCKPIT · ON-SET ASSURANCE
          </span>
        </div>

        <p className="eyebrow" style={{ color: '#94a3b8' }}>Shoot day · The Last Ferry, a fictional production</p>
        <h1 id="page-title" tabIndex={-1} style={{ fontSize: '2.5rem', fontWeight: 800, letterSpacing: '-0.02em', margin: '8px 0 16px', color: '#f8fafc' }}>
          Know what still blocks wrap.
        </h1>
        <p className="landing-lede" style={{ fontSize: '1.15rem', color: '#cbd5e1', lineHeight: 1.6, maxWidth: '780px' }}>
          For the script supervisor and 1st AD: before the set comes down, reconcile the script, the takes and the releases, record the human wrap decision, and hand editorial a traceable turnover.
        </p>
        <p className="landing-result" style={{ fontSize: '0.95rem', color: '#94a3b8', maxWidth: '780px' }}>
          <strong style={{ color: '#f1f5f9' }}>Your result:</strong> a saved editorial turnover with the take map, the human decisions and any accepted exceptions still visible. Nothing is approved for you; absent evidence is a finding, never a pass.
        </p>

        <div className="landing-actions" style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', marginTop: '24px' }}>
          {returning && (
            <a
              className="button primary"
              href={link(page === 'actions' ? 'scene' : page, newest.run_id)}
              onClick={handleNav(page === 'actions' ? 'scene' : page)}
              style={{ padding: '12px 24px', fontSize: '0.95rem', fontWeight: 600 }}
            >
              Continue my saved shoot day
            </a>
          )}
          <button
            className={returning ? '' : 'primary'}
            disabled={busy}
            onClick={start}
            style={{ padding: '12px 24px', fontSize: '0.95rem', fontWeight: 600 }}
          >
            Start this fictional shoot day
          </button>
          <button
            disabled={busy}
            onClick={start}
            style={{ padding: '12px 20px', fontSize: '0.95rem' }}
          >
            New shoot-day run
          </button>
          <a className="button" href={link('journeys', newest?.run_id)} onClick={handleNav('journeys')}>
            4 Production Journeys →
          </a>
          <a className="button" href={link('architecture', newest?.run_id)} onClick={handleNav('architecture')}>
            System Architecture →
          </a>
          <a className="button" href={link('roi', newest?.run_id)} onClick={handleNav('roi')}>
            Production ROI →
          </a>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '16px',
            marginTop: '28px',
            padding: '18px 24px',
            background: 'rgba(9, 13, 22, 0.75)',
            borderRadius: '12px',
            border: '1px solid rgba(255, 255, 255, 0.08)'
          }}
        >
          <div>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>PREVENTED PICKUP COST</span>
            <strong style={{ display: 'block', color: 'var(--teal, #14b8a6)', fontSize: '1.35rem', fontWeight: 800, marginTop: '2px' }}>$50,000 – $250,000</strong>
          </div>
          <div>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>TIME TO VERIFY WRAP</span>
            <strong style={{ display: 'block', color: 'var(--amber, #f59e0b)', fontSize: '1.35rem', fontWeight: 800, marginTop: '2px' }}>&lt; 5 Seconds</strong>
          </div>
          <div>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>AUDIT INTEGRITY</span>
            <strong style={{ display: 'block', color: '#38bdf8', fontSize: '1.35rem', fontWeight: 800, marginTop: '2px' }}>Cryptographic S3 Seal</strong>
          </div>
        </div>

        {returning && (
          <p className="landing-saved" style={{ marginTop: '18px', color: '#94a3b8', fontSize: '0.85rem' }}>
            Saved: <strong>{runStatus(newest)}</strong> · created <time dateTime={newest.created_at}>{new Date(newest.created_at).toLocaleString()}</time>
            {saved.length > 1 && (
              <> · <a href={link('history', newest.run_id)} onClick={handleNav('history')}>all {saved.length} saved runs on this page</a></>
            )}
            . Continuing does not change or delete anything; a fresh shoot day keeps the old one.
          </p>
        )}
        {!returning && (
          <p className="landing-saved" style={{ marginTop: '18px', color: '#94a3b8', fontSize: '0.85rem' }}>
            Nothing to upload and no account: the fictional records are already supplied.
          </p>
        )}
      </div>

      <div className="landing-grid" style={{ marginTop: '32px' }}>
        <article className="panel landing-scene" aria-label="The scene you will check">
          <p className="eyebrow">The scene you will check</p>
          {preview ? (
            <>
              <h2><span className="slate-index">{preview.scene_id}</span> {preview.scene_heading}</h2>
              <dl className="landing-facts">
                <div><dt>Required beats</dt><dd>{preview.required_beats}</dd></div>
                <div><dt>Supplied takes</dt><dd>{preview.supplied_takes}</dd></div>
                <div><dt>Script revision</dt><dd>{preview.revision}</dd></div>
              </dl>
              <ol className="landing-script" aria-label="Opening beats of the lined script">
                {preview.opening_beats.map(b => (
                  <li key={b.beat_id}>
                    <span className="page-line">{b.page}:{b.line}</span>
                    <span>{b.slug}</span>
                  </li>
                ))}
                <li className="landing-more">
                  <span className="page-line">…</span>
                  <span>{Math.max(0, preview.required_beats - preview.opening_beats.length)} more required beats, {preview.optional_beats} optional inserts</span>
                </li>
              </ol>
              <p className="fine">Whether a beat is covered is only ever said by the checkpoint. These are the supplied records, not a result.</p>
            </>
          ) : (
            <>
              <h2>One fictional scene, its takes and its releases.</h2>
              <p>The checkpoint compares the script with the captured takes, the camera and sound reports and the rights ledger, and says which required beats still have no evidence behind them.</p>
            </>
          )}
        </article>

        <article className="panel landing-stages" aria-label="What happens">
          <p className="eyebrow">What happens, in three stages</p>
          <ol className="stage-list">
            <li><strong>Evidence.</strong> A wrap checkpoint runs four bounded checks over the supplied records and shows every exception with its source. Absent evidence is an exception.</li>
            <li><strong>Human decision.</strong> The script supervisor and the DIT review each exception in their own role. Only the 1st AD can approve a pickup or the wrap, and the run waits for them across a real process boundary.</li>
            <li><strong>Turnover.</strong> After the approval, a sealed manifest and a portable receipt go to editorial with every accepted exception still on them.</li>
          </ol>
          <p className="fine">Real Strands interrupts, a real event bus, a scripted planner and an offline lexical interpreter. No footage or audio is analysed and nothing is cleared in law.</p>
        </article>
      </div>
    </section>
  );
}
