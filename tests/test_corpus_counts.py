"""The five numbers, asserted against the pipeline that produces them.

CLAUDE.md calls 34 / 31 / 2 / 1 a designed corpus target. This file is where it
stops being a target: the counts come out of the same rollup the CLI prints, so
if the corpus or the rule drifts, this fails rather than the video being wrong.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lasttake.adapters.local.interpreter import OfflineInterpreter
from lasttake.checks import continuity, coverage, metadata, rights
from lasttake.domain import policy, rollup
from lasttake.domain.findings import CheckType, TruthState
from lasttake.domain.package import load_package

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
RUN = "count-run"


@pytest.fixture(scope="module")
def package():
    return load_package(CORPUS)


@pytest.fixture(scope="module")
def findings(package):
    interp = OfflineInterpreter()
    return (
        coverage.run(package, RUN, interp, policy.POLICY_VERSION)
        + continuity.run(package, RUN, interp, policy.POLICY_VERSION)
        + metadata.run(package, RUN, policy.POLICY_VERSION)
        + rights.run(package, RUN, policy.POLICY_VERSION)
    )


def test_the_shoot_day_is_the_size_it_claims_to_be(package):
    assert len(package.required_beats) == 34
    assert len(package.takes) == 40
    assert len(package.beats) == 36, "34 required plus 2 optional inserts"


def test_the_headline_count(package, findings):
    head = rollup.headline(rollup.roll_up(package, findings))
    assert {k: v for k, v in head.items() if k != "basis"} == {
        "required_beats": 34,
        "covered_with_evidence": 31,
        "raising_exceptions": 2,
        "without_release_record": 1,
        "not_assessed": 0,
    }


def test_the_count_says_what_it_rests_on(package, findings):
    """Four things, never one word.

    "Covered" was doing four jobs and the ambiguity surfaced as a number nobody
    could explain: this corpus reads 31 of 34 through the offline lexical
    interpreter and 19 of 34 through Bedrock. Neither is wrong. They agree on
    what the production declared and disagree on how much of it a second reader
    can corroborate, and until the outcome carried a basis there was nowhere for
    that distinction to live.
    """
    head = rollup.headline(rollup.roll_up(package, findings))
    basis = head["basis"]
    assert set(basis) == {
        "declared_by_the_production",
        "corroborated_by_the_interpreter",
        "confirmed_by_a_named_human",
        "insufficient_evidence",
    }
    assert sum(basis.values()) == head["required_beats"]

    # Only a corroborated or confirmed beat may be counted as covered.
    assert basis["corroborated_by_the_interpreter"] + basis["confirmed_by_a_named_human"] == (
        head["covered_with_evidence"]
    )
    # B-17 has no take at all, so it rests on nothing.
    assert basis["insufficient_evidence"] == 1


def test_a_model_that_answers_nothing_leaves_the_declaration_standing_and_nothing_else():
    """The failure direction, measured on the basis rather than on the total.

    With no interpreter reachable, every mapping the production declared is
    still declared, and not one of them is corroborated. Coverage falls to zero
    and no beat quietly keeps a pass it had not earned.
    """
    from lasttake.ports.interpreter import BeatMatch, ContinuityOpinion

    class Unreachable:
        model_id = "unreachable/0"

        def match_beat_to_take(self, **_):
            return BeatMatch(covers=False, confidence=0.0, rationale="not reached")

        def compare_continuity(self, **_):
            return ContinuityOpinion(
                states_agree=False,
                possibly_intentional=True,
                confidence=0.0,
                rationale="not reached",
            )

    pkg = load_package(CORPUS)
    out = (
        coverage.run(pkg, "t", Unreachable(), policy.POLICY_VERSION)
        + coverage.orphan_shots(pkg, "t", policy.POLICY_VERSION)
        + continuity.run(pkg, "t", Unreachable(), policy.POLICY_VERSION)
        + metadata.run(pkg, "t", policy.POLICY_VERSION)
        + rights.run(pkg, "t", policy.POLICY_VERSION)
    )
    head = rollup.headline(rollup.roll_up(pkg, out))
    assert head["covered_with_evidence"] == 0
    assert head["basis"]["corroborated_by_the_interpreter"] == 0
    assert head["basis"]["declared_by_the_production"] == 33, (
        "the production's own record does not depend on our interpreter"
    )


def test_the_sentence_a_first_ad_hears(package, findings):
    assert rollup.sentence(rollup.roll_up(package, findings)) == (
        "Of 34 required beats, 31 covered with evidence, 2 raising exceptions "
        "with named sources, 1 with no release record and routed to production."
    )


def test_the_planted_coverage_gap_is_found(package, findings):
    gap = next(f for f in findings if f.requirement_id == "B-17" and f.check_type is CheckType.COVERAGE)
    assert gap.truth_state is TruthState.MISSING
    assert "never on the shot plan" in gap.observation


def test_the_planted_continuity_conflict_names_both_takes(package, findings):
    conflict = next(
        f
        for f in findings
        if f.check_type is CheckType.CONTINUITY and f.truth_state is TruthState.CONFLICTING
    )
    takes = [locator.value for locator in conflict.locators if locator.kind == "take"]
    assert len(takes) == 2
    # Both notes are quoted on the face of the finding, so the supervisor can
    # judge without opening anything.
    assert "half full" in conflict.observation and "empty" in conflict.observation
    assert "both flagged preferred" in conflict.observation
    # And it recommends a decision rather than making one.
    assert conflict.recommended_action and "Decide which take" in conflict.recommended_action


def test_a_conflict_where_neither_take_matches_the_reference_reads_as_intentional():
    """Drift from the reference on both sides is more likely a choice than an error."""
    from lasttake.adapters.local.interpreter import OfflineInterpreter

    opinion = OfflineInterpreter().compare_continuity(
        subject="enamel mug",
        established_state="half full, no steam, handle turned to camera left",
        note_a="mug is open on the table",
        note_b="mug is closed and stowed",
    )
    assert opinion.states_agree is False
    assert opinion.possibly_intentional is True


def test_a_missing_continuity_note_is_unknown_not_agreement():
    from lasttake.adapters.local.interpreter import OfflineInterpreter

    opinion = OfflineInterpreter().compare_continuity(
        subject="enamel mug", established_state="half full", note_a="", note_b="mug empty"
    )
    assert opinion.states_agree is False
    assert opinion.confidence < 0.6, "silence is insufficient evidence, not agreement"


def test_the_planted_media_mismatch_does_not_make_its_beat_uncovered(package, findings):
    """One bad take does not uncover a beat that has a good one. This is the rule."""
    mismatch = next(
        f
        for f in findings
        if f.check_type is CheckType.METADATA and f.truth_state is TruthState.CONFLICTING
    )
    beat_ids = package.take(mismatch.requirement_id).beat_ids
    outcomes = {o.beat_id: o for o in rollup.roll_up(package, findings)}
    for beat_id in beat_ids:
        assert outcomes[beat_id].status is rollup.BeatStatus.COVERED
    # The finding is still real and still routed to the DIT.
    assert mismatch.required_role.value == "dit"


def test_the_unreleased_background_performer_is_found(package, findings):
    gap = next(f for f in findings if f.requirement_id == "BG-07")
    assert gap.truth_state is TruthState.MISSING
    assert "not a pass" in gap.observation
    assert gap.required_role.value == "production_coordinator"


def test_the_orphan_shot_is_advisory_and_blocks_nothing(package):
    orphans = coverage.orphan_shots(package, RUN, policy.POLICY_VERSION)
    assert len(orphans) == 1
    assert orphans[0].severity.value == "advisory"
    assert orphans[0].requirement_id is None


def test_deterministic_checks_never_claim_less_than_certainty(findings):
    for finding in findings:
        if finding.check_type in {CheckType.METADATA, CheckType.RIGHTS}:
            assert finding.confidence == 1.0
            assert finding.inference is None


def test_model_assisted_checks_never_claim_certainty(findings):
    for finding in findings:
        if finding.inference is not None:
            assert finding.confidence < 1.0, (
                f"{finding.finding_id} presents an interpretation as a fact"
            )


# -- the comparative numbers, so they cannot drift unnoticed ----------------


def test_the_ablation_numbers_are_the_ones_the_readme_publishes():
    """The README states what each rule is worth. This is where that is measured.

    A number on a judge-facing surface has to be produced by something that can
    be re-run, and it has to fail when the thing it measures changes. Both
    ablations below found a real fail-open the first time they were run: the
    covered count went *up* when the model was removed.
    """
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "tools/ablation.py"],
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads((root / "docs" / "ablation.json").read_text(encoding="utf-8"))
    by_name = {r["ablation"]: r for r in rows}

    model = by_name["the model cannot be reached"]
    assert "31 of 34" in model["with_the_rule"]
    assert "0 of 34" in model["without_the_rule"], (
        "removing the model must remove the evidence. If this reads anything other "
        "than zero, something is counting a beat as covered without a coverage "
        "result, which is absent evidence read as a pass."
    )

    stale = by_name["staleness is asserted from a table instead of derived from digests"]
    assert "50 stale findings admitted instead of 0" in stale["delta"]

    seal = by_name["the finding seal is not verified"]
    assert "1 tampered record admitted instead of 0" in seal["delta"]
