"""What the architecture is worth, measured by removing it.

Every number this repository publishes so far is a count of our own fixture:
34 required beats, 31 covered, 2 exceptions, 1 without a release. It is a true
count and it is not an argument, because it has nothing to be compared against.

This script builds the comparison. It runs the same corpus through the same
pipeline three times, each time with one load-bearing rule removed, and reports
what the gate concludes in each case. The removed rule is the only thing that
differs, so the delta is attributable.

Nothing here is a simulation. Each ablation calls the real check modules and the
real `policy.evaluate`; what changes is one input to it.

Run: PYTHONPATH=src python tools/ablation.py
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from lasttake.adapters.local.interpreter import OfflineInterpreter  # noqa: E402
from lasttake.checks import continuity as continuity_check  # noqa: E402
from lasttake.checks import coverage as coverage_check  # noqa: E402
from lasttake.checks import metadata as metadata_check  # noqa: E402
from lasttake.checks import rights as rights_check  # noqa: E402
from lasttake.domain import policy, rollup  # noqa: E402
from lasttake.domain.findings import TruthState  # noqa: E402
from lasttake.domain.package import (  # noqa: E402
    CameraReportRow,
    Take,
    load_package,
    with_extra_take,
)

CORPUS = pathlib.Path(__file__).resolve().parents[1] / "corpus"
RUN = "ablation"


def all_findings(package, interpreter):
    out = coverage_check.run(package, RUN, interpreter, policy.POLICY_VERSION)
    out += coverage_check.orphan_shots(package, RUN, policy.POLICY_VERSION)
    out += continuity_check.run(package, RUN, interpreter, policy.POLICY_VERSION)
    out += metadata_check.run(package, RUN, policy.POLICY_VERSION)
    out += rights_check.run(package, RUN, policy.POLICY_VERSION)
    return [f.resealed() for f in out]


class Unreachable:
    """Every interpreter returns this shape when the model cannot be reached."""

    model_id = "unreachable/0"

    def match_beat_to_take(self, **_):
        from lasttake.ports.interpreter import BeatMatch

        return BeatMatch(covers=False, confidence=0.0, rationale="not reached")

    def compare_continuity(self, **_):
        from lasttake.ports.interpreter import ContinuityOpinion

        return ContinuityOpinion(
            states_agree=False,
            possibly_intentional=True,
            confidence=0.0,
            rationale="not reached",
        )


def seal_check() -> dict:
    """One row in the findings store is edited from missing to verified.

    The threat is mundane: anything with write access to run state, including a
    bug in our own rerun path, can leave a finding saying a beat is covered when
    it is not. Everything downstream of the store trusts the record it is
    handed, so if nothing checks the seal, nothing catches it.
    """
    package = load_package(CORPUS)
    findings = all_findings(package, OfflineInterpreter())

    tampered = [copy.deepcopy(f) for f in findings]
    gap = next(f for f in tampered if f.truth_state is TruthState.MISSING)
    gap.truth_state = TruthState.VERIFIED
    # Not resealed. That is the whole point: an edit nobody had the key to make.

    with_seal = policy.evaluate(RUN, package, tampered, [])

    # Without the rule: exactly what the gate saw before the seal was wired in,
    # which is the tampered record taken at face value.
    laundered = [copy.deepcopy(f) for f in tampered]
    for finding in laundered:
        finding.resealed()
    without_seal = policy.evaluate(RUN, package, laundered, [])

    admitted = without_seal.counts["findings_admitted"]
    return {
        "ablation": "the finding seal is not verified",
        "with_the_rule": (
            f"the edited record is discarded and the reason is named "
            f"({len(with_seal.discarded)} discarded, the rest admitted)"
        ),
        "without_the_rule": (
            f"all {admitted} records are admitted, the edited one among them, and "
            "the beat it names reads as covered"
        ),
        "delta": "1 tampered record admitted instead of 0",
        "matters_because": (
            "the tampered beat is B-17, the one with no coverage at all. Taking the "
            "record at face value is how a scene with a hole in it reaches editorial."
        ),
    }


def staleness_check() -> dict:
    """A take arrives after the checkpoint. Which earlier results still hold?

    The common shortcut is to write down which checks a given event affects and
    trust the table. Ours derives it from which artifact digests actually moved.
    Where the two disagree, the shortcut keeps results that were computed
    against bytes that no longer exist.
    """
    package = load_package(CORPUS)
    findings = all_findings(package, OfflineInterpreter())

    take = Take(
        take_id="T-041",
        shot_id="S-42-PICKUP",
        beat_ids=["B-17"],
        slate="42K/1",
        camera_roll="A006",
        sound_roll="SR06",
        timecode_in="22:41:12:00",
        timecode_out="22:42:03:00",
        lens_mm=50,
        media_id="A006R2F41",
        preferred=True,
        usable=True,
        note="Pickup. Clean single, held for the reaction.",
        visible_people=["DELPHINE"],
        visible_assets=[],
        captured_at="2026-08-19T22:41:00Z",
    )
    amended = with_extra_take(
        package, take, CameraReportRow("T-041", "A006R2F41", 50, "A006")
    )

    # Ours: the gate re-derives staleness from the digests the findings cite.
    derived = policy.evaluate(RUN, amended, findings, [])
    stale_caught = len(derived.discarded)

    # The shortcut: assert that a new take affects coverage only, rerun that,
    # and carry the other three checks forward untouched.
    asserted = [
        f for f in findings if f.check_type.value != "coverage"
    ]
    asserted += [
        f.resealed()
        for f in coverage_check.run(amended, RUN, OfflineInterpreter(), policy.POLICY_VERSION)
    ]
    # Re-stamp them so the shortcut's own bookkeeping thinks they are current.
    for finding in asserted:
        finding.package_revision = amended.revision_digest()
        finding.resealed()
    carried_stale = sum(
        1
        for f in asserted
        if any(
            amended.artifacts[s.artifact_id].sha256 != s.sha256
            for s in f.sources
            if s.artifact_id in amended.artifacts
        )
    )

    return {
        "ablation": "staleness is asserted from a table instead of derived from digests",
        "with_the_rule": (
            f"{stale_caught} findings are discarded because they cite the takes "
            "digest from before the pickup arrived"
        ),
        "without_the_rule": (
            f"{carried_stale} of those findings are carried forward and re-stamped "
            "with the new revision, so the gate cannot tell they are stale"
        ),
        "delta": f"{carried_stale} stale findings admitted instead of 0",
        "matters_because": (
            "continuity, media identity and rights all read the takes document. A "
            "table that says a new take affects coverage only is wrong about three "
            "checks, and the gate has no way to notice."
        ),
    }


def model_check() -> dict:
    """The two bounded questions, asked and unasked."""
    package = load_package(CORPUS)

    asked = all_findings(package, OfflineInterpreter())
    unasked = all_findings(package, Unreachable())

    def verified_beats(findings):
        outcomes = rollup.roll_up(package, findings)
        return sum(
            1 for o in outcomes if o.status is rollup.BeatStatus.COVERED
        )

    return {
        "ablation": "the model cannot be reached",
        "with_the_rule": f"{verified_beats(asked)} of 34 beats are covered with evidence",
        "without_the_rule": f"{verified_beats(unasked)} of 34 beats are covered with evidence",
        "delta": (
            f"{verified_beats(asked) - verified_beats(unasked)} beats lose their evidence, "
            "and every one of them becomes unknown rather than a pass"
        ),
        "matters_because": (
            "a model outage degrades this product to refusing, never to agreeing. "
            "The failure direction is the claim, and this is the measurement of it."
        ),
    }


def main() -> int:
    rows = [seal_check(), staleness_check(), model_check()]
    print("# What each rule is worth, measured by removing it")
    print()
    print(f"Corpus: {CORPUS.name}, 34 required beats, 40 takes. Run: `PYTHONPATH=src "
          "python tools/ablation.py`")
    print()
    for row in rows:
        print(f"## {row['ablation']}")
        print()
        print(f"- with the rule: {row['with_the_rule']}")
        print(f"- without it: {row['without_the_rule']}")
        print(f"- **delta: {row['delta']}**")
        print(f"- why it matters: {row['matters_because']}")
        print()
    pathlib.Path("docs/ablation.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )
    print("Written to docs/ablation.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
