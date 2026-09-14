# Model evidence: what has run and what has not

**Real-model evaluation has not been run.** No real model has answered the 16 labelled
development cases, so there is no accuracy figure for either of the two bounded language
questions. The tools record this as `NOT_RUN`, and the owner's tracking items for this evidence,
LT2 and C1, stay open ([model-evidence-inventory.json](model-evidence-inventory.json)). The hosted
demo always runs offline, with no Bedrock switch.

This page is for anyone checking a claim about a model in LastTake, and for the owner preparing a
bounded real-model run. It expands
[README, Running against Amazon Bedrock](../README.md#running-against-amazon-bedrock) and the
interpreter rows in
[README, The numbers, and the commands that produce them](../README.md#the-numbers-and-the-commands-that-produce-them).

| Evidence | Real model? | Section |
|---|---|---|
| A checkpoint through Bedrock inside a dispatched backend deploy | Yes. It yields counts, not accuracy | [Bedrock on the deploy runner](#bedrock-on-the-deploy-runner) |
| Covered beats, offline and through Bedrock, and what each count rests on | The offline count comes from a test; the Bedrock count from one deploy run | [What covered rests on](#what-covered-rests-on-and-why-two-readers-count-differently) |
| A 16-case text development set with separate gold labels | No. Only the offline lexical interpreter has answered it, in source CI | [Text interpretation evidence](#text-interpretation-evidence-source-preparation-not-model-accuracy) |
| A one-off collector and a private supervisor for a real-model cohort | No. Prepared and inactive | [Bounded collector](#bounded-collector-preparation-evaluation-only-not-production-strands), [Private supervisor](#private-supervisor-prepared-inactive-live-verification-not_run) |
| The hosted demo at the live URL | No. It always runs offline | [Bedrock on the deploy runner](#bedrock-on-the-deploy-runner) |

<a id="bedrock-on-the-deployed-role"></a>

## Bedrock on the deploy runner

**Where the model runs.** The backend deploy workflow,
[deploy.yml](../.github/workflows/deploy.yml), has a deploy job that runs only when the owner
dispatches it with the `deploy` action (deploy.yml:38). A push to main that touches `src/**`,
`corpus/**` or `infra/stack.yaml` starts the workflow, but that job does not run. Every dispatched
backend deploy runs paid Bedrock steps.

The step named "the Strands to Bedrock path, actually run" (deploy.yml:356-419) installs the
package on the GitHub runner and runs `lasttake checkpoint --bedrock` there. The AWS credentials on
that runner are the access-key secrets that
[infra/setup_ci_identity.py](../infra/setup_ci_identity.py) issues to the `lasttake-ci` IAM user
(deploy.yml:66-71; setup_ci_identity.py:7 and :134-144). The Lambda execution role is not used:
only `lambda.amazonaws.com` can assume it (infra/stack.yaml:162). The next step sends one
`aws bedrock-runtime converse` request asking the model to reply "OK" (deploy.yml:421-429).
Whatever that step's name says, it runs on the same runner with the same keys, and it proves
connectivity only.

**What the checkpoint exercises.** `--bedrock` swaps only the interpreter.
[cli.py](../src/lasttake/cli.py) builds `BedrockInterpreter` (cli.py:74-85), which runs two Strands
agents on `BedrockModel` and calls `structured_output` for the two bounded questions
([bedrock_interpreter.py](../src/lasttake/adapters/aws/bedrock_interpreter.py):126-200). The
planner that drives the orchestrator stays the scripted offline one. So `BedrockModel` plus
`agent.structured_output` is exercised rather than described.

**What the deploy asserts.** After the checkpoint, the step reads the run's findings and fails
unless all of these hold:

- exactly 34 findings carry a model inference: `assert len(interpreted) == 34` (deploy.yml:379)
- those findings are coverage and continuity findings only, each with a `model_id` starting
  `bedrock:` (deploy.yml:380-381)
- every one reports confidence below 1.0 (deploy.yml:388-389)
- required beats stay 34, and covered beats may fall below the offline 31 but never rise above it
  (deploy.yml:412-416)

It does not require Bedrock to reproduce the offline 31 covered beats. Model identifiers in
exported findings come only from their serialized records.

**What it printed.** `[PRIMARY]` 2026-09-08, deploy run 34195514875. `[PRIMARY]` marks a figure
taken from the run's own output rather than carried from notes. That run produced **34 findings
carrying a real model inference**, and 19 of 34 required beats read as covered (the table is in the
next section). The step prints one model-touched finding's inference, cut at 220 characters
(deploy.yml:385). The historical observation included this one, on the mug conflict:

> Established state calls for a half-full mug with handle to camera left. First take matches
> this exactly. Second take describes the mug as empty with handle turned to camera right.

The [spent-evidence inventory](model-evidence-inventory.json), observed 2026-09-10, read the same
figures from the log of a later deploy run, 34385084102: 34 interpreted findings, and 19 covered
beats against the lexical interpreter's 31. It also records that the workflow uploads no per-call
inputs, raw responses or usage, so the model usage and cost of these runs are `UNKNOWN`, which
means they were never recorded.

**Counts are not accuracy.** 34 model-touched findings and 19 covered beats show that the path ran
and what it answered. Without labelled ground truth, neither count says whether any answer was
right.

**The hosted demo always runs offline, with no Bedrock switch.** The Lambda handler always builds
`OfflineInterpreter` ([handler.py](../src/lasttake/app/handler.py):146), and the orchestrator uses
the scripted planner because no model is passed to it (orchestrator.py:218-219). The stack sets
`LASTTAKE_BEDROCK_MODEL_ID` and the Lambda role may invoke Bedrock (infra/stack.yaml:196-205 and
:249), but the HTTP path never reads that variable.

**How the default identifier was chosen.** The first draft of this repository defaulted to
`us.anthropic.claude-sonnet-4-5-20250929-v1:0`. Asking a real account returned neither that
identifier nor that region. The default is now `global.anthropic.claude-sonnet-5`
(bedrock_interpreter.py:37-39; infra/stack.yaml:29-31), verified by invocation on 2026-08-22
against one account, which is not the same as verified against yours. That is why the README asks
you to set an identifier that `lasttake doctor --bedrock` printed for your own account.

## What covered rests on, and why two readers count differently

`[PRIMARY]` 2026-09-08, deploy run 34195514875. At this head the deploy job runs
`lasttake checkpoint --bedrock` on the GitHub runner with the AWS access-key secrets that
`infra/setup_ci_identity.py` issues to the `lasttake-ci` IAM user, not with the Lambda execution
role, and prints the count.

| Interpreter | Covered, of 34 |
|---|---|
| `offline-lexical/1.0.0`, which the live URL runs | **31** |
| `bedrock:global.anthropic.claude-sonnet-5` | **19** |

Neither count establishes correctness without labelled ground truth. "Covered" was one word doing
four jobs, so each outcome now carries **what it rests on**, and the rollup headline reports that
basis beside the count ([rollup.py](../src/lasttake/domain/rollup.py)). This is the basis for the
offline interpreter and for an interpreter that cannot be reached:

| Basis | What it means | offline | model unreachable |
|---|---|---|---|
| declared by the production | a take names this beat. The people who were there said so | 2 | 33 |
| corroborated by the interpreter | a second reader agrees the take contains the beat | **31** | 0 |
| confirmed by a named human | the role that owns the check said so. This outranks both | 0 | 0 |
| insufficient evidence | no take, a model that could not tell, a timeout | 1 | 1 |

```bash
PYTHONPATH=src python -m pytest -q tests/test_corpus_counts.py
```

That test asserts the offline column in full and, for an unreachable interpreter, 0 corroborated
and 33 declared ([test_corpus_counts.py](../tests/test_corpus_counts.py):48-123). It does not
assert the unreachable column's other two rows. They are 0 confirmed, because neither run has a
human decision, and 1 insufficient, because B-17 has no take at all (the comment at
test_corpus_counts.py:83); an in-memory run of the same checks printed both on 2026-09-14. This
page has no basis breakdown for the Bedrock run.

Read the two columns together and the 31-against-19 gap stops being a mystery. **What the
production declared does not move**: the 33 declarations the unreachable column keeps are the 2
declared plus the 31 corroborated in the offline column. What moves is how much of it a given
reader will corroborate, and a stricter reader corroborates less.

Why the model corroborates fewer beats is an ESTIMATE, because no per-beat model answers were
kept. The model is shown the beat, the slate, the supervisor's note and the setup description, and
30 of the 40 takes carry no note ([corpus/takes.json](../corpus/takes.json)), because a supervisor
writes one where continuity matters and not on every take. The coverage prompt tells the model to
return a low confidence when the note or setup gives it nothing to go on
(bedrock_interpreter.py:69-73). Asked whether a slate with no note contains a particular beat, a
careful reader says it cannot tell.

Three things follow:

- `insufficient` is never a pass. A low-confidence answer turns the coverage finding into
  `unknown` (coverage.py:123-133), and the gate blocks on any exception nobody has triaged
  (policy.py:330-342), so a timeout and a model failure both block rather than clear.
- A beat resting on the production's declaration alone is **not** counted as covered, because one
  assertion is not two.
- No interpreter can raise the count above what the evidence supports. The coverage check lets an
  interpreter downgrade a cover but never create one
  ([coverage.py](../src/lasttake/checks/coverage.py):1-12), and the deploy asserts that required
  beats stay 34 and covered may fall and may never rise (deploy.yml:412-416).

What this exposes is the gap already declared in [assurance.md](assurance.md): there is no
independent, real-model evaluation of the two bounded questions. The source-only development set
in [Text interpretation evidence](#text-interpretation-evidence-source-preparation-not-model-accuracy)
does not close that gap, because its 16 gold labels are assistant-authored and no real model has
answered them. Closing it means independent labelled ground truth for "does this take contain this
beat", which the demo corpus does not have and one shoot day would not settle.

## Text interpretation evidence: source preparation, not model accuracy

The fixed [16-case protocol](model-evidence-protocol.json), [supplied text](model-evidence-cases.json)
and [separate gold labels](model-evidence-gold.json) were committed before the instrument. These
are assistant-authored synthetic development cases, ten coverage questions and six continuity
questions, not held-out research data or practitioner labels. Only supplied notes and text
descriptions are interpreted. There is no footage or audio analysis, and no creative or legal
judgement.

Future integration must preserve preregistration commit
`c0593b9e5c464f7b3cdb5574aece7ff8aabb71ba` as an ancestor: use a merge preserving
history, not squash or rebase. CI checks that ancestry and the frozen input hashes.
Do not rewrite the preregistration or relax the check to accommodate integration.
The check is in [model_evidence.py](../tools/model_evidence.py):29-33 and :65-68.

Source CI first runs the test suite (ci.yml:73-77), which includes controls for malformed or unsafe
responses, missing slots, interrupted writes, wrong or stale request bindings and metric
denominators ([test_model_evidence.py](../tests/test_model_evidence.py)). It then runs this step,
offline (ci.yml:81-84):

```bash
python tools/model_evidence.py --output source-evidence/model-evidence
```

The fresh output directory contains:

- the existing lexical interpreter's raw outputs
- all 16 future-model slots marked `UNRUN`, which means no model answer was ever requested for them
- the existing bounded Bedrock prompts and schemas, captured without constructing a model
- source, request and response hashes
- fixed denominators for capture, false positives, false exceptions and abstention

Gold never enters the prompts. Failed or unrun attempts are not dropped or replaced, and malformed
responses are failures, not successful abstentions. The question-level ruler is not the complete
production eligibility policy. No model quality threshold or independent accuracy claim is
attached to these development results.

`--replay <already-captured.json>` reads inert structured responses only, with exact protocol and
request bindings. It keeps the original bytes even when it refuses them; hashes bind bytes, not
model origin. Tests use explicitly labelled fake responses.

The [spent-evidence inventory](model-evidence-inventory.json) found no complete, comparable raw
semantic cohort in its bounded inspection on 2026-09-10. The two latest successful deploy runs at
that time, 34385084102 and 34382836826, list no artifacts. The newer run's log keeps counts, one
rationale cut at 220 characters and a separate connectivity-only `OK` response. None of it
establishes accuracy.

Real-model evaluation remains `NOT_RUN`; LT2/C1 is not closed. The frozen offline instrument is
unchanged. The separate bounded collector in the next section prepares a future owner-activated
cohort. Unrecorded model usage and cost, and runner and infrastructure cost, remain `UNKNOWN`.
Zero model calls describes only offline execution.

## Bounded collector preparation: evaluation only, not production Strands

[tools/bounded_model_evidence.py](../tools/bounded_model_evidence.py) wraps the frozen requests and
the offline replay. Source CI runs fake full-flow, budget and binding denial, malformed response,
interrupted call and raw-retention controls
([test_bounded_model_evidence.py](../tests/test_bounded_model_evidence.py)) before this export,
which needs no credentials and makes no call (ci.yml:86-89):

```bash
python tools/bounded_model_evidence.py export --output source-evidence/bounded-export
```

The artifact contains:

- every exact SDK request
- each case's serialized ASCII byte size
- request, config, protocol and source hashes
- an input-token reservation for each case, and a fixed ceiling of 512 output tokens
- reference worst-cost arithmetic
- a grant template marked `NOT_AUTHORIZED`, which cannot authorize a call

It is not a measurement or authority to spend. The supervisor in the next section adds an inactive
job that could call a live model once activated. It adds no app changes, IAM setup or deployment.

The candidate configuration, all in tools/bounded_model_evidence.py:

| Setting | Value | Line |
|---|---|---|
| Model | `eu.anthropic.claude-opus-5` | 26 |
| Region | `eu-west-1` | 27 |
| Thinking | disabled | 33, 59 |
| Output | one forced `record_opinion` tool result | 33, 60-63 |
| Calls | at most one plain Converse request for each of the 16 frozen cases | 34 |
| Output ceiling | 512 tokens per call | 28 |
| Request ceiling | 16384 serialized bytes | 29, 65-66 |
| SDK attempts | `total_max_attempts=1` | 208 |
| Timeouts | 5-second connect, 30-second read | 208-209 |
| Process bound | 900 seconds, and grant expiry, checked before each call | 271 |

System and user prompts, schemas, gold, thresholds, evaluator bytes and preregistration ancestry
stay unchanged. Before it builds any request, the collector checks that the frozen evaluator's
bytes are unchanged and that its instrument commit, `e1a0901`, is in history (lines 50-52). Plain
Converse does not exercise the production Strands structured-output orchestration, and this
transport and config difference rules out any claim that the collector is equivalent to the
production adapter. There is no tool execution, repair, retry, fallback, warmup or replacement
sample.

Input tokens are reserved conservatively: one token per serialized ASCII request byte, plus 4096
tokens for hidden model and tool framing (lines 30 and 69). This counts the whole schema and the
escaped supplied text. It is an explicit reviewed assumption, not a provider-certified tokenizer
bound or a CountTokens measurement. The parent, meaning the owner's approval step that issues the
grant, must accept this exact allowance or refuse activation. Actual usage above the bound, unknown
usage, errors or expiry stop further calls (lines 271-288).

Reference rates of 5.50 and 27.50 USD per million input and output tokens are illustrative pricing
for a geographic inference profile, not an active grant (line 188). Only exact, positive, finite
decimal rate strings in the parent's digest-bound grant can authorize the plan (lines 85-91 and
112-149), and the supervisor also refuses rates below those reference figures
(tools/evaluation_runner.py:84-86). The entire worst-case cohort must fit this application's
allocated share before the SDK client is created (lines 146-147, checked before line 269). The
shared USD 5 pool is never read as LastTake's available balance.

## Private supervisor: prepared, inactive, live verification NOT_RUN

Here `NOT_RUN` means the supervisor and its AWS authority have never been exercised against live
GitHub or AWS services.

[tools/evaluation_runner.py](../tools/evaluation_runner.py) and the separate `evaluation-parent`
job in [ci.yml](../.github/workflows/ci.yml) (line 188) prepare the parent boundary around this
collector. Push and pull-request CI export an inert plan and exercise injected fake GitHub and model
responses only ([test_evaluation_runner.py](../tests/test_evaluation_runner.py)). They cannot
activate that job. The frozen evaluator, the frozen requests and the `e1a0901` and `c0593b9`
ancestry remain.

Activation needs all of these, and none is provisioned by this code:

- a reviewed manual dispatch of the exact source, on run attempt 1, in a private repository
  (ci.yml:191-194)
- a separately approved `lasttake-bounded-evaluation` environment with required reviewer
  protection (ci.yml:198)
- a model-only OIDC role in `LASTTAKE_EVAL_ROLE_ARN`; the job narrows it for 900 seconds to
  `bedrock:InvokeModel` on `eu.anthropic.claude-opus-5` (ci.yml:227-236)
- the exact SHA-256 of the approved plan bytes in the **repository-level** variable
  `LASTTAKE_EVAL_APPROVED_PLAN_SHA256`, so the job-level condition can inspect it (ci.yml:194)

No deploy keys or application role are a fallback: the supervisor refuses any role other than the
one the approved plan names (evaluation_runner.py:122-123). The inline session policy can only
restrict an existing role; it cannot grant missing permission. Keep the plan variable empty until
the parent has reviewed the source, price, bound and authority.

CI exports `supervisor-plan/plan-NOT_APPROVED.json` (ci.yml:101-104), a template whose status
`NOT_APPROVED` means it cannot start a run (evaluation_runner.py:57). To approve a plan, a parent
must supply:

- for each of the three applications in the plan, the source, request, config and protocol hashes
- fixed dollar slices whose sum is at most USD 5 (evaluation_runner.py:106)
- reviewed token bounds and verified decimal prices
- one budget ID
- the exact future manual workflow run numbers and refs
- issue and expiry timestamps no more than one hour apart

The current run ID is bound by the supervisor after dispatch, not guessed in advance. A different
run number refuses activation and needs a fresh review (evaluation_runner.py:109-116). Changing
whitespace in the approved JSON also invalidates its configured digest.

This implementation consumes **LastTake's slice only**. The plan's other two applications, Merismos
and Archon, must remain inactive until their runners consume their own slices from the same fixed
parent plan. The sum check is not a deployed distributed budget controller, an AWS billing limit,
or permission to give each application a fresh USD 5 grant.

Before any AWS credentials exist in the job (the reserve step at ci.yml:223 comes before the
credentials step at :227), the supervisor verifies the actual private repository ID and creates one
annotated reservation at `eval-reservations/<budget-id>/lasttake` (evaluation_runner.py:165-191). A
duplicate, failed or uncertain ref creation is never retried and never refunds the slice. Before
launching, the supervisor re-reads the remote ref and tag payload and checks the exact source, run
and local grant (lines 222-245). A create-only launch marker prevents a duplicate child launch
(line 342), and GitHub tokens and OIDC request credentials are removed from the child's
environment (lines 344-346).

Repository administrators can alter Git refs. This is a cooperative trusted-runner record,
**not WORM** (write-once) storage, owner authentication or protection against privileged writers.
No code here deletes or rewrites a reservation. Reference API contracts:
[create a ref](https://docs.github.com/en/rest/git/refs#create-a-reference) and
[create an annotated tag](https://docs.github.com/en/rest/git/tags#create-a-tag-object).

The child command below shows the same collector boundary. **Do not invoke it directly to bypass
the supervisor or its consumed reservation**:

```bash
timeout --signal=TERM --kill-after=5s 960s python tools/bounded_model_evidence.py collect --grant /private/grant.json --output /private/lasttake-cohort
```

On a timeout, SIGTERM or SIGINT, the supervisor stops and reaps the child's process group; SIGKILL
and a lost host cannot be caught (evaluation_runner.py:248-301). The job is capped at 20 minutes
(ci.yml:197). Only a GitHub manual `workflow_dispatch`, on run attempt 1, with a matching grant and
context, is accepted.

Before each call, the create-only journal fsyncs the reservation and the full request. After the
call, the full SDK-decoded response is fsynced before any semantic parsing, and each record is also
printed to stdout as a flushed base64 backup (bounded_model_evidence.py:152-164 and 276-288). The
journal keeps request IDs and usage, not just a rationale. These are SDK receipts, not original
HTTP wire bytes or independently authenticated model origin. Request hashes are mechanical
provenance, not model-authored citations.

An unknown outcome consumes its entire worst-case reservation, with no refund or retry. All 16
slots, failed and unrun ones included, stay in the frozen evaluator's denominators. Recorded
usage-cost arithmetic is not an AWS bill; runner and infrastructure cost and the response-body byte
count stay `UNKNOWN`.

When `collect` ends on its own, even after an error, it seals a `final/` copy and replays only
those captured bytes through the frozen evaluator (bounded_model_evidence.py:292-293). If the
process is killed, the parent must first make sure it has terminated, then run the **offline**
finalizer below, and only if `final/` does not exist; the finalizer refuses otherwise (line 304).
The supervisor's offline `recover` step also verifies the final seal: an incomplete `final/` is
preserved and replayed from raw bytes into a fresh `recovery/` snapshot, and an interrupted
recovery is refused, never overwritten (evaluation_runner.py:316-336). Never rerun `collect`. If a
denominator file is missing or corrupt, the finalizer keeps the available raw bytes, a refusal
report and hashes, without a successful summary:

```bash
python tools/bounded_model_evidence.py finalize --output /private/lasttake-cohort
```

The prepared job uploads the whole run directory, journal and `final/` included, with
`if: always()`, so the upload happens even on failure (ci.yml:241-249). A fully lost or forcibly
cancelled runner can still lose artifacts or unflushed service logs, and the stdout backup is not a
durability guarantee. Reference contracts:
[Converse](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html),
[single SDK attempt](https://docs.aws.amazon.com/botocore/latest/reference/config.html),
[model profile](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5.html),
[pricing to re-verify before grant](https://platform.claude.com/docs/en/about-claude/pricing).
