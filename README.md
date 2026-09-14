# LastTake

[![ci](https://github.com/upgradedev/lasttake-aws/actions/workflows/ci.yml/badge.svg)](https://github.com/upgradedev/lasttake-aws/actions/workflows/ci.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

Before the set is struck, LastTake shows a script supervisor which evidence is missing or in conflict, and the 1st AD (first assistant director) decides pickup and wrap.

The pickup and the wrap stop the run with a real Strands Agents SDK interrupt, and a later request can resume it in a different process from the session saved on S3.

[Open the AWS workspace](https://d3kf6hquzlli8g.cloudfront.net/) and choose **Start this fictional shoot day**. The next-step panel follows the saved evidence through the human wrap decision to a turnover for the assistant editor.

[Current automated acceptance](https://d3kf6hquzlli8g.cloudfront.net/acceptance.html) checks whether the latest published receipt from the automated browser tests names the frontend and backend code the site serves right now, and is at most 24 hours old. Missing, malformed, mismatched or older proof cannot establish a current pass. Human UAT (user acceptance testing) remains NOT_RUN: no person has completed the 22-case manual UAT testbook, which is separate from automated acceptance.

The live browser uses a scripted planner and an offline word-overlap matcher in place of a language model, with real Strands tool calls, S3 session resume and role-gated decisions. It does not analyse footage or audio, send emails, make payments or establish legal sufficiency. Demo role selection is not authenticated staff identity. Hashes identify bytes, not truth.

![Scene review in the LastTake workspace for fictional scene SC-042. The count strip reads 34 required beats, 31 covered with evidence, 2 raising exceptions and 1 with no release record, with the evidence gate blocked and the human wrap decision not approved. Below it are the script beats with their takes, a continuity discrepancy about a mug with its source digests, and the script supervisor's decision form for CR-01.](docs/scene-review.png)

*Scene review after a wrap checkpoint. Cropped and scaled from the LT-DASH workspace capture in the `ui-screenshots` artifact of [frontend CI run 34788421972](https://github.com/upgradedev/lasttake-aws/actions/runs/34788421972) (pull request #37 at commit 8475164), which ran against the offline local server. All data shown is synthetic.*

## Contents

- **Understand:** [Who this is for](#who-this-is-for) · [How Strands is load-bearing](#how-strands-is-load-bearing) · [Architecture](#architecture) · [The rule the whole product turns on](#the-rule-the-whole-product-turns-on)
- **Try it:** [Try it without installing anything](#try-it-without-installing-anything) · [What the demo shows](#what-the-demo-shows)
- **Run it yourself:** [Quickstart](#quickstart) · [Bring your own record](#bring-your-own-record) · [Running against Amazon Bedrock](#running-against-amazon-bedrock)
- **Verify:** [The numbers, and the commands that produce them](#the-numbers-and-the-commands-that-produce-them)
- **Deploy:** [What is deployed, and what it costs](#what-is-deployed-and-what-it-costs)
- **Disclosures:** [What it will not do](#what-it-will-not-do) · [The demo corpus is synthetic](#the-demo-corpus-is-synthetic) · [Assurance and residual gaps](#assurance-and-residual-gaps) · [Pre-existing components](#pre-existing-components) · [Licence](#licence)
- **Reference:** [Documentation](#documentation)

## Who this is for

A **script supervisor** on a shoot day, with the **1st AD** as the second reader.

**Terms used on this page.**

- **Script supervisor**: tracks every take against the script and keeps the continuity notes.
- **Take** and **beat**: a take is one recorded attempt at a shot; a beat is one moment the script requires on screen.
- **Continuity**: props, positions and actions matching between takes that may be cut together.
- **Pickup**: an extra shot filmed to fill a gap.
- **Wrap**: the end of shooting on the scene. A **struck** set has been taken down.
- **1st AD**: the first assistant director, who runs the shooting schedule on set and here approves a pickup or wrap.
- **DIT**: the digital imaging technician, who manages camera media and its records.
- **Release**: a person's signed permission to appear on screen; a visible asset needs a licence.
- **Turnover**: the handoff package that editorial receives.
- **UAT**: user acceptance testing, where a person works through written test cases.

Not film crews, not production teams, not creators. One person, one shoot day, one decision: is this scene ready to wrap, and if not, what exactly is missing and who can fix it while the set is still standing.

At the end of a shoot day, the evidence for that call sits in seven places: the current script revision, the shot plan, the captured takes, the supervisor's notes, the camera and sound reports, the continuity references, and the rights ledger. Nobody holds all of it at once. The task is to make missing or conflicting records visible while a human can still review them. No observed time saving, avoided pickup cost or production benefit is claimed. The fictional demo day plants six such problems on purpose; see [What the demo shows](#what-the-demo-shows).

## How Strands is load-bearing

Remove the Strands Agents SDK and four things disappear at once: the orchestration loop, the tool calls, the two human approvals, and the resume that makes an overnight approval possible. What is left is a script that cannot stop and wait for a person.

The capability the product is built on is **interrupt and resume across process death**:

- Inside a terminal tool, `ToolContext.interrupt(name, reason=...)` stops the run, and the agent returns `stop_reason` of `interrupt`.
- A session manager saves the paused run: `FileSessionManager` offline, `S3SessionManager` on Lambda, where `/tmp` does not survive the night.
- A **different process**, hours later, calls the agent with an `interruptResponse`, and the run continues from the same point.

On a set this is not academic. The checkpoint finds a coverage gap at 23:10 as the crew is wrapping. The 1st AD is not looking at a screen. They approve at 06:40 before the first setup, and the run resumes across a process that no longer exists.

**The flow, from question to governed write and back**

```mermaid
sequenceDiagram
    autonumber
    participant RQ as CLI or API route
    participant OR as Orchestrator<br/>(Strands)
    participant GA as Deterministic gate
    participant AD as 1st AD

    Note over RQ,GA: The request records<br/>scene.wrap-checkpoint.requested<br/>on the event bus, then starts<br/>the orchestrator itself.<br/>No EventBridge rule or subscriber<br/>routes events today.
    RQ->>OR: start the<br/>checkpoint run
    OR->>OR: run all four required checks,<br/>findings, each citing<br/>a source digest
    OR->>GA: evaluate
    GA-->>OR: not eligible,<br/>4 causes,<br/>one per check
    OR->>AD: request_pickup_approval(B-17)
    Note over OR,AD: The run STOPS. The process exits.<br/>23:10, the crew is wrapping.
    AD-->>OR: approved
    Note over OR,AD: 06:40 the next morning.<br/>A different process resumes here.
    OR->>OR: publish pickup.requested<br/>(idempotent, with receipt)
    RQ->>RQ: a late take or release<br/>reruns its listed checks
    Note over RQ,OR: Inside the API route,<br/>without the orchestrator.
    RQ->>RQ: publish<br/>take.captured or<br/>rights.record.updated
    RQ->>GA: evaluate again, after the role decisions
    GA-->>AD: wrap.eligible with<br/>the gate's counts,<br/>not the headline<br/>sentence
    AD->>OR: approve wrap
    OR->>OR: publish wrap.ready,<br/>which nothing subscribes to
    AD->>RQ: Publish approved turnover (POST /api/turnover)
    RQ->>RQ: publish<br/>turnover.generated<br/>by publish_turnover,<br/>sealed and verifiable
```

How this is proved:

- The ci.yml job "interrupt survives process death" runs `lasttake checkpoint` and `lasttake approve --yes --hours 7.5` as two separate `run:` steps, which are two operating system processes. No step compares the two process ids. Its last step deletes `.lasttake/sessions` and requires `lasttake approve --yes` to fail. That negative control runs after the only interrupt was already answered, so the command exits 1 even with the session left on disk, and the step does not show that resume needs the saved session. [Interrupt and resume across process death](docs/strands-interrupt-resume.md#in-ci-two-processes-and-a-negative-control) explains this and gives a local sequence that does isolate the session files.
- Every dispatched backend deploy fires the checkpoint in one HTTP request, retires every warm Lambda container with a configuration change, approves in a second request, and asserts `c1 != c2`. A run where Lambda reused a container fails the deploy.

**One design constraint this forced.** On resume the tool body re-enters from its first line and `interrupt()` returns the stored answer: a replay, not a frozen stack frame. So every approved action puts its external call after the interrupt, behind an idempotency key derived from the event payload; placed before it, the call would run twice. See [`src/lasttake/agents/tools.py`](src/lasttake/agents/tools.py), and [docs/strands-interrupt-resume.md](docs/strands-interrupt-resume.md) for the CI steps and the historical Lambda run.

## Architecture

The required diagram is a file of its own, [`docs/architecture.svg`](docs/architecture.svg), so it can be opened and downloaded without this README around it.

<img src="docs/architecture.svg" width="100%" alt="LastTake architecture: a React workspace served from S3 through CloudFront calls the API through API Gateway; a wrap checkpoint request starts an orchestrator on Lambda, four bounded checks read the scene package bundled with the function plus amendments stored on S3 and write findings to Aurora DSQL, a deterministic gate with no model in it combines them, two material transitions suspend the run for a named human, every run event is published to EventBridge, and a sealed, versioned turnover is saved for editorial.">

An interpreter answers exactly two language questions: does this take plausibly contain this beat, and do these two notes describe the same physical state. Everything else is compared and counted in code; see [How LastTake works](docs/how-it-works.md#where-an-interpreter-is-used-and-where-code-decides).

The system view, the eight tools and the repository layout are in [docs/how-it-works.md](docs/how-it-works.md). Every deployed resource and both release paths are in [docs/infrastructure.md](docs/infrastructure.md).

## The rule the whole product turns on

**It never infers a pass from absent evidence.** Absent evidence is a finding.

There are four truth states and there is no fifth. `verified`, `missing`, `conflicting`, `unknown`. Three of those are exceptions. There is no `pass`, no `clear`, no `safe`, and a test asserts there never will be.

The gate that combines them contains no model call, no heuristic and no randomness. It fails closed in eight ways, and each has a test that tries to make it fail open:

- a check that produced no result is a missing result, not a pass
- a check that produced two results is a contradiction, not a pass
- a finding that cites a source whose digest has since changed is discarded, not reused
- a finding whose seal does not verify is discarded
- a finding judged under any other policy version, older or newer, is discarded
- a decision bound to an older seal of its finding no longer counts
- an exception no authorised human has looked at is not a pass
- a decision taken by the wrong role is not weak evidence, it is no evidence

The last one is a table, not an `if`. A DIT may resolve a media identity question and may not accept a rights exception. Nobody at all may accept away a missing release, including the role that owns rights, because that decision belongs to production and counsel and not to this system.

## Try it without installing anything

[LastTake on AWS](https://d3kf6hquzlli8g.cloudfront.net/). No account or install is required for the fictional demo. The steps follow the order the tested browser journey uses.

1. Press **Start this fictional shoot day**, then **Run wrap checkpoint**. **Scene review** shows the lined script, the takes and the current exceptions, with the count above them. Missing evidence stays missing.
2. Set **Demo role** to **1st AD**, reload the page, and answer the saved pickup request. It survives the reload because the Strands run stopped at a real interrupt. A pickup does not approve wrap.
3. Press **Open guided demo**, then **Add take or release**. Press **Try valid take**, then **Save evidence & rerun checks**, to save a take for B-17. Press **Add take or release** again, set **Record type** to **Release / licence record**, press **Fill synthetic example** and save. That is the release BG-07 lacks, and no role may accept a missing release away.
4. As **Script supervisor**, record **Accept the exception** with a reason on continuity CR-01. As **DIT / data manager**, do the same on metadata T-013. Then, as **1st AD**, press **Review wrap readiness**. **Request wrap approval** appears once the gate reports eligible. Press it, inspect **Current package fingerprint · SHA-256**, and approve or decline.
5. In **Handoff**, press **Publish approved turnover**, set **Receipt purpose** to **Wrap review**, and press **Prepare receipt**. A delivery reads pending, accepted, rejected or unknown, and accepted means only that the event bus took the event.

In the **Add take or release** form, **Try refused date** loads a release with an impossible expiry date: saving it must return HTTP 400 and write nothing. A decision recorded before an evidence change stops applying, and its card says so. A run whose findings were judged under a different policy version (the current one is 1.1.0) shows **Fresh checkpoint required** with the reason. Every click, refusal and date example is in [docs/workspace-guide.md](docs/workspace-guide.md).

## What the demo shows

One fictional shoot day, made messy on purpose. Six things are wrong with it and each exercises a different part of the pipeline.

| What is wrong | Which check finds it | Who it goes to |
|---|---|---|
| B-17 was added in the Blue revision and never made the shot plan, so no camera rolled | coverage | script supervisor |
| Shot `S-42C-ORPHAN` plans for a beat the revision cut | coverage, advisory only | script supervisor |
| Two takes of B-23 are both flagged preferred and the mug does not match | continuity | script supervisor |
| T-013's media identifier does not match the camera report row | metadata | DIT |
| Background performer BG-07 is visible in a take and has no release record | rights | production coordinator |
| A late take arrives after the checkpoint | all four checks rerun, because each one cites the takes | nobody; the checks rerun by themselves |

Note the fourth row. T-013 has a real problem, and beat B-11 is still **covered**, because a second take of it is clean. A beat is covered when at least one take of it is usable, reconciles with the camera report, carries no unresolved continuity conflict and has every subject released. The coverage check's current finding for that beat must also be verified: a clean take whose coverage finding is absent or not verified still counts as no viable coverage. Treating "some take has a problem" as "the beat is missing" would report footage as absent that is sitting on the card.

## Quickstart

Prerequisites: Python 3.11 or newer, and git. No AWS account and no credential is needed for the offline path below, which exercises the real checks, the real gate and the real pickup approval. No CLI command requests wrap approval or publishes a turnover.

```bash
git clone https://github.com/upgradedev/lasttake-aws.git
cd lasttake-aws
python -m pip install -e ".[dev]"
```

The ci.yml job "interrupt survives process death" runs the checkpoint, approval, late take, release and event-log commands below as separate processes on pushes to `main`, `build/**` and `codex/**`, on every pull request and on manual dispatch.

**Step 1. Run a wrap checkpoint.** The command records the checkpoint event, then starts the orchestrator itself.

```bash
lasttake checkpoint
```

Expected: the four checks and the deterministic gate run, the count prints, and the run **stops** with a pickup request waiting for the 1st AD. The process then exits.

```
Of 34 required beats, 31 covered with evidence, 2 raising exceptions with named sources, 1 with no release record and routed to production.

[pid 2378] the run has stopped and is waiting for a human.
  who: first_ad
  what: pickup on B-17
```

**Step 2. The 1st AD answers, in a different process.** The first process is gone. Run this now, or tomorrow morning.

```bash
lasttake approve --yes
```

Expected: a new process picks the run up from exactly where it stopped, the waiting tool finishes, and the bus response is reported with its receipt. This does not establish a downstream action.

**Step 3. A late take arrives.** Every check cites the takes document, so all four rerun.

```bash
lasttake late-take --beat B-17
```

**Step 4. Production supplies the missing release.** Only rights reruns.

```bash
lasttake resolve rights --subject BG-07
```

Expected, run straight after Step 3:

```
rights.record.updated for BG-07. Affected checks: rights. Coverage, continuity and media identity keep their results.
Reran 7 rights check(s). The other 79 finding(s) still cite digests that have not moved, so the gate accepts them without a rerun.
```

The second line is fixed text. `resolve` counts every finding that is not a rights finding as carried and compares no digests (`src/lasttake/cli.py:356-367`), and the headline printed under it is counted from the saved findings without the gate. Straight after Step 2 that line holds. After Step 3 it does not. `resolve` rebuilds the package from `corpus/` without the late take T-041. The coverage, continuity and metadata findings written in Step 3 cite a takes digest that package no longer has, so the gate would discard them. B-17 prints as `no_viable_coverage` again.

**Step 5. Read the event log, and verify a turnover manifest.**

```bash
lasttake events
```

No CLI step writes a turnover. **Download turnover** on the workspace's **Handoff** page saves `<run id>-turnover.json`. Save it as `turnover.json`, and this re-hashes it against its own seal:

```bash
lasttake verify turnover.json
```

Run the test suite, including the gate's own failure proofs:

```bash
python -m pytest --cov --cov-report=term-missing
```

## Bring your own record

The page and the API take a take or release document you write.

For a session-owned run, set `URL=https://d3kf6hquzlli8g.cloudfront.net` and replace both placeholders below. `POST /api/session` returns your private `session_id`, and `POST /api/reset` with that `session_id` returns your `run_id`. Keep the `session_id` private: it grants access to your saved runs, so leave it out of shared examples, screenshots and logs.

```bash
curl -s -X POST "$URL/api/ingest" -H 'content-type: application/json' -d '{
  "run_id": "REPLACE_WITH_YOUR_RUN_ID",
  "session_id": "REPLACE_WITH_YOUR_PRIVATE_SESSION_ID",
  "kind": "take",
  "document": {
    "take_id": "T-900", "shot_id": "S-42-PICKUP", "beat_ids": ["B-17"],
    "slate": "42L/1", "camera_roll": "A007", "sound_roll": "SR07",
    "timecode_in": "23:04:00:00", "timecode_out": "23:04:41:00",
    "lens_mm": 50, "media_id": "A007R2G01",
    "preferred": true, "usable": true,
    "note": "Pickup on the reaction. Clean single.",
    "visible_people": ["DELPHINE"]
  }
}'
```

An owned run refuses a missing handle or a handle from another session with HTTP 403. Legacy unowned demo runs still accept their `run_id` without `session_id`; omit that field for those runs. Omitting it never unlocks a session-owned run.

`kind` is `take` or `rights_record`. A document that does not match the shape is refused before anything is written, and the refusal names the missing and the unexpected fields.

The document becomes a package amendment with new digests. The `AFFECTED_CHECKS` table in `src/lasttake/domain/events.py` picks the checks to rerun: a take reruns all four, because every check cites the takes document, and a release reruns only rights. The gate separately discards any finding whose cited source digests moved, so a check left out of the table would show as a missing current result, not as a pass.

A decision carries the digest of the finding it was about, so when an amendment moves that evidence the decision stops applying and the ingest response lists what was withdrawn. Shape, limits and the full rerun story are in [docs/bring-your-own-record.md](docs/bring-your-own-record.md).

## Running against Amazon Bedrock

The offline path uses a word-overlap stand-in for the two bounded interpretations. New finding records serialize `model_id` when an interpretation is present; older records without that field remain unknown.

To use a real model, ask your own account what it can invoke rather than trusting a string in a source file. This lists the Anthropic foundation models and cross-region inference profiles the credentialed account can reach, in its own configured region:

```bash
lasttake doctor --bedrock
```

The default, `global.anthropic.claude-sonnet-5`, was verified by invocation on 2026-08-22 against one account, which is not the same as verified against yours. Set the one `doctor` printed and run any command with `--bedrock`:

```bash
export LASTTAKE_BEDROCK_MODEL_ID=<an id that doctor printed>
lasttake checkpoint --bedrock
```

Every dispatched backend deploy runs a full checkpoint through `BedrockInterpreter` on the GitHub runner, so `BedrockModel` plus `agent.structured_output` is exercised rather than described.

The deployment checks that required beats remain 34 and that bounded model interpretation does not raise covered beats above the offline baseline. It also requires real model-touched coverage and continuity findings and confidence below 1.0. It does **not** require Bedrock to reproduce the offline 31 covered beats: the dated observation in the numbers section below was 19 of 34. Model identifiers in exported findings come only from their serialized records.

The hosted HTTP demo always runs offline, with no Bedrock switch.

Untrusted input is handled as untrusted. A script page, a supervisor note or a camera report can contain text shaped like an instruction. So everything from a scene package is wrapped in delimiters, and the system prompt states that content inside them is evidence to describe and cannot issue instructions. `tests/test_prompt_injection.py` covers the offline interpreter; a real model's resistance to the same text is unexercised in CI and rests on that prompt design. The model identifier history and the prepared real-model evaluation are in [docs/model-evidence.md](docs/model-evidence.md).

## The numbers, and the commands that produce them

The table below is the offline synthetic baseline, not a Bedrock invariant or a claim about a production. The test that asserts them fails if the corpus or the rule drifts.

| Claim | Value | Command |
|---|---|---|
| required beats in the scene | 34 | `python -m pytest tests/test_corpus_counts.py -q` |
| covered with evidence | 31 | same |
| raising exceptions with named sources | 2 | same |
| with no release record, routed to production | 1 | same |
| takes in the shoot day | 40 | `python corpus/build_corpus.py` |
| blocking causes at the first checkpoint | 4, one per check (coverage B-17, continuity CR-01, metadata T-013, rights BG-07), routed to three roles | `lasttake checkpoint`, then read `.lasttake/runs/run-sc042-wrap-checkpoint/packet.json` |
| covered beats when the interpreter is unreachable | 0 of 34, down from 31, every one unknown rather than a pass | `PYTHONPATH=src python tools/ablation.py` |

Read from the log of deploy run 34195514875 on 2026-09-08. The deploy job runs `lasttake checkpoint --bedrock` on the GitHub runner with the AWS access keys that `infra/setup_ci_identity.py` issues to the `lasttake-ci` IAM user, not with the Lambda execution role, and prints the count.

| Interpreter | Covered, of 34 |
|---|---|
| `offline-lexical/1.0.0`, which the live URL runs | **31** |
| `bedrock:global.anthropic.claude-sonnet-5` | **19** |

Neither count establishes correctness without labelled ground truth. What the production declared does not move; a stricter reader corroborates less of it, and most takes carry no supervisor note. The basis behind each count is in [Model evidence](docs/model-evidence.md#what-covered-rests-on-and-why-two-readers-count-differently).

`PYTHONPATH=src python tools/evaluation_cases.py` runs a correct, an incomplete, a conflicting and a changed input through the pipeline offline, and a test pins all four outcomes. **These are our cases, scored by our pipeline.** They describe behaviour, not judgement quality against labelled ground truth, and **no practising script supervisor has run any of it**.

`PYTHONPATH=src python tools/measure.py` holds a baseline and expected outcomes written before the run, and reports a case that disagrees as a failure. Human active time, interruptions, corrections and Bedrock inference cost are deliberately not measured. Both harnesses are described in [docs/evaluation-harness.md](docs/evaluation-harness.md).

**Known failure.** At this commit `tools/measure.py` reports 7 of 8 cases matching and exits 1, because its retry-and-recovery expectation predates commit 911fa59 and has not been corrected; no workflow runs it. Run from the repository root, it also overwrites `docs/measurement.json`, so restore that file with `git checkout -- docs/measurement.json`. Details are in [Evaluation harness](docs/evaluation-harness.md#a-baseline-written-before-the-run).

## What is deployed, and what it costs

Two CloudFormation stacks run in eu-west-1:

- **Backend, stack `lasttake-app` from [`infra/stack.yaml`](infra/stack.yaml):** an API Gateway HTTP API, one arm64 Lambda running Strands, Aurora DSQL for run state, one S3 data bucket and one EventBridge bus. These five backend services are declared in `infra/stack.yaml` and deployed by `.github/workflows/deploy.yml`, only when an owner dispatches it with action `deploy`.
- **Frontend, stack `lasttake-frontend` from [`infra/frontend_stack.py`](infra/frontend_stack.py):** a private S3 site bucket that CloudFront reads through origin access control; `/api/*`, `/api` and `/healthz` go uncached to the HTTP API. Every push to main, docs included, publishes the site and runs live Playwright acceptance (`frontend-deploy.yml`).

The CloudFront frontend stack and the CI identities are set up outside any workflow: the owner provisions `infra/frontend_stack.py` once and runs `infra/setup_ci_identity.py` by hand.

```mermaid
flowchart TB
    subgraph BE["Backend · stack.yaml"]
        api["API Gateway<br/>HTTP API"]
        fn("Lambda · arm64<br/>Strands Agents SDK<br/>role may invoke Bedrock<br/>hosted demo does not")
        dsql[("Aurora DSQL<br/>findings, decisions,<br/>packets, audit,<br/>handled events")]
        data[("S3 data bucket<br/>sessions,<br/>amendments,<br/>events, turnovers")]
        bus(["EventBridge bus<br/>every run event,<br/>no subscriber built,<br/>no rule declared"])
    end
    subgraph FE["Frontend · frontend_stack.py"]
        browser["Browser<br/>no account"]
        cf["CloudFront distribution<br/>/api/*, /api, /healthz<br/>to HTTP API, uncached"]
        site[("S3 site bucket<br/>private, static files")]
    end
    browser --> cf
    cf --> site
    cf --> api
    api --> fn
    fn <--> dsql
    fn <--> data
    fn ---> bus

    %% LastTake palette: role colour fill, navy ink pinned, so node text reads the same in GitHub light and dark
    classDef surface fill:#8b95b8,stroke:#0b0f1e,stroke-width:1.5px,color:#0b0f1e
    classDef agent fill:#7ea4f7,stroke:#0b0f1e,stroke-width:1.5px,color:#0b0f1e
    classDef store fill:#4fc3a1,stroke:#0b0f1e,stroke-width:1.5px,color:#0b0f1e
    classDef event fill:#a996ea,stroke:#0b0f1e,stroke-width:1.5px,color:#0b0f1e
    classDef laneFront fill:#8b95b81f,stroke:#7d88aa,stroke-width:1px
    classDef laneBack fill:#7ea4f71f,stroke:#7d88aa,stroke-width:1px
    class browser,cf,api surface
    class fn agent
    class site,dsql,data store
    class bus event
    class FE laneFront
    class BE laneBack
```

Two approvals of the same pickup arriving together become one `INSERT ... ON CONFLICT DO NOTHING` on DSQL, so the pickup is not requested twice. `/healthz` reports `run_state_store`, and the backend deploy fails unless it reads `aurora-dsql`, so a silent fall back to S3 cannot pass.

**Costs and timing.** No measured invoice, human-active time or savings are claimed. AWS charges and quotas depend on the account and request pattern; CI timings are validation timings, not time saved for a crew. The receipt exposes measured publication elapsed time without treating it as human time.

**Tearing it down.** An owner runs `gh workflow run deploy.yml -f action=teardown` to delete the backend stack. The data bucket and the Aurora DSQL cluster are retained on purpose (`DeletionPolicy: Retain`), because they hold the audit trail; empty them deliberately if you want them gone.

Resources and their settings, least privilege, and why DSQL and an HTTP API were chosen are in [docs/infrastructure.md](docs/infrastructure.md). Releases and scheduled live checks are in [docs/release-and-acceptance.md](docs/release-and-acceptance.md).

## What it will not do

It is a second set of eyes and an integrity layer. It replaces nobody.

It may not judge creative quality or choose a performance. It may not declare a scene legally cleared, safe or creatively complete. It may not approve a pickup, a wrap, a schedule, a spend, a permit or an external communication. It may not edit or delete original media. And it may not infer a pass from absent evidence.

A rights row reading `verified` means the expected record was found and its structured fields matched the configured policy. It is not a legal opinion and it does not state that a use is lawful. Counsel determines sufficiency. That sentence is printed on the face of every turnover packet, not buried here.

## The demo corpus is synthetic

THE LAST FERRY is a fictional production. Every person, place, identifier and record in `corpus/` is invented for this demonstration: no real production data, no real person's release, and no footage. `python corpus/build_corpus.py` is deterministic, with no clock and no randomness, so the digests are stable; CI regenerates the corpus and fails if the committed files differ.

## Assurance and residual gaps

[`docs/assurance.md`](docs/assurance.md) holds three tables: AWS Well-Architected across six pillars plus the Agentic AI Lens, the EU AI Act articles this class of system has to answer for, and what is done with personal data.

Every row of the Well-Architected and EU AI Act tables names a residual gap, and none is empty; the data-protection table answers questions and has no residual-gap column. The residual gaps include:

- no measured AWS latency p95
- no restore drill
- real-model evaluation is NOT_RUN: a 16-case synthetic development set with assistant-authored gold labels is prepared, but no real model has been scored on it, so accuracy is unmeasured
- no staff authentication on the public endpoint, by design
- long-lived access keys for the backend deploy, although the frontend release already uses GitHub OIDC
- no practising script supervisor has run it

The page does not claim that the system meets any regulation, and `tools/prose_gate.py` fails the build on words that would. That judgement belongs to an assessment body, not to the people who wrote the system.

## Documentation

| Page | What it answers |
|---|---|
| [How LastTake works](docs/how-it-works.md) | The system view, the eight tools, where code decides instead of an interpreter, and the repository layout |
| [Interrupt and resume across process death](docs/strands-interrupt-resume.md) | The CI steps and negative control, the historical Lambda run across two containers, and where the pattern lives in code |
| [Using the LastTake workspace](docs/workspace-guide.md) | The full walk of the live site, page by page, with its refusals, sessions and saved runs |
| [Bring your own record](docs/bring-your-own-record.md) | The document shape, limits on a supplied record, what reruns, and why an approval goes stale |
| [Evaluation harness](docs/evaluation-harness.md) | The baseline written before the run, the rule-removal probes, four kinds of input, and the source hero measurement |
| [Model evidence: what has run and what has not](docs/model-evidence.md) | Bedrock on the deploy runner, why two readers count covered beats differently, and the real-model evaluation that has not run |
| [Infrastructure](docs/infrastructure.md) | Every deployed resource with its file and line, both release paths, least privilege, and teardown |
| [Releases and acceptance evidence](docs/release-and-acceptance.md) | How the frontend and backend are released, what the public receipt requires, scheduled checks and dated journey counts |
| [Assurance](docs/assurance.md) | Well-Architected and EU AI Act rows with their residual gaps, and how personal data is handled |
| [LastTake: optional AgentCore design notes](docs/BEDROCK_AGENTCORE_ARCHITECTURE.md) | A design proposal for a move onto Bedrock AgentCore; nothing in it is deployed |
| [architecture.svg](docs/architecture.svg) | The required architecture diagram, as a file of its own |

Evidence files in `docs/`:

- `measurement.json` and `evaluation_cases.json` are written by `tools/measure.py` and `tools/evaluation_cases.py`.
- `ablation.json` is historical, and `tools/ablation.py` no longer overwrites it.
- `hero-measurement-protocol.json`, `model-evidence-protocol.json`, `model-evidence-cases.json` and `model-evidence-gold.json` were committed before their instruments. The three model-evidence files have not changed since. The hero protocol was edited once afterwards (9b9584c, 2026-09-13) to restore spaces inside its text strings. It was measured once, in [run 34481212393](docs/evaluation-harness.md#historical-measured-cohort-2026-09-10) on 2026-09-10, and its status field still reads `PREREGISTERED_NOT_MEASURED`.
- `model-evidence-inventory.json` records the spent-evidence inventory.
- Unpublished drafts: `build_stories.json` holds three and is written by no tool, and `submission_description.json` is the submission description draft.

## Pre-existing components

Required disclosure. The historical component disclosures below are retained. The optional video tooling also retains its source-kit provenance in its file headers; none of its original upstream records was removed. Current video source is NOT_CONFIGURED, which means the video pipeline is not set up to run: its preflight fails on purpose until the owner provides narration credentials and verifies exact-release capture and timing. No candidate recording is claimed.

| Component | Where it came from | What was carried |
|---|---|---|
| `src/lasttake/domain/sealing.py` | ClaimScene, MIT, same author, `src/claimscene/provenance.py` | `sha256_bytes`, `canonical_json`, and the sealed-record approach. About thirty lines of primitives, plus the idea of sealing a record with the digest of its own canonical JSON. ClaimScene shares them with Cinemory. |
| The product thesis | A private research package written 2026-07-28 by the same author, 2,365 lines across 13 files: the problem definition, the user roles, the four truth states, the finding contract, and the event list | Carried as specification, not as code. Every line of implementation here is new. |
| CI shape, and the README's original structure | A private submission toolkit by the same author | Workflow layout, which CI still follows. The README followed the toolkit's section ordering until 2026-09-14, when its sections were regrouped by reader task. |
| Production workspace visual direction | Kerdon interface and the owner's approved workspace reference | Visual inspiration only: deep navy panels, amber LastTake accents, compact navigation and connected context/evidence/decision panes. Implemented here with existing React, TypeScript and Tailwind dependencies. No Kerdon customer data, tenant configuration, source IDs, assets or dependency code was reused. |

The AWS adapters, the Strands agent definitions, the deterministic gate, the checks, the demo corpus and the CLI are all new.

## Licence

MIT. See [LICENSE](LICENSE).
