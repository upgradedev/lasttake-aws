"""What the HTTP routes say back, read as a sentence on the page.

Two banners were read as something they did not mean. After the checkpoint a
green banner said "This process is now finished" directly above a blocked gate,
and a visitor reads that as the workflow being done. After a decision the
banner showed "(dit) accept_exception": two stored identifiers where a role and
an action belong.

Same offline ports as tests/test_handler.py, no AWS account.
"""

from __future__ import annotations

import json

import pytest

from lasttake.adapters.local.infrastructure import (
    LocalArtifactStore,
    LocalEventBus,
    LocalRunStore,
)
from lasttake.app import handler as H

RUN = "demo-wording00001"


class _Context:
    aws_request_id = "test-request-id-wording"


@pytest.fixture(autouse=True)
def offline_backends(tmp_path, monkeypatch):
    bus = LocalEventBus(tmp_path / "events")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    runs = LocalRunStore(tmp_path / "runs")
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


def test_the_checkpoint_banner_does_not_read_as_the_workflow_being_done():
    body = post("/api/checkpoint", {"run_id": RUN})
    assert body["pending_approval"] is not None
    assert body["eligible"] is False

    message = body["message"]
    assert "waiting for the 1st AD" in message
    assert "saved" in message and "exited" in message, message
    for word in ("finished", "complete", "done"):
        assert word not in message.lower(), message


def test_the_decision_banner_names_the_role_and_the_action_in_words():
    started = post("/api/checkpoint", {"run_id": RUN})
    mismatch = next(e for e in started["exceptions"] if e["check_type"] == "metadata")
    body = post(
        "/api/decide",
        {
            "run_id": RUN,
            "finding_id": mismatch["finding_id"],
            "finding_sha256": mismatch["record_sha256"],
            "action": "accept_exception",
            "role": "dit",
            "actor": "Synthetic reviewer",
            "reason": "Card re-read on the cart; the sidecar identifier is authoritative.",
        },
    )
    assert body["status"] == 200, body

    message = body["message"]
    assert message == (
        "Decision saved: accept exception by Synthetic reviewer (DIT / data manager). "
        "The original finding is unchanged and stays visible on the turnover."
    )
    assert "(dit)" not in message and "accept_exception" not in message
    # The decision card on the page carries its own "Recorded: accept exception"
    # line, and browser tests find the card by it. The banner must not be a
    # second element that matches.
    assert not message.startswith("Recorded: accept exception")


@pytest.mark.parametrize(
    ("action", "in_words"),
    [("confirm", "confirm"), ("reject_false_positive", "reject false positive")],
)
def test_every_decision_action_reads_in_words(action, in_words):
    started = post("/api/checkpoint", {"run_id": RUN})
    conflict = next(e for e in started["exceptions"] if e["check_type"] == "continuity")
    body = post(
        "/api/decide",
        {
            "run_id": RUN,
            "finding_id": conflict["finding_id"],
            "finding_sha256": conflict["record_sha256"],
            "action": action,
            "role": "script_supervisor",
            "actor": "Synthetic reviewer",
            "reason": "Reviewed both notes against the reference.",
        },
    )
    assert body["status"] == 200, body
    assert body["message"].startswith(
        f"Decision saved: {in_words} by Synthetic reviewer (Script supervisor). "
    ), body["message"]


def test_the_headline_stops_routing_to_production_once_the_release_is_supplied():
    post("/api/checkpoint", {"run_id": RUN})
    body = post("/api/resolve-rights", {"run_id": RUN, "subject": "BG-07"})
    assert body["counts"]["without_release_record"] == 0
    assert body["headline"].endswith("0 with no release record."), body["headline"]
    assert "routed to production" not in body["headline"]
