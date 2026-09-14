# Evaluation harness

This page is for a judge or reviewer who wants to re-run an offline evidence claim and read its
declared limits. It expands
[README, The numbers, and the commands that produce them](../README.md#the-numbers-and-the-commands-that-produce-them).
Three of the four tools below run offline on the synthetic corpus, through our own pipeline; the
fourth, the hero benchmark, ran once in source CI. None of it is scored against independent ground
truth, and no practising script supervisor has run any of it.

| Tool | Command | What it writes | What pins it |
|---|---|---|---|
| `tools/measure.py` | `PYTHONPATH=src python tools/measure.py` | rewrites the repository's `docs/measurement.json` from any directory, keeping its `_current_scope` and `history` | nothing: no workflow or test runs it, and `tests/test_claim_drift.py` reads only the `_current_scope` note the tool carries forward |
| `tools/ablation.py` | `PYTHONPATH=src python tools/ablation.py` | stdout only | `tests/test_claim_drift.py`, `tests/test_corpus_counts.py` |
| `tools/evaluation_cases.py` | `PYTHONPATH=src python tools/evaluation_cases.py` | rewrites `docs/evaluation_cases.json` | `tests/test_corpus_counts.py` |
| hero benchmark | manual dispatch of `.github/workflows/frontend-ci.yml` on one branch | a CI artifact | `frontend/tests/hero-measurement.test.mjs` |

## A baseline written before the run

[`tools/measure.py`](../tools/measure.py) is the protocol, not a results file. The baseline, the
fixtures and every expected outcome are literals in the file (`BASELINE`, `DEVELOPMENT` and
`HELD_OUT`), written from the product's rules before anything ran. A case that disagrees with its
expectation is reported as a failure. It does not quietly become the new expectation. One case
has since been rewritten after a contract change and one expectation corrected, and both are
published below rather than absorbed.

```bash
PYTHONPATH=src python tools/measure.py
```

The baseline is the corpus as it ships, read by the offline lexical interpreter, with no human
decisions recorded. That is the configuration the hosted demo runs. A Bedrock count is a different
configuration and is reported separately in the
[README numbers section](../README.md#the-numbers-and-the-commands-that-produce-them).

Five development cases were used while building. Three held-out cases were written after the
behaviour was fixed and were not used to change it. That is weaker than a set somebody else wrote,
and the file labels it weaker.

| Set | Case | Expected outcome, as written in the file |
|---|---|---|
| development | ordinary | headline counts from `rollup.headline`: 34 required beats, 31 covered with evidence, 2 raising exceptions, 1 without a release record, 0 not assessed |
| development | missing evidence | 7 rights findings; BG-07 is the only subject with no release; 1 beat without a release record |
| development | changed input | a pickup take moves B-17 from `no_viable_coverage` to `covered_with_evidence`, and the gate discards the findings that cite the old takes digest |
| development | refusal | a take with no slate is refused and the refusal names `slate`; a wrong field type and a camera report row for another take are also refused |
| development | retry and recovery | the bus returns a definite rejection for the first publish, the retry publishes, a third call returns the saved receipt without reaching the bus, and the bus is called twice |
| held out | no interpreter reachable | 0 beats covered, 0 corroborated by the interpreter, 33 with basis `declared_by_the_production` |
| held out | a record edited in storage | the scene is not eligible, and the discard reason names the seal |
| held out | the missing release filed | 0 beats without a release record, 32 covered, 2 still raising exceptions |

**Retry and recovery was rewritten, not re-expected.** Run at this head on 2026-09-14, the command
reports all 8 cases matching and exits with status 0. Since commit 911fa59 (2026-09-09),
`WrapRun.publish` records a publish that raised as outcome unknown and refuses a resend until
someone reconciles it ([`src/lasttake/agents/runtime.py`](../src/lasttake/agents/runtime.py), lines
72-77 and 93-97). Only an accepted or rejected outcome releases the claim on the logical effect
(lines 110-113). The case used to make the first publish raise, so against that contract it saw no
raised error, no retry and one bus call instead of two: the unmodified tool at commit ab0a1d3, run
on 2026-09-14, reported 7 of 8 cases matching and exited with status 1. Setting the four expected
values to what it observed would have recorded a case named retry and recovery as matching when no
retry happened, so the scenario was replaced instead. The bus now returns a definite rejection and
then accepts, and a third call must return the saved receipt without reaching the bus. Those
expectations were written from the `WrapRun.publish` contract before the rewritten case first ran,
and `test_a_publish_that_fails_can_be_retried` in
[`tests/test_rerun_and_events.py`](../tests/test_rerun_and_events.py) pins the same sequence. The
retired scenario, its expectation and what it observed are kept in `REWRITES` in the tool. The tool
prints the rewrite, with the correction described below, in a section of its output headed
"Published rather than absorbed". No workflow or test runs `tools/measure.py`, so CI would not
catch a case that stops matching.

[`docs/measurement.json`](measurement.json) records a run of the rewritten tool in which all 8 cases
match, with a `rewrites` entry beside `corrections`. Its own scope line says: "Historical entries
below are preserved, not exact-current-release acceptance." Its `history` keeps two earlier runs.
The first is the file as committed at ab0a1d3 without its `_current_scope` block: 8 of 8, with retry
and recovery matching under the retired scenario. The second is the 7 of 8 run of the unmodified
tool at ab0a1d3. The tool reads `_current_scope` and `history` back from the committed file and
writes them again, and it writes the repository's `docs/measurement.json` whichever directory it
runs from, even when a case fails. Nothing appends to `history`: an entry is added by hand when a
contract change retires a case. Everything else is regenerated on each run, including each case's
measured `wall_seconds`.

Three fields are deliberately empty in every row. **Human active time, interruptions and
corrections are not measured, because no human was observed doing any of this.** The fields
`human_active_seconds`, `human_interruptions` and `human_corrections_of_the_output` are null, not
zero. A zero would read as "needed no help", and timing the model and calling the result human time
would be a fabricated benchmark. The harness does record wall time (`wall_seconds`) and counts
interpreter calls at the port (`interpreter_calls`). `cost_usd` is 0.0 because the offline
interpreter makes no model call. Bedrock inference cost is not measured: it needs per-call token
counts this harness does not collect.

One expectation was wrong on its first run, and the correction is published rather than absorbed
(`CORRECTIONS` in the tool, `corrections` in the JSON). Rights findings were declared as 6 and
observed as 7. The corpus has five people plus two visible assets, so the product was right and the
expectation never was. No product code was changed, and the two assertions that carry the meaning
held on the first run: BG-07 is the subject with no release, and it leaves 1 beat without a release
record.

## What each rule is worth, measured by removing it

These are synthetic protocol probes on the corpus, not measurements of human work or model
correctness. Each probe bypasses one rule and compares what the gate admits with and without it.

```bash
PYTHONPATH=src python tools/ablation.py
```

The tool prints a report and its rows as JSON to stdout, and writes no file. In the `verify` job of
[`frontend-ci.yml`](../.github/workflows/frontend-ci.yml), a step saves that stdout as
`frontend/test-results/claims/ablation.txt`, which is uploaded with the rest of
`frontend/test-results/` in the `frontend-evidence-` artifact for that commit (lines 226-229 and
285).

- **The seal probe** edits one stored finding, B-17, from missing to verified without resealing it,
  then compares the result with the same edit resealed.
- **The staleness probe** adds a pickup take. A deliberately wrong shortcut table says a new take
  affects coverage only, so the shortcut carries the other findings forward and re-stamps them with
  the new package revision. The real gate then evaluates them.
- **The model-outage probe** replaces every interpreter answer with "not reached" at confidence 0.

The results below are what the command prints at commit e92348b.

| Probe, as the tool names it | With the rule | Without it |
|---|---|---|
| the finding seal is not verified | the edited record is discarded and the reason is named | all 85 records are admitted and B-17 reads as covered: 1 tampered record admitted instead of 0 |
| staleness is asserted from a table instead of derived from digests | all 85 findings cite the takes digest from before the pickup, and all are discarded | the shortcut carries 50 stale findings; the gate still discards all 50, and `actually_admitted_stale` is 0 |
| the model cannot be reached | 31 of 34 beats covered with evidence | 0 of 34: the 31 beats lose their evidence, and their coverage findings read `unknown`, never a pass |

The seal is a SHA-256 digest, not a signature. It catches a record that was changed without being
resealed, and anyone who can rewrite the record can also recompute it.

**Carried stale records are not admitted stale records.** Re-stamping a package revision does not
change the source digests a finding cites, and the gate discards any finding whose cited source
digest has moved (`_admissible` in [`src/lasttake/domain/policy.py`](../src/lasttake/domain/policy.py)).
The table in the probe is deliberately wrong. The product's own table, `AFFECTED_CHECKS` in
[`src/lasttake/domain/events.py`](../src/lasttake/domain/events.py), chooses which checks rerun and
maps `take.captured` to all four. The digest rule is the separate safeguard: a table entry that
leaves out an affected check shows up in the eligibility result as a missing current result, not as
a pass. [bring-your-own-record.md](bring-your-own-record.md#what-reruns-and-why) walks through the
rerun.

The model probe measures the failure direction. An interpreter outage degrades the product to
refusing, never to agreeing: `unknown` is one of the three exception states in
[the rule the whole product turns on](../README.md#the-rule-the-whole-product-turns-on).

[`docs/ablation.json`](ablation.json) keeps earlier output of this tool plus an appended correction
row, and `tools/ablation.py` no longer overwrites it. The historical staleness row counted the
carried findings and worded that count as an admission without asking the gate. That wording is not
supported. The correction row says so and sends the reader to the exact-run CI output above for the
current counter. Two tests hold the file still. `tests/test_claim_drift.py` checks that running the
probe leaves the file's bytes unchanged, and requires `carried_stale` above 0 with
`actually_admitted_stale` at 0. `tests/test_corpus_counts.py` checks that the historical rows are
still present as written, so it confirms the history is intact, not that the historical staleness
wording is right.

## Four kinds of input, and what the pipeline does with each

```bash
PYTHONPATH=src python tools/evaluation_cases.py
```

| Input | What happens |
|---|---|
| **correct**, a take that covers the uncovered beat | B-17 goes from `no_viable_coverage`, basis `insufficient_evidence`, to `covered_with_evidence`, basis `corroborated_by_the_interpreter` |
| **incomplete**, the same take with no slate | refused before anything is written, naming `slate` |
| **conflicting**, a camera report naming a different card | `media_identity_exception`, basis `declared_by_the_production`. The only take does not reconcile, so the beat is not covered |
| **changed**, evidence moving under an approval already given | the acceptance stops applying: `resolved=True` becomes `resolved=None`, so no decision closes the finding any more |

It runs offline with no account and no credential, because the local adapters implement the same
ports the deployed build uses. At commit e92348b all four hold and the command exits 0. A test pins
all four so they cannot drift (`test_the_four_evaluation_cases_hold` in
[`tests/test_corpus_counts.py`](../tests/test_corpus_counts.py)). The command also rewrites
[`docs/evaluation_cases.json`](evaluation_cases.json) with the four results.

**These are our cases, scored by our pipeline.** That is a description of behaviour under four
kinds of input. It is not an evaluation of judgement quality against labelled ground truth, and
**no practising script supervisor has run any of it**. The trial that would matter is whether a
supervisor finds the evidence available before wrap, and whether the reconciliation work actually
goes down. That has not happened, and nothing here should be read as though it had.

A separate set of 16 synthetic cases, ten coverage and six continuity, exists for the two
interpreter questions, with gold labels written by the implementing assistant
([model-evidence-protocol.json](model-evidence-protocol.json),
[model-evidence-gold.json](model-evidence-gold.json)). It is not independent ground truth and has
not been run against a real model, so accuracy stays unmeasured. See
[model-evidence.md](model-evidence.md#text-interpretation-evidence-source-preparation-not-model-accuracy).

## Source hero measurement protocol

The optional source hero measurement is preregistered in
[`docs/hero-measurement-protocol.json`](hero-measurement-protocol.json): protocol
`LT-X1-SOURCE-20-20260910`, declared at 2026-09-10T12:44:17Z and committed as 19ef0723. The file's
`status` reads `PREREGISTERED_NOT_MEASURED`, which means it was written down before any
measurement. It keeps that value after a run, because
[`frontend/scripts/run-hero-benchmark.mjs`](../frontend/scripts/run-hero-benchmark.mjs) refuses to
start if the protocol file differs from the preregistration commit. Results live in the run
artifact, not in this file.

| Rule | What the protocol and workflow fix |
|---|---|
| When it runs | only on manual opt-in after normal source verification: a `workflow_dispatch` of [`frontend-ci.yml`](../.github/workflows/frontend-ci.yml) with `run_source_benchmark` set to true, on branch `codex/hero-measurement-20260910`, after the `verify` job. On main, or without the input, no benchmark job runs |
| Sample | 20 fixed attempts, 10 desktop (1440 by 1000) and 10 mobile (375 by 812), one worker, no retries, no recordings and no discarded warmup |
| Boundary | the unchanged hero helper, [`web/video/hero-journey.mjs`](../web/video/hero-journey.mjs), is timed from just before its first action, which clicks **Run wrap checkpoint**, through changed evidence, fresh wrap approval and verified handoff downloads. Install, build, server start and first navigation fall outside |
| Kept | raw slots, failures, unrun slots, byte counts, and source and runtime identity recorded independently, with the p50 and nearest-rank p95 methods written in advance: p95 is the successful duration at rank ceil(0.95 times the number of successful attempts), with no outlier trimming |
| Bytes | request bodies only. Response-body bytes are `UNKNOWN`, meaning they were not captured, so no total network byte figure is claimed |
| Cost | external model cost is 0 only when the offline guards verify; infrastructure and runner cost are unknown |
| Failure retention | a later workflow step seals an isolated snapshot once, holding the captured original bytes plus a derived summary and hashes, and only that snapshot is uploaded. Each file is written on its own; the set of files is not one transaction |

**This is scripted source-CI completion time, not AWS latency or human time.**

The file supersedes an earlier unmeasured protocol at commit 176b58b, which stays unchanged on its
branch. It is superseded, not rewritten. The new file gives the reasons: the baseline changed, and
the earlier declared time was ahead of the observed clock, so it was not a truthful commit
timestamp.

## Historical measured cohort, 2026-09-10

The protocol's single measured run is
[run 34481212393](https://github.com/upgradedev/lasttake-aws/actions/runs/34481212393), on
2026-09-10, at source commit `faf7f17128549155cda7144fdd1cd560c0f0a5c5`. Every figure below comes
from its
[raw artifact 10154044857](https://github.com/upgradedev/lasttake-aws/actions/runs/34481212393/artifacts/10154044857),
which retains 26 hashed files.

| Observation | Value in artifact 10154044857 |
|---|---|
| attempts completed | 20 of 20, 10 per viewport |
| failed, incomplete or unrun slots | 0 |
| retries | 0 |
| p50 completion time | 5662.1155775 ms |
| nearest-rank p95 completion time | 6547.501716 ms |
| benchmark process | 165481.102184 ms, exit 0 |
| requests inside the declared boundary | 1540 |
| observed request-body bytes | 179300 |
| requests with an unknown body size | 0 |
| response-body bytes | not captured |

Reproduce these from `slot-*.json`, `summary.json`, `process.json` and `manifest.json` in that
artifact, not from whole Playwright test timings. The protocol keeps uploads for 90 days, and the
benchmark job uploads with `retention-days: 90` (frontend-ci.yml, line 66), so the artifact may stop
downloading after about 2026-12-09 (ESTIMATE: 90 days from the run date, assuming that run used the
same setting).

These observations belong only to `faf7f17`. They are scripted completion times against local
servers in source CI, not AWS latency and not human time. Later timeout-retention fixes were tested
in source CI with a detached writer that outlives the driver, and they replay these already-spent
bytes: [`frontend/scripts/replay-hero-measurement.mjs`](../frontend/scripts/replay-hero-measurement.mjs)
re-checks every original hash, the source identity, exit 0 and the 20 passed slots, and requires the
replayed statistics to match. A replay is not another measured cohort and does not measure newer
source. The three steps that fetch, replay and upload the spent cohort check the branch, not the
event: they run only when the run's branch is `codex/hero-measurement-20260910`, as on a push to it
or a manual dispatch on it, or when a pull request comes from it (frontend-ci.yml, lines 204, 213 and
217). Live acceptance of the deployed site is a separate record, described in
[release-and-acceptance.md](release-and-acceptance.md#current-automated-acceptance).
