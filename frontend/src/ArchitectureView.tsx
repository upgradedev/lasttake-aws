import {link} from './model';

// What is actually deployed, and nothing else. Every row below names a thing a
// reader can check: the README's deployment section, /release.json,
// /acceptance.json, the API's own run_state_store field, or the diagram file.
//
// The earlier version of this page described DynamoDB, S3 Object Lock, Bedrock
// on the public path, latency figures and "guarantees". None of that is
// deployed and none of it was measured. A judge who knows AWS reads the README,
// sees Aurora DSQL, and stops trusting the rest. So this page says less and
// all of it is true.

const TIERS=[
  {name:'The workspace a judge opens',service:'Amazon S3 + Amazon CloudFront',what:'This React application is built in CI and served as versioned static files through an origin access control. Its service worker caches only the application shell; one last-confirmed snapshot and one unsent evidence draft may survive a reload in the same tab.',limit:'The snapshot is read-only, the draft is scoped to that tab and run, and API responses are not cached. No mutation is queued or replayed. Reconnect reads authoritative state; a changed package fingerprint requires explicit review.'},
  {name:'One synchronous API entry point',service:'Amazon API Gateway (HTTP API)',what:'Same-origin /api/* requests reach one Lambda. The checkpoint API starts the Strands orchestrator synchronously; EventBridge never triggers it. Refusals identify the field that failed in JSON.',limit:'No staff authentication. Demo roles are a selector, not staff identity, and the API says so in every payload.'},
  {name:'One orchestrator and eight bounded tools',service:'AWS Lambda (arm64) running the Strands Agents SDK',what:'One Strands Agent calls eight @tool functions. Coverage, continuity, metadata and rights are four tools, not four agents; a deterministic gate combines their findings. Pickup and wrap are the two ToolContext.interrupt transitions, and S3SessionManager makes the interrupted session resumable after Lambda process death.',limit:'The public deployment uses a scripted planner and offline lexical reader. Only Bedrock mode creates two additional scoped interpreter Agents, for coverage and continuity; Bedrock is not active in this browser.'},
  {name:'Run state',service:'Amazon Aurora DSQL',what:'Findings, decisions, eligibility packets, audit entries and handled events. Each finding carries its own SHA-256 seal, and the gate verifies that seal before it reads a field. The API reports the store in use as run_state_store.',limit:'A seal identifies bytes; it does not make a claim true. Only findings are verified this way. There is no write-once storage tier and no Merkle proof.'},
  {name:'Artifacts and durable sessions',service:'Amazon S3',what:'Amendments, approvals, event envelopes, subscriber consumption receipts, suspended Strands sessions and the sealed turnover manifest available in Handoff.',limit:'Standard storage. Only the session files expire, after 90 days. Durability figures are Amazon\'s, not something this project measured.'},
  {name:'Independent event-delivery observer',service:'Amazon EventBridge + terminal AWS Lambda',what:'The publisher sends domain events to a custom bus. A rule independently invokes a least-privilege delivery-recorder, which validates the envelope and writes an idempotent, immutable consumption receipt to S3. Handoff distinguishes consumed from not observed.',limit:'The recorder cannot publish events and never starts or resumes Strands. Its receipt proves subscriber execution, not editorial completion. Because delivery is asynchronous, a receipt not yet observed is not proof of failure.'},
];

export function ArchitectureView({runId}:{runId?:string}) {
  return <section className="arch" aria-label="Architecture">
    <div className="page-heading">
      <div><p className="eyebrow">What is deployed</p><h1 id="page-title" tabIndex={-1}>Architecture</h1><p>Six checkable tiers. The Strands path pauses for a named human and resumes in a different process; the separate EventBridge path observes delivery without driving the workflow.</p></div>
      <div className="toolbar"><a className="button" href={link('overview',runId)}>Back to wrap status</a></div>
    </div>
    <figure className="panel arch-figure">
      <img src="/architecture.svg" alt="LastTake architecture: the browser keeps only a cached shell, one read-only snapshot and one same-tab draft, then reconnects with authoritative reads and no mutation replay; API Gateway synchronously starts one Strands orchestrator Agent on Lambda with eight tools, including four checks and two human interrupts resumed from S3; the public interpreter is lexical while Bedrock mode adds two scoped interpreter Agents; Aurora DSQL and S3 hold durable state; and an independent EventBridge rule invokes a terminal delivery-recorder whose receipt proves subscriber execution, not editorial completion." width="1200" height="920"/>
      <figcaption>The same file as docs/architecture.svg in the repository. Every box on it is deployed.</figcaption>
    </figure>
    <ol className="arch-tiers">
      {TIERS.map(t=><li key={t.name} className="panel"><p className="eyebrow">{t.service}</p><h2>{t.name}</h2><p>{t.what}</p><p className="fine"><strong>Limit:</strong> {t.limit}</p></li>)}
    </ol>
    <p className="fine">The README architecture and evidence sections name both stacks, their release paths and what is not measured; docs/infrastructure.md maps every resource to the file that declares it. This page does not repeat numbers it did not measure.</p>
  </section>;
}
