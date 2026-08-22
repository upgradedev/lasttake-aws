"""The whole loop, including the interrupt, in one process.

The two-process version is the real claim and lives in the CI workflow, which
runs `lasttake checkpoint` and `lasttake approve` as separate `run:` steps.
This file covers the same path in-process so the logic is testable without
shelling out, and asserts the things that would otherwise only be visible in a
log a human has to read.
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
from lasttake.adapters.local.interpreter import OfflineInterpreter
from lasttake.agents.orchestrator import build_orchestrator
from lasttake.agents.runtime import WrapRun
from lasttake.domain import policy, rollup
from lasttake.domain.events import EventType
from lasttake.domain.findings import from_dict
from lasttake.domain.package import load_package
from lasttake.domain.sealing import verify_seal

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


@pytest.fixture()
def run(tmp_path):
    return WrapRun(
        run_id="e2e",
        correlation_id="c-e2e",
        package=load_package(CORPUS),
        bus=LocalEventBus(tmp_path / "events"),
        artifacts=LocalArtifactStore(tmp_path / "artifacts"),
        runs=LocalRunStore(tmp_path / "runs"),
        interpreter=OfflineInterpreter(),
        candidate_sha="deadbeef",
    )


def _findings(run):
    return [from_dict(f) for f in run.load_findings()]


def test_the_checkpoint_runs_every_check_and_reports_the_count(run, tmp_path):
    agent = build_orchestrator(run, session_dir=tmp_path / "sessions")
    result = agent("Run the wrap checkpoint.")

    assert result.stop_reason == "end_turn"
    outcomes = rollup.roll_up(run.package, _findings(run))
    assert rollup.headline(outcomes)["covered_with_evidence"] == 31

    packet = run.load_packet()
    assert packet is not None
    assert packet["eligible"] is False
    assert verify_seal(packet), "the eligibility packet seals itself"


def test_the_pickup_request_stops_the_run_and_a_second_agent_resumes_it(run, tmp_path):
    sessions = tmp_path / "sessions"
    agent = build_orchestrator(run, session_dir=sessions)
    agent("Run the wrap checkpoint.")

    result = agent("Request a pickup approval for B-17. Justification: no take covers it.")
    assert result.stop_reason == "interrupt"
    interrupt = list(result.interrupts)[0]
    assert interrupt.reason["required_role"] == "first_ad"
    assert interrupt.reason["beat_id"] == "B-17"
    assert "does not wrap the scene" in interrupt.reason["note"]

    # Nothing has been routed yet. The request exists only as a question.
    log = LocalEventBus(tmp_path / "events").replay() if False else run.bus.replay()
    assert not any(e["event_type"] == "pickup.requested" for e in log)

    # A second agent object, built from the persisted session, resumes it.
    resumed_agent = build_orchestrator(run, session_dir=sessions)
    resumed = resumed_agent(
        [{"interruptResponse": {"interruptId": interrupt.id, "response": "y"}}]
    )
    assert resumed.stop_reason != "interrupt"

    log = run.bus.replay()
    pickups = [e for e in log if e["event_type"] == "pickup.requested"]
    assert len(pickups) == 1, "approved once, routed once"
    assert pickups[0]["payload"]["beat_id"] == "B-17"


def test_a_declined_pickup_routes_nothing(run, tmp_path):
    sessions = tmp_path / "sessions"
    agent = build_orchestrator(run, session_dir=sessions)
    agent("Run the wrap checkpoint.")
    result = agent("Request a pickup approval for B-17. Justification: no coverage.")
    interrupt = list(result.interrupts)[0]

    build_orchestrator(run, session_dir=sessions)(
        [{"interruptResponse": {"interruptId": interrupt.id, "response": "n"}}]
    )
    assert not any(e["event_type"] == "pickup.requested" for e in run.bus.replay())


def test_the_turnover_refuses_to_publish_without_a_human_approval(run, tmp_path):
    from lasttake.agents.tools import build_tools

    tools = {t.tool_name if hasattr(t, "tool_name") else t.__name__: t for t in build_tools(run)}
    agent = build_orchestrator(run, session_dir=tmp_path / "sessions")
    agent("Run the wrap checkpoint.")

    result = agent("Publish the turnover.")
    text = str(result)
    assert "Refusing" in text or "refus" in text.lower()
    assert not any(e["event_type"] == "turnover.generated" for e in run.bus.replay())


def test_the_full_loop_reaches_a_verifiable_turnover(run, tmp_path):
    """Checkpoint, pickup, late take, release supplied, DIT resolves, wrap, turnover."""
    from lasttake.checks import coverage as coverage_check
    from lasttake.checks import metadata as metadata_check
    from lasttake.checks import rights as rights_check
    from lasttake.domain.findings import CheckType, Role, TruthState
    from lasttake.domain.package import (
        CameraReportRow,
        RightsRecord,
        Take,
        with_extra_take,
        with_rights_record,
    )

    sessions = tmp_path / "sessions"
    build_orchestrator(run, session_dir=sessions)("Run the wrap checkpoint.")

    # 1. A late take closes the coverage gap.
    take = Take(
        take_id="T-041",
        shot_id="S-42-PICKUP",
        beat_ids=["B-17"],
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
    # 2. Production supplies the missing release.
    package = with_rights_record(
        package,
        RightsRecord(
            "REL-007", "BG-07", "person", "background release", "all media",
            "worldwide", None, "executed",
        ),
    )
    run = run.with_package(package)

    # Everything is now on a new revision, so re-run every check once. In the
    # CLI this is the targeted path; here the point is the end state.
    interp = OfflineInterpreter()
    from lasttake.checks import continuity as continuity_check

    findings = (
        coverage_check.run(package, run.run_id, interp, policy.POLICY_VERSION)
        + continuity_check.run(package, run.run_id, interp, policy.POLICY_VERSION)
        + metadata_check.run(package, run.run_id, policy.POLICY_VERSION)
        + rights_check.run(package, run.run_id, policy.POLICY_VERSION)
    )
    run.store_findings(findings)

    head = rollup.headline(rollup.roll_up(package, findings))
    assert head["covered_with_evidence"] == 33, "B-17 covered, B-09 released"
    assert head["without_release_record"] == 0

    # 3. The humans close what is left: the mug and the card.
    conflict = next(
        f for f in findings
        if f.check_type is CheckType.CONTINUITY and f.truth_state is TruthState.CONFLICTING
    )
    mismatch = next(
        f for f in findings
        if f.check_type is CheckType.METADATA and f.truth_state is TruthState.CONFLICTING
    )
    run.record_decision(
        policy.HumanDecision(
            "d1", conflict.finding_id, policy.DecisionAction.ACCEPT_EXCEPTION,
            "the script supervisor", Role.SCRIPT_SUPERVISOR,
            "the change was intentional, the second take is preferred",
        ).to_dict()
    )
    run.record_decision(
        policy.HumanDecision(
            "d2", mismatch.finding_id, policy.DecisionAction.ACCEPT_EXCEPTION,
            "the DIT", Role.DIT, "card relabelled on the cart, report is authoritative",
        ).to_dict()
    )

    # 4. The gate, then the 1st AD, then the turnover.
    agent = build_orchestrator(run, session_dir=sessions, plan=("evaluate_wrap_eligibility",))
    agent("Evaluate eligibility.")
    packet = run.load_packet()
    assert packet["eligible"] is True, packet["causes"]

    result = agent("Ask the 1st AD to approve the wrap.")
    assert result.stop_reason == "interrupt"
    interrupt = list(result.interrupts)[0]
    assert "not a statement that the scene is legally cleared" in interrupt.reason["note"]

    build_orchestrator(run, session_dir=sessions, plan=())(
        [{"interruptResponse": {"interruptId": interrupt.id, "response": "y"}}]
    )
    assert run.wrap_approved()

    from lasttake.agents.tools import build_tools

    publish = [t for t in build_tools(run)][-1]
    message = publish()
    assert "Turnover published" in str(message)

    # 5. The packet editorial receives verifies, and says what it is not.
    key = next(
        e["payload"]["artifact_key"]
        for e in run.bus.replay()
        if e["event_type"] == "turnover.generated"
    )
    manifest = json.loads(run.artifacts.get(key).decode("utf-8"))
    assert verify_seal(manifest)
    assert manifest["counts"]["required_beats"] == 34
    assert "not a legal opinion" in manifest["rights_disclaimer"]
    assert len(manifest["human_decisions"]) == 2
    assert manifest["outstanding_and_accepted_exceptions"], (
        "accepted exceptions stay visible downstream"
    )

    # Tamper with one number and the seal stops matching.
    manifest["counts"]["required_beats"] = 35
    assert not verify_seal(manifest)
