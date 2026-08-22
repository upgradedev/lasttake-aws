"""The Lambda behind the live URL.

The deployment shape is the argument. Every HTTP request is a separate Lambda
invocation, and nothing about a paused run is held in memory between them: the
agent is rebuilt from S3 on each request, does its work, and the process ends.
So when a visitor starts a checkpoint, closes the laptop, and approves the
pickup an hour later, the resume genuinely crosses a process boundary. It is not
a demonstration of the claim, it is the claim, running.

Each response reports its own invocation id and the id minted when this
container booted, so a visitor can watch the identifiers change under them
rather than taking the sentence on trust.

One Lambda, one Function URL, one bucket, one event bus. No API Gateway, no
container registry, no database, nothing running when nobody is looking.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from ..adapters.aws.infrastructure import from_environment
from ..adapters.local.interpreter import OfflineInterpreter
from ..agents.orchestrator import build_orchestrator
from ..agents.runtime import WrapRun
from ..checks import continuity as continuity_check
from ..checks import coverage as coverage_check
from ..checks import metadata as metadata_check
from ..checks import rights as rights_check
from ..domain import policy, rollup
from ..domain.events import EventType, affected_by
from ..domain.findings import from_dict
from ..domain.package import (
    CameraReportRow,
    RightsRecord,
    Take,
    load_package,
    with_extra_take,
    with_rights_record,
)

#: Minted when this container boots. Two requests that report different values
#: were served by different processes. Two that report the same value were
#: served by one container, which changes nothing: the run was still rebuilt
#: from S3 both times and held nothing in memory in between.
CONTAINER_ID = uuid.uuid4().hex[:8]
BOOTED_AT = time.time()

CORPUS = Path(__file__).resolve().parents[3] / "corpus"
STATIC = Path(__file__).resolve().parent / "static"

#: A visitor's run id, so two people on the live URL never collide.
RUN_ID_PATTERN = re.compile(r"^[a-z0-9-]{8,64}$")

_PACKAGE = None


def scene_package():
    """Parse the corpus once per container. It never changes at runtime."""
    global _PACKAGE
    if _PACKAGE is None:
        _PACKAGE = load_package(CORPUS)
    return _PACKAGE


def build_run(run_id: str, package=None) -> WrapRun:
    bus, artifacts, runs = from_environment()
    return WrapRun(
        run_id=run_id,
        correlation_id=run_id,
        package=package or scene_package(),
        bus=bus,
        artifacts=artifacts,
        runs=runs,
        interpreter=OfflineInterpreter(),
        candidate_sha=os.environ.get("LASTTAKE_COMMIT_SHA"),
    )


def session_dir(run_id: str) -> str:
    return os.environ["LASTTAKE_BUCKET"]


def build_agent(run: WrapRun, plan=None):
    """Build the agent on an S3-backed session.

    This is the line the whole deployment exists to exercise. On a local disk the
    interrupt-and-resume claim is proven but not portable, because Lambda's
    ``/tmp`` does not survive the gap between the checkpoint and the approval.
    """
    from strands.session import S3SessionManager

    manager = S3SessionManager(
        session_id=run.run_id,
        bucket=os.environ["LASTTAKE_BUCKET"],
        prefix="sessions/",
    )
    return build_orchestrator(run, session_manager=manager, plan=plan)


# -- responses --------------------------------------------------------------


def _json(status: int, payload: dict, request_id: str) -> dict:
    payload["served_by"] = {
        "lambda_request_id": request_id,
        "container_id": CONTAINER_ID,
        "container_age_seconds": round(time.time() - BOOTED_AT, 1),
        "note": (
            "The run is rebuilt from S3 on every request and nothing about it is "
            "held in memory in between. A different container_id means a different "
            "process served you."
        ),
    }
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
        },
        "body": json.dumps(payload, indent=2, sort_keys=True),
    }


def _page() -> dict:
    return {
        "statusCode": 200,
        "headers": {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer",
            "content-security-policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; img-src data:"
            ),
        },
        "body": (STATIC / "index.html").read_text(encoding="utf-8"),
    }


# -- shared shaping ---------------------------------------------------------


def _state(run: WrapRun) -> dict:
    findings = [from_dict(f) for f in run.load_findings()]
    outcomes = rollup.roll_up(run.package, findings)
    packet = run.load_packet()
    return {
        "run_id": run.run_id,
        "scene_id": run.package.scene_id,
        "production_id": run.package.production_id,
        "revision": run.package.revision,
        "headline": rollup.sentence(outcomes) if findings else None,
        "counts": rollup.headline(outcomes) if findings else None,
        "beats": [o.to_dict() for o in outcomes],
        "exceptions": [
            f.to_dict() for f in sorted(findings, key=lambda f: f.finding_id)
            if f.truth_state.is_exception
        ],
        "eligible": bool(packet and packet.get("eligible")),
        "causes": (packet or {}).get("causes", []),
        "wrap_approved": run.wrap_approved(),
        "interpreter": run.interpreter.model_id,
    }


def _pending_interrupt(result) -> dict | None:
    interrupts = list(getattr(result, "interrupts", []) or [])
    if not interrupts:
        return None
    first = interrupts[0]
    return {"id": first.id, "reason": getattr(first, "reason", {}) or {}}


def _last_tool_result(agent) -> str:
    latest = ""
    for message in agent.messages:
        for block in message.get("content", []):
            if isinstance(block, dict) and "toolResult" in block:
                for inner in block["toolResult"].get("content", []):
                    if isinstance(inner, dict) and "text" in inner:
                        latest = inner["text"]
    return latest


# -- routes -----------------------------------------------------------------


def route_checkpoint(body: dict, request_id: str) -> dict:
    run_id = body["run_id"]
    run = build_run(run_id)
    run.publish(
        EventType.WRAP_CHECKPOINT_REQUESTED,
        {"requested_by_role": "script_supervisor", "scene_id": run.package.scene_id},
    )
    agent = build_agent(run)
    agent(
        f"Run the wrap checkpoint for scene {run.package.scene_id}, revision "
        f"{run.package.revision}. Report the count."
    )

    state = _state(run)
    uncovered = [
        b for b in state["beats"] if b["status"] == rollup.BeatStatus.NO_COVERAGE.value
    ]
    pending = None
    if uncovered:
        beat = uncovered[0]
        result = agent(
            f"Request a pickup approval for {beat['beat_id']}. Justification: "
            f"{beat['reason']}, and the set is still standing."
        )
        pending = _pending_interrupt(result)
        state = _state(run)

    state["pending_approval"] = pending
    state["message"] = (
        "The run has stopped and is waiting for the 1st AD. This process is now "
        "finished. Approve whenever you like, even tomorrow."
        if pending
        else "Checkpoint complete."
    )
    return _json(200, state, request_id)


def route_approve(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    agent = build_agent(run)
    decision = "y" if body.get("approve") else "n"
    result = agent(
        [
            {
                "interruptResponse": {
                    "interruptId": body["interrupt_id"],
                    "response": decision,
                }
            }
        ]
    )
    state = _state(run)
    state["message"] = _last_tool_result(agent) or "Resumed."
    state["pending_approval"] = _pending_interrupt(result)
    return _json(200, state, request_id)


def route_late_take(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    beat = body.get("beat_id", "B-17")
    take = Take(
        take_id="T-041",
        shot_id="S-42-PICKUP",
        beat_ids=[beat],
        slate="42P/1",
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
    package = with_extra_take(
        run.package, take, CameraReportRow("T-041", "A006R2F41", 50, "A006")
    )
    new_run = build_run(run.run_id, package)
    event = new_run.build_event(
        EventType.TAKE_CAPTURED, {"take_id": take.take_id, "beat_ids": [beat]}
    )
    new_run.bus.publish(event)

    findings = (
        coverage_check.run(package, new_run.run_id, new_run.interpreter, policy.POLICY_VERSION)
        + continuity_check.run(package, new_run.run_id, new_run.interpreter, policy.POLICY_VERSION)
        + metadata_check.run(package, new_run.run_id, policy.POLICY_VERSION)
        + rights_check.run(package, new_run.run_id, policy.POLICY_VERSION)
    )
    new_run.store_findings(findings)

    state = _state(new_run)
    state["affected_checks"] = list(affected_by(event))
    state["message"] = (
        f"{take.take_id} arrived after the checkpoint. A new take changes the takes "
        "digest and all four checks read it, so all four reran. Compare with "
        "supplying a release, where one artifact moves and one check reruns."
    )
    return _json(200, state, request_id)


def route_resolve_rights(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    subject = body.get("subject", "BG-07")
    record = RightsRecord(
        record_id="REL-007",
        subject_id=subject,
        subject_kind="person",
        document_type="background release",
        scope="all media",
        territory="worldwide",
        expires_on=None,
        status="executed",
    )
    package = with_rights_record(run.package, record)
    new_run = build_run(run.run_id, package)
    event = new_run.build_event(
        EventType.RIGHTS_RECORD_UPDATED,
        {"subject_id": subject, "record_id": record.record_id},
    )
    new_run.bus.publish(event)

    fresh = rights_check.run(package, new_run.run_id, policy.POLICY_VERSION)
    carried = [f for f in run.load_findings() if f["check_type"] != "rights"]
    new_run.runs.save_findings(new_run.run_id, carried)
    new_run.store_findings(fresh)

    state = _state(new_run)
    state["affected_checks"] = list(affected_by(event))
    state["message"] = (
        f"Release supplied for {subject}. Only the rights check reran. The other "
        f"{len(carried)} findings still cite digests that have not moved, and the "
        "gate re-derives that independently rather than taking our word for it."
    )
    return _json(200, state, request_id)


def route_decide(body: dict, request_id: str) -> dict:
    """Record a human decision, and refuse one taken by the wrong role."""
    run = build_run(body["run_id"])
    finding_id = body["finding_id"]
    raw = next((f for f in run.load_findings() if f["finding_id"] == finding_id), None)
    if raw is None:
        return _json(404, {"error": f"no finding {finding_id} on this run"}, request_id)

    finding = from_dict(raw)
    action = policy.DecisionAction(body["action"])
    role = policy.Role(body["role"])
    if not policy.authority_check(finding.check_type, action, role):
        return _json(
            403,
            {
                "error": (
                    f"a {role.value} may not {action.value} a "
                    f"{finding.check_type.value} finding. Not recorded: a decision "
                    "taken by the wrong role is not weak evidence, it is no evidence."
                ),
                **_state(run),
            },
            request_id,
        )

    decision = policy.HumanDecision(
        decision_id=f"dec-{uuid.uuid4().hex[:8]}",
        finding_id=finding_id,
        action=action,
        actor=body.get("actor", "unnamed"),
        role=role,
        reason=body.get("reason", ""),
    )
    run.record_decision(decision.to_dict())
    state = _state(run)
    state["message"] = (
        f"Recorded: {decision.actor} ({role.value}) {action.value}. The original "
        "finding is unchanged and stays visible on the turnover."
    )
    return _json(200, state, request_id)


def route_evaluate(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    agent = build_agent(run, plan=("evaluate_wrap_eligibility",))
    agent("Evaluate eligibility.")
    state = _state(run)
    state["message"] = _last_tool_result(agent) or "Evaluated."
    return _json(200, state, request_id)


def route_wrap(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    agent = build_agent(run, plan=())
    if body.get("interrupt_id"):
        result = agent(
            [
                {
                    "interruptResponse": {
                        "interruptId": body["interrupt_id"],
                        "response": "y" if body.get("approve") else "n",
                    }
                }
            ]
        )
        state = _state(run)
        state["message"] = _last_tool_result(agent) or "Resumed."
        state["pending_approval"] = _pending_interrupt(result)
        return _json(200, state, request_id)

    result = agent("Ask the 1st AD for wrap approval.")
    state = _state(run)
    state["pending_approval"] = _pending_interrupt(result)
    state["message"] = _last_tool_result(agent) or "Asked the 1st AD."
    return _json(200, state, request_id)


def route_turnover(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    from ..agents.tools import build_tools

    publish = build_tools(run)[-1]
    message = str(publish())
    state = _state(run)
    state["message"] = message

    key = f"turnover/{run.run_id.replace(':', '_')}.json"
    if run.artifacts.exists(key):
        state["turnover"] = json.loads(run.artifacts.get(key).decode("utf-8"))
        state["turnover_download"] = run.artifacts.url_for(key)
    return _json(200, state, request_id)


def route_events(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    rows = run.bus.replay(run.correlation_id)
    return _json(
        200,
        {
            "run_id": run.run_id,
            "events": [
                {
                    "event_type": r["event_type"],
                    "event_id": r["event_id"],
                    "parent_event_id": r.get("parent_event_id"),
                    "occurred_at": r["occurred_at"],
                    "idempotency_key": r["idempotency_key"][:16],
                    "payload": r["payload"],
                }
                for r in rows
            ],
        },
        request_id,
    )


def route_state(body: dict, request_id: str) -> dict:
    return _json(200, _state(build_run(body["run_id"])), request_id)


def route_reset(body: dict, request_id: str) -> dict:
    """Hand the visitor a clean run id rather than deleting anything.

    Nothing in this system deletes. A new run id is a new correlation, the old
    one stays exactly as it was, and the audit trail of a demo that somebody
    else is halfway through is not disturbed.
    """
    return _json(
        200,
        {"run_id": f"demo-{uuid.uuid4().hex[:12]}", "message": "New run. Nothing was deleted."},
        request_id,
    )


ROUTES = {
    "/api/checkpoint": route_checkpoint,
    "/api/approve": route_approve,
    "/api/late-take": route_late_take,
    "/api/resolve-rights": route_resolve_rights,
    "/api/decide": route_decide,
    "/api/evaluate": route_evaluate,
    "/api/wrap": route_wrap,
    "/api/turnover": route_turnover,
    "/api/events": route_events,
    "/api/state": route_state,
    "/api/reset": route_reset,
}


def handler(event: dict, context: Any) -> dict:
    request_id = getattr(context, "aws_request_id", "local")
    http = event.get("requestContext", {}).get("http", {})
    path = http.get("path", "/")
    method = http.get("method", "GET")

    if method == "GET" and path in {"/", "/index.html"}:
        return _page()
    if method == "GET" and path == "/healthz":
        return _json(200, {"ok": True, "scene": scene_package().scene_id}, request_id)

    route = ROUTES.get(path)
    if route is None:
        return _json(404, {"error": f"no route {method} {path}"}, request_id)

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return _json(400, {"error": "body must be JSON"}, request_id)

    if path != "/api/reset":
        run_id = str(body.get("run_id", ""))
        if not RUN_ID_PATTERN.match(run_id):
            return _json(
                400,
                {"error": "run_id must be 8 to 64 characters of a-z, 0-9 and hyphen"},
                request_id,
            )

    try:
        return route(body, request_id)
    except Exception as exc:  # noqa: BLE001 - surface it, never a blank 500
        import traceback

        return _json(
            500,
            {
                "error": f"{type(exc).__name__}: {exc}",
                "where": traceback.format_exc().splitlines()[-3:],
            },
            request_id,
        )
