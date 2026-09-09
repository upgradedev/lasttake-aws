"""Owned demo runs and recoverable UI context, using the existing storage ports.

The opaque session handle is a bearer capability, not an authenticated identity.
Only its hash is stored. Role selection demonstrates policy, not real staff login.
Legacy runs stay accessible for the existing demonstration; owned runs never do.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets

from ..domain import policy, receipt, rollup
from ..domain.findings import from_dict


def owner_id(handle):
    if not isinstance(handle, str) or not re.fullmatch(r"[0-9a-f]{64}", handle):
        raise ValueError("The saved session is invalid. Start a new demo session.")
    return "visitor-" + hashlib.sha256(handle.encode()).hexdigest()


def session(body, build_run, environment):
    _, artifacts, runs = environment()
    handle = body.get("session_id") or secrets.token_hex(32)
    owner = owner_id(handle)
    key = f"visitors/{owner}.json"
    if body.get("session_id") and not artifacts.exists(key):
        raise PermissionError("This session is unavailable. Start a new demo session.")
    if not artifacts.exists(key):
        artifacts.put(key, b'{"schema":"lasttake/session/v1"}')
    records = runs.load_audit(owner)
    summaries = []
    for record in records:
        if record.get("kind") != "ui.run.created":
            continue
        run = build_run(record["run_id"])
        summaries.append({
            "run_id": run.run_id, "created_at": record["created_at"],
            "production_id": run.package.production_id, "scene_id": run.package.scene_id,
            "revision": run.package.revision, "checked": bool(run.load_findings()),
            "wrap_approved": run.wrap_approved(),
            "turnover_published": run.artifacts.exists(f"turnover/{run.run_id}.json"),
        })
    return {"session_id": handle, "runs": list(reversed(summaries)),
            "identity_mode": "synthetic-role-selection"}


def register_run(handle, run_id, environment):
    from ..domain.sealing import utc_now_iso
    _, artifacts, runs = environment()
    owner = owner_id(handle)
    if not artifacts.exists(f"visitors/{owner}.json"):
        raise PermissionError("This session is unavailable. Start a new demo session.")
    artifacts.put(f"owners/{run_id}.json", json.dumps({"owner": owner}).encode())
    runs.append_audit(owner, {"kind": "ui.run.created", "run_id": run_id,
                              "created_at": utc_now_iso()})


def authorize(body, environment):
    _, artifacts, _ = environment()
    key = f"owners/{body['run_id']}.json"
    if not artifacts.exists(key):
        if body.get("session_id"):
            raise PermissionError("That run does not belong to this session.")
        return False
    if not body.get("session_id"):
        raise PermissionError("A session handle is required for this saved run.")
    if json.loads(artifacts.get(key))["owner"] != owner_id(body["session_id"]):
        raise PermissionError("That run does not belong to this session.")
    return True


def pending_for(run):
    for entry in reversed(run.runs.load_audit(run.run_id)):
        if entry.get("kind") == "ui.pending":
            pending = entry.get("pending")
            if pending:
                changed = entry["package_digest"] != run.package.revision_digest()
                if pending["reason"].get("kind") == "wrap":
                    changed = changed or pending["reason"].get("review_digest") != run.review_binding()["review_digest"]
                return {**pending, "evidence_changed": changed}
            return None
    return None


def remember_pending(run, pending):
    run.audit("ui.pending", {"pending": pending, "package_digest": run.package.revision_digest()})


def receipt_subject(body, package):
    """LT03-R1: caller prose must never become a sealed system assertion."""
    subject = body.get("subject")
    if subject is None or subject == {}:
        return None
    if not isinstance(subject, dict) or set(subject) != {"beat_id"}:
        raise ValueError("receipt subject accepts only a beat_id from this scene")
    beat_id = subject["beat_id"]
    if not isinstance(beat_id, str) or not package.beat(beat_id):
        raise ValueError("receipt subject beat_id must name a beat in this scene")
    return {"beat_id": beat_id}


def current_eligibility(run):
    return policy.evaluate(run.run_id, run.package,
                           [from_dict(f) for f in run.load_findings()],
                           [policy.decision_from_dict(d) for d in run.load_decisions()])


def recovery_state(run):
    versions = sorted({f.get("policy_version", "unrecorded") for f in run.load_findings()})
    needs_checkpoint = bool(versions and versions != [policy.POLICY_VERSION])
    return {"needs_checkpoint": needs_checkpoint, "current_policy_version": policy.POLICY_VERSION,
            "finding_policy_versions": versions,
            "recovery_reason": (f"Saved findings use policy {', '.join(versions)}; current policy is {policy.POLICY_VERSION}. "
                "Historical counts are not current eligibility. Decline any saved pending request, then run a fresh checkpoint and review. "
                "Existing decisions and receipts remain in history." if needs_checkpoint else None)}


def execution_record(run):
    return {"mode": "offline-demo", "planner": "offline-scripted/1.0.0",
            "backend_revision": run.candidate_sha, "identity_mode": "synthetic-role-selection",
            "note": "Current HTTP runtime configuration, not attribution for historical findings. Finding model IDs come only from serialized records."}


def receipt_response(body, request_id, build_run, json_response):
    """Build a portable record without importing unchecked subject assertions."""
    run = build_run(body["run_id"])
    kind = body.get("kind", "pickup")
    if kind not in ("pickup", "wrap"):
        return json_response(400, {"error": "a receipt is about a pickup or a wrap",
                                   "accepted_kinds": ["pickup", "wrap"]}, request_id)
    findings = [from_dict(f) for f in run.load_findings()]
    if not findings:
        return json_response(409, {"error": "nothing has been checked on this run yet, so there is nothing to give a receipt for"}, request_id)
    approved_by = run.wrap_approver() if run.wrap_approved() else None
    manifest = receipt.build(
        kind=kind, run_id=run.run_id, package=run.package, findings=findings,
        decisions=[policy.decision_from_dict(d) for d in run.load_decisions()],
        policy_version=policy.POLICY_VERSION,
        approved_by=approved_by if kind == "wrap" else None,
        approved_role=policy.Role.FIRST_AD.value if approved_by else None,
        subject=receipt_subject(body, run.package),
        execution=execution_record(run), deliveries=run.delivery_states(), recovery=recovery_state(run),
    )
    return json_response(200, {"run_id": run.run_id, "receipt": manifest}, request_id)


def guard_action(path, body, run, owned):
    if path in ("/api/approve", "/api/wrap") and "approve" in body:
        if type(body["approve"]) is not bool:
            return 400, "approve must be a boolean"
    if owned and path in ("/api/approve", "/api/wrap") and body.get("role") != "first_ad":
        return 403, "Only the 1st AD may answer a pickup or wrap approval."
    if path == "/api/retry-delivery" and body.get("role") != "first_ad":
        return 403, "Only the 1st AD may explicitly retry a consequential delivery."
    if owned and path == "/api/decide" and not body.get("finding_sha256"):
        return 400, "The reviewed finding digest is required. Refresh the scene."
    if path in ("/api/approve", "/api/wrap") and body.get("approve") is True:
        pending = pending_for(run)
        if pending and pending["reason"].get("kind") == "wrap":
            if pending["evidence_changed"] or not run.wrap_guard(pending["reason"]):
                return 409, "Evidence changed after this wrap request. Decline it and request a fresh approval after review."
    return None

def state_for(run, store_kind) -> dict:
    findings = [from_dict(f) for f in run.load_findings()]
    decisions = run.load_decisions()
    recovery = recovery_state(run)
    current = bool(findings) and not recovery["needs_checkpoint"]
    outcomes = rollup.roll_up(run.package, findings if current else [], decisions)
    packet = current_eligibility(run).to_dict() if findings else None
    turnover_key = f"turnover/{run.run_id.replace(':', '_')}.json"
    return {
        "run_id": run.run_id,
        "scene_id": run.package.scene_id,
        "production_id": run.package.production_id,
        "revision": run.package.revision,
        "headline": rollup.sentence(outcomes) if current else None,
        "counts": rollup.headline(outcomes) if current else None,
        **recovery,
        "execution": execution_record(run),
        "delivery_outcomes": run.delivery_states(),
        "beats": [o.to_dict() for o in outcomes],
        # The seal travels with the finding, because the page has to tell a live
        # approval from a withdrawn one. A decision carries the digest of the
        # reading it was taken about; without the current digest beside it the
        # interface would keep showing an approval the gate has already stopped
        # honouring, which is the exact confusion this rule exists to remove.
        "exceptions": [
            {**f.to_dict(), "record_sha256": f.record_sha256, "next_action": receipt.next_action(f)}
            for f in sorted(findings, key=lambda f: f.finding_id)
            if f.truth_state.is_exception
        ],
        # What a human already decided about a finding, so the page can say so
        # beside it rather than offering the same control twice.
        "decisions": decisions,
        "eligible": bool(packet and packet.get("eligible")),
        "causes": (packet or {}).get("causes", []),
        "wrap_approved": run.wrap_approved(),
        "interpreter": run.interpreter.model_id,
        "run_state_store": store_kind(),
        "pending_approval": pending_for(run),
        **({"turnover": json.loads(run.artifacts.get(turnover_key))} if run.artifacts.exists(turnover_key) else {}),
        "package_revision_digest": run.package.revision_digest(),
    }
