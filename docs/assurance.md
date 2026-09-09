# Assurance

For a script supervisor and the 1st AD. [Open LastTake on AWS](https://d3kf6hquzlli8g.cloudfront.net/): create a run, start a checkpoint, inspect sources, and answer the saved request. History provides the evidence bundle and delivery status. The hosted demo uses offline interpretation with real Strands tool replay and S3 session resume; no footage/audio analysis or downstream completion is established.

Current reliability scope: policy 1.1 rejects stale or unbound decisions, preserves missing camera reports, validates dates before amendments, and distinguishes pending, rejected, unknown and bus-accepted delivery. Old findings need an explicitly explained fresh checkpoint. Historical evidence remains historical; current UAT starts NOT_RUN until exact-commit CI. Required pre-existing component disclosures remain in the README.


Three tables: what AWS asks of a workload, what the EU AI Act asks of this class of
system, and what the data protection regulation asks of anything holding a person's name.

**Every row names a residual gap and none of them is empty.** A row with nothing left to do
is a row nobody looked at hard enough. Where a control is not implemented it says so and says
what would be needed, rather than describing an intention in the present tense.

Two words are absent on purpose, and a CI gate fails the build if either appears: the
adjective claiming a system meets a regulation, and the noun for the assessment that decides
it. Neither is ours to use. That judgement belongs to an assessment body, and this document
is an account of what was built, not a verdict on it.

---

## Well-Architected, six pillars, plus the Agentic AI Lens

| Pillar | What is actually built | Where | Residual gap |
|---|---|---|---|
| **Operational excellence** | Infrastructure is one CloudFormation template applied by pipeline; nothing is created by hand. Deploy verifies the live URL and fails on non-200, then walks the product's whole loop over HTTP. A twice-daily check walks the same journey and opens an issue when it breaks. | `infra/stack.yaml`, `.github/workflows/deploy.yml`, `tools/uptime_check.py` | No operational metrics dashboard or alarms. A failure is caught within twelve hours by the schedule, not within minutes. No runbook beyond this repository. |
| **Security** | Deploy identity scoped to `lasttake-*` resources plus Bedrock inference; execution role reaches only its own bucket, its own bus, its own cluster, and Anthropic models. Database auth is IAM, so no password exists anywhere. Bucket is private, encrypted, versioned, TLS-only. CodeQL `security-extended` on every push and weekly. Untrusted document text is delimited and tested against injection. | `infra/setup_ci_identity.py`, `infra/stack.yaml`, `tests/test_prompt_injection.py`, `.github/workflows/codeql.yml` | **There is no authentication.** The role in the demo page is a claim the request makes and the server checks it against the policy tables, so a decision by the wrong role is refused, but nothing establishes who the caller is. Anyone with the URL can stand in any chair. A production deployment puts SSO in front of it and maps a real identity to a role; that work is not done and is not claimed. The public endpoint has no authentication, by design, because a judge must reach it without an account. That means anyone can create runs. There is no WAF and no rate limit beyond Lambda concurrency. No DAST beyond the journey check. Long-lived access keys in GitHub secrets rather than OIDC federation. |
| **Reliability** | Consequential publication records pending, bus-accepted, rejected or unknown outcomes. DSQL atomic claims exclude concurrent unresolved logical effects across approvals; accepted replay uses its saved receipt. Only definite rejection allows retry. A paused run survives process death on S3-backed sessions, asserted on every deploy by retiring warm containers and requiring the container id to change. Findings citing moved source digests are rejected rather than reused. | `src/lasttake/domain/events.py`, `src/lasttake/adapters/aws/dsql.py`, `.github/workflows/deploy.yml` | Single region. No backup or restore drill for the DSQL cluster. No tested recovery procedure, so recovery time is unknown rather than measured. The API Gateway integration caps a request at 30 seconds; a slow checkpoint surfaces as a gateway timeout. |
| **Performance efficiency** | ARM64 Lambda. The corpus parses once per container. Two of the four checks never call a model at all, and the two that do get one bounded question each. A targeted rerun re-executes only the checks whose sources moved. | `infra/stack.yaml`, `src/lasttake/checks/`, `src/lasttake/domain/policy.py` | No load test and no measured p95. Cold start is unmeasured. Memory at 1024MB was chosen, not tuned. |
| **Cost optimisation** | Serverless execution avoids a provisioned application server; storage and request charges still apply. Lifecycle rules expire demo runs at 90 days. boto3 is excluded from the deployment package because the runtime already has it. | `infra/stack.yaml`, `.github/workflows/deploy.yml` | No budget alarm and no cost anomaly detection. No measured bill or idle-cost estimate. |
| **Sustainability** | The configured Lambda architecture is ARM64; no comparative energy result was measured. Model calls are bounded to two narrow questions rather than passing whole documents to a model. | `infra/stack.yaml`, `src/lasttake/ports/interpreter.py` | No measured energy use or environmental benefit. |
| **Agentic AI Lens** | The agent orchestrates and decides nothing. A deterministic, versioned gate combines results and fails closed six ways, each with a test that tries to make it fail open. Required checks are derived from the package, so an agent cannot make a requirement disappear by not looking. Two material transitions stop and wait for a named human role. Model output is confined to two bounded questions. It cannot make a requirement disappear, and it cannot produce `missing`, which is arithmetic over the package. It **does** decide between `verified` and `unknown` on those two questions, so the honest statement is that a model can withhold a pass and cannot manufacture one: every failure path returns `unknown`, `unknown` is an exception rather than a success, and a critical `unknown` blocks the gate until a named human triages it. | `src/lasttake/domain/policy.py`, `src/lasttake/agents/tools.py`, `tests/test_gate.py` | No evaluation set for the model's judgement quality, so its accuracy on the two bounded questions is unmeasured, and a model that wrongly answers `covers: true` with high confidence would produce a `verified` a human then has to catch. The size of that gap is now measured even though its correctness is not: on the same corpus the offline lexical interpreter establishes 31 of 34 beats and Bedrock establishes 19, because most takes carry no supervisor note and a careful reader answers `unknown` rather than guessing (deploy run 34195514875, 2026-09-08). Which of the two is right is exactly what an evaluation set would decide, and there is not one. No cost or latency budget per run. No human review queue outside the demo page. |

### Cost and timing limits

No measured invoice, human-active time, savings or energy result is available. CI duration measures tests, not a crew’s work. The dashboard counts saved session outcomes and recorded decisions without converting them into benefits. Pricing and quotas require account-specific verification.


---

## EU AI Act, Regulation (EU) 2024/1689

**This is an account of design decisions against named articles. It is not a legal
assessment, and no risk classification here is authoritative.** Our own reading is that this
system is not high-risk under Annex III, because it makes no decision about a person and the
rights check is a record lookup that explicitly refuses to interpret legal sufficiency. That
reading is ours. A deployer in a jurisdiction that reads it differently should take advice.

| Article | What it asks | What is built | Residual gap |
|---|---|---|---|
| **Art. 10**, data governance | Training, validation and testing data governed for relevance, representativeness and error | No model is trained or fine-tuned here. The only data is one synthetic scene package, generated deterministically by a committed script, regenerated and diffed in CI so it cannot drift unnoticed. Every artifact is content-addressed and cited by digest in the findings that read it. | The corpus is one fictional scene. It is not representative of production practice across formats, territories or departments, and nothing here claims it is. No dataset documentation beyond the generator's own comments. |
| **Art. 12**, record keeping | Automatic recording of events over the lifetime | Every event carries an id, a correlation id, a causation id, a parent, an idempotency key and the source digests as read. S3 retains event bytes and publication receipts separately report whether EventBridge accepted them. An S3 record is not proof of bus acceptance or target delivery. Findings, decisions, eligibility packets and the audit trail are in DSQL. The turnover carries a hash that detects changed bytes, not an authenticated signature; a writer able to replace the packet could also recompute it. | Retention is 90 days on demo prefixes, chosen for a demo rather than for a records policy. No log integrity protection beyond S3 versioning. No export in a standard audit format. |
| **Art. 13**, transparency | Users understand output and its limitations | Every finding names the sources it read with their digests, the locators a human can open, and the role that may act on it. Model interpretation is a separate field from direct observation, so a reader can always tell which is which. New interpreted findings serialize the model identifier. Older records without it remain unknown; a run's current configuration cannot supply historical model provenance. The turnover states on its face what a `verified` rights row does and does not mean. | No user documentation for a script supervisor beyond this repository. Nothing measures whether the distinction between observation and inference is actually understood by the people reading it. |
| **Art. 14**, human oversight | Humans can oversee, interpret and override | Two material transitions stop and wait for a named role, and the run cannot continue without an answer. Authority is a table, not an `if`: a DIT may resolve media identity and may not accept a rights exception, and **nobody at all** may accept away a missing release. A human may reject a finding as a false positive; the original is preserved unchanged beside the rejection. Eligibility is explicitly not authority to wrap. | Identity is asserted, not authenticated: the public demo takes a role at its word. There is no audit of whether the human actually reviewed the evidence rather than clicking through. No training material. |
| **Art. 15**, accuracy, robustness and cybersecurity | Accuracy, resilience, and resistance to manipulation | The four truth states make absent evidence a finding rather than a pass, and a test asserts no fifth state can appear. Arithmetic, identity comparison and record lookup never touch a model. A model may downgrade a claimed cover to `unknown`; it can never turn an absent take into a cover. Prompt injection is tested: hostile text in every note cannot cover a beat, produce a release, reconcile an identifier, or make a scene eligible. Timeouts produce `unknown`. | Accuracy of the two bounded model questions is unmeasured; there is no labelled evaluation set. Injection resistance is proven against the deterministic interpreter, and against the model only by prompt design. No adversarial testing of the deployed endpoint. |
| **Art. 50**, transparency obligations | People are told when they interact with an AI system | The demo page states what the system is, that its data is synthetic, and which interpreter produced any inference. New interpreted findings carry a serialized model_id. Historical records without it report unknown provenance; agent_version and current runtime configuration are not model identity. | No explicit "you are interacting with an AI system" banner in those words. Synthetic content is labelled in the corpus files and on the page, not watermarked. |

---

## Data protection

**The shipped corpus contains fictional people. User-supplied text is not verified to be fictional; do not enter real personal data.**

Every name, identifier, release record and note in `corpus/` is invented. `THE LAST FERRY`
is not a production. There is no real footage, no real release, and no customer-derived data
of any kind.

Proven rather than asserted. Each corpus file carries a disclaimer field, and CI regenerates
the corpus from its committed generator and fails if the result differs:

```bash
python corpus/build_corpus.py && git diff --exit-code -- corpus/
```

| Question | Answer |
|---|---|
| What is collected from a visitor? | A bearer session handle, run identifier, role selection, and user-supplied fictional actor/reason/document fields. There is no staff authentication; do not enter real personal data. |
| What is stored? | Findings, decisions and events for that run identifier, in DSQL and S3, including user-supplied text that must be fictional for this demo. |
| Where does it live? | Application storage is configured in `eu-west-1`. The browser receives requested records. Optional Bedrock inference may use a cross-region profile; the default offline mode makes no model API calls. |
| How long? | 90 days by lifecycle rule on demo prefixes, then deleted. |
| Is anything shared? | The default uses AWS hosting with offline interpretation. Optional Bedrock receives bounded text inputs; no footage or audio is analyzed. No email or payment integration is active. |
| Logs? | Lambda logs for 30 days. No document text, no prompts and no media are logged by design. |

**In a real deployment this would change completely**, and the honest statement is that the
design here anticipates it without having been tested against it. Real releases name real
people, so a production deployment needs a lawful basis, a retention schedule set by the
production rather than by a demo lifecycle rule, subject access and erasure procedures, and a
data protection impact assessment. None of those exist here, because none of them can be
exercised against invented people.
