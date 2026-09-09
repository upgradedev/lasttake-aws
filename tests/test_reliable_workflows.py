"""Boundary regressions: original triggers, alternate routes and valid controls."""
import copy

import pytest

from lasttake.app import handler as H
from lasttake.app.ingest import load_amendments
from lasttake.domain import policy
from lasttake.domain.events import EventType
from lasttake.ports.infrastructure import Receipt
from .test_handler import A_TAKE, offline_backends, post
from .test_workspace import owned


RELEASE = dict(record_id="REL-TEST", subject_id="BG-07", subject_kind="person",
               document_type="background release", scope="all media",
               territory="worldwide", status="executed")
REPORT = dict(take_id="T-900", media_id="A007R2G01", lens_mm=50, camera_roll="A007")


def eligible(body):
    state = post("/api/checkpoint", body)
    answer = {**body, "role": "first_ad", "approve": False,
              "interrupt_id": state["pending_approval"]["id"]}
    assert post("/api/approve", answer)["status"] == 200
    assert post("/api/late-take", body)["status"] == 200
    state = post("/api/resolve-rights", body)
    for cause in state["causes"]:
        finding = next(f for f in state["exceptions"] if f["finding_id"] == cause["finding_id"])
        result = post("/api/decide", {**body, "finding_id": finding["finding_id"],
            "finding_sha256": finding["record_sha256"], "role": cause["required_role"],
            "action": "accept_exception", "actor": "Synthetic reviewer", "reason": "Reviewed records."})
        assert result["status"] == 200
    assert post("/api/evaluate", body)["eligible"]


@pytest.mark.parametrize("route", ["approve", "wrap"])
def test_pending_wrap_cannot_approve_changed_evidence_through_either_route(route):
    body = owned()
    eligible(body)
    pending = post("/api/wrap", {**body, "role": "first_ad"})["pending_approval"]
    assert pending["reason"]["kind"] == "wrap"
    assert post("/api/ingest", {**body, "kind": "rights_record", "document": RELEASE})["status"] == 200
    answer = {**body, "role": "first_ad", "interrupt_id": pending["id"], "approve": True}
    refused = post("/api/" + route, answer)
    assert refused["status"] == 409
    assert not post("/api/state", body)["wrap_approved"]
    assert not any(e["event_type"] == "wrap.ready" for e in post("/api/events", body)["events"])
    assert post("/api/" + route, {**answer, "approve": False})["status"] == 200
    fresh = post("/api/wrap", {**body, "role": "first_ad"})["pending_approval"]
    assert fresh and fresh["id"] != pending["id"]
    approved = post("/api/" + route, {**answer, "interrupt_id": fresh["id"]})
    assert approved["status"] == 200 and approved["wrap_approved"]


@pytest.mark.parametrize("report,truth", [(None, "missing"), (REPORT, "verified"),
    ({**REPORT, "media_id": "OTHER-CARD"}, "conflicting")])
def test_camera_corroboration_requires_an_actual_supplied_report(report, truth):
    body = owned()
    document = copy.deepcopy(A_TAKE)
    document.pop("camera_report_row", None)
    if report is not None:
        document["camera_report_row"] = report
    result = post("/api/ingest", {**body, "kind": "take", "document": document})
    assert result["status"] == 200
    run = H.build_run(body["run_id"])
    finding = next(f for f in run.load_findings() if f["check_type"] == "metadata" and f["requirement_id"] == "T-900")
    assert finding["truth_state"] == truth
    assert bool(run.package.camera_row("T-900")) == (report is not None)
    assert post("/api/state", body)["package_revision_digest"] == result["package_revision_digest"]


@pytest.mark.parametrize("expiry", ["tomorrow", "2026-02-30", "2026-9-09", "20260909", 42, True, [], {}])
def test_invalid_rights_date_refuses_before_any_persist_and_allows_correction(expiry):
    body = owned()
    post("/api/checkpoint", body)
    run = H.build_run(body["run_id"])
    before = (run.package.revision_digest(), run.load_findings(), run.load_decisions(),
              run.runs.load_audit(run.run_id), load_amendments(run.artifacts, run.run_id))
    events = post("/api/events", body)["events"]
    rejected = post("/api/ingest", {**body, "kind": "rights_record", "document": {**RELEASE, "expires_on": expiry}})
    assert rejected["status"] == 400
    restored = H.build_run(run.run_id)
    after = (restored.package.revision_digest(), restored.load_findings(), restored.load_decisions(),
             restored.runs.load_audit(run.run_id), load_amendments(restored.artifacts, run.run_id))
    assert after == before
    assert post("/api/events", body)["events"] == events
    corrected = post("/api/ingest", {**body, "kind": "rights_record", "document": {**RELEASE, "expires_on": "2030-02-28"}})
    assert corrected["status"] == 200
    assert corrected["package_revision_digest"] != before[0]


def test_latest_confirm_revokes_old_acceptance_in_gate_and_receipt():
    body = owned()
    eligible(body)
    state = post("/api/state", body)
    finding = next(f for f in state["exceptions"] if f["requirement_id"] == "CR-01")
    action = {**body, "finding_id": finding["finding_id"], "finding_sha256": finding["record_sha256"],
              "role": "script_supervisor", "actor": "Synthetic supervisor", "reason": "The mismatch still stands."}
    revoked = post("/api/decide", {**action, "action": "confirm"})
    assert not revoked["eligible"]
    record = post("/api/receipt", body)["receipt"]
    current = next(row for row in record["still_open"] if row["finding_id"] == finding["finding_id"])
    assert current["a_human_decided"]["action"] == "confirm"
    assert post("/api/decide", {**action, "action": "accept_exception"})["eligible"]


def test_explicit_bus_rejection_is_retryable_but_a_claim_is_not_success(monkeypatch):
    body = owned()
    run = H.build_run(body["run_id"])
    attempts = []
    def reject(event):
        attempts.append(event)
        return Receipt(False, event.event_id, "EventBridge rejected entry")
    monkeypatch.setattr(run.bus, "publish", reject)
    payload = {"beat_id": "B-17"}
    first = run.publish(EventType.PICKUP_REQUESTED, payload, idempotent=True)
    assert not first.accepted
    second = run.publish(EventType.PICKUP_REQUESTED, payload, idempotent=True)
    assert not second.accepted and len(attempts) == 2
    key = run.build_event(EventType.PICKUP_REQUESTED, payload).idempotency_key
    assert run.runs.claim(key, run.run_id)
    pending = run.publish(EventType.PICKUP_REQUESTED, payload, idempotent=True)
    assert not pending.accepted and len(attempts) == 2


def test_ambiguous_publish_exception_does_not_blindly_resend(monkeypatch):
    body = owned()
    run = H.build_run(body["run_id"])
    attempts = []
    def uncertain(event):
        attempts.append(event)
        raise TimeoutError("Response lost after submission")
    monkeypatch.setattr(run.bus, "publish", uncertain)
    first = run.publish(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"}, idempotent=True)
    again = run.publish(EventType.PICKUP_REQUESTED, {"beat_id": "B-17"}, idempotent=True)
    assert not first.accepted and not again.accepted
    assert len(attempts) == 1
