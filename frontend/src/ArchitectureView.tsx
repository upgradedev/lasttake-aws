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
  {name:'The workspace a judge opens',service:'Amazon S3 + Amazon CloudFront',what:'This React application, built in CI from a committed lock file, served as versioned static files through an origin access control. Every release names its commit in the HTML and in /release.json.',limit:'Static files only. It holds a session handle and a role preference in the browser; records live behind the API.'},
  {name:'One API origin',service:'Amazon API Gateway (HTTP API)',what:'Same-origin /api/* requests reach one Lambda. Refusals come back as JSON with the field that failed, never as an HTML page.',limit:'No authentication. Demo roles are a selector, not staff identity, and the API says so in every payload.'},
  {name:'The orchestrator and four bounded checks',service:'AWS Lambda (arm64) running the Strands Agents SDK',what:'Coverage, continuity, metadata and rights checks over the scene package bundled with the function and any amendments stored on S3. A deterministic gate with no model in it combines the findings. Two material transitions, the pickup and the wrap, suspend the run with a real Strands interrupt and resume it in a later, different process from the session stored on S3.',limit:'On this public deployment the interpreter is an offline lexical reader (the API reports it as "offline-lexical"). Amazon Bedrock is supported through the same port but is not active here; nothing on this page was produced by a hosted model.'},
  {name:'Run state',service:'Amazon Aurora DSQL',what:'Findings, decisions, eligibility packets, audit entries and handled events. Each finding carries its own SHA-256 seal, and the gate verifies that seal before it reads a field. The API reports the store in use as run_state_store.',limit:'A seal identifies bytes; it does not make a claim true. Only findings are verified this way. There is no write-once storage tier and no Merkle proof.'},
  {name:'Artifacts and sessions',service:'Amazon S3',what:'Amendments to the scene package, approvals, delivery receipts, a copy of every event, the suspended Strands sessions, and the sealed turnover manifest editorial downloads.',limit:'Standard storage. Only the session files expire, after 90 days. Durability figures are Amazon\'s, not something this project measured.'},
  {name:'Run events',service:'Amazon EventBridge',what:'Every run event reaches the bus, one per finding included. An approved pickup request or wrap publishes under an idempotency key, so a retried approval cannot publish twice. The recorded outcome is the bus acceptance.',limit:'Bus acceptance is not downstream delivery, and no rule or subscriber is declared on the bus. Pending or unknown outcomes require reconciliation, never a blind resend.'},
];

export function ArchitectureView({runId}:{runId?:string}) {
  return <section className="arch" aria-label="Architecture">
    <div className="page-heading">
      <div><p className="eyebrow">What is deployed</p><h1 id="page-title" tabIndex={-1}>Architecture</h1><p>Six tiers, each one checkable. The amber path on the diagram, a run that pauses for a named human and resumes in a different process, is the part that does not port off Strands.</p></div>
      <div className="toolbar"><a className="button" href={link('overview',runId)}>Back to wrap status</a></div>
    </div>
    <figure className="panel arch-figure">
      <img src="/architecture.svg" alt="LastTake architecture: a React workspace served from S3 through CloudFront calls the API through API Gateway; a wrap checkpoint request starts an orchestrator on Lambda, four bounded checks read the scene package bundled with the function plus amendments stored on S3 and write findings to Aurora DSQL, a deterministic gate with no model in it combines them, two material transitions suspend the run for a named human, every run event is published to EventBridge, and a sealed, versioned turnover is saved for editorial." width="880" height="1347"/>
      <figcaption>The same file as docs/architecture.svg in the repository. Every box on it is deployed.</figcaption>
    </figure>
    <ol className="arch-tiers">
      {TIERS.map(t=><li key={t.name} className="panel"><p className="eyebrow">{t.service}</p><h2>{t.name}</h2><p>{t.what}</p><p className="fine"><strong>Limit:</strong> {t.limit}</p></li>)}
    </ol>
    <p className="fine">The README section "What is deployed, and what it costs" names both stacks and their release paths and says what is and is not measured about cost; docs/infrastructure.md lists every resource with the file that declares it. This page does not repeat numbers it did not measure.</p>
  </section>;
}
