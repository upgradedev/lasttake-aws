import { link } from './model';

export function GtmProductionView({ runId }: { runId?: string }) {
  return (
    <div className="panel padded" style={{ maxWidth: '1200px', margin: '20px auto' }}>
      <div className="section-heading" style={{ borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '20px' }}>
        <div>
          <p className="eyebrow">PROFESSIONAL AGENTS · GTM & PRODUCTION ECONOMICS</p>
          <h1 id="page-title" tabIndex={-1} style={{ fontSize: '1.8rem', margin: '4px 0' }}>Production ROI & Market Wedge</h1>
          <p style={{ color: 'var(--muted)', margin: 0 }}>
            Why preventing a single missing take saves up to $250,000 on a commercial or film shoot day.
          </p>
        </div>
        <a className="button primary" href={link('overview', runId)}>
          Return to Wrap Cockpit →
        </a>
      </div>

      {/* Hero Numbers */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px', marginBottom: '24px' }}>
        <div style={{ background: 'var(--bg, #090d16)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
          <span className="eyebrow" style={{ color: 'var(--teal, #14b8a6)' }}>COST OF A PICKUP DAY</span>
          <strong style={{ display: 'block', fontSize: '1.8rem', margin: '4px 0' }}>$50k – $250k</strong>
          <small style={{ color: 'var(--muted)' }}>Re-booking actors, camera packages, stages, and crew.</small>
        </div>
        <div style={{ background: 'var(--bg, #090d16)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
          <span className="eyebrow" style={{ color: 'var(--amber, #f59e0b)' }}>TIME TO VERIFY WRAP</span>
          <strong style={{ display: 'block', fontSize: '1.8rem', margin: '4px 0' }}>&lt; 5 Seconds</strong>
          <small style={{ color: 'var(--muted)' }}>Replaces 45 minutes of manual department cross-checks.</small>
        </div>
        <div style={{ background: 'var(--bg, #090d16)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
          <span className="eyebrow" style={{ color: '#38bdf8' }}>LASTTAKE RUN COST</span>
          <strong style={{ display: 'block', fontSize: '1.8rem', margin: '4px 0' }}>&lt; $0.05 / Scene</strong>
          <small style={{ color: 'var(--muted)' }}>Serverless on-demand pricing on AWS Bedrock & Lambda.</small>
        </div>
      </div>

      {/* What LastTake Replaces */}
      <section className="panel padded" style={{ background: 'var(--bg, #090d16)', marginBottom: '24px' }}>
        <div className="section-heading">
          <div>
            <p className="eyebrow">COMPETITIVE COMPARISON</p>
            <h2 style={{ fontSize: '1.3rem', margin: '4px 0' }}>What LastTake Replaces on the Production Cart</h2>
          </div>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.88rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                <th style={{ padding: '12px 8px' }}>Incumbent Tool</th>
                <th style={{ padding: '12px 8px' }}>What It Does</th>
                <th style={{ padding: '12px 8px' }}>Where It Fails</th>
                <th style={{ padding: '12px 8px' }}>LastTake Advantage</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '12px 8px' }}><strong>ScriptE Systems</strong></td>
                <td>Desktop/iPad continuity logging for script supervisors.</td>
                <td>Holds supervisor notes only; cannot read sound mixer CSVs or DIT camera logs to verify cross-department coverage.</td>
                <td style={{ color: 'var(--teal, #14b8a6)' }}><strong>Cross-Department Ingest:</strong> Automatically reconciles camera, sound, and script.</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '12px 8px' }}><strong>Scriptation</strong></td>
                <td>Apple Pencil script annotation and manual lining.</td>
                <td>100% manual; relies on human memory under fatigue at 7:00 PM on a Friday.</td>
                <td style={{ color: 'var(--teal, #14b8a6)' }}><strong>Agentic AI Checking:</strong> Detects blown audio, clipped lines, or missing angles.</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '12px 8px' }}><strong>Wrapbook</strong></td>
                <td>Payroll, digital call sheets, and insurance paperwork.</td>
                <td>Back-office administrative platform; completely detached from live on-set camera decisions.</td>
                <td style={{ color: 'var(--teal, #14b8a6)' }}><strong>Live Set Wrap Gate:</strong> Real-time Return-of-Control decision before striking lights.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Offline Edge Roadmap */}
      <section className="panel padded" style={{ background: 'var(--panel, #0f172a)' }}>
        <p className="eyebrow" style={{ color: 'var(--amber, #f59e0b)' }}>SET REALITY & OFFLINE ROADMAP</p>
        <h2 style={{ fontSize: '1.25rem', margin: '4px 0 8px' }}>Remote Location Resilience (RF-Shielded Stages & Forest Sets)</h2>
        <p style={{ color: 'var(--muted)', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>
          Film locations frequently lack internet connectivity. LastTake is architected with a <strong>Local-First Edge Strategy</strong>:
          the client caches active scene state in local SQLite/IndexedDB on the supervisor’s iPad. In high-security studio environments, an on-set
          mini-server running <strong>AWS IoT Greengrass</strong> executes local validation offline, syncing encrypted turnover packages with Amazon S3 the moment cellular or stage Wi-Fi is re-established.
        </p>
      </section>
    </div>
  );
}
