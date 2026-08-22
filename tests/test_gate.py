"""The gate must fail closed. These tests try to make it fail open.

Each one removes a different kind of evidence and asserts the scene does not
become eligible as a result. A gate that only gets tested on the happy path is
a gate nobody has actually checked.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from lasttake.checks import continuity, coverage, metadata, rights
from lasttake.domain import policy, rollup
from lasttake.domain.findings import CheckType, Role, TruthState, from_dict
from lasttake.domain.package import load_package
from lasttake.adapters.local.interpreter import OfflineInterpreter

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
RUN = "test-run"


@pytest.fixture(scope="module")
def package():
    return load_package(CORPUS)


@pytest.fixture(scope="module")
def findings(package):
    interp = OfflineInterpreter()
    out = coverage.run(package, RUN, interp, policy.POLICY_VERSION)
    out += coverage.orphan_shots(package, RUN, policy.POLICY_VERSION)
    out += continuity.run(package, RUN, interp, policy.POLICY_VERSION)
    out += metadata.run(package, RUN, policy.POLICY_VERSION)
    out += rights.run(package, RUN, policy.POLICY_VERSION)
    return out


def test_the_corpus_is_not_eligible_on_the_first_pass(package, findings):
    packet = policy.evaluate(RUN, package, findings, [])
    assert packet.eligible is False
    assert packet.causes, "a scene with a missing release must produce causes"


def test_a_missing_check_result_is_not_a_pass(package, findings):
    """Delete one check's result. The scene must not become eligible."""
    without_rights = [f for f in findings if f.check_type is not CheckType.RIGHTS]
    packet = policy.evaluate(RUN, package, without_rights, [])
    assert packet.eligible is False
    reasons = " ".join(c.reason for c in packet.causes)
    assert "no current result" in reasons


def test_two_results_for_one_check_is_a_contradiction(package, findings):
    duplicated = list(findings) + [copy.deepcopy(findings[0])]
    duplicated[-1].truth_state = TruthState.VERIFIED
    packet = policy.evaluate(RUN, package, duplicated, [])
    reasons = " ".join(c.reason for c in packet.causes)
    assert "current results for one check" in reasons


def test_a_finding_whose_evidence_moved_is_discarded_not_reused(package, findings):
    """Staleness is per source. Re-stamping a revision must not launder it."""
    from lasttake.domain.findings import Source

    stale = copy.deepcopy(findings)
    for finding in stale:
        finding.sources = [
            Source(s.artifact_id, "f" * 64, s.kind) for s in finding.sources
        ]
    packet = policy.evaluate(RUN, package, stale, [])
    assert packet.eligible is False
    assert len(packet.discarded) == len(stale)
    assert packet.counts["findings_admitted"] == 0
    assert "no longer current" in packet.discarded[0]


def test_only_the_findings_that_read_the_changed_artifact_go_stale(package, findings):
    """This is the targeted rerun, derived rather than asserted.

    Supplying a release changes one artifact. Coverage, continuity and media
    identity never read it, so the gate keeps them without a rerun. If this
    ever stops holding, the CLI's `Affected checks: rights` line becomes a
    claim the gate does not back, and the test fails rather than the demo.
    """
    from lasttake.domain.package import RightsRecord, with_rights_record

    updated = with_rights_record(
        package,
        RightsRecord(
            "REL-007", "BG-07", "person", "background release", "all media",
            "worldwide", None, "executed",
        ),
    )
    packet = policy.evaluate(RUN, updated, findings, [])
    rights_count = len([f for f in findings if f.check_type is CheckType.RIGHTS])
    assert len(packet.discarded) == rights_count
    assert all("rights_ledger" in d for d in packet.discarded)


def test_a_finding_judged_under_an_older_policy_is_discarded(package, findings):
    old = copy.deepcopy(findings)
    for finding in old:
        finding.policy_version = "0.0.1"
    packet = policy.evaluate(RUN, package, old, [])
    assert all("policy" in d for d in packet.discarded)


def test_the_wrong_role_cannot_close_an_exception(package, findings):
    """A DIT accepting a rights exception is no evidence, not weak evidence."""
    rights_exception = next(
        f
        for f in findings
        if f.check_type is CheckType.RIGHTS and f.truth_state is not TruthState.VERIFIED
    )
    decision = policy.HumanDecision(
        decision_id="d1",
        finding_id=rights_exception.finding_id,
        action=policy.DecisionAction.ACCEPT_EXCEPTION,
        actor="a data manager",
        role=Role.DIT,
        reason="looks fine to me",
    )
    packet = policy.evaluate(RUN, package, findings, [decision])
    still_blocked = [
        c for c in packet.causes if c.requirement_id == rights_exception.requirement_id
    ]
    assert still_blocked, "a DIT must not be able to close a rights exception"


def test_nobody_may_accept_away_a_missing_release():
    """Not even the role that owns rights. That decision is not on this system."""
    assert policy.MAY_ACCEPT_EXCEPTION[CheckType.RIGHTS] == set()
    assert not policy.authority_check(
        CheckType.RIGHTS,
        policy.DecisionAction.ACCEPT_EXCEPTION,
        Role.PRODUCTION_COORDINATOR,
    )


def test_a_supervisor_rejecting_a_false_positive_closes_a_coverage_exception(
    package, findings
):
    coverage_gap = next(
        f
        for f in findings
        if f.check_type is CheckType.COVERAGE
        and f.truth_state is TruthState.MISSING
        and f.requirement_id
    )
    decision = policy.HumanDecision(
        decision_id="d2",
        finding_id=coverage_gap.finding_id,
        action=policy.DecisionAction.REJECT_FALSE_POSITIVE,
        actor="the script supervisor",
        role=Role.SCRIPT_SUPERVISOR,
        reason="we shot it on the B camera, it is on the other card",
    )
    before = policy.evaluate(RUN, package, findings, [])
    after = policy.evaluate(RUN, package, findings, [decision])
    blocked_before = {c.requirement_id for c in before.causes}
    blocked_after = {c.requirement_id for c in after.causes}
    assert coverage_gap.requirement_id in blocked_before
    assert coverage_gap.requirement_id not in blocked_after
    # And the finding itself is untouched.
    assert coverage_gap.truth_state is TruthState.MISSING


def test_expected_checks_come_from_the_package_not_from_the_agent(package):
    """An agent cannot make a requirement vanish by not looking at it."""
    expected = policy.expected_checks(package)
    beat_checks = {c.requirement_id for c in expected if c.check_type is CheckType.COVERAGE}
    assert beat_checks == {b.beat_id for b in package.required_beats}
    assert len(expected) > len(package.required_beats)
