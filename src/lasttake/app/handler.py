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

One Lambda behind an HTTP API, one Aurora DSQL cluster for run state, one
bucket for artifacts and the Strands sessions, one event bus. No container
registry, no instance to size, and every one of them scales to zero, so nothing
runs when nobody is looking.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from ..adapters.aws.infrastructure import from_environment, run_store_kind
from ..adapters.local.interpreter import OfflineInterpreter
from ..agents.orchestrator import build_orchestrator
from ..agents.runtime import WrapRun
from ..checks import continuity as continuity_check
from ..checks import coverage as coverage_check
from ..checks import metadata as metadata_check
from ..checks import rights as rights_check
from ..domain import policy, receipt, rollup
from ..domain.events import EventType, affected_by
from ..domain.findings import from_dict
from ..domain.sealing import SEAL_KEY
from ..domain.package import (
    CameraReportRow,
    RightsRecord,
    Take,
    load_package,
    with_extra_take,
    with_rights_record,
)
from .ingest import (
    apply_amendments,
    bad_identifier,
    load_amendments,
    perform_ingest,
    record_amendment,
    shape_error,
)
from .scene_view import scene_view
from . import workspace

#: Minted when this container boots. Two requests that report different values
#: were served by different processes. Two that report the same value were
#: served by one container, which changes nothing: the run was still rebuilt
#: from S3 both times and held nothing in memory in between.
CONTAINER_ID = uuid.uuid4().hex[:8]
BOOTED_AT = time.time()

def _find_corpus() -> Path:
    """Locate the scene package, in a checkout or in a Lambda bundle.

    The depth differs between the two. In the repository this file sits at
    ``<root>/src/lasttake/app/handler.py``; in the deployment zip it sits at
    ``/var/task/lasttake/app/handler.py``, one level shallower because there is
    no ``src``. A single hard-coded ``parents[n]`` is therefore right in one
    place and silently wrong in the other, which is exactly how it failed: the
    tests passed and the first deployed request raised ``KeyError:
    'script_revision'``.

    Candidates are checked by looking for a file that must be there, not by
    checking the directory exists, so a stale empty folder cannot win.
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "corpus",  # Lambda bundle: /var/task/corpus
        here.parents[3] / "corpus",  # repository checkout: <root>/corpus
        Path(os.environ.get("LASTTAKE_CORPUS", "")) if os.environ.get("LASTTAKE_CORPUS") else None,
    ]
    for candidate in candidates:
        if candidate and (candidate / "script_revision.json").is_file():
            return candidate
    raise RuntimeError(
        "no scene package found. Looked in: "
        + ", ".join(str(c) for c in candidates if c)
    )


CORPUS = _find_corpus()
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


_SCHEMA_READY = False


def build_run(run_id: str, package=None) -> WrapRun:
    """Assemble a run against the deployed adapters.

    The schema is created once per container rather than once per request. It
    is `CREATE TABLE IF NOT EXISTS`, so a second container racing the first is
    harmless, and putting it here means a fresh cluster works on its first
    request instead of needing a migration step nobody remembers to run.
    """
    global _SCHEMA_READY
    bus, artifacts, runs = from_environment()
    if not _SCHEMA_READY and hasattr(runs, "ensure_schema"):
        runs.ensure_schema()
        _SCHEMA_READY = True
    if package is None:
        package = apply_amendments(scene_package(), load_amendments(artifacts, run_id))
    return WrapRun(
        run_id=run_id,
        correlation_id=run_id,
        package=package,
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
    decisions = run.load_decisions()
    outcomes = rollup.roll_up(run.package, findings, decisions)
    packet = workspace.current_eligibility(run).to_dict() if findings else None
    turnover_key = f"turnover/{run.run_id.replace(':', '_')}.json"
    return {
        "run_id": run.run_id,
        "scene_id": run.package.scene_id,
        "production_id": run.package.production_id,
        "revision": run.package.revision,
        "headline": rollup.sentence(outcomes) if findings else None,
        "counts": rollup.headline(outcomes) if findings else None,
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
        "run_state_store": run_store_kind(),
        "pending_approval": workspace.pending_for(run),
        **({"turnover": json.loads(run.artifacts.get(turnover_key))} if run.artifacts.exists(turnover_key) else {}),
        "package_revision_digest": run.package.revision_digest(),
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


def resumed_with_a_bad_interrupt(exc: Exception) -> bool:
    """True when a caller answered an approval that is not open on this run.

    Strands raises for a response whose interrupt id it does not recognise, and
    that is the caller getting it wrong, not the service failing. It was
    returning 500, which is both a lie about whose fault it is and, before the
    trace stopped being public, a free look at the internals.
    """
    text = str(exc).lower()
    return isinstance(exc, (ValueError, KeyError)) and (
        "interrupt" in text or "interruptresponse" in text
    )


def resume_required(exc: Exception) -> bool:
    """True when Strands refused a plain prompt because a run is mid-interrupt.

    A run that has stopped for the 1st AD can only be spoken to with an
    interruptResponse. Any route that prompts with a sentence therefore fails
    while an approval is outstanding, and it was failing as a raw 500 with a
    stack trace, which tells a script supervisor nothing and tells a judge
    something worse.
    """
    return isinstance(exc, TypeError) and "must resume from interrupt" in str(exc)


WAITING = (
    "This run has stopped and is waiting for a human. Answer the approval that "
    "is open before asking it to do anything else. Nothing was changed."
)


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
    workspace.remember_pending(run, pending)
    state["message"] = (
        "The run has stopped and is waiting for the 1st AD. This process is now "
        "finished. Approve whenever you like, even tomorrow."
        if pending
        else "Checkpoint complete."
    )
    return _json(200, state, request_id)


def route_approve(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    problem = bad_identifier("interrupt_id", body.get("interrupt_id"))
    if problem:
        return _json(400, {"error": problem, **_state(run)}, request_id)
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
    workspace.remember_pending(run, state["pending_approval"])
    return _json(200, state, request_id)


def route_late_take(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    beat = body.get("beat_id", "B-17")
    problem = bad_identifier("beat_id", beat)
    if problem:
        return _json(400, {"error": problem, **_state(run)}, request_id)
    take = Take(
        take_id="T-041",
        shot_id="S-42-PICKUP",
        beat_ids=[beat],
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
    row = CameraReportRow("T-041", "A006R2F41", 50, "A006")
    already = any(t.take_id == take.take_id for t in run.package.takes)
    if not already:
        record_amendment(
            run.artifacts,
            run.run_id,
            {"kind": "take", "take": take.__dict__, "camera_report_row": row.__dict__},
        )
    package = run.package if already else with_extra_take(run.package, take, row)
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
    problem = bad_identifier("subject", subject)
    if problem:
        return _json(400, {"error": problem, **_state(run)}, request_id)
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
    already = any(r.record_id == record.record_id for r in run.package.rights_records)
    if not already:
        record_amendment(
            run.artifacts, run.run_id, {"kind": "rights_record", "record": record.__dict__}
        )
    package = run.package if already else with_rights_record(run.package, record)
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
    if body.get("finding_sha256") and body["finding_sha256"] != finding.record_sha256:
        return _json(409, {"error": "This finding changed since you reviewed it. Refresh and review the current evidence.", **_state(run)}, request_id)
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
        # Bound to this reading of this requirement. When the evidence moves and
        # the finding is recomputed, the digest changes and this decision stops
        # applying, which is the point: nobody has looked at the new facts.
        finding_sha256=finding.record_sha256,
    )
    run.record_decision(decision.to_dict())
    state = _state(run)
    state["message"] = (
        f"Recorded: {decision.actor} ({role.value}) {action.value}. The original "
        "finding is unchanged and stays visible on the turnover."
    )
    return _json(200, state, request_id)


def route_evaluate(body: dict, request_id: str) -> dict:
    """Run the gate directly, not through a prompt.

    The gate is deterministic policy and the architecture's fourth property is
    that a model does not combine the findings. Asking a model to please invoke
    it put the model back in the path for no gain, and it cost correctness: on
    a run that had already been resumed once, the prompt did not reach the tool
    and the response carried the *previous* eligibility packet, so a scene that
    had been fixed still read as broken. Calling the tool is what the turnover
    route already does.
    """
    run = build_run(body["run_id"])
    from ..agents.tools import build_tools

    evaluate = build_tools(run)[4]
    assert evaluate.__name__ == "evaluate_wrap_eligibility", evaluate.__name__
    state = _state(run)
    state["message"] = str(evaluate())
    state.update({k: v for k, v in _state(run).items() if k in ("eligible", "causes")})
    return _json(200, state, request_id)


def route_wrap(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    if body.get("interrupt_id") is None:
        run.store_packet(workspace.current_eligibility(run).sealed())
    agent = build_agent(run, plan=())
    if body.get("interrupt_id") is not None:
        problem = bad_identifier("interrupt_id", body.get("interrupt_id"))
        if problem:
            return _json(400, {"error": problem, **_state(run)}, request_id)
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
        workspace.remember_pending(run, state["pending_approval"])
        return _json(200, state, request_id)

    try:
        result = agent("Ask the 1st AD for wrap approval.")
    except Exception as exc:  # noqa: BLE001 - one known cause, re-raised otherwise
        if not resume_required(exc):
            raise
        state = _state(run)
        state["message"] = WAITING
        return _json(409, state, request_id)
    state = _state(run)
    state["pending_approval"] = _pending_interrupt(result)
    workspace.remember_pending(run, state["pending_approval"])
    state["message"] = _last_tool_result(agent) or "Asked the 1st AD."
    return _json(200, state, request_id)


def route_turnover(body: dict, request_id: str) -> dict:
    run = build_run(body["run_id"])
    from ..agents.tools import build_tools

    key = f"turnover/{run.run_id.replace(':', '_')}.json"
    if run.artifacts.exists(key):
        state = _state(run)
        state["message"] = "The original sealed turnover is already saved. Returned without republishing."
        return _json(200, state, request_id)
    publish = build_tools(run)[-1]
    message = str(publish())
    state = _state(run)
    state["message"] = message

    key = f"turnover/{run.run_id.replace(':', '_')}.json"
    if run.artifacts.exists(key):
        state["turnover"] = json.loads(run.artifacts.get(key).decode("utf-8"))
        state["turnover_download"] = run.artifacts.url_for(key)
    return _json(200, state, request_id)


def route_receipt(body: dict, request_id: str) -> dict:
    return workspace.receipt_response(body, request_id, build_run, _json)


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


def route_ingest(body: dict, request_id: str) -> dict:
    """Validate a supplied document, apply it, and report what moved."""
    run = build_run(body["run_id"])
    problem = shape_error(body.get("kind"), body.get("document"))
    if problem:
        return _json(400, problem, request_id)
    try:
        state = perform_ingest(
            run, body["kind"], body["document"], build_run, scene_package, _state
        )
    except ValueError as exc:
        return _json(400, {"error": str(exc)}, request_id)
    return _json(200, state, request_id)


def route_scene(body: dict, request_id: str) -> dict:
    """The lined script. No model, no findings, no judgement. See scene_view."""
    run = build_run(body["run_id"])
    payload = scene_view(run.package)
    payload["run_id"] = run.run_id
    return _json(200, payload, request_id)


def route_state(body: dict, request_id: str) -> dict:
    return _json(200, _state(build_run(body["run_id"])), request_id)


def route_reset(body: dict, request_id: str) -> dict:
    """Hand the visitor a clean run id rather than deleting anything.

    Nothing in this system deletes. A new run id is a new correlation, the old
    one stays exactly as it was, and the audit trail of a demo that somebody
    else is halfway through is not disturbed.
    """
    run_id = f"demo-{uuid.uuid4().hex[:12]}"
    if body.get("session_id"):
        workspace.register_run(body["session_id"], run_id, from_environment)
    return _json(
        200,
        {"run_id": run_id, "message": "New run. Nothing was deleted."},
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
    "/api/receipt": route_receipt,
    "/api/events": route_events,
    "/api/ingest": route_ingest,
    "/api/scene": route_scene,
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
        return _json(
            200,
            {
                "ok": True,
                "scene": scene_package().scene_id,
                "run_state_store": run_store_kind(),
                "commit": os.environ.get("LASTTAKE_COMMIT_SHA", "unknown"),
            },
            request_id,
        )

    if method == "GET" and path == "/api/blocked":
        # The query object storage could not answer: every run with an open
        # exception, across scenes, and who each is waiting on.
        _bus, _artifacts, runs = from_environment()
        if not hasattr(runs, "blocked_scenes"):
            return _json(
                501,
                {"error": "this deployment stores run state in S3, which cannot answer a cross-run query"},
                request_id,
            )
        visible = [row for row in runs.blocked_scenes()
                   if not _artifacts.exists(f"owners/{row['run_id']}.json")]
        return _json(200, {"blocked": visible}, request_id)

    route = ROUTES.get(path)
    if path == "/api/session":
        route = lambda body, request_id: _json(200, workspace.session(body, build_run, from_environment), request_id)
    if route is None:
        return _json(404, {"error": f"no route {method} {path}"}, request_id)

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return _json(400, {"error": "body must be JSON"}, request_id)

    if not isinstance(body, dict):
        return _json(400, {"error": "body must be a JSON object"}, request_id)

    if path not in ("/api/reset", "/api/session"):
        run_id = str(body.get("run_id", ""))
        if not RUN_ID_PATTERN.match(run_id):
            return _json(
                400,
                {"error": "run_id must be 8 to 64 characters of a-z, 0-9 and hyphen"},
                request_id,
            )

    try:
        if path not in ("/api/reset", "/api/session"):
            owned = workspace.authorize(body, from_environment)
            problem = workspace.guard_action(path, body, build_run(body["run_id"]), owned)
            if problem:
                return _json(problem[0], {"error": problem[1]}, request_id)
        return route(body, request_id)
    except Exception as exc:  # noqa: BLE001 - logged in full, never returned in full
        import traceback

        if resumed_with_a_bad_interrupt(exc):
            return _json(
                400,
                {
                    "error": "no such approval is open on this run",
                    "detail": (
                        "An interrupt id can only be answered on the run that raised "
                        "it, and only while it is open. Fetch the run's state and use "
                        "the id in pending_approval."
                    ),
                },
                request_id,
            )

        if isinstance(exc, PermissionError):
            return _json(403, {"error": str(exc)}, request_id)
        if isinstance(exc, ValueError):
            return _json(400, {"error": str(exc)}, request_id)

        # The full trace goes to CloudWatch, where the operator can read it and
        # the public cannot. The response carries the exception type and the
        # invocation id, which is enough for a visitor to report it and enough
        # for us to find it, and no file paths, no line numbers and no internal
        # names. A stack trace on a public endpoint is a map of the code.
        print(f"unhandled {type(exc).__name__} on {path}: {traceback.format_exc()}")
        return _json(
            500,
            {
                "error": type(exc).__name__,
                "detail": (
                    "Something failed on our side and the details are in our logs, not "
                    "in this response. Quote the invocation id below and we can find it."
                ),
            },
            request_id,
        )
