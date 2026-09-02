"""The HTTP surface a judge touches, exercised with no AWS account.

The routes are the product for anyone who does not clone the repository, so
they are tested rather than deployed and hoped for. S3 and EventBridge are
swapped for the offline adapters through the same ports the deployed build
uses, which is the whole reason the ports exist.

What this does not cover, and says so rather than implying otherwise: that S3
and EventBridge behave like the offline adapters. That is what the deploy
workflow's live check is for, against the real URL.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lasttake.adapters.local.infrastructure import (
    LocalArtifactStore,
    LocalEventBus,
    LocalRunStore,
)
from lasttake.app import handler as H

RUN = "demo-testrun0001"


class _Context:
    aws_request_id = "test-request-id-0001"


@pytest.fixture(autouse=True)
def offline_backends(tmp_path, monkeypatch):
    """Same ports, local implementations, no credential anywhere."""
    bus = LocalEventBus(tmp_path / "events")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    runs = LocalRunStore(tmp_path / "runs")

    # The local bus takes no correlation argument; the deployed one does.
    monkeypatch.setattr(bus, "replay", lambda *a, **k: LocalEventBus.replay(bus), raising=False)
    monkeypatch.setattr(H, "from_environment", lambda: (bus, artifacts, runs))
    monkeypatch.setattr(
        H,
        "build_agent",
        lambda run, plan=None: __import__(
            "lasttake.agents.orchestrator", fromlist=["build_orchestrator"]
        ).build_orchestrator(run, session_dir=tmp_path / "sessions", plan=plan),
    )
    monkeypatch.setenv("LASTTAKE_BUCKET", "unused-offline")
    monkeypatch.setenv("LASTTAKE_EVENT_BUS", "unused-offline")
    return bus, artifacts, runs


def post(path: str, body: dict) -> dict:
    event = {
        "requestContext": {"http": {"path": path, "method": "POST"}},
        "body": json.dumps(body),
    }
    response = H.handler(event, _Context())
    return {"status": response["statusCode"], **json.loads(response["body"])}


def get(path: str) -> dict:
    event = {"requestContext": {"http": {"path": path, "method": "GET"}}}
    return H.handler(event, _Context())


# -- the page and the shape of every response -------------------------------


def test_the_root_serves_a_page_with_the_promise_on_it():
    response = get("/")
    assert response["statusCode"] == 200
    assert "text/html" in response["headers"]["content-type"]
    body = response["body"]
    assert "know whether you truly have the scene" in body
    assert "Synthetic data" in body, "a visitor must be told the corpus is invented"
    assert "content-security-policy" in response["headers"]


def test_healthz_answers():
    response = get("/healthz")
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["scene"] == "SC-042"


def test_every_response_says_which_process_served_it():
    """The claim is about process boundaries, so the boundary is in the payload."""
    body = post("/api/state", {"run_id": RUN})
    served = body["served_by"]
    assert served["lambda_request_id"] == "test-request-id-0001"
    assert len(served["container_id"]) == 8
    assert "rebuilt from S3 on every request" in served["note"]


def test_an_unknown_route_is_a_404_not_a_page():
    event = {"requestContext": {"http": {"path": "/api/nope", "method": "POST"}}, "body": "{}"}
    assert H.handler(event, _Context())["statusCode"] == 404


def test_a_malformed_run_id_is_refused():
    body = post("/api/checkpoint", {"run_id": "../../etc/passwd"})
    assert body["status"] == 400
    assert "run_id must be" in body["error"]


def test_a_missing_run_id_is_refused():
    assert post("/api/checkpoint", {})["status"] == 400


def test_a_body_that_is_not_json_is_refused():
    event = {
        "requestContext": {"http": {"path": "/api/state", "method": "POST"}},
        "body": "not json",
    }
    assert H.handler(event, _Context())["statusCode"] == 400


# -- the loop ---------------------------------------------------------------


def test_the_checkpoint_returns_the_count_and_stops_for_the_first_ad():
    body = post("/api/checkpoint", {"run_id": RUN})
    assert body["status"] == 200
    assert body["counts"] == {
        "required_beats": 34,
        "covered_with_evidence": 31,
        "raising_exceptions": 2,
        "without_release_record": 1,
        "not_assessed": 0,
    }
    assert "31 covered with evidence" in body["headline"]

    pending = body["pending_approval"]
    assert pending is not None
    assert pending["reason"]["required_role"] == "first_ad"
    assert pending["reason"]["beat_id"] == "B-17"
    assert "does not wrap the scene" in pending["reason"]["note"]
    assert body["eligible"] is False


def test_every_exception_carries_its_sources_and_a_role():
    body = post("/api/checkpoint", {"run_id": RUN})
    assert body["exceptions"], "the corpus has planted exceptions"
    for exception in body["exceptions"]:
        assert exception["sources"], "a finding with nothing behind it is an opinion"
        for source in exception["sources"]:
            assert len(source["sha256"]) == 64
        assert exception["required_role"]
        assert exception["truth_state"] in {"missing", "conflicting", "unknown"}


def test_a_second_request_resumes_the_run_the_first_one_stopped():
    started = post("/api/checkpoint", {"run_id": RUN})
    pending = started["pending_approval"]
    resumed = post(
        "/api/approve",
        {"run_id": RUN, "interrupt_id": pending["id"], "approve": True},
    )
    assert resumed["status"] == 200
    assert "Pickup approved" in resumed["message"]


def test_declining_the_pickup_routes_nothing(offline_backends):
    bus, _artifacts, _runs = offline_backends
    started = post("/api/checkpoint", {"run_id": RUN})
    post(
        "/api/approve",
        {"run_id": RUN, "interrupt_id": started["pending_approval"]["id"], "approve": False},
    )
    assert not any(e["event_type"] == "pickup.requested" for e in bus.replay())


def test_a_late_take_reports_which_checks_were_affected():
    post("/api/checkpoint", {"run_id": RUN})
    body = post("/api/late-take", {"run_id": RUN, "beat_id": "B-17"})
    assert set(body["affected_checks"]) == {"coverage", "continuity", "metadata", "rights"}
    assert body["counts"]["covered_with_evidence"] == 32


def test_supplying_a_release_affects_one_check_only():
    post("/api/checkpoint", {"run_id": RUN})
    body = post("/api/resolve-rights", {"run_id": RUN, "subject": "BG-07"})
    assert body["affected_checks"] == ["rights"]
    assert body["counts"]["without_release_record"] == 0
    assert "digests that have not moved" in body["message"]


def test_the_wrong_role_is_refused_over_http_too():
    started = post("/api/checkpoint", {"run_id": RUN})
    rights_gap = next(e for e in started["exceptions"] if e["check_type"] == "rights")
    body = post(
        "/api/decide",
        {
            "run_id": RUN,
            "finding_id": rights_gap["finding_id"],
            "action": "accept_exception",
            "role": "dit",
            "actor": "a data manager",
            "reason": "looks fine",
        },
    )
    assert body["status"] == 403
    assert "may not accept_exception" in body["error"]
    assert "no evidence" in body["error"]


def test_a_decision_on_an_unknown_finding_is_a_404():
    post("/api/checkpoint", {"run_id": RUN})
    body = post(
        "/api/decide",
        {"run_id": RUN, "finding_id": "nope", "action": "confirm", "role": "dit"},
    )
    assert body["status"] == 404


def test_the_turnover_refuses_without_a_wrap_approval(offline_backends):
    bus, _a, _r = offline_backends
    post("/api/checkpoint", {"run_id": RUN})
    body = post("/api/turnover", {"run_id": RUN})
    assert "Refusing" in body["message"]
    assert "turnover" not in body
    assert not any(e["event_type"] == "turnover.generated" for e in bus.replay())


def test_the_event_log_reads_back_with_the_chain_intact():
    post("/api/checkpoint", {"run_id": RUN})
    body = post("/api/events", {"run_id": RUN})
    types = [e["event_type"] for e in body["events"]]
    assert "scene.wrap-checkpoint.requested" in types
    assert "finding.recorded" in types
    for event in body["events"]:
        assert len(event["idempotency_key"]) == 16


def test_reset_hands_out_a_new_run_and_deletes_nothing():
    post("/api/checkpoint", {"run_id": RUN})
    body = post("/api/reset", {})
    assert body["run_id"].startswith("demo-")
    assert body["run_id"] != RUN
    assert "Nothing was deleted" in body["message"]
    # The old run is still exactly where it was.
    assert post("/api/state", {"run_id": RUN})["counts"]["required_beats"] == 34


def test_an_unexpected_failure_returns_the_reason_not_a_blank_500(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("the cart caught fire")

    monkeypatch.setattr(H, "route_state", boom)
    monkeypatch.setitem(H.ROUTES, "/api/state", boom)
    body = post("/api/state", {"run_id": RUN})
    assert body["status"] == 500
    assert "the cart caught fire" in body["error"]


# -- the lined script, which is the first thing a visitor sees --------------


def test_the_scene_route_paints_without_running_a_single_check():
    """It answers from the package alone, so it returns before the checkpoint."""
    scene = post("/api/scene", {"run_id": RUN})
    assert scene["status"] == 200
    assert scene["scene_id"] == "SC-042"
    assert scene["required_beats"] == 34
    assert len(scene["beats"]) == 36
    assert scene["take_count"] == 40
    assert scene["scene_heading"] and scene["revision"]

    # No verdict of any kind. Judgement belongs to the checks and the gate.
    assert "eligible" not in scene and "counts" not in scene
    for beat in scene["beats"]:
        assert "status" not in beat


def test_the_scene_route_refuses_a_malformed_run_id_like_every_other():
    assert post("/api/scene", {"run_id": "no"})["status"] == 400


def test_the_page_cannot_draw_a_control_the_policy_withholds():
    scene = post("/api/scene", {"run_id": RUN})
    assert scene["authority"]["rights"]["may_accept"] == []
    assert scene["authority"]["coverage"]["may_confirm"] == ["script_supervisor"]


def test_a_decision_by_the_wrong_role_is_refused_by_the_server():
    """The role in the slate is a claim the page makes. The server checks it."""
    state = post("/api/checkpoint", {"run_id": RUN})
    rights = [f for f in state["exceptions"] if f["check_type"] == "rights"][0]

    refused = post(
        "/api/decide",
        {
            "run_id": RUN,
            "finding_id": rights["finding_id"],
            "action": "confirm",
            "role": "dit",
            "actor": "someone else",
        },
    )
    assert refused["status"] == 403
    assert not refused["decisions"], "nothing was recorded"

    # And nobody at all may accept a missing release away.
    for role in ("production_coordinator", "script_supervisor", "first_ad", "dit"):
        blocked = post(
            "/api/decide",
            {
                "run_id": RUN,
                "finding_id": rights["finding_id"],
                "action": "accept_exception",
                "role": role,
                "actor": role,
            },
        )
        assert blocked["status"] == 403, f"{role} was allowed to accept away a release"


def test_a_decision_by_the_right_role_is_recorded_and_the_finding_survives():
    state = post("/api/checkpoint", {"run_id": RUN})
    coverage = [f for f in state["exceptions"] if f["check_type"] == "coverage"][0]

    after = post(
        "/api/decide",
        {
            "run_id": RUN,
            "finding_id": coverage["finding_id"],
            "action": "confirm",
            "role": "script_supervisor",
            "actor": "demo visitor standing in as the script supervisor",
        },
    )
    assert after["status"] == 200
    recorded = [d for d in after["decisions"] if d["finding_id"] == coverage["finding_id"]]
    assert len(recorded) == 1 and recorded[0]["action"] == "confirm"
    assert any(
        f["finding_id"] == coverage["finding_id"] for f in after["exceptions"]
    ), "a confirmed finding does not disappear; it travels on the turnover"


# -- what has to survive the request that created it ------------------------


def test_a_captured_take_is_still_there_on_the_next_request():
    """It was not, and the symptom was a beat that covered itself and uncovered.

    `POST /api/late-take` reported B-17 covered; the next `POST /api/state`
    reported it uncovered again. The package was amended in memory and thrown
    away when the function returned, so the finding that cited the new take was
    stale on the following request and the gate withdrew it. The gate was
    right. The take should have been there.
    """
    post("/api/checkpoint", {"run_id": RUN})
    after = post("/api/late-take", {"run_id": RUN, "beat_id": "B-17"})
    covered = {b["beat_id"]: b["status"] for b in after["beats"]}
    assert covered["B-17"] == "covered_with_evidence"

    later = post("/api/state", {"run_id": RUN})
    still = {b["beat_id"]: b["status"] for b in later["beats"]}
    assert still["B-17"] == "covered_with_evidence", (
        "the take stopped existing between two requests"
    )

    scene = post("/api/scene", {"run_id": RUN})
    assert scene["take_count"] == 41
    slates = [t["slate"] for b in scene["beats"] for t in b["takes"]]
    assert len(set(slates)) == 41, "the pickup reused a slate"


def test_a_filed_release_is_still_there_on_the_next_request():
    post("/api/checkpoint", {"run_id": RUN})
    post("/api/resolve-rights", {"run_id": RUN, "subject": "BG-07"})
    scene = post("/api/scene", {"run_id": RUN})
    subjects = {s["subject_id"]: s["released"] for s in scene["subjects"]}
    assert subjects["BG-07"] is True


def test_amending_twice_does_not_add_the_take_twice():
    post("/api/checkpoint", {"run_id": RUN})
    post("/api/late-take", {"run_id": RUN, "beat_id": "B-17"})
    post("/api/late-take", {"run_id": RUN, "beat_id": "B-17"})
    scene = post("/api/scene", {"run_id": RUN})
    ids = [t["take_id"] for b in scene["beats"] for t in b["takes"]]
    assert ids.count("T-041") == 1


def test_a_run_waiting_on_a_human_refuses_a_sentence_instead_of_a_stack_trace():
    """A route that prompts with a string fails while an interrupt is open.

    It was failing as a raw 500 carrying a Strands stack trace. A judge who
    asked for the wrap before answering the pickup would have seen it.
    """
    state = post("/api/checkpoint", {"run_id": RUN})
    assert state["pending_approval"], "this test needs the run to be stopped"

    refused = post("/api/wrap", {"run_id": RUN})
    assert refused["status"] == 409
    assert "waiting for a human" in refused["message"]
    assert refused["counts"], "the state still comes back, so the page keeps working"


def test_the_gate_runs_without_a_prompt_and_therefore_without_a_model():
    """It is arithmetic over evidence and it answers whenever it is asked.

    It used to be reached by asking a model to please invoke it, which put a
    model back inside a deterministic decision and, on a run that had been
    resumed once, quietly returned the previous packet.
    """
    post("/api/checkpoint", {"run_id": RUN})
    evaluated = post("/api/evaluate", {"run_id": RUN})
    assert evaluated["status"] == 200
    assert evaluated["eligible"] is False
    assert evaluated["causes"], "the gate has to say what is blocking"


def test_the_whole_shoot_day_reaches_a_turnover():
    """The five moves the page walks a judge through, end to end.

    Each one is a separate request, which is the point: nothing about the run
    is held in memory between them.
    """
    state = post("/api/checkpoint", {"run_id": RUN})
    assert state["counts"]["covered_with_evidence"] == 31
    pending = state["pending_approval"]
    assert pending["reason"]["required_role"] == "first_ad"

    resumed = post(
        "/api/approve",
        {"run_id": RUN, "interrupt_id": pending["id"], "approve": True},
    )
    assert resumed["status"] == 200

    post("/api/late-take", {"run_id": RUN, "beat_id": "B-17"})
    post("/api/resolve-rights", {"run_id": RUN, "subject": "BG-07"})
    evaluated = post("/api/evaluate", {"run_id": RUN})
    assert evaluated["counts"]["covered_with_evidence"] == 33
    assert evaluated["counts"]["without_release_record"] == 0
    assert evaluated["eligible"] is False, "two conflicts are still untriaged"

    # Supplying evidence is not the same as settling a judgement. Two conflicts
    # remain and each belongs to a different person: what counts as intentional
    # continuity is the supervisor's, and the authoritative technical record is
    # the DIT's. The gate names both, and it names who.
    owed = {c["finding_id"]: c["required_role"] for c in evaluated["causes"]}
    assert set(owed.values()) == {"script_supervisor", "dit"}
    for finding_id, role in owed.items():
        recorded = post(
            "/api/decide",
            {
                "run_id": RUN,
                "finding_id": finding_id,
                "action": "accept_exception",
                "role": role,
                "actor": f"the {role} on this unit",
                "reason": "Reviewed on the floor before wrap.",
            },
        )
        assert recorded["status"] == 200, recorded.get("error")

    evaluated = post("/api/evaluate", {"run_id": RUN})
    assert evaluated["eligible"] is True, evaluated.get("causes")

    asked = post("/api/wrap", {"run_id": RUN})
    approval = asked["pending_approval"]
    assert approval and approval["reason"]["required_role"] == "first_ad"
    wrapped = post(
        "/api/wrap",
        {"run_id": RUN, "interrupt_id": approval["id"], "approve": True},
    )
    assert wrapped["wrap_approved"] is True

    turnover = post("/api/turnover", {"run_id": RUN})
    assert turnover["turnover"], "editorial received nothing"
