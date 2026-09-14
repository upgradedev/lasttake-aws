"""ALL-01. Fixed inputs, a declared baseline, expected outcomes written first.

The rule this is built to satisfy: define the same raw inputs, the baseline and
the expected outcome **before** measuring, then report every run including the
ones that failed.

So the expectations below are literals in this file. They were written from the
product's stated rules, not read off a run and pasted back, and a case that
disagrees with its expectation is reported as a failure rather than quietly
becoming the new expectation.

When the product contract changes on purpose, a case can stop describing
anything the product is meant to do. That case is rewritten, not re-expected:
the retired expectation and the run it failed are kept in `REWRITES` and under
`history` in docs/measurement.json.

## What is measured, and what is not

`wall_seconds` is measured. `interpreter_calls` is measured by counting them at
the port. **`human_active_seconds` is null in every row**, because no human was
observed doing any of this, and a number produced by timing a model and calling
it human time would be a fabricated benchmark. Model time, wall time and human
time are three different things and only two of them exist here.

`cost_basis` says how cost was arrived at. On the offline interpreter it is zero
because no model is called, which is a fact about the configuration and not a
claim about the product. Bedrock cost is not measured here: it needs token
counts per call, which this harness does not collect, so the field says so
rather than guessing.

## Two sets

`DEVELOPMENT` cases were used while building. `HELD_OUT` cases were written after
the behaviour was fixed and were not used to change it. That is weaker than an
independent set somebody else wrote, and it is labelled weaker rather than
presented as validation.

Run: PYTHONPATH=src python tools/measure.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from lasttake.adapters.local.interpreter import OfflineInterpreter  # noqa: E402
from lasttake.app.ingest import shape_error  # noqa: E402
from lasttake.checks import continuity as continuity_check  # noqa: E402
from lasttake.checks import coverage as coverage_check  # noqa: E402
from lasttake.checks import metadata as metadata_check  # noqa: E402
from lasttake.checks import rights as rights_check  # noqa: E402
from lasttake.domain import policy, rollup  # noqa: E402
from lasttake.domain.package import (  # noqa: E402
    CameraReportRow,
    Take,
    load_package,
    with_extra_take,
    with_rights_record,
)

CORPUS = pathlib.Path(__file__).resolve().parents[1] / "corpus"
OUTPUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "measurement.json"
RUN = "measure"

#: Read back from the committed file and written again on every run, never
#: regenerated. The scope note is what tests/test_claim_drift.py checks, and
#: `history` holds earlier runs, failed ones included, which a new run must not
#: overwrite.
CARRIED = ("_current_scope", "history")

BASELINE = {
    "what": (
        "The scene package as the corpus ships it, read by the offline lexical "
        "interpreter, with no human decisions recorded."
    ),
    "why_this_one": (
        "It is the configuration the live URL runs, so every number here is about "
        "the thing a judge can open. A Bedrock baseline would measure a different "
        "deployment and is reported separately in the README."
    ),
    "expected_headline": {
        "required_beats": 34,
        "covered_with_evidence": 31,
        "raising_exceptions": 2,
        "without_release_record": 1,
        "not_assessed": 0,
    },
}

#: Every expectation in this file that has been changed since it was first
#: declared, and why. An expectation edited to match a run is the failure mode
#: this whole harness exists to prevent, so a correction is published rather
#: than absorbed.
CORRECTIONS = [
    {
        "case": "missing evidence",
        "field": "rights_findings",
        "declared_first": 6,
        "observed": 7,
        "which_was_wrong": "the expectation",
        "why": (
            "Written from memory of the corpus rather than from the corpus. The "
            "ledger covers five people and two visible assets, so seven rights "
            "findings is correct and six never was. No product code was changed."
        ),
        "unchanged_assertions_that_held_first_time": [
            "missing_release_subjects == ['BG-07']",
            "beats_without_release == 1",
        ],
    },
]

#: Cases whose scenario was replaced, which is not the same as a correction. A
#: correction says an expectation was wrong about behaviour that had not
#: changed. A rewrite says the product contract changed on purpose, so the old
#: scenario stopped describing anything the product is meant to do. The retired
#: expectation stays here with what it observed against the new contract, and
#: that failing run stays under `history` in docs/measurement.json.
REWRITES = [
    {
        "case": "retry and recovery",
        "rewritten_on": "2026-09-14",
        "which_changed": "the product contract, on purpose, not the expectation",
        "contract_change": {
            "commit": "911fa59",
            "committed_on": "2026-09-09",
            "where": "WrapRun.publish in src/lasttake/agents/runtime.py",
            "before": (
                "A publish that raised released its idempotency claim and re-raised, "
                "so a later idempotent publish of the same event retried it."
            ),
            "after": (
                "A publish that raises returns a receipt with status unknown and "
                "keeps its claims. A later idempotent publish of the same logical "
                "effect answers that an earlier attempt remains unresolved and does "
                "not call the bus. Only an accepted or rejected outcome releases the "
                "effect claim, so a definite rejection is the retry the contract allows."
            ),
        },
        "retired_scenario": (
            "The bus raises on the first attempt, then accepts. The retry must "
            "publish and a third call must not reach the bus."
        ),
        "retired_expected": {
            "first_attempt_failed": True,
            "retry_published": True,
            "third_was_not_republished": True,
            "bus_calls": 2,
        },
        "retired_observed_against_the_new_contract": {
            "run": "origin/main at ab0a1d3, 2026-09-14, tools/measure.py unmodified",
            "cases_matched": "7 of 8",
            "observed": {
                "first_attempt_failed": False,
                "retry_published": False,
                "third_was_not_republished": False,
                "bus_calls": 1,
            },
        },
        "why_not_edited_to_match": (
            "Setting those four literals to the observed values would have recorded "
            "'a raised publish is never retried' as a pass for a case named retry "
            "and recovery. A disagreement is a failure here, so the retired "
            "expectation and its failing run are kept and the scenario is replaced."
        ),
        "new_scenario": (
            "The bus returns a definite rejection, then accepts. The retry must "
            "publish, and a third call must return the saved receipt without "
            "reaching the bus."
        ),
        "new_expectations_written_from": (
            "the WrapRun.publish contract, before the rewritten case first ran. "
            "tests/test_rerun_and_events.py::test_a_publish_that_fails_can_be_retried "
            "pins the same sequence."
        ),
        "raised_publish_now_pinned_by": (
            "tests/test_reliable_workflows.py::"
            "test_ambiguous_publish_exception_does_not_blindly_resend"
        ),
    },
]

A_PICKUP = {
    "take_id": "T-900", "shot_id": "S-42-PICKUP", "beat_ids": ["B-17"],
    "slate": "42L/1", "camera_roll": "A007", "sound_roll": "SR07",
    "timecode_in": "23:04:00:00", "timecode_out": "23:04:41:00", "lens_mm": 50,
    "media_id": "A007R2G01", "preferred": True, "usable": True,
    "note": "DELPHINE's reaction, held. Clean single.",
    "visible_people": ["DELPHINE"], "visible_assets": [], "captured_at": "",
}


class CountingInterpreter:
    """The real interpreter, with a counter at the port."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0

    @property
    def model_id(self):
        return self._inner.model_id

    def match_beat_to_take(self, **kwargs):
        self.calls += 1
        return self._inner.match_beat_to_take(**kwargs)

    def compare_continuity(self, **kwargs):
        self.calls += 1
        return self._inner.compare_continuity(**kwargs)


def fixture_hash() -> dict:
    """Every corpus file and its digest, so a run names the bytes it read."""
    digests = {}
    for path in sorted(CORPUS.glob("*.json")):
        digests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    combined = hashlib.sha256(
        json.dumps(digests, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {"files": digests, "corpus_sha256": combined}


def carried_forward() -> dict:
    """The parts of the committed file a run keeps rather than regenerates."""
    if not OUTPUT.exists():
        return {}
    previous = json.loads(OUTPUT.read_text(encoding="utf-8"))
    return {k: previous[k] for k in CARRIED if k in previous}


def analyse(package, interpreter):
    out = coverage_check.run(package, RUN, interpreter, policy.POLICY_VERSION)
    out += coverage_check.orphan_shots(package, RUN, policy.POLICY_VERSION)
    out += continuity_check.run(package, RUN, interpreter, policy.POLICY_VERSION)
    out += metadata_check.run(package, RUN, policy.POLICY_VERSION)
    out += rights_check.run(package, RUN, policy.POLICY_VERSION)
    return [f.resealed() for f in out]


# -- the cases --------------------------------------------------------------
#
# Each returns (observed, expected). Both are dicts, compared field by field, so
# a mismatch names which field moved rather than printing two blobs.


def case_ordinary(interpreter):
    package = load_package(CORPUS)
    head = rollup.headline(rollup.roll_up(package, analyse(package, interpreter)))
    observed = {k: v for k, v in head.items() if k != "basis"}
    return observed, BASELINE["expected_headline"]


def case_missing_evidence(interpreter):
    """BG-07 has no release. The corpus ships it that way on purpose."""
    package = load_package(CORPUS)
    findings = analyse(package, interpreter)
    rights = [f for f in findings if f.check_type.value == "rights"]
    missing = [f for f in rights if f.truth_state.value == "missing"]
    return (
        {
            "rights_findings": len(rights),
            "missing_release_subjects": sorted(f.requirement_id for f in missing),
            "beats_without_release": rollup.headline(
                rollup.roll_up(package, findings)
            )["without_release_record"],
        },
        {
            # Corrected once, in the open. This was first declared as 6, written
            # from memory of the corpus rather than from the corpus: it is five
            # people and two assets, so seven. The product was right and the
            # expectation was wrong. The two assertions that carry the meaning,
            # which subject is missing and how many beats it costs, held on the
            # first run and are unchanged.
            "rights_findings": 7,
            "missing_release_subjects": ["BG-07"],
            "beats_without_release": 1,
        },
    )


def case_changed_input(interpreter):
    """A pickup take arrives. Which checks may rerun is derived, not asserted."""
    package = load_package(CORPUS)
    before = rollup.roll_up(package, analyse(package, interpreter))
    b17_before = next(o for o in before if o.beat_id == "B-17")

    amended = with_extra_take(
        package, Take(**A_PICKUP), CameraReportRow("T-900", "A007R2G01", 50, "A007")
    )
    after = rollup.roll_up(amended, analyse(amended, interpreter))
    b17_after = next(o for o in after if o.beat_id == "B-17")

    # Which findings the gate must discard, because the takes digest moved and
    # every check reads it.
    stale = len(policy.evaluate(RUN, amended, analyse(package, interpreter), []).discarded)
    return (
        {
            "b17_before": [b17_before.status.value, b17_before.basis.value],
            "b17_after": [b17_after.status.value, b17_after.basis.value],
            "stale_findings_discarded": stale > 0,
        },
        {
            "b17_before": ["no_viable_coverage", "insufficient_evidence"],
            "b17_after": ["covered_with_evidence", "corroborated_by_the_interpreter"],
            "stale_findings_discarded": True,
        },
    )


def case_refusal(interpreter):
    """A document missing a required field. Refused before anything is written."""
    problem = shape_error("take", {k: v for k, v in A_PICKUP.items() if k != "slate"})
    wrong_type = shape_error("take", {**A_PICKUP, "lens_mm": "fifty"})
    foreign_row = shape_error(
        "take", {**A_PICKUP, "camera_report_row": {
            "take_id": "T-013", "media_id": "A002R2B13", "lens_mm": 50,
            "camera_roll": "A002"}},
    )
    return (
        {
            "missing_field_named": (problem or {}).get("missing"),
            "wrong_type_refused": bool(wrong_type),
            "foreign_report_row_refused": bool(foreign_row),
        },
        {
            "missing_field_named": ["slate"],
            "wrong_type_refused": True,
            "foreign_report_row_refused": True,
        },
    )


def case_retry_recovery(interpreter):
    """A publish the bus rejects, then accepts. One event, and the retry is allowed.

    Rewritten on 2026-09-14, see REWRITES. Since 911fa59 a publish that raises
    has an unknown outcome and is never resent, so the retry the contract
    allows is the one after a definite rejection. The expectations below were
    written from the `WrapRun.publish` contract before this version ran.
    """
    import tempfile

    from lasttake.adapters.local.infrastructure import (
        LocalArtifactStore,
        LocalRunStore,
    )
    from lasttake.agents.runtime import WrapRun
    from lasttake.domain.events import EventType
    from lasttake.ports.infrastructure import Receipt

    class RejectingBus:
        def __init__(self):
            self.attempts = 0
            self.accepting = False

        def publish(self, event):
            self.attempts += 1
            if not self.accepting:
                return Receipt(
                    accepted=False, reference=event.event_id,
                    detail="entry explicitly rejected",
                )
            return Receipt(accepted=True, reference=event.event_id, detail="published")

    tmp = pathlib.Path(tempfile.mkdtemp())
    bus = RejectingBus()
    run = WrapRun(
        run_id="measure-retry",
        correlation_id="measure-retry",
        package=load_package(CORPUS),
        bus=bus,
        artifacts=LocalArtifactStore(tmp / "a"),
        runs=LocalRunStore(tmp / "r"),
        interpreter=interpreter,
    )
    first = run.publish(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"}, idempotent=True)

    bus.accepting = True
    second = run.publish(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"}, idempotent=True)
    third = run.publish(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"}, idempotent=True)
    return (
        {
            "first_attempt_rejected": first.outcome == "rejected" and not first.accepted,
            "retry_published": second.accepted and second.outcome == "accepted",
            # A fresh publish would carry a new event id as its reference, so an
            # identical receipt is the saved one, not a second send. Compared as
            # dicts: the saved copy spells out the status the live one derives.
            "third_replayed_the_saved_receipt": third.to_dict() == second.to_dict(),
            "bus_calls": bus.attempts,
        },
        {
            "first_attempt_rejected": True,
            "retry_published": True,
            "third_replayed_the_saved_receipt": True,
            "bus_calls": 2,
        },
    )


# -- held out ---------------------------------------------------------------
#
# Written after the behaviour was fixed and not used to change it. Weaker than
# an independent set somebody else wrote, and labelled weaker.


def held_no_interpreter(_interpreter):
    """Every declaration stands and nothing is corroborated."""
    from lasttake.ports.interpreter import BeatMatch, ContinuityOpinion

    class Unreachable:
        model_id = "unreachable/0"

        def match_beat_to_take(self, **_):
            return BeatMatch(covers=False, confidence=0.0, rationale="not reached")

        def compare_continuity(self, **_):
            return ContinuityOpinion(
                states_agree=False, possibly_intentional=True,
                confidence=0.0, rationale="not reached",
            )

    package = load_package(CORPUS)
    head = rollup.headline(rollup.roll_up(package, analyse(package, Unreachable())))
    return (
        {
            "covered": head["covered_with_evidence"],
            "declared": head["basis"]["declared_by_the_production"],
            "corroborated": head["basis"]["corroborated_by_the_interpreter"],
        },
        {"covered": 0, "declared": 33, "corroborated": 0},
    )


def held_tampered_record(interpreter):
    """A finding edited in storage without being resealed is discarded."""
    package = load_package(CORPUS)
    findings = analyse(package, interpreter)
    tampered = [copy.deepcopy(f) for f in findings]
    gap = next(f for f in tampered if f.truth_state.value == "missing")
    gap.truth_state = type(gap.truth_state).VERIFIED  # not resealed

    packet = policy.evaluate(RUN, package, tampered, [])
    return (
        {
            "eligible": packet.eligible,
            "named_the_seal": any("seal does not verify" in d for d in packet.discarded),
        },
        {"eligible": False, "named_the_seal": True},
    )


def held_release_filed(interpreter):
    """Filing the missing release closes exactly one thing and no more."""
    from lasttake.domain.package import RightsRecord

    package = load_package(CORPUS)
    amended = with_rights_record(package, RightsRecord(
        record_id="REL-900", subject_id="BG-07", subject_kind="person",
        document_type="background release", scope="all media",
        territory="worldwide", expires_on=None, status="executed",
    ))
    head = rollup.headline(rollup.roll_up(amended, analyse(amended, interpreter)))
    return (
        {
            "without_release_record": head["without_release_record"],
            "covered": head["covered_with_evidence"],
            "still_raising_exceptions": head["raising_exceptions"],
        },
        {"without_release_record": 0, "covered": 32, "still_raising_exceptions": 2},
    )


DEVELOPMENT = [
    ("ordinary", case_ordinary),
    ("missing evidence", case_missing_evidence),
    ("changed input", case_changed_input),
    ("refusal", case_refusal),
    ("retry and recovery", case_retry_recovery),
]

HELD_OUT = [
    ("no interpreter reachable", held_no_interpreter),
    ("a record edited in storage", held_tampered_record),
    ("the missing release filed", held_release_filed),
]


def run_case(name, fn):
    interpreter = CountingInterpreter(OfflineInterpreter())
    started = time.perf_counter()
    error = None
    observed = expected = None
    try:
        observed, expected = fn(interpreter)
    except Exception as exc:  # noqa: BLE001 - a case that raises is a result
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - started

    if error:
        mismatches = {"raised": [None, error]}
    else:
        mismatches = {
            k: [expected[k], observed.get(k)]
            for k in expected
            if observed.get(k) != expected[k]
        }
    return {
        "case": name,
        "expected": expected,
        "observed": observed,
        "error": error,
        "correct": error is None and not mismatches,
        "mismatches": mismatches,
        "wall_seconds": round(wall, 3),
        "interpreter_calls": interpreter.calls,
        # Not measured, and named rather than estimated. Nobody was observed.
        "human_active_seconds": None,
        "human_time_basis": "no human was observed performing this case",
        # Asked for by name, and answered by name. Nobody interrupted a run and
        # nobody corrected an output, because nobody ran one: these are counts
        # of human behaviour and there was no human in the loop to count.
        "human_interruptions": None,
        "human_corrections_of_the_output": None,
        "interventions_basis": (
            "not measured. These count what a person did during a run and no "
            "person ran one; a zero here would read as 'needed no help'"
        ),
        "cost_usd": 0.0,
        "cost_basis": (
            "offline lexical interpreter, no model call, so no inference cost. "
            "Bedrock cost is not measured here: it needs per-call token counts "
            "this harness does not collect"
        ),
    }


def main() -> int:
    fixtures = fixture_hash()
    carried = carried_forward()
    dev = [run_case(name, fn) for name, fn in DEVELOPMENT]
    held = [run_case(name, fn) for name, fn in HELD_OUT]
    scope = {"_current_scope": carried["_current_scope"]} if "_current_scope" in carried else {}
    report = {
        **scope,
        "schema": "lasttake/measurement/v1",
        "baseline": BASELINE,
        # Kept, because the rule was to keep the failures. Without this the file
        # reads 8 of 8 and hides that one expectation was declared wrong.
        "corrections": CORRECTIONS,
        # Kept for the same reason. Without this the file reads 8 of 8 and hides
        # that one case failed after the contract changed and was replaced.
        "rewrites": REWRITES,
        "fixtures": fixtures,
        "command": "PYTHONPATH=src python tools/measure.py",
        "development_cases": dev,
        "held_out_cases": held,
        "what_was_not_measured": [
            "human active time, interruptions and corrections: no human was observed",
            "Bedrock inference cost: needs per-call token counts this harness "
            "does not collect",
            "judgement quality against labelled ground truth: these cases check "
            "behaviour against declared expectations, which is a weaker claim",
        ],
        "held_out_caveat": (
            "Written after the behaviour was fixed and not used to change it. That "
            "is weaker than a set somebody else wrote, and it is not user "
            "validation: no practising script supervisor has run any of this."
        ),
        "history": carried.get("history", []),
    }

    print("# Measurement, against a baseline declared before the run")
    print()
    print(f"Corpus `{fixtures['corpus_sha256'][:16]}`, {len(fixtures['files'])} files.")
    print(f"Baseline: {BASELINE['what']}")
    print()
    print("| Set | Case | Correct | Wall s | Interpreter calls | Human time |")
    print("|---|---|---|---|---|---|")
    for label, rows in (("development", dev), ("held out", held)):
        for row in rows:
            print(
                f"| {label} | {row['case']} | {'yes' if row['correct'] else 'NO'} "
                f"| {row['wall_seconds']} | {row['interpreter_calls']} | not measured |"
            )
    print()

    failed = [r for r in dev + held if not r["correct"]]
    for row in failed:
        print(f"## {row['case']} did not match")
        print()
        if row["error"]:
            print(f"- raised: {row['error']}")
        for field, (want, got) in row["mismatches"].items():
            print(f"- `{field}`: expected `{want}`, observed `{got}`")
        print()

    print("## Published rather than absorbed")
    print()
    for c in CORRECTIONS:
        print(
            f"- Correction, {c['case']}: `{c['field']}` was declared as "
            f"{c['declared_first']} and observed as {c['observed']}; "
            f"{c['which_was_wrong']} was wrong."
        )
    for r in REWRITES:
        change = r["contract_change"]
        retired = r["retired_observed_against_the_new_contract"]
        print(
            f"- Rewrite, {r['case']}: rewritten on {r['rewritten_on']} after "
            f"{change['commit']} changed {change['where']}. Run against that "
            f"contract, the retired case did not match and {retired['cases_matched']} "
            f"cases did ({retired['run']}). The retired expectation and that run "
            "are kept in REWRITES and under history in docs/measurement.json."
        )
    print()

    print("Human time is not measured in any row. No human was observed, and timing")
    print("a model and calling the result human time would be a fabricated benchmark.")
    print()
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if failed:
        print(f"{len(failed)} of {len(dev) + len(held)} cases did not match. Kept, not hidden.")
        return 1
    print(f"All {len(dev) + len(held)} matched. Written to docs/measurement.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
