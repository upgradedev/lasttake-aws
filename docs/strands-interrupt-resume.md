# Interrupt and resume across process death

This page is for a judge checking the Strands claim and for an engineer who wants to reuse the
pattern. It expands [README, How Strands is load-bearing](../README.md#how-strands-is-load-bearing):
what stops the run, where the paused run is kept, the two proofs and what each one shows, the
replay constraint, and where each piece lives in the code.

## What stops, and what resumes

The specific capability the product is built on is **interrupt and resume across process
death**. Inside each of the two approval tools, `ToolContext.interrupt(name, reason=...)` stops
the run. The agent returns `stop_reason` of `interrupt`. A session manager writes the paused run
to storage. A **different process**, later and possibly hours later, calls the agent with an
`interruptResponse` and the run continues from the same point.

On strands-agents 1.53.0, the minimum `pyproject.toml:13` requires, the signature is
`ToolContext.interrupt(self, name: str, reason: Any = None, response: Any = None)`. It was printed
on 2026-09-14 by `python -c "import inspect; from strands.types.tools import ToolContext; print(inspect.signature(ToolContext.interrupt))"`.

The run can be stopped and resumed from the command line or through the HTTP API:

| | Command line | HTTP API on Lambda |
|---|---|---|
| Stops the run | `lasttake checkpoint` stops at the pickup approval (`cli.py:135-178`). No CLI command requests wrap approval. | `POST /api/checkpoint` stops at the pickup approval (`handler.py:275-310`). `POST /api/wrap` without an interrupt id stops at the wrap approval (`handler.py:535-536`). |
| Where the paused run is saved | `FileSessionManager` in `.lasttake/sessions` (`orchestrator.py:221-226`) | `S3SessionManager` under the `sessions/` prefix of the data bucket (`handler.py:155-169`) |
| How the interrupt id travels | Read back from the session files (`cli.py:212-227`), or passed with `--interrupt-id` | Returned as `pending_approval.id` (`handler.py:221-226`, `:299-302`) and sent back as `interrupt_id` |
| Resumes the run | `lasttake approve --yes` (`cli.py:181-209`) | `POST /api/approve` or `POST /api/wrap` with an interrupt id (`handler.py:314-335`, `:510-533`) |

The checkpoint request, from the command or from `POST /api/checkpoint` behind the **Run wrap
checkpoint** button, publishes `scene.wrap-checkpoint.requested` and then starts the orchestrator
itself in the same process (`cli.py:145-151`, `handler.py:278-286`). No EventBridge rule routes
that event: `infra/stack.yaml:130-136` declares the bus and nothing that subscribes to it.

Both approvals are addressed to the 1st AD. The interrupt is named `first-ad-pickup-approval` or
`first-ad-wrap-approval` (`tools.py:92`). `publish_approved` refuses a payload whose
`approved_by_role` is not `first_ad` (`runtime.py:179-180`), but both approval tools set that
field to `first_ad` themselves (`tools.py:287`, `:349`), so that check does not show who answered.
Only a session-owned HTTP run checks the role the answer claims (`workspace.py:162-163`). The CLI
(`cli.py:181-209`) and HTTP runs with no owner (`workspace.py:72-75`) check no role at all. Even
on an owned run, that role is a claim in the request, not an authenticated identity.

What resumes is the saved Strands session. On the deployed stack, findings, decisions,
eligibility packets and the audit trail are stored in Aurora DSQL (`dsql.py:193-334`), but a
paused run resumes after a container restart from its session on S3, not from DSQL. LastTake
computes no digest over the session it saves (`handler.py:164-168`). Session objects under
`sessions/` expire 90 days after they are written (`infra/stack.yaml:72-75`).

## In CI: two processes and a negative control

The job named `interrupt survives process death` (`ci.yml:254-293`) runs with the rest of
`ci.yml`: on pushes to `main`, `build/**` and `codex/**` (`ci.yml:7-9`), on every pull request
(`ci.yml:11`), and on manual dispatch (`ci.yml:13`). A push to any other branch does not run it.
The job has no condition of its own. Each `run:` step starts a new shell, so
each command below runs in its own operating system process (the comment at `ci.yml:265-267`
says so).

| Step name in ci.yml | What it runs | Lines |
|---|---|---|
| `install` | `python -m pip install -e .` | 262-263 |
| `process 1  ·  23:10, the checkpoint stops at the 1st AD` | `lasttake checkpoint` | 268-269 |
| `what survived on disk between the two processes` | `find .lasttake/sessions -type f \| sort` | 271-272 |
| `process 2  ·  06:40, a new process resumes the same run` | `lasttake approve --yes --hours 7.5` | 274-275 |
| `the late take arrives, and only the affected checks rerun` | `lasttake late-take --beat B-17` | 277-278 |
| `production supplies the missing release` | `lasttake resolve rights --subject BG-07` | 280-281 |
| `the event log, end to end` | `lasttake events` | 283-284 |
| `negative control  ·  wipe the session, resume must FAIL` | `rm -rf .lasttake/sessions`, then `lasttake approve --yes` must exit non-zero | 286-293 |

Apart from the commands' own output, the job writes one line. When the control holds it prints
this (`ci.yml:293`):

```text
NEGATIVE CONTROL HELD: with the session wiped, there is nothing to resume.
```

If `lasttake approve --yes` succeeds instead, the job prints
`NEGATIVE CONTROL FAILED: resumed with no session on disk.` and exits 1 (`ci.yml:289-291`).

**What process 2 has to work with.** Process 2 shares nothing with process 1 except the
`.lasttake` directory in the checkout. It finds the pending interrupt id in the session files
(`cli.py:197`, `:212-227`). It builds a new agent on the same `FileSessionManager` directory
(`cli.py:189`) and answers with an `interruptResponse` (`cli.py:202`). If no interrupt is found,
the command exits 1 (`cli.py:198-200`). If Strands cannot resume, it raises. Either way the step
fails. In a local run, the `find` step lists `session.json` under
`session_run-sc042-wrap-checkpoint/`, and `agent.json` plus one `messages/message_N.json` file per
message under its `agents/agent_default/`.

**What this job does not show.**

- The times in the step names are labels. The steps run back to back, and `--hours 7.5` only
  changes the banner text (`cli.py:186`, `:510`). Nothing waits.
- No step compares the two process ids or checks the approval message. The checkpoint and the
  approval each print a `[pid N]` line (`cli.py:117`, `:187`), so the ids can be read in the log,
  but nothing asserts them.
- The late-take step name says only the affected checks rerun. For a new take that is all four
  checks, coverage, continuity, metadata and rights, not a narrower set, because each check
  cites the takes (`events.py:129-130`, the comment at `cli.py:283-287`). The four reruns are at
  `cli.py:293-298`.
- The negative control runs after process 2 has already answered the only interrupt. At that
  point `lasttake approve --yes` exits 1 with `Nothing is waiting for a decision.` even when the
  session is left in place. A local run on 2026-09-14 showed this by running the job's commands
  in its order (`checkpoint`, `approve --yes --hours 7.5`, `late-take --beat B-17`,
  `resolve rights --subject BG-07`, `events`) and then `approve --yes` without the wipe. So this
  step shows that the CLI refuses when it finds nothing to resume. On its own, it does not show
  that the session files are what let process 2 resume. The step also sends stderr to `/dev/null`
  and checks only for a non-zero exit (`ci.yml:289`), so any failure, a crash included, prints the
  same `NEGATIVE CONTROL HELD` line.

**A local run that does isolate the session files.** Run from the repository root:

```sh
lasttake checkpoint
mv .lasttake/sessions sessions.saved
lasttake approve --yes --interrupt-id "$TOKEN"
rm -rf .lasttake/sessions
mv sessions.saved .lasttake/sessions
lasttake approve --yes --interrupt-id "$TOKEN"
```

`$TOKEN` holds the `correlation token` value the checkpoint prints (`cli.py:124`).

1. With the session files moved away, the first approve exits 1. Strands refuses with
   `ValueError: Received interrupt responses but agent is not in interrupt state.`
2. That attempt also leaves a new, empty session behind, which the `rm -rf` clears.
3. With the saved files back, the same command resumes the run in a new process and prints
   `Pickup approved for B-17 by the 1st AD.`

This was run on 2026-09-14 on this branch with strands-agents 1.53.0, with `LASTTAKE_WORKDIR`
pointed at a scratch folder.

## On Lambda: two requests, two containers, historical

**Historical cross-process evidence, recorded on 2026-08-22. It is not acceptance of the current
release.**

On a Lambda, `/tmp` does not survive the gap between 23:10 and 06:40, so the sessions live on
`S3SessionManager`. The manually dispatched backend deploy fires the checkpoint in one HTTP
request, then **retires every warm container** with a configuration change, then approves in a
second request, and asserts the two were served by different processes:

```text
=== request 1 of 2: fire the checkpoint ===
Of 34 required beats, 31 covered with evidence, 2 raising exceptions with named
sources, 1 with no release record and routed to production.
stopped for: first_ad on B-17
served by container 5783cd7e

=== between the two: force a new execution environment ===
every warm container has been retired

=== request 2 of 2: a separate invocation approves ===
Pickup approved for B-17 by the 1st AD and routed to the assistant director's board.
container that stopped the run:  5783cd7e
container that resumed it:       0310464e
```

The transcript above is retained as historical output. Its old "routed to the board" wording did
not prove downstream delivery. Current tools report bus acceptance explicitly.

The assertion is `c1 != c2`, so a run where Lambda happened to reuse a container fails the
pipeline rather than quietly passing on a weaker claim.

The transcript carries no run id. It entered the README in commit `3f2296d` on 2026-08-22.

**How the same step runs today.**

- **The step.** It is `the hero, on the deployed architecture` (`deploy.yml:233-331`), with
  `assert c1 != c2` at `deploy.yml:314`.
- **When it runs.** The step belongs to the deploy job, which runs only when someone dispatches
  the workflow by hand with action `deploy` (`deploy.yml:11-18`, `:38`). It also needs deploy
  credentials to be configured (`deploy.yml:48`, `:234`). A push to main that touches `src/**`,
  `corpus/**` or `infra/stack.yaml` starts the workflow but not this job (`deploy.yml:19-26`).
  The workflow was set up differently at commit `3f2296d`: the deploy job's only condition was
  `inputs.action != 'teardown'`, so that version also ran the job on those pushes. The
  dispatch-only condition arrived in commit `1a84e86` on 2026-09-10. See
  [Backend release by manual dispatch](release-and-acceptance.md#backend-release-by-manual-dispatch).
- **What `c1` and `c2` are.** Every API response carries `served_by.container_id`, a random
  eight-character id chosen once when a Lambda container loads the handler (`handler.py:69`,
  `:175-185`). The approval request builds a new agent from the S3 session (`handler.py:314-321`,
  `:155-169`).
- **How the cold start is forced.** The step changes only the function description and waits for
  the update (`deploy.yml:285-290`). It then checks that `/healthz` still reports `aurora-dsql`
  (`deploy.yml:293-297`).
- **What else it asserts.** The approval message must contain `Pickup approved` and
  `Bus accepted` (`deploy.yml:307`). There must be exactly one accepted `pickup.requested`
  receipt (`deploy.yml:308-309`), and run state must be on Aurora DSQL (`deploy.yml:310`).
  `Bus accepted` means EventBridge accepted the event. The repository declares no rule or target
  for the bus (`infra/stack.yaml:130-136`), so this shows acceptance by the bus, not delivery to
  anyone.
- **Its output today.** It also prints the counts, the Lambda request id and a configuration line
  that the 2026-08-22 transcript does not have (`deploy.yml:258`, `:262`, `:297`).
- **The test that keeps it.** `tests/test_claim_drift.py:86-92` fails if `assert c1 != c2`, the
  receipt assertion or the Aurora DSQL assertion disappears from `deploy.yml`.

## Replay, not a frozen stack frame

**One design constraint this forced, found before the build rather than during it.** On resume
the tool body re-enters from its first line and `interrupt()` returns the stored answer. It is a
replay, not a frozen stack frame. So anything with a side effect placed before the interrupt runs
twice. Every approved action in this repository puts its external call after the interrupt,
behind an idempotency key derived from the event payload. See `src/lasttake/agents/tools.py`.

- **Where it is written down.** The module docstring records the rule and says it was found in a
  spike on 2026-08-22 (`tools.py:8-14`).
- **The boundary in the pickup tool.** In `request_pickup_approval` the boundary is a comment
  (`tools.py:250-251`). Above it, the tool only looks up the beat (`tools.py:246-248`). Below it
  and before the answer, it loads or builds the approval record (`tools.py:252`) and, on the first
  raise only, saves that record and an audit entry (`tools.py:93-96`). After the answer it
  publishes `pickup.requested` (`tools.py:281-290`).
- **The saved review.** The review record the 1st AD answers is saved when the interrupt is first
  raised, and reloaded on replay rather than rebuilt (`tools.py:75-100`).
- **The idempotency key.** The key is a digest of the event type, production, scene, payload and
  correlation id (`events.py:78-88`). Before publishing, the run also claims the logical action
  (event type, run and beat), so an unresolved earlier attempt blocks a resend
  (`runtime.py:69-79`, `:116-123`). An accepted receipt is saved and handed back on a repeat
  (`runtime.py:70-71`, `:98-100`).
- **What it covers.** `pickup.requested` and `wrap.ready` (`runtime.py:177-192`), and
  `turnover.generated` (`tools.py:396-400`). Gate evaluation and its `wrap.eligible` event are
  not deduplicated (`tools.py:210-216`).
- **A stale wrap request.** A resumed wrap request still reaches `interrupt()` so it can be
  declined (`tools.py:308-311`). `wrap.ready` is refused if the evidence changed after the review
  (`runtime.py:181-182`).
- **The test.** `tests/test_end_to_end.py:66-92` stops a run, resumes it with a second agent
  object built on the same session, and asserts that exactly one `pickup.requested` was
  published.

## Where it lives in the code

For the full list of tools the orchestrator calls, see
[The orchestrator and its eight tools](how-it-works.md#the-orchestrator-and-its-eight-tools).

| What | Where |
|---|---|
| Pickup approval tool, `@tool(context=True)` | [src/lasttake/agents/tools.py:233-296](../src/lasttake/agents/tools.py#L233) |
| Wrap approval tool, `@tool(context=True)` | [src/lasttake/agents/tools.py:298-356](../src/lasttake/agents/tools.py#L298) |
| The `interrupt()` call both tools share | [src/lasttake/agents/tools.py:87-100](../src/lasttake/agents/tools.py#L87), the call at `:90` |
| The replay rule, written down | [src/lasttake/agents/tools.py:8-14](../src/lasttake/agents/tools.py#L8), and the comment at `:248-249` |
| The external effect, after the answer | [src/lasttake/agents/runtime.py:177-192](../src/lasttake/agents/runtime.py#L177) |
| Idempotency key and logical-action claim | [src/lasttake/domain/events.py:78-88](../src/lasttake/domain/events.py#L78) and [src/lasttake/agents/runtime.py:116-123](../src/lasttake/agents/runtime.py#L116) |
| Local session store, `FileSessionManager` | [src/lasttake/agents/orchestrator.py:221-226](../src/lasttake/agents/orchestrator.py#L221), used by `cli.py:150` and `:189` |
| Deployed session store, `S3SessionManager` | [src/lasttake/app/handler.py:155-169](../src/lasttake/app/handler.py#L155) |
| `build_s3_session_manager`, a helper with no caller today; its docstring says the handler uses it, but the handler builds its own `S3SessionManager` | [src/lasttake/agents/orchestrator.py:236-246](../src/lasttake/agents/orchestrator.py#L236) |
| Resume with `interruptResponse` | [src/lasttake/cli.py:202](../src/lasttake/cli.py#L202), [src/lasttake/app/handler.py:321-330](../src/lasttake/app/handler.py#L321) and `handler.py:519-528` |
| Container id on every response | [src/lasttake/app/handler.py:69](../src/lasttake/app/handler.py#L69) and `:175-185` |
| Session files expire at 90 days | [infra/stack.yaml:72-75](../infra/stack.yaml#L72) |
| CI job `interrupt survives process death` | [.github/workflows/ci.yml:254-293](../.github/workflows/ci.yml#L254) |
| Deploy step, with `assert c1 != c2` at `:314` | [.github/workflows/deploy.yml:233-331](../.github/workflows/deploy.yml#L233) |
| Test that keeps the deploy assertions | [tests/test_claim_drift.py:86-92](../tests/test_claim_drift.py#L86) |
| In-process resume tests | [tests/test_end_to_end.py:66-92](../tests/test_end_to_end.py#L66), [tests/test_handler.py:163-171](../tests/test_handler.py#L163) and [tests/test_cli.py:48-58](../tests/test_cli.py#L48) |
