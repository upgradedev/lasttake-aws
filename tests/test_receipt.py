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


def test_the_orphan_advisory_is_not_told_to_shoot_a_beat_that_is_gone():
    """The page and the receipt have to agree about what to do.

    The orphan-shot finding is a coverage finding with no requirement id: a shot
    planned against a beat the current revision no longer has. Telling somebody
    to shoot one more setup for it sends them after something that does not
    exist, and a receipt read away from the page is exactly where that would go
    uncorrected.
    """
    manifest = a_receipt()
    orphan = next(
        r for r in manifest["still_open"]
        if r["check_type"] == "coverage" and r["truth_state"] == "unknown"
    )
    assert "rebuilt against the current script revision" in orphan["next_action"]

    missing = next(
        r for r in manifest["still_open"]
        if r["check_type"] == "coverage" and r["truth_state"] == "missing"
    )
    assert "Shoot one more setup" in missing["next_action"]
    assert missing["next_action"] != orphan["next_action"]


# -- the summary a person pastes, once a human has decided ------------------


def _media_mismatch(findings):
    return next(
        f
        for f in findings
        if f.check_type.value == "metadata" and f.truth_state.value == "conflicting"
    )


def _summary_line(manifest, finding_id):
    return next(
        line
        for line in manifest["human_readable"].splitlines()
        if line.startswith(f"{finding_id}:")
    )


def _decided(finding, action, role, decision_id="dec-w", digest=None):
    return policy.HumanDecision(
        decision_id=decision_id,
        finding_id=finding.finding_id,
        action=action,
        actor="Synthetic reviewer",
        role=role,
        reason="Reviewed the supplied sources for this fictional scene.",
        finding_sha256=digest or finding.record_sha256,
    )


def _receipt_with(package, findings, decisions):
    return receipt.build(
        kind="wrap",
        run_id=RUN,
        package=package,
        findings=findings,
        decisions=decisions,
        policy_version=policy.POLICY_VERSION,
    )


def test_an_accepted_exception_is_summarised_as_decided_not_as_work_to_do():
    """The DIT accepted the identifier mismatch.

    The receipt must not then tell somebody to reconcile it before it is
    cleared, and it must still say the finding is open.
    """
    package = load_package(CORPUS)
    findings = findings_for(package)
    mismatch = _media_mismatch(findings)
    accepted = _decided(mismatch, policy.DecisionAction.ACCEPT_EXCEPTION, policy.Role.DIT)
    manifest = _receipt_with(package, findings, [accepted])
    assert receipt.verify(manifest)

    line = _summary_line(manifest, mismatch.finding_id)
    assert "Exception accepted by Synthetic reviewer (DIT / data manager)" in line
    assert "stays open on the turnover" in line
    assert "Next:" not in line
    assert "before it is cleared" not in line
    assert "(dit)" not in line and "accept_exception" not in line

    row = next(r for r in manifest["still_open"] if r["finding_id"] == mismatch.finding_id)
    assert line.endswith(row["next_action"]), "the field and the summary say one thing"
    assert "before it is cleared" not in row["next_action"]
    # The sealed record of the decision itself is unchanged.
    assert row["a_human_decided"]["action"] == "accept_exception"
    assert row["a_human_decided"]["role"] == "dit"
    assert "not a fixed one" in row["a_human_decided"]["still_open_because"]

    text = json.dumps(manifest).lower()
    for clearance in ("clear to shoot", "cleared to shoot", "rules verified",
                      "no issues found", "safe to wrap.", "legally cleared"):
        assert clearance not in text, clearance


def test_the_summary_gives_the_same_next_step_as_the_turnover():
    """One handoff page shows both documents, and they must not give two next steps."""
    from lasttake.domain import turnover

    package = load_package(CORPUS)
    findings = findings_for(package)
    manifest = _receipt_with(package, findings, [])
    packet = policy.evaluate(RUN, package, findings, [])
    handoff = turnover.generate(
        RUN, package, findings, [], packet, approved_by="a 1st AD", approved_role="first_ad"
    ).manifest

    retained = handoff["outstanding_and_accepted_exceptions"]
    assert retained, "the corpus ships with open items on purpose"
    for item in retained:
        assert item["recommended_action"], item["finding_id"]
        line = _summary_line(manifest, item["finding_id"])
        assert line.endswith(f"Next: {item['recommended_action']}"), line


def test_a_confirmed_finding_keeps_its_instruction_and_names_who_confirmed_it():
    """Confirming agrees the problem is real. It settles nothing, so the next step stands."""
    package = load_package(CORPUS)
    findings = findings_for(package)
    mismatch = _media_mismatch(findings)
    confirmed = _decided(mismatch, policy.DecisionAction.CONFIRM, policy.Role.DIT)
    manifest = _receipt_with(package, findings, [confirmed])

    line = _summary_line(manifest, mismatch.finding_id)
    assert "Confirmed by Synthetic reviewer (DIT / data manager); the finding is still open." in line
    assert line.endswith(f"Next: {mismatch.recommended_action}")
    row = next(r for r in manifest["still_open"] if r["finding_id"] == mismatch.finding_id)
    assert row["next_action"] == receipt.next_action(mismatch)


def test_a_rejected_false_positive_is_summarised_as_decided_and_still_listed():
    package = load_package(CORPUS)
    findings = findings_for(package)
    conflict = next(
        f for f in findings if f.check_type.value == "continuity" and f.requirement_id
    )
    rejected = _decided(
        conflict, policy.DecisionAction.REJECT_FALSE_POSITIVE, policy.Role.SCRIPT_SUPERVISOR
    )
    manifest = _receipt_with(package, findings, [rejected])

    line = _summary_line(manifest, conflict.finding_id)
    assert "Rejected as a false positive by Synthetic reviewer (Script supervisor)" in line
    assert "stays open on the record" in line
    assert "Next:" not in line


def test_a_decision_the_evidence_outran_is_not_summarised_as_standing():
    package = load_package(CORPUS)
    findings = findings_for(package)
    conflict = next(
        f for f in findings if f.check_type.value == "continuity" and f.requirement_id
    )
    stale = _decided(
        conflict,
        policy.DecisionAction.ACCEPT_EXCEPTION,
        policy.Role.SCRIPT_SUPERVISOR,
        digest="0" * 64,
    )
    manifest = _receipt_with(package, findings, [stale])

    line = _summary_line(manifest, conflict.finding_id)
    assert "An earlier decision no longer applies" in line
    assert "Exception accepted" not in line
    assert line.endswith(f"Next: {conflict.recommended_action}")


def test_the_summary_names_roles_the_way_the_page_does():
    manifest = a_receipt()
    items = [
        line for line in manifest["human_readable"].splitlines() if line.startswith(f"{RUN}:")
    ]
    assert items
    body = "\n".join(items)
    for stored in ("script_supervisor", "production_coordinator", "; dit"):
        assert stored not in body, stored
    for label in ("Script supervisor", "DIT / data manager", "Production coordinator"):
        assert label in body, label


def test_every_role_has_the_label_the_interface_shows():
    """The labels from frontend/src/model.ts, so one role does not read two ways on one screen.

    Keyed here by the backend's stored role value. The interface keys the
    assistant editor as ``editorial``; the label it shows is the same.
    """
    assert receipt.ROLE_LABELS == {
        "script_supervisor": "Script supervisor",
        "first_ad": "1st AD",
        "dit": "DIT / data manager",
        "production_coordinator": "Production coordinator",
        "assistant_editor": "Assistant editor",
    }
    for role in policy.Role:
        assert receipt.role_label(role) == receipt.ROLE_LABELS[role.value]
        assert receipt.role_label(role.value) == receipt.ROLE_LABELS[role.value]
    assert receipt.action_words(policy.DecisionAction.ACCEPT_EXCEPTION) == "accept exception"


def test_the_page_next_action_follows_the_latest_authorised_decision():
    """The finding detail on the page, given the run's stored decisions.

    The scene page prints ``next_action`` under "Next action". Given the latest
    authorised decision over the finding, a settling decision replaces the
    instruction, and everything else keeps it: a later confirmation brings the
    instruction back, a decision by a role without authority changes nothing,
    and a decision the evidence has outrun changes nothing. Stored decisions
    are dicts, so they go through the one reader the rest of the code uses.
    """
    import dataclasses

    package = load_package(CORPUS)
    mismatch = _media_mismatch(findings_for(package))
    instruction = receipt.next_action(mismatch)
    assert "before it is cleared" in instruction

    def at(decision, when):
        return dataclasses.replace(decision, at=f"2026-08-19T{when}:00Z")

    def page(*decisions):
        stored = [policy.decision_from_dict(d.to_dict()) for d in decisions]
        return receipt.next_action(mismatch, policy.latest_decision(mismatch, stored))

    Action, Role = policy.DecisionAction, policy.Role
    accept = at(_decided(mismatch, Action.ACCEPT_EXCEPTION, Role.DIT, "dec-1"), "23:10")
    confirm_later = at(_decided(mismatch, Action.CONFIRM, Role.DIT, "dec-2"), "23:20")
    confirm_earlier = at(_decided(mismatch, Action.CONFIRM, Role.DIT, "dec-0"), "23:00")
    wrong_role_later = at(
        _decided(mismatch, Action.CONFIRM, Role.SCRIPT_SUPERVISOR, "dec-3"), "23:30"
    )
    outrun = at(
        _decided(mismatch, Action.ACCEPT_EXCEPTION, Role.DIT, "dec-4", digest="0" * 64),
        "23:40",
    )
    rejected = at(_decided(mismatch, Action.REJECT_FALSE_POSITIVE, Role.DIT, "dec-5"), "23:10")

    settled = page(accept)
    assert settled.startswith("Exception accepted by Synthetic reviewer (DIT / data manager). ")
    assert "stays open on the turnover" in settled
    assert "before it is cleared" not in settled

    assert page() == instruction
    assert page(accept, confirm_later) == instruction
    assert page(confirm_earlier, accept) == settled
    assert page(accept, wrong_role_later) == settled
    assert page(accept, outrun) == instruction
    assert page(rejected).startswith(
        "Rejected as a false positive by Synthetic reviewer (DIT / data manager). "
    )
