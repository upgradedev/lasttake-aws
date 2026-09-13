import { useState } from 'react';
import { link } from './model';
import type { RunState } from './types';

interface JourneyStage {
  id: string;
  number: string;
  title: string;
  role: string;
  timing: string;
  summary: string;
  checksEnforced: string[];
  awsServices: string[];
  artifactProduced: string;
  deepDive: string;
}

const STAGES: JourneyStage[] = [
  {
    id: 'ingest',
    number: '01',
    title: 'Camera & Sound Log Ingest',
    role: 'DIT / Data Manager & Sound Mixer',
    timing: 'Continuous on set (< 30s per scene)',
    summary: 'Sound mixer CSV reports, camera roll logs, and talent appearance releases are ingested into the shoot-day workspace.',
    checksEnforced: [
      'Sound roll and camera roll timecode continuity',
      'Corroborating camera report must accompany each take',
      'Media ID registration in DIT custody ledger',
      'Talent releases verified against character appearances',
    ],
    awsServices: ['API Gateway', 'AWS Lambda (Ingest Engine)', 'Amazon DynamoDB'],
    artifactProduced: 'Corpus entity graph with verified timecode and media references',
    deepDive: 'On a fast-paced set, sound and camera departments work in parallel. LastTake continuously ingests their distinct reports. If a sound roll reports audio clipping on track 2 while the camera report marks the take as preferred, LastTake flags the discrepancy immediately rather than letting post-production discover it weeks later.',
  },
  {
    id: 'reconciliation',
    number: '02',
    title: 'Script Lined Beats & Coverage Reconciliation',
    role: 'Script Supervisor',
    timing: '5 seconds after take wrap',
    summary: 'Amazon Bedrock and the deterministic coverage engine cross-examine captured takes against required script beats.',
    checksEnforced: [
      'Every mandatory beat must have at least one usable take',
      'Audio quality verified: no clipping, no background interference',
      'Camera framing verified: master shot, close-up, reaction shots',
      'Actors in shot must have active legal release records',
    ],
    awsServices: ['Amazon Bedrock (Claude 3.5 Sonnet)', 'AWS Strands SDK', 'AWS Lambda'],
    artifactProduced: 'Interactive Wrap Board & Coverage Matrix with flagged exceptions',
    deepDive: 'Script supervisors traditionally draw lines on paper scripts with colored pens. LastTake digitizes this workflow by mapping every beat to its captured slates and takes. Bedrock parses complex director notes and continuity comments, while the deterministic rule engine verifies whether the coverage graph is mathematically closed.',
  },
  {
    id: 'wrap-gate',
    number: '03',
    title: '10-Minute Pre-Wrap Alert & 1st AD Approval',
    role: '1st Assistant Director (1st AD)',
    timing: '10 minutes before releasing crew',
    summary: 'The crucial Return-of-Control decision gate: knowing whether the set can be struck or if a pickup take is mandatory.',
    checksEnforced: [
      'Evidence gate: all blocking exceptions reviewed or accepted',
      'Single-button 1st AD cryptographic wrap approval',
      'State graph preserved across process boundaries using AWS Strands',
      'Zero automatic wrap sign-offs: human accountability strictly enforced',
    ],
    awsServices: ['AWS Strands SDK (Interrupt-and-Resume)', 'CloudFront', 'Amazon DynamoDB'],
    artifactProduced: 'Cryptographically sealed Wrap Approval Decision with 1st AD signature',
    deepDive: 'The 1st AD is responsible for time and money. Ten minutes before calling wrap on a $150,000 shoot day, the 1st AD consults the Wrap Board. If Beat 4 (the critical plot reveal line) only has an aborted take with blown audio, LastTake highlights it in amber. The 1st AD orders a 3-minute pickup take while the lights and actors are still in position, saving tens of thousands of dollars.',
  },
  {
    id: 'turnover',
    number: '04',
    title: 'Editorial Turnover & Immutable S3 Handoff',
    role: 'Assistant Editor / Post-Production Supervisor',
    timing: 'Immediately at set wrap (< 2s)',
    summary: 'A complete, tamper-evident turnover manifest and portable receipt are delivered to editorial with all decisions recorded.',
    checksEnforced: [
      'Turnover manifest signed with SHA256 package digest',
      'Accepted production exceptions remain visibly documented',
      'Portable JSON/Markdown receipt published to Amazon S3',
      'Replay-safe audit trail for studio insurance and bonding companies',
    ],
    awsServices: ['Amazon S3 (Editorial Turnover Bucket)', 'Amazon EventBridge', 'AWS Lambda'],
    artifactProduced: 'Turnover Manifest (`turnover.json`) & Public Receipt (`receipt.json`)',
    deepDive: 'Editorial usually spends the first 2 days of post-production chasing missing sound logs or calling the script supervisor about illegible handwriting. LastTake generates a verified, machine-readable editorial turnover package with every preferred take, camera roll, and director preference clearly indexed.',
  },
];

export function UserJourneysView({ runId }: { runId?: string }) {
  const [activeStageId, setActiveStageId] = useState('wrap-gate');
  const activeStage = STAGES.find(s => s.id === activeStageId) || STAGES[0];

  return (
    <div className="panel padded" style={{ maxWidth: '1200px', margin: '20px auto' }}>
      <div className="section-heading" style={{ borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '20px' }}>
        <div>
          <p className="eyebrow">PROFESSIONAL SHOOT-DAY LIFECYCLE</p>
          <h1 id="page-title" tabIndex={-1} style={{ fontSize: '1.8rem', margin: '4px 0' }}>The 4 Production Assurance Journeys</h1>
          <p style={{ color: 'var(--muted)', margin: 0 }}>
            How LastTake safeguards the shoot day from morning sound sync to evening editorial turnover.
          </p>
        </div>
        <a className="button primary" href={link('overview', runId)}>
          Return to Wrap Cockpit →
        </a>
      </div>

      {/* Stage Selector Tabs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginBottom: '24px' }}>
        {STAGES.map(stage => {
          const isSelected = stage.id === activeStageId;
          return (
            <button
              key={stage.id}
              onClick={() => setActiveStageId(stage.id)}
              className="panel"
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                textAlign: 'left',
                padding: '16px 14px',
                cursor: 'pointer',
                borderColor: isSelected ? 'var(--amber, #f59e0b)' : 'var(--border)',
                background: isSelected ? 'var(--raised, #1e293b)' : 'var(--panel, #0f172a)',
                color: 'var(--text)',
                margin: 0,
                transition: 'border-color 0.15s, background-color 0.15s',
              }}
            >
              <span style={{ fontSize: '0.8rem', fontWeight: 800, color: isSelected ? 'var(--amber, #f59e0b)' : 'var(--muted)' }}>
                STAGE {stage.number}
              </span>
              <strong style={{ display: 'block', fontSize: '0.95rem', marginTop: '6px' }}>{stage.title}</strong>
              <small style={{ color: 'var(--muted)', display: 'block', marginTop: '4px' }}>{stage.role}</small>
            </button>
          );
        })}
      </div>

      {/* Active Stage Detail */}
      <article className="panel padded" style={{ background: 'var(--bg, #090d16)' }}>
        <div className="section-heading" style={{ marginBottom: '16px' }}>
          <div>
            <span className="eyebrow">STAGE {activeStage.number} BREAKDOWN</span>
            <h2 style={{ fontSize: '1.4rem', margin: '4px 0' }}>{activeStage.title}</h2>
            <p style={{ color: 'var(--muted)', margin: 0 }}>{activeStage.summary}</p>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Turnaround Timing:</span>
            <strong style={{ display: 'block', color: 'var(--teal, #14b8a6)' }}>{activeStage.timing}</strong>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: '24px' }}>
          <div>
            <h3 style={{ fontSize: '1rem', marginBottom: '8px' }}>On-Set Workflow Detail</h3>
            <p style={{ lineHeight: 1.65, fontSize: '0.92rem', color: 'var(--text)', marginBottom: '16px' }}>
              {activeStage.deepDive}
            </p>

            <h3 style={{ fontSize: '1rem', marginBottom: '8px' }}>Department Verification Criteria</h3>
            <ul style={{ paddingLeft: '18px', fontSize: '0.88rem', color: 'var(--muted)', lineHeight: 1.7 }}>
              {activeStage.checksEnforced.map((check, idx) => (
                <li key={idx}><strong style={{ color: 'var(--text)' }}>{check}</strong></li>
              ))}
            </ul>
          </div>

          <div style={{ background: 'var(--panel, #0f172a)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <h3 style={{ fontSize: '0.95rem', color: 'var(--amber, #f59e0b)', marginBottom: '10px' }}>AWS Cloud & Strands Primitives</h3>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '16px' }}>
              {activeStage.awsServices.map(svc => (
                <span key={svc} className="badge" style={{ fontSize: '0.75rem' }}>{svc}</span>
              ))}
            </div>

            <h3 style={{ fontSize: '0.95rem', color: 'var(--teal, #14b8a6)', marginBottom: '6px' }}>Production Artifact Created</h3>
            <p style={{ fontFamily: 'monospace', fontSize: '0.78rem', background: 'var(--bg, #090d16)', padding: '8px 10px', borderRadius: '6px', border: '1px solid var(--border)' }}>
              {activeStage.artifactProduced}
            </p>

            <div style={{ marginTop: '20px', paddingTop: '12px', borderTop: '1px solid var(--border)' }}>
              <a href={link('scene', runId)} className="button primary" style={{ width: '100%', textAlign: 'center' }}>
                Open Scene Review Workspace →
              </a>
            </div>
          </div>
        </div>
      </article>
    </div>
  );
}
