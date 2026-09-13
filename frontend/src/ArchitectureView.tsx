import { useState } from 'react';
import { link } from './model';

interface ArchLayer {
  id: string;
  name: string;
  category: 'Edge & Client' | 'API Gateway' | 'Compute & Logic' | 'Agentic Intelligence' | 'Storage & Audit';
  awsService: string;
  description: string;
  securityPillar: string;
  costPillar: string;
  reliabilityPillar: string;
}

const LAYERS: ArchLayer[] = [
  {
    id: 'edge',
    name: 'Production Edge Terminal',
    category: 'Edge & Client',
    awsService: 'Amazon CloudFront & S3 Static Origin',
    description: 'Serves the single-page application to script supervisor iPad carts and DIT stations with sub-second response times and HTTPS encryption.',
    securityPillar: 'Strict Origin Access Control (OAC), TLS 1.3 only, isolated public anonymous read permissions.',
    costPillar: 'Less than $0.05 per shoot day in data transfer.',
    reliabilityPillar: 'Globally distributed PoPs with automatic edge failover.',
  },
  {
    id: 'api',
    name: 'Serverless HTTP Gateway',
    category: 'API Gateway',
    awsService: 'Amazon API Gateway v2',
    description: 'Directs shoot-day API payloads (checkpoints, approvals, manual intakes) directly to specialized Lambda workers with sub-15ms overhead.',
    securityPillar: 'Scoped CORS restrictions, rate-limiting (100 req/sec burst limit), payload schema validation.',
    costPillar: '$1.00 per million requests; negligible cost per shoot day.',
    reliabilityPillar: 'Managed multi-AZ availability with zero idle infrastructure.',
  },
  {
    id: 'compute',
    name: 'Reconciliation Lambda Fleet',
    category: 'Compute & Logic',
    awsService: 'AWS Lambda (Python 3.11+ / ARM64)',
    description: 'Executes the deterministic verification engine, anti-join coverage checks, and turnover manifest assembly.',
    securityPillar: 'Execution IAM roles scoped strictly to table and bucket resource ARNs; no wildcard permissions.',
    costPillar: 'Billed per millisecond of compute. Average scene check takes <400ms.',
    reliabilityPillar: 'Stateless execution handles concurrent takes from multiple cameras seamlessly.',
  },
  {
    id: 'strands',
    name: 'AWS Strands Agentic Engine',
    category: 'Agentic Intelligence',
    awsService: 'AWS Strands SDK & Amazon Bedrock',
    description: 'Coordinates multi-agent state persistence across process death on set. Bedrock (Claude 3.5 Sonnet) handles fuzzy script-to-take alignment.',
    securityPillar: 'Amazon Bedrock guardrails prevent data leakage; customer shoot scripts never used for model training.',
    costPillar: 'Targeted prompt caching; invokes Bedrock only when unstructured notes require semantic parsing.',
    reliabilityPillar: 'Interrupt-and-resume capability guarantees state is never lost if a tablet dies or reloads.',
  },
  {
    id: 'storage',
    name: 'Shoot-Day Operational Ledger',
    category: 'Storage & Audit',
    awsService: 'Amazon DynamoDB',
    description: 'Single-table design storing active scenes, beats, takes, findings, and human approval decisions with sub-10ms latency.',
    securityPillar: 'AWS KMS encryption at rest, DynamoDB condition expressions preventing duplicate wrap approvals.',
    costPillar: 'On-demand pay-per-request pricing; zero cost between shoot days.',
    reliabilityPillar: 'Synchronous cross-AZ replication with Point-in-Time Recovery (PITR).',
  },
  {
    id: 's3',
    name: 'Editorial Turnover Vault',
    category: 'Storage & Audit',
    awsService: 'Amazon S3',
    description: 'Houses signed turnover manifests, portable JSON receipts, and audit archives for post-production delivery.',
    securityPillar: 'S3 Object Lock (WORM compliance) prevents retrospective alteration of production wrap records.',
    costPillar: '$0.023 per GB/month for standard storage tier.',
    reliabilityPillar: '11 nines (99.999999999%) of data durability guarantees editorial handoffs are never lost.',
  },
];

export function ArchitectureView({ runId }: { runId?: string }) {
  const [selectedLayerId, setSelectedLayerId] = useState('strands');
  const activeLayer = LAYERS.find(l => l.id === selectedLayerId) || LAYERS[0];

  return (
    <div className="panel padded" style={{ maxWidth: '1200px', margin: '20px auto' }}>
      <div className="section-heading" style={{ borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '20px' }}>
        <div>
          <p className="eyebrow">AWS WELL-ARCHITECTED AGENTIC STACK</p>
          <h1 id="page-title" tabIndex={-1} style={{ fontSize: '1.8rem', margin: '4px 0' }}>LastTake AWS Architecture</h1>
          <p style={{ color: 'var(--muted)', margin: 0 }}>
            How AWS Strands, Amazon Bedrock, and Serverless Primitives deliver bulletproof shoot-day assurance.
          </p>
        </div>
        <a className="button primary" href={link('overview', runId)}>
          Return to Wrap Cockpit →
        </a>
      </div>

      {/* Layer Tabs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '14px', marginBottom: '24px' }}>
        {LAYERS.map((layer, index) => {
          const isSelected = layer.id === selectedLayerId;
          return (
            <button
              key={layer.id}
              onClick={() => setSelectedLayerId(layer.id)}
              className="panel"
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'space-between',
                minHeight: '135px',
                textAlign: 'center',
                padding: '16px 12px',
                cursor: 'pointer',
                borderColor: isSelected ? 'var(--teal, #14b8a6)' : 'var(--border)',
                background: isSelected ? 'var(--raised, #1e293b)' : 'var(--panel, #0f172a)',
                color: 'var(--text)',
                margin: 0,
                transition: 'all 0.2s ease',
                boxShadow: isSelected ? '0 0 16px rgba(20, 184, 166, 0.2)' : 'none',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                <span style={{ fontSize: '0.68rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px', background: isSelected ? 'rgba(20, 184, 166, 0.25)' : 'rgba(255,255,255,0.08)', color: isSelected ? 'var(--teal, #14b8a6)' : 'var(--muted)' }}>
                  0{index + 1}
                </span>
                <span style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--muted)', display: 'block' }}>
                  {layer.category}
                </span>
              </div>
              <strong style={{ display: 'block', fontSize: '0.92rem', fontWeight: 700, color: isSelected ? 'var(--teal, #14b8a6)' : 'var(--text)', lineHeight: 1.35, margin: 'auto 0' }}>
                {layer.name}
              </strong>
              <span className="badge" style={{ marginTop: '10px', fontSize: '0.72rem', padding: '3px 8px', borderRadius: '6px', background: isSelected ? 'rgba(20, 184, 166, 0.15)' : 'rgba(255,255,255,0.06)', color: isSelected ? 'var(--teal, #14b8a6)' : 'var(--muted)', border: isSelected ? '1px solid var(--teal, #14b8a6)' : '1px solid var(--border)' }}>
                {layer.awsService}
              </span>
            </button>
          );
        })}
      </div>

      {/* Layer Detail Inspector */}
      <article className="panel padded" style={{ background: 'var(--bg, #090d16)' }}>
        <div className="section-heading" style={{ marginBottom: '16px' }}>
          <div>
            <span className="eyebrow">{activeLayer.category.toUpperCase()} SPECIFICATION</span>
            <h2 style={{ fontSize: '1.35rem', margin: '4px 0' }}>{activeLayer.name} ({activeLayer.awsService})</h2>
            <p style={{ color: 'var(--muted)', margin: 0 }}>{activeLayer.description}</p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '18px' }}>
          <div style={{ background: 'var(--panel, #0f172a)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: 'var(--teal, #14b8a6)' }}>SECURITY & PERMISSIONS</span>
            <h3 style={{ fontSize: '0.95rem', margin: '4px 0 8px' }}>Least-Privilege Isolation</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--muted)', lineHeight: 1.6, margin: 0 }}>
              {activeLayer.securityPillar}
            </p>
          </div>

          <div style={{ background: 'var(--panel, #0f172a)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: 'var(--amber, #f59e0b)' }}>COST OPTIMIZATION</span>
            <h3 style={{ fontSize: '0.95rem', margin: '4px 0 8px' }}>Shoot-Day Economics</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--muted)', lineHeight: 1.6, margin: 0 }}>
              {activeLayer.costPillar}
            </p>
          </div>

          <div style={{ background: 'var(--panel, #0f172a)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
            <span className="eyebrow" style={{ color: '#38bdf8' }}>MISSION-CRITICAL RELIABILITY</span>
            <h3 style={{ fontSize: '0.95rem', margin: '4px 0 8px' }}>Zero-Downtime Guarantee</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--muted)', lineHeight: 1.6, margin: 0 }}>
              {activeLayer.reliabilityPillar}
            </p>
          </div>
        </div>
      </article>
    </div>
  );
}
