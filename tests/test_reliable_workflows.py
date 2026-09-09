"""Boundary regressions: original triggers, alternate routes and valid controls."""
import copy
import json
import subprocess
import sys

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


def test_renewed_wrap_review_supersedes_old_authority_without_deleting_receipt():
    body = {**owned(), "role": "first_ad"}
    eligible(body)
    first = post("/api/wrap", body)["pending_approval"]
    assert post("/api/approve", {**body, "interrupt_id": first["id"], "approve": True})["wrap_approved"]
    run = H.build_run(body["run_id"])
    saved_approval = run.current_wrap_approval()
    second = post("/api/wrap", body)
    assert not second["wrap_approved"] and second["pending_approval"]["id"] != first["id"]
    assert "Refusing" in post("/api/turnover", body)["message"]
    declined = post("/api/approve", {**body, "interrupt_id": second["pending_approval"]["id"], "approve": False})
    assert not declined["wrap_approved"]
    assert "Refusing" in post("/api/turnover", body)["message"]
    assert saved_approval in run.runs.load_audit(run.run_id)
    assert run.publish_approved(EventType.WRAP_READY, {k:v for k,v in saved_approval.items()
        if k not in {"kind", "at", "receipt", "accepted"}}).outcome == "refused"
    third = post("/api/wrap", body)["pending_approval"]
    assert post("/api/wrap", {**body, "interrupt_id": third["id"], "approve": True})["wrap_approved"]
    accepted = [d for d in run.delivery_states() if d["event_type"] == "wrap.ready" and d["accepted"]]
    assert len(accepted) == 2
    assert len({d["idempotency_key"] for d in accepted}) == 2
    assert post("/api/turnover", body)["turnover"]


def test_old_policy_findings_require_explicit_checkpoint_without_history_loss():
    body = owned()
    state = post("/api/checkpoint", body)
    run = H.build_run(body["run_id"])
    historical = run.load_findings()
    for finding in historical:
        finding["policy_version"] = "1.0.0"
    run.runs.save_findings(run.run_id, historical)
    restored = post("/api/state", body)
    assert restored["needs_checkpoint"] and restored["counts"] is None
    assert "1.0.0" in restored["recovery_reason"] and "fresh checkpoint" in restored["recovery_reason"]
    assert not restored["eligible"]
    assert post("/api/approve", {**body, "role": "first_ad", "approve": False,
        "interrupt_id": state["pending_approval"]["id"]})["status"] == 200
    fresh = post("/api/checkpoint", body)
    assert fresh["counts"] and not fresh["needs_checkpoint"]


def test_finding_delivery_batch_preserves_outcomes_without_per_finding_audit(monkeypatch):
    from lasttake.agents.tools import build_tools
    run = H.build_run(owned()["run_id"])
    monkeypatch.setattr(run.bus, "publish", lambda event: Receipt(False, event.event_id, "Explicit rejection"))
    assert "need review" in str(build_tools(run)[2]())
    audits = run.runs.load_audit(run.run_id)
    assert len([a for a in audits if a["kind"] == "event.delivery.batch"]) == 1
    assert not any(a["kind"] == "event.delivery" for a in audits)
    assert len(run.delivery_states()) == len(run.load_findings())
    assert all(d["status"] == "rejected" and d["elapsed_ms"] >= 0 for d in run.delivery_states())


@pytest.mark.parametrize("response,status", [
    ({"FailedEntryCount": 1, "Entries": [{"ErrorCode": "InternalFailure", "ErrorMessage": "rejected"}]}, "rejected"),
    ({"FailedEntryCount": 0, "Entries": [{"ErrorCode": "AccessDeniedException"}]}, "rejected"),
    ({"FailedEntryCount": 0, "Entries": []}, "unknown"),
    ({"FailedEntryCount": 0, "Entries": [{"EventId": "actual-aws-event-id"}]}, "accepted"),
    (TimeoutError("response lost"), "unknown"),
])
def test_aws_entry_receipts_do_not_infer_acceptance_from_s3(response, status):
    from types import SimpleNamespace
    from lasttake.adapters.aws.infrastructure import EventBridgeBus
    saved = []
    def put_events(**_):
        if isinstance(response, Exception):
            raise response
        return response
    bus = EventBridgeBus("configured-bus", "artifacts", events_client=SimpleNamespace(put_events=put_events),
        s3_client=SimpleNamespace(put_object=lambda **kw: saved.append(kw)))
    run = H.build_run(owned()["run_id"])
    result = bus.publish(run.build_event(EventType.PICKUP_REQUESTED, {"approval_id": "review-a"}))
    assert len(saved) == 1 and result.outcome == status
    assert result.accepted == (status == "accepted")
    if result.accepted:
        assert result.reference == "actual-aws-event-id" and "downstream completion is not established" in result.detail


def test_rejected_pickup_retries_through_owned_api_and_replays_actual_receipt(monkeypatch):
    body = owned()
    run = H.build_run(body["run_id"])
    attempts = []
    original = type(run.bus).publish
    def publish(bus, event):
        if event.event_type is EventType.PICKUP_REQUESTED:
            attempts.append(event)
            if len(attempts) == 1:
                return Receipt(False, event.event_id, "Explicit entry rejection")
        return original(bus, event)
    monkeypatch.setattr(type(run.bus), "publish", publish)
    pending = post("/api/checkpoint", body)["pending_approval"]
    state = post("/api/approve", {**body, "role": "first_ad", "approve": True, "interrupt_id": pending["id"]})
    assert "rejected" in state["message"] and "Pickup approved" not in state["message"]
    rejected = next(row for row in state["delivery_outcomes"] if row["event_type"] == "pickup.requested")
    retry = {**body, "role": "first_ad", "idempotency_key": rejected["idempotency_key"]}
    assert post("/api/retry-delivery", {**retry, "role": "editorial"})["status"] == 403
    assert post("/api/retry-delivery", {**retry, "session_id": "0" * 64})["status"] == 403
    accepted = post("/api/retry-delivery", retry)
    assert accepted["status"] == 200 and accepted["delivery"]["accepted"]
    assert post("/api/retry-delivery", retry)["delivery"] == accepted["delivery"]
    assert len(attempts) == 2


def test_final_wrap_guard_refuses_stale_or_wrong_role_without_http_guard():
    body = owned()
    eligible(body)
    run = H.build_run(body["run_id"])
    payload = {**run.review_binding(), "approval_id": "direct-review", "required_role": "first_ad",
               "approved_by_role": "first_ad"}
    assert run.publish_approved(EventType.WRAP_READY, {**payload, "approved_by_role": "editorial"}).outcome == "refused"
    assert post("/api/ingest", {**body, "kind": "rights_record", "document": RELEASE})["status"] == 200
    changed = H.build_run(run.run_id)
    assert changed.publish_approved(EventType.WRAP_READY, payload).outcome == "refused"
    assert not any(d["event_type"] == "wrap.ready" for d in changed.delivery_states())
    assert changed.publish_approved(EventType.WRAP_READY, {**payload, **changed.review_binding()}).accepted


def test_evidence_bundle_reports_serialized_model_and_unknown_human_metrics():
    body = owned()
    post("/api/checkpoint", body)
    bundle = post("/api/receipt", body)["receipt"]
    assert bundle["source_manifest"] and bundle["execution"]["mode"] == "offline-demo"
    assert bundle["human_active_seconds"] is None and bundle["measured_benefit"] is None
    assert "SHA-256 identifies bytes" in bundle["human_readable"]
    assert "does not prove source authenticity, human identity or factual truth" in bundle["human_readable"]
    assert bundle["delivery_outcomes"] and bundle["finding_provenance"]
    assert any(f["model_id"] is None for f in bundle["finding_provenance"])
    assert any(f["model_id"] == "offline-lexical/1.0.0" for f in bundle["finding_provenance"])


def fresh_process_request(root, path, body):
    code = """import json,sys
from pathlib import Path
from types import SimpleNamespace
from lasttake.app.local_server import configure
from lasttake.app import handler as H
configure(Path(sys.argv[1]))
response=H.handler({'requestContext':{'http':{'path':sys.argv[2],'method':'POST'}},'body':sys.argv[3]}, SimpleNamespace(aws_request_id='fresh-process'))
print(json.dumps({'status':response['statusCode'],**json.loads(response['body'])}))
"""
    result = subprocess.run([sys.executable, "-c", code, str(root), path, json.dumps(body)],
                            capture_output=True, text=True, check=True, timeout=20)
    return json.loads(result.stdout.splitlines()[-1])


def test_unknown_wrap_cannot_be_resent_using_a_new_approval_id(monkeypatch, tmp_path):
    body = {**owned(), "role": "first_ad"}
    eligible(body)
    run = H.build_run(body["run_id"])
    original = type(run.bus).publish
    attempts = []
    def publish(bus, event):
        if event.event_type is EventType.WRAP_READY:
            attempts.append(event)
            raise TimeoutError("No response")
        return original(bus, event)
    monkeypatch.setattr(type(run.bus), "publish", publish)
    a = post("/api/wrap", body)["pending_approval"]
    first = post("/api/approve", {**body, "interrupt_id": a["id"], "approve": True})
    assert not first["wrap_approved"] and "unknown" in first["message"]
    b = post("/api/wrap", body)["pending_approval"]
    assert b["id"] != a["id"]
    second = post("/api/approve", {**body, "interrupt_id": b["id"], "approve": True})
    assert not second["wrap_approved"] and "unknown" in second["message"]
    assert len(attempts) == 1
    key = next(d["idempotency_key"] for d in run.delivery_states() if d["event_type"] == "wrap.ready")
    response = fresh_process_request(tmp_path, "/api/retry-delivery", {**body, "idempotency_key": key})
    assert response["status"] == 409 and "do not resend" in response["error"]


def test_concurrent_logical_wrap_claim_excludes_different_approval_ids(monkeypatch):
    run = H.build_run(owned()["run_id"])
    competing = []
    def publish(event):
        fresh = H.build_run(run.run_id)
        competing.append(fresh.publish(EventType.WRAP_READY, {"approval_id": "B"}, idempotent=True))
        return Receipt(True, "one-bus-receipt", "Bus accepted")
    monkeypatch.setattr(run.bus, "publish", publish)
    first = run.publish(EventType.WRAP_READY, {"approval_id": "A"}, idempotent=True)
    assert first.accepted and len(competing) == 1
    assert not competing[0].accepted and competing[0].outcome == "pending"


def test_rejected_turnover_retries_in_fresh_process_but_changed_review_cannot_reuse_manifest(monkeypatch, tmp_path):
    body = {**owned(), "role": "first_ad"}
    eligible(body)
    pending = post("/api/wrap", body)["pending_approval"]
    assert post("/api/approve", {**body, "interrupt_id": pending["id"], "approve": True})["wrap_approved"]
    run = H.build_run(body["run_id"])
    original = type(run.bus).publish
    monkeypatch.setattr(type(run.bus), "publish", lambda bus,event:
        Receipt(False, event.event_id, "Explicit rejection") if event.event_type is EventType.TURNOVER_GENERATED else original(bus,event))
    saved = post("/api/turnover", body)
    manifest = saved["turnover"]
    assert "Bus rejected" in saved["message"]
    key = next(d["idempotency_key"] for d in saved["delivery_outcomes"] if d["event_type"] == "turnover.generated")
    recovered = fresh_process_request(tmp_path, "/api/retry-delivery", {**body, "idempotency_key": key})
    assert recovered["status"] == 200 and recovered["delivery"]["accepted"]
    assert recovered["turnover"] == manifest
    finding = next(f for f in run.load_findings() if f["check_type"] == "continuity" and f["requirement_id"])
    assert post("/api/decide", {**body, "role": "script_supervisor", "finding_id": finding["finding_id"],
        "finding_sha256": finding["record_sha256"], "action": "accept_exception", "actor": "Another review", "reason": "New intent."})["status"] == 200
    fresh = post("/api/wrap", body)["pending_approval"]
    assert post("/api/approve", {**body, "interrupt_id": fresh["id"], "approve": True})["wrap_approved"]
    from lasttake.agents.tools import build_tools
    assert "historical" in str(build_tools(run)[-1]())
    assert post("/api/retry-delivery", {**body, "idempotency_key": key})["status"] == 409
    assert post("/api/turnover", body)["turnover"] == manifest
