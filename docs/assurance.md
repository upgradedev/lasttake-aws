# Assurance

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
| **Operational excellence** | Infrastructure is one CloudFormation template applied by pipeline; nothing is created by hand. Deploy verifies the live URL and fails on non-200, then walks the product's whole loop over HTTP. A twice-daily check walks the same journey and opens an issue when it breaks. | `infra/stack.yaml`, `.github/workflows/deploy.yml`, `tools/uptime_check.py` | No dashboard and no metric alarms. A failure is caught within twelve hours by the schedule, not within minutes. No runbook beyond this repository. |
| **Security** | Deploy identity scoped to `lasttake-*` resources plus Bedrock inference; execution role reaches only its own bucket, its own bus, its own cluster, and Anthropic models. Database auth is IAM, so no password exists anywhere. Bucket is private, encrypted, versioned, TLS-only. CodeQL `security-extended` on every push and weekly. Untrusted document text is delimited and tested against injection. | `infra/setup_ci_identity.py`, `infra/stack.yaml`, `tests/test_prompt_injection.py`, `.github/workflows/codeql.yml` | **There is no authentication.** The role in the demo page is a claim the request makes and the server checks it against the policy tables, so a decision by the wrong role is refused, but nothing establishes who the caller is. Anyone with the URL can stand in any chair. A production deployment puts SSO in front of it and maps a real identity to a role; that work is not done and is not claimed. The public endpoint has no authentication, by design, because a judge must reach it without an account. That means anyone can create runs. There is no WAF and no rate limit beyond Lambda concurrency. No DAST beyond the journey check. Long-lived access keys in GitHub secrets rather than OIDC federation. |
| **Reliability** | Duplicate delivery is harmless: events carry an idempotency key derived from content, and the handled set is a single `INSERT ... ON CONFLICT` in DSQL. A paused run survives process death on S3-backed sessions, asserted on every deploy by retiring warm containers and requiring the container id to change. Findings citing moved source digests are rejected rather than reused. | `src/lasttake/domain/events.py`, `src/lasttake/adapters/aws/dsql.py`, `.github/workflows/deploy.yml` | Single region. No backup or restore drill for the DSQL cluster. No tested recovery procedure, so recovery time is unknown rather than measured. The API Gateway integration caps a request at 30 seconds; a slow checkpoint surfaces as a gateway timeout. |
| **Performance efficiency** | ARM64 Lambda. The corpus parses once per container. Two of the four checks never call a model at all, and the two that do get one bounded question each. A targeted rerun re-executes only the checks whose sources moved. | `infra/stack.yaml`, `src/lasttake/checks/`, `src/lasttake/domain/policy.py` | No load test and no measured p95. Cold start is unmeasured. Memory at 1024MB was chosen, not tuned. |
| **Cost optimisation** | Every component scales to zero: Lambda bills per request, DSQL has no idle charge, S3 bills for what is stored, EventBridge per event. Lifecycle rules expire demo runs at 90 days. boto3 is excluded from the deployment package because the runtime already has it. | `infra/stack.yaml`, `.github/workflows/deploy.yml` | No budget alarm and no cost anomaly detection. The idle figure below is computed from published prices, not read off a bill. |
| **Sustainability** | Scale to zero means no idle compute. ARM64 draws less power than x86 for the same work. Model calls are bounded to two narrow questions rather than passing whole documents to a model. | `infra/stack.yaml`, `src/lasttake/ports/interpreter.py` | No measurement. The claim is architectural, not observed. |
| **Agentic AI Lens** | The agent orchestrates and decides nothing. A deterministic, versioned gate combines results and fails closed six ways, each with a test that tries to make it fail open. Required checks are derived from the package, so an agent cannot make a requirement disappear by not looking. Two material transitions stop and wait for a named human role. Model output is confined to two bounded questions. It cannot make a requirement disappear, and it cannot produce `missing`, which is arithmetic over the package. It **does** decide between `verified` and `unknown` on those two questions, so the honest statement is that a model can withhold a pass and cannot manufacture one: every failure path returns `unknown`, `unknown` is an exception rather than a success, and a critical `unknown` blocks the gate until a named human triages it. | `src/lasttake/domain/policy.py`, `src/lasttake/agents/tools.py`, `tests/test_gate.py` | No evaluation set for the model's judgement quality, so its accuracy on the two bounded questions is unmeasured, and a model that wrongly answers `covers: true` with high confidence would produce a `verified` a human then has to catch. No cost or latency budget per run. No human review queue outside the demo page. |

### What it costs when nobody is looking

Computed from the AWS pricing pages, **not measured from a bill**, and therefore an ESTIMATE
that keeps the label.

| Service | Idle | Per demo run |
|---|---|---|
| Lambda | nothing | roughly 8 invocations, well inside the free tier |
| API Gateway HTTP API | nothing | $1.00 per million requests |
| Aurora DSQL | nothing when idle, and the first 100,000 DPUs are free monthly | a few hundred DPUs |
| S3 | $0.023 per GB-month, and a run is a few hundred KB | negligible |
| EventBridge | nothing | $1.00 per million custom events |

Idle monthly cost is dominated by S3 storage and rounds to under $0.01.

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
| **Art. 12**, record keeping | Automatic recording of events over the lifetime | Every event carries an id, a correlation id, a causation id, a parent, an idempotency key and the source digests as read. All are written to S3 and published to EventBridge. Findings, decisions, eligibility packets and the audit trail are in DSQL. The turnover seals itself so tampering is detectable by re-hashing. | Retention is 90 days on demo prefixes, chosen for a demo rather than for a records policy. No log integrity protection beyond S3 versioning. No export in a standard audit format. |
| **Art. 13**, transparency | Users understand output and its limitations | Every finding names the sources it read with their digests, the locators a human can open, and the role that may act on it. Model interpretation is a separate field from direct observation, so a reader can always tell which is which. The interpreter identifies itself on every finding, including the offline stand-in. The turnover states on its face what a `verified` rights row does and does not mean. | No user documentation for a script supervisor beyond this repository. Nothing measures whether the distinction between observation and inference is actually understood by the people reading it. |
| **Art. 14**, human oversight | Humans can oversee, interpret and override | Two material transitions stop and wait for a named role, and the run cannot continue without an answer. Authority is a table, not an `if`: a DIT may resolve media identity and may not accept a rights exception, and **nobody at all** may accept away a missing release. A human may reject a finding as a false positive; the original is preserved unchanged beside the rejection. Eligibility is explicitly not authority to wrap. | Identity is asserted, not authenticated: the public demo takes a role at its word. There is no audit of whether the human actually reviewed the evidence rather than clicking through. No training material. |
| **Art. 15**, accuracy, robustness and cybersecurity | Accuracy, resilience, and resistance to manipulation | The four truth states make absent evidence a finding rather than a pass, and a test asserts no fifth state can appear. Arithmetic, identity comparison and record lookup never touch a model. A model may downgrade a claimed cover to `unknown`; it can never turn an absent take into a cover. Prompt injection is tested: hostile text in every note cannot cover a beat, produce a release, reconcile an identifier, or make a scene eligible. Timeouts produce `unknown`. | Accuracy of the two bounded model questions is unmeasured; there is no labelled evaluation set. Injection resistance is proven against the deterministic interpreter, and against the model only by prompt design. No adversarial testing of the deployed endpoint. |
| **Art. 50**, transparency obligations | People are told when they interact with an AI system | The demo page states what the system is, that its data is synthetic, and which interpreter produced any inference. Every finding carries its `agent_version` and the interpreter's identity into the turnover, so a downstream reader who never saw the page still knows. | No explicit "you are interacting with an AI system" banner in those words. Synthetic content is labelled in the corpus files and on the page, not watermarked. |

---

## Data protection

**What personal data is processed: none belonging to a real person.**

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
| What is collected from a visitor? | A run identifier they generate in their own browser. No account, no email, no name, no cookie. |
| What is stored? | Findings, decisions and events for that run identifier, in DSQL and S3, all describing fictional people. |
| Where does it live? | One AWS region, `eu-west-1`. Nothing leaves it except a Bedrock inference call. |
| How long? | 90 days by lifecycle rule on demo prefixes, then deleted. |
| Is anything shared? | No third party. Bedrock is invoked for two bounded questions, carrying only a beat description and a supervisor's note about fictional people. |
| Logs? | Lambda logs for 30 days. No document text, no prompts and no media are logged by design. |

**In a real deployment this would change completely**, and the honest statement is that the
design here anticipates it without having been tested against it. Real releases name real
people, so a production deployment needs a lawful basis, a retention schedule set by the
production rather than by a demo lifecycle rule, subject access and erasure procedures, and a
data protection impact assessment. None of those exist here, because none of them can be
exercised against invented people.
