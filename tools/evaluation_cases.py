"""Four inputs, four outcomes, run offline by anyone with the repository.

Correct, incomplete, conflicting, changed. These are the four things a scene
package can be when somebody hands it to you, and this runs each one through the
real pipeline and prints what the system concluded and on what basis.

It needs no AWS account and no credential: the local adapters implement the same
ports the deployed build uses, which is the reason the ports exist. So a judge
can check every number below by running one command rather than believing this
file.

**These are our own cases, scored by our own pipeline.** They are a description
of behaviour under four kinds of input, not an evaluation of judgement quality
against labelled ground truth, and not validation by a script supervisor.
No practising script supervisor has run this. That gap is stated in the README
and in docs/assurance.md and is not closed by anything here.

Run: PYTHONPATH=src python tools/evaluation_cases.py
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from lasttake.adapters.local.infrastructure import (  # noqa: E402
    LocalArtifactStore,
    LocalEventBus,
    LocalRunStore,
)
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
)

CORPUS = pathlib.Path(__file__).resolve().parents[1] / "corpus"
RUN = "evaluation"

#: A take that genuinely covers B-17, the one beat the corpus leaves uncovered.
GOOD_TAKE = {
    "take_id": "T-900",
    "shot_id": "S-42-PICKUP",
    "beat_ids": ["B-17"],
    "slate": "42L/1",
    "camera_roll": "A007",
    "sound_roll": "SR07",
    "timecode_in": "23:04:00:00",
    "timecode_out": "23:04:41:00",
    "lens_mm": 50,
    "media_id": "A007R2G01",
    "preferred": True,
    "usable": True,
    "note": "DELPHINE's reaction, held, before she speaks. Clean single.",
    "visible_people": ["DELPHINE"],
    "visible_assets": [],
    "captured_at": "2026-08-19T23:04:00Z",
}


def findings_for(package, interpreter=None):
    interpreter = interpreter or OfflineInterpreter()
    out = coverage_check.run(package, RUN, interpreter, policy.POLICY_VERSION)
    out += coverage_check.orphan_shots(package, RUN, policy.POLICY_VERSION)
    out += continuity_check.run(package, RUN, interpreter, policy.POLICY_VERSION)
    out += metadata_check.run(package, RUN, policy.POLICY_VERSION)
    out += rights_check.run(package, RUN, policy.POLICY_VERSION)
    return [f.resealed() for f in out]


def beat(outcomes, beat_id):
    return next(o for o in outcomes if o.beat_id == beat_id)


def case_correct() -> dict:
    """A well-formed take against the beat nothing covers."""
    package = load_package(CORPUS)
    before = beat(rollup.roll_up(package, findings_for(package)), "B-17")

    take = Take(**GOOD_TAKE)
    amended = with_extra_take(
        package, take, CameraReportRow("T-900", "A007R2G01", 50, "A007")
    )
    after = beat(rollup.roll_up(amended, findings_for(amended)), "B-17")
    return {
        "case": "correct: a take that covers the uncovered beat",
        "before": f"B-17 {before.status.value}, basis {before.basis.value}",
        "after": f"B-17 {after.status.value}, basis {after.basis.value}",
        "expected": "the beat becomes covered, and rests on a corroborated reading",
        "held": after.status is rollup.BeatStatus.COVERED
        and after.basis is rollup.EvidenceBasis.INTERPRETED,
    }


def case_incomplete() -> dict:
    """The same take with a required field removed."""
    document = {k: v for k, v in GOOD_TAKE.items() if k != "slate"}
    problem = shape_error("take", document)
    return {
        "case": "incomplete: the same take with no slate",
        "before": "the document is offered",
        "after": f"refused: missing {problem['missing']}" if problem else "accepted",
        "expected": "refused before anything is written, naming the missing field",
        "held": bool(problem) and problem.get("missing") == ["slate"],
    }


def case_conflicting() -> dict:
    """A take whose camera report row disagrees with its own sidecar."""
    package = load_package(CORPUS)
    take = Take(**GOOD_TAKE)
    amended = with_extra_take(
        package,
        take,
        # The report says a different card. This is the mundane failure the
        # metadata check exists for, and it must not become a pass.
        CameraReportRow("T-900", "A007R2G0X", 50, "A007"),
    )
    outcomes = rollup.roll_up(amended, findings_for(amended))
    after = beat(outcomes, "B-17")
    return {
        "case": "conflicting: the camera report names a different card",
        "before": "B-17 has one take and it looks usable",
        "after": f"B-17 {after.status.value}, basis {after.basis.value}",
        "expected": "the beat is not covered, because the only take does not reconcile",
        "held": after.status is not rollup.BeatStatus.COVERED,
    }


def case_changed() -> dict:
    """An approval taken about one reading, then the reading changes."""
    package = load_package(CORPUS)
    findings = findings_for(package)
    conflict = next(
        f for f in findings if f.check_type.value == "continuity" and f.requirement_id
    )
    accepted = policy.HumanDecision(
        decision_id="dec-eval",
        finding_id=conflict.finding_id,
        action=policy.DecisionAction.ACCEPT_EXCEPTION,
        actor="a script supervisor",
        role=policy.Role.SCRIPT_SUPERVISOR,
        reason="Reviewed on the floor.",
        finding_sha256=conflict.record_sha256,
    )
    before = policy._resolution(conflict, [accepted])

    reread = copy.deepcopy(conflict)
    reread.observation = conflict.observation + " Re-read after a later take."
    reread.resealed()
    after = policy._resolution(reread, [accepted])
    return {
        "case": "changed: the evidence moves under an approval already given",
        "before": f"the acceptance closes the finding: resolved={before}",
        "after": f"the same id, a new reading: resolved={after}",
        "expected": "the approval stops applying, because nobody has looked at the new facts",
        "held": before is True and after is None,
    }


def main() -> int:
    cases = [case_correct(), case_incomplete(), case_conflicting(), case_changed()]

    print("# Four kinds of input, through the real pipeline")
    print()
    print("Run offline with `PYTHONPATH=src python tools/evaluation_cases.py`. No account,")
    print("no credential: the local adapters implement the same ports the deployed build")
    print("uses.")
    print()
    print("**Our cases, scored by our pipeline.** This describes behaviour under four kinds")
    print("of input. It is not an evaluation of judgement quality against labelled ground")
    print("truth, and no practising script supervisor has run it.")
    print()

    failed = []
    for row in cases:
        mark = "holds" if row["held"] else "DOES NOT HOLD"
        print(f"## {row['case']}")
        print()
        print(f"- before: {row['before']}")
        print(f"- after: {row['after']}")
        print(f"- expected: {row['expected']}")
        print(f"- **{mark}**")
        print()
        if not row["held"]:
            failed.append(row["case"])

    pathlib.Path("docs/evaluation_cases.json").write_text(
        json.dumps(cases, indent=2), encoding="utf-8"
    )
    if failed:
        print(f"{len(failed)} case(s) did not hold: {failed}")
        return 1
    print("All four hold. Written to docs/evaluation_cases.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
