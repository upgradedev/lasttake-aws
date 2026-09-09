"""The receipt has to survive leaving the page.

Everything here is about that one property. A receipt is going to be pasted into
an email, read on a phone at 06:40, and opened again a week later by somebody
who never saw the interface. So the test asks the question that reader asks:
can this document, on its own, tell me which run it is about, what policy read
it, what is still open, and what it is not claiming?
"""

from __future__ import annotations

import copy
import json
import pathlib

from lasttake.checks import continuity as continuity_check
from lasttake.checks import coverage as coverage_check
from lasttake.checks import metadata as metadata_check
from lasttake.checks import rights as rights_check
from lasttake.domain import policy, receipt
from lasttake.domain.package import load_package

CORPUS = pathlib.Path(__file__).resolve().parents[1] / "corpus"
RUN = "receipt-test"


def findings_for(package):
    from lasttake.adapters.local.interpreter import OfflineInterpreter

    interpreter = OfflineInterpreter()
    out = coverage_check.run(package, RUN, interpreter, policy.POLICY_VERSION)
    out += coverage_check.orphan_shots(package, RUN, policy.POLICY_VERSION)
    out += continuity_check.run(package, RUN, interpreter, policy.POLICY_VERSION)
    out += metadata_check.run(package, RUN, policy.POLICY_VERSION)
    out += rights_check.run(package, RUN, policy.POLICY_VERSION)
    return [f.resealed() for f in out]


def a_receipt(decisions=None, kind="pickup"):
    package = load_package(CORPUS)
    return receipt.build(
        kind=kind,
        run_id=RUN,
        package=package,
        findings=findings_for(package),
        decisions=decisions or [],
        policy_version=policy.POLICY_VERSION,
    )


def test_it_names_its_own_run_version_and_package():
    """The four fields without which a copy is an anecdote."""
    manifest = a_receipt()
    assert manifest["run_id"] == RUN
    assert manifest["schema"] == receipt.RECEIPT_SCHEMA
    assert manifest["policy_version"] == policy.POLICY_VERSION
    assert len(manifest["package_revision_digest"]) == 64
    assert manifest["scene_id"]
    assert manifest["script_revision"]


def test_it_seals_itself_and_the_seal_is_checkable():
    manifest = a_receipt()
    assert receipt.verify(manifest)

    tampered = copy.deepcopy(manifest)
    tampered["still_open_count"] = 0
    assert not receipt.verify(tampered)


def test_every_open_item_carries_a_role_a_next_action_and_a_source():
    """The three things LT-03 asks a reader to find without an agent trace."""
    manifest = a_receipt()
    assert manifest["still_open"], "the corpus ships with open items on purpose"
    for row in manifest["still_open"]:
        assert row["responsible_role"], row
        assert row["next_action"], row
        assert row["read_from"], row
        for source in row["read_from"]:
            assert len(source["sha256"]) == 64


def test_an_accepted_exception_still_travels_as_open():
    """The one that matters downstream.

    Somebody signed for it, and it is still a known problem. A receipt that
    quietly drops it is how an approved defect reaches the edit as a surprise.
    """
    package = load_package(CORPUS)
    findings = findings_for(package)
    conflict = next(
        f for f in findings if f.check_type.value == "continuity" and f.requirement_id
    )
    accepted = policy.HumanDecision(
        decision_id="dec-1",
        finding_id=conflict.finding_id,
        action=policy.DecisionAction.ACCEPT_EXCEPTION,
        actor="a script supervisor",
        role=policy.Role.SCRIPT_SUPERVISOR,
        reason="Reviewed on the floor, the change is intentional.",
        finding_sha256=conflict.record_sha256,
    )
    manifest = receipt.build(
        kind="pickup",
        run_id=RUN,
        package=package,
        findings=findings,
        decisions=[accepted],
        policy_version=policy.POLICY_VERSION,
    )
    row = next(
        r for r in manifest["still_open"] if r["finding_id"] == conflict.finding_id
    )
    assert row["a_human_decided"]["action"] == "accept_exception"
    assert row["a_human_decided"]["role"] == "script_supervisor"
    assert "not a fixed one" in row["a_human_decided"]["still_open_because"]


def test_a_decision_the_evidence_outran_is_marked_rather_than_shown_as_current():
    package = load_package(CORPUS)
    findings = findings_for(package)
    conflict = next(
        f for f in findings if f.check_type.value == "continuity" and f.requirement_id
    )
    stale = policy.HumanDecision(
        decision_id="dec-2",
        finding_id=conflict.finding_id,
        action=policy.DecisionAction.ACCEPT_EXCEPTION,
        actor="a script supervisor",
        role=policy.Role.SCRIPT_SUPERVISOR,
        reason="Taken about an earlier reading.",
        finding_sha256="0" * 64,
    )
    manifest = receipt.build(
        kind="pickup",
        run_id=RUN,
        package=package,
        findings=findings,
        decisions=[stale],
        policy_version=policy.POLICY_VERSION,
    )
    row = next(
        r for r in manifest["still_open"] if r["finding_id"] == conflict.finding_id
    )
    assert row["a_human_decided"] is None
    assert row["an_earlier_decision_no_longer_applies"] is True


def test_it_says_what_it_is_not_claiming():
    manifest = a_receipt()
    limits = " ".join(manifest["what_this_does_not_say"]).lower()
    assert "cleared in law" in limits
    assert "creatively complete" in limits
    assert "absent evidence" in limits
    assert manifest["rights_disclaimer"]


def test_it_says_the_production_is_invented():
    manifest = a_receipt()
    assert "fictional" in manifest["synthetic_corpus_notice"].lower()


def test_it_never_prints_a_clearance():
    """The same sentences the live probe and the uptime check forbid."""
    text = json.dumps(a_receipt()).lower()
    # Exactly the tuples in tools/prose_gate.py and tools/dast_probe.py. Those
    # match substrings and cannot tell an assertion from its denial, so the
    # receipt must not contain one even while disclaiming it.
    for clearance in ("clear to shoot", "cleared to shoot", "rules verified",
                      "no issues found", "safe to wrap.", "legally cleared"):
        assert clearance not in text, clearance


def test_a_receipt_is_about_a_pickup_or_a_wrap():
    import pytest

    with pytest.raises(ValueError):
        a_receipt(kind="whatever")
