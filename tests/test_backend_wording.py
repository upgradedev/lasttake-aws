"""Sentences the product prints, checked for what they say and not only that they exist.

Each test here pins a wording defect seen on the rendered page: a count that
read "1 raising exceptions", a zero count still "routed to production", a tool
summary that said "finding(s)", and a take note quoted with two full stops.

The corpus sentence the README quotes is pinned byte for byte in
tests/test_corpus_counts.py. These cover the other numbers the same code
produces once evidence moves, which is exactly when nobody re-reads it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lasttake.adapters.local.infrastructure import (
    LocalArtifactStore,
    LocalEventBus,
    LocalRunStore,
)
from lasttake.adapters.local.interpreter import OfflineInterpreter
from lasttake.agents.runtime import WrapRun
from lasttake.agents.tools import _record
from lasttake.checks import continuity, metadata, rights
from lasttake.domain import policy, rollup
from lasttake.domain.findings import TruthState
from lasttake.domain.package import load_package
from lasttake.domain.rollup import BeatOutcome, BeatStatus

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


def outcomes(covered=0, exceptions=0, unreleased=0, exception_status=BeatStatus.NO_COVERAGE):
    """Synthetic beat outcomes in the proportions a test names."""
    rows: list[BeatOutcome] = []
    for status, count in (
        (BeatStatus.COVERED, covered),
        (exception_status, exceptions),
        (BeatStatus.NO_RELEASE_RECORD, unreleased),
    ):
        for _ in range(count):
            rows.append(
                BeatOutcome(
                    beat_id=f"B-{len(rows) + 1:02d}",
                    slug="synthetic beat",
                    status=status,
                    reason="synthetic",
                    evidence_take_id=None,
                    blocking_finding_ids=(),
                )
            )
    return rows


# -- the count sentence -----------------------------------------------------


@pytest.mark.parametrize(
    ("covered", "exceptions", "unreleased", "expected"),
    [
        (
            31, 2, 1,
            "Of 34 required beats, 31 covered with evidence, 2 raising exceptions "
            "with named sources, 1 with no release record and routed to production.",
        ),
        (
            33, 1, 0,
            "Of 34 required beats, 33 covered with evidence, 1 raising an exception "
            "with named sources, 0 with no release record.",
        ),
        (
            32, 1, 1,
            "Of 34 required beats, 32 covered with evidence, 1 raising an exception "
            "with named sources, 1 with no release record and routed to production.",
        ),
        (
            32, 2, 0,
            "Of 34 required beats, 32 covered with evidence, 2 raising exceptions "
            "with named sources, 0 with no release record.",
        ),
        (
            34, 0, 0,
            "Of 34 required beats, 34 covered with evidence, 0 raising exceptions "
            "with named sources, 0 with no release record.",
        ),
        (
            31, 0, 3,
            "Of 34 required beats, 31 covered with evidence, 0 raising exceptions "
            "with named sources, 3 with no release record and routed to production.",
        ),
        (
            1, 0, 0,
            "Of 1 required beat, 1 covered with evidence, 0 raising exceptions "
            "with named sources, 0 with no release record.",
        ),
        (
            0, 1, 0,
            "Of 1 required beat, 0 covered with evidence, 1 raising an exception "
            "with named sources, 0 with no release record.",
        ),
    ],
)
def test_the_count_sentence_follows_the_numbers(covered, exceptions, unreleased, expected):
    assert rollup.sentence(outcomes(covered, exceptions, unreleased)) == expected


@pytest.mark.parametrize(
    "status",
    [BeatStatus.NO_COVERAGE, BeatStatus.CONTINUITY_EXCEPTION, BeatStatus.MEDIA_EXCEPTION],
)
def test_one_exception_of_any_kind_reads_in_the_singular(status):
    text = rollup.sentence(outcomes(covered=33, exceptions=1, exception_status=status))
    assert "1 raising an exception with named sources" in text
    assert "raising exceptions" not in text


def test_nothing_is_said_to_be_routed_to_production_when_nothing_was():
    text = rollup.sentence(outcomes(covered=33, exceptions=1, unreleased=0))
    assert text.endswith("0 with no release record.")
    assert "routed to production" not in text


def test_the_deploy_workflow_still_reads_the_count_after_the_grammar_change():
    """deploy.yml parses this sentence out of a live run with a regular expression.

    The grammar may follow the numbers, but the opening it matches must not
    move for the corpus the deployment runs against.
    """
    pattern = r"Of (\d+) required beats, (\d+) covered with evidence"
    for covered, exceptions, unreleased in ((31, 2, 1), (33, 1, 0), (0, 34, 0)):
        text = rollup.sentence(outcomes(covered, exceptions, unreleased))
        match = re.search(pattern, text)
        assert match, text
        assert (int(match.group(1)), int(match.group(2))) == (34, covered)


# -- the tool summary the orchestrator reads --------------------------------


@pytest.fixture()
def run(tmp_path):
    return WrapRun(
        run_id="wording",
        correlation_id="c-wording",
        package=load_package(CORPUS),
        bus=LocalEventBus(tmp_path / "events"),
        artifacts=LocalArtifactStore(tmp_path / "artifacts"),
        runs=LocalRunStore(tmp_path / "runs"),
        interpreter=OfflineInterpreter(),
        candidate_sha="deadbeef",
    )


def test_the_tool_summary_counts_findings_in_words(run):
    media = metadata.run(run.package, run.run_id, policy.POLICY_VERSION)
    mismatch = next(f for f in media if f.truth_state is TruthState.CONFLICTING)
    clean = next(f for f in media if f.truth_state is TruthState.VERIFIED)
    gap = next(
        f
        for f in rights.run(run.package, run.run_id, policy.POLICY_VERSION)
        if f.truth_state.is_exception
    )

    def first_line(findings):
        return _record(run, findings).splitlines()[0]

    assert first_line([mismatch]) == "1 finding recorded, 1 raising an exception."
    assert first_line([clean]) == "1 finding recorded, 0 raising exceptions."
    assert first_line([mismatch, clean]) == "2 findings recorded, 1 raising an exception."
    assert first_line([mismatch, gap]) == "2 findings recorded, 2 raising exceptions."


# -- a take note quoted inside a continuity observation ---------------------


def test_the_planted_conflict_quotes_each_note_with_one_full_stop():
    package = load_package(CORPUS)
    conflict = next(
        f
        for f in continuity.run(package, "wording", OfflineInterpreter(), policy.POLICY_VERSION)
        if f.truth_state is TruthState.CONFLICTING
    )
    assert ".." not in conflict.observation, conflict.observation
    assert (
        "T-026 notes: Circled. Mug half full, handle camera left. Good on the sit. "
        "T-027 notes: Also circled by the director."
    ) in conflict.observation
    assert conflict.observation.endswith("Mug empty, handle camera right.")


@pytest.mark.parametrize(
    ("note", "as_quoted"),
    [
        ("Good on the sit.", "Good on the sit."),
        ("No full stop", "No full stop."),
        ("Held on the look...", "Held on the look..."),
        ("Trailing space. ", "Trailing space."),
        ("", "no note."),
        (None, "no note."),
        ("   ", "no note."),
    ],
)
def test_one_trailing_period_is_dropped_before_the_observation_adds_its_own(note, as_quoted):
    """One stop, never more: an ellipsis the supervisor wrote still reads as one."""
    assert f"{continuity._note_in_sentence(note)}." == as_quoted
