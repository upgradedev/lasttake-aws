"""The command line a judge actually runs.

The interesting path is deliberately two commands, not one:

    lasttake checkpoint          # runs the checks, stops at the 1st AD
    lasttake approve --yes       # a NEW process resumes the same run

That is the product's claim made executable. The agent stops when it needs a
human and the process ends; the human answers whenever they answer; a different
process picks the run up from the same point. No subcommand runs the whole
sequence: each step is invoked on its own, so which parts were separate
processes stays visible, because a demo that blurs that has hidden the only
hard part.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

from .adapters.local.infrastructure import LocalArtifactStore, LocalEventBus, LocalRunStore
from .adapters.local.interpreter import OfflineInterpreter
from .agents.orchestrator import build_orchestrator
from .agents.runtime import WrapRun
from .domain import policy, rollup
from .domain.events import EventType, affected_by
from .domain.findings import from_dict
from .domain.package import (
    CameraReportRow,
    RightsRecord,
    Take,
    load_package,
    with_extra_take,
    with_rights_record,
)
from .domain.sealing import verify_seal

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO_ROOT / "corpus"
DEFAULT_WORK = Path(os.environ.get("LASTTAKE_WORKDIR", REPO_ROOT / ".lasttake"))

RUN_ID = "run-sc042-wrap-checkpoint"
CORRELATION_ID = "corr-sc042-2026-08-19"


def _paths(work: Path) -> dict[str, Path]:
    return {
        "events": work / "events",
        "artifacts": work / "artifacts",
        "runs": work / "runs",
        "sessions": work / "sessions",
    }


def _build_run(corpus: Path, work: Path, interpreter=None) -> WrapRun:
    paths = _paths(work)
    package = load_package(corpus)
    return WrapRun(
        run_id=RUN_ID,
        correlation_id=CORRELATION_ID,
        package=package,
        bus=LocalEventBus(paths["events"]),
        artifacts=LocalArtifactStore(paths["artifacts"]),
        runs=LocalRunStore(paths["runs"]),
        interpreter=interpreter or OfflineInterpreter(),
        candidate_sha=os.environ.get("GITHUB_SHA"),
    )


def _interpreter(use_bedrock: bool, needed: bool = True):
    """Build an interpreter, and only pay for one where a model is used.

    ``resolve`` and ``verify`` call nothing but deterministic checks, so
    constructing a Bedrock client for them would burn a round trip and fail on a
    machine with no credentials for a command that never needed any.
    """
    if not use_bedrock or not needed:
        return OfflineInterpreter()
    from .adapters.aws.bedrock_interpreter import BedrockInterpreter

    return BedrockInterpreter()


def _banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}", flush=True)


def last_tool_result(agent) -> str:
    """The most recent tool's own words.

    ``str(result)`` is the planner's summary. What the 1st AD needs to see is
    what the tool actually did, including the receipt, so that is what gets
    printed rather than a paraphrase of it.
    """
    latest = ""
    for message in agent.messages:
        for block in message.get("content", []):
            if isinstance(block, dict) and "toolResult" in block:
                for inner in block["toolResult"].get("content", []):
                    if isinstance(inner, dict) and "text" in inner:
                        latest = inner["text"]
    return latest


def _report_interrupt(result) -> Optional[str]:
    """Print what the run is waiting for, and return the interrupt id."""
    interrupts = list(getattr(result, "interrupts", []) or [])
    if not interrupts:
        return None
    first = interrupts[0]
    reason = getattr(first, "reason", {}) or {}
    print(f"\n[pid {os.getpid()}] the run has stopped and is waiting for a human.")
    print(f"  who: {reason.get('required_role', 'unknown role')}")
    print(f"  what: {reason.get('kind', 'decision')} on {reason.get('beat_id') or reason.get('scene_id')}")
    if reason.get("justification"):
        print(f"  why: {reason['justification']}")
    if reason.get("note"):
        print(f"  note: {reason['note']}")
    print(f"  correlation token: {first.id}")
    print(
        "\n  This process is about to exit. The run is on disk. Resume it with:\n"
        "      lasttake approve --yes"
    )
    return first.id


# -- commands ---------------------------------------------------------------


def cmd_checkpoint(args) -> int:
    work = Path(args.workdir)
    run = _build_run(Path(args.corpus), work, _interpreter(args.bedrock))
    paths = _paths(work)

    _banner(
        f"WRAP CHECKPOINT  ·  {run.package.production_id}  ·  scene "
        f"{run.package.scene_id}  ·  revision {run.package.revision}"
    )
    run.publish(
        EventType.WRAP_CHECKPOINT_REQUESTED,
        {"requested_by_role": "script_supervisor", "scene_id": run.package.scene_id},
    )
    print(
        f"[pid {os.getpid()}] recorded scene.wrap-checkpoint.requested; "
        "this command starts the orchestrator directly; event publication never triggers Strands. "
        "The AWS subscriber, when deployed, records delivery only."
    )

    agent = build_orchestrator(run, session_dir=paths["sessions"])
    result = agent(
        f"Run the wrap checkpoint for scene {run.package.scene_id}, revision "
        f"{run.package.revision}. Report the count."
    )
    print("\n" + str(result))

    findings = [from_dict(f) for f in run.load_findings()]
    outcomes = rollup.roll_up(run.package, findings, run.load_decisions())
    _banner(rollup.sentence(outcomes))
    for outcome in outcomes:
        if outcome.status is not rollup.BeatStatus.COVERED:
            print(f"  {outcome.beat_id} {outcome.slug}: {outcome.status.value} — {outcome.reason}")

    uncovered = [o for o in outcomes if o.status is rollup.BeatStatus.NO_COVERAGE]
    if uncovered and result.stop_reason != "interrupt":
        beat = uncovered[0]
        print(f"\n[pid {os.getpid()}] requesting a pickup for {beat.beat_id}.")
        result = agent(
            f"Request a pickup approval for {beat.beat_id}. Justification: "
            f"{beat.reason}, and the set is still standing."
        )

    if result.stop_reason == "interrupt":
        _report_interrupt(result)
        return 0

    print("\nNo approval was needed. Nothing is waiting.")
    return 0


def cmd_approve(args) -> int:
    work = Path(args.workdir)
    run = _build_run(Path(args.corpus), work, _interpreter(args.bedrock))
    paths = _paths(work)

    _banner(f"1st AD DECISION  ·  a new process, {args.hours} hours later")
    print(f"[pid {os.getpid()}] this process did not exist when the run stopped.")

    agent = build_orchestrator(run, session_dir=paths["sessions"])
    answer = "y" if args.yes else "n"

    # The interrupt id is the correlation token the approval link carries.
    from strands.types.interrupt import InterruptResponse  # noqa: F401  (shape check)

    pending = args.interrupt_id
    if not pending:
        pending = _latest_interrupt_id(paths["sessions"])
    if not pending:
        print("Nothing is waiting for a decision.", file=sys.stderr)
        return 1

    result = agent([{"interruptResponse": {"interruptId": pending, "response": answer}}])
    outcome = last_tool_result(agent)
    if outcome:
        print(f"\n{outcome}")

    if result.stop_reason == "interrupt":
        _report_interrupt(result)
    return 0


def _latest_interrupt_id(session_dir: Path) -> Optional[str]:
    """Find the pending interrupt by reading the persisted session.

    In the product this token arrives with the approval request. Here it is
    recovered from disk so the two commands compose without a side channel.
    """
    candidates = sorted(session_dir.rglob("*.json"))
    for path in reversed(candidates):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        found = _find_interrupt_id(blob)
        if found:
            return found
    return None


def _find_interrupt_id(node) -> Optional[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"id", "interruptId"} and isinstance(value, str) and value.startswith("v1:"):
                return value
            found = _find_interrupt_id(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_interrupt_id(item)
            if found:
                return found
    return None


def cmd_late_take(args) -> int:
    """A take arrives after the checkpoint. Only the affected checks rerun."""
    work = Path(args.workdir)
    run = _build_run(Path(args.corpus), work, _interpreter(args.bedrock))

    take = Take(
        take_id="T-041",
        shot_id="S-42-PICKUP",
        beat_ids=[args.beat],
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
    row = CameraReportRow(
        take_id="T-041", media_id="A006R2F41", lens_mm=50, camera_roll="A006"
    )
    new_package = with_extra_take(run.package, take, row)
    new_run = run.with_package(new_package)

    _banner(f"take.captured  ·  {take.take_id} arrives after the checkpoint")
    event = new_run.build_event(
        EventType.TAKE_CAPTURED, {"take_id": take.take_id, "beat_ids": take.beat_ids}
    )
    new_run.bus.publish(event)
    affected = affected_by(event)
    print(f"Affected checks: {', '.join(affected)}. Everything else keeps its result.")

    # A new take changes the `takes` digest, and all four checks read `takes`,
    # so all four are genuinely affected. The gate would discard any of them
    # that was not rerun, which is the point: the narrowing is derived, not
    # asserted. Compare with `resolve rights`, where one artifact moves and one
    # check reruns.
    from .checks import continuity as continuity_check
    from .checks import coverage as coverage_check
    from .checks import metadata as metadata_check
    from .checks import rights as rights_check

    findings = (
        coverage_check.run(new_package, new_run.run_id, new_run.interpreter, policy.POLICY_VERSION)
        + continuity_check.run(new_package, new_run.run_id, new_run.interpreter, policy.POLICY_VERSION)
        + metadata_check.run(new_package, new_run.run_id, policy.POLICY_VERSION)
        + rights_check.run(new_package, new_run.run_id, policy.POLICY_VERSION)
    )
    _merge(new_run, findings)
    _print_headline(new_run)
    return 0


def _merge(run: WrapRun, fresh) -> None:
    """Add the fresh findings beside the ones whose evidence did not move.

    Nothing is re-stamped. A finding carries the digests it actually read, and
    the gate discards it if any of them has moved. So a check that was not
    rerun survives only when it genuinely still applies, and the decision is
    the gate's rather than this function's.
    """
    run.store_findings(list(fresh))


def _print_headline(run: WrapRun) -> None:
    findings = [from_dict(f) for f in run.load_findings()]
    outcomes = rollup.roll_up(run.package, findings, run.load_decisions())
    _banner(rollup.sentence(outcomes))
    for outcome in outcomes:
        if outcome.status is not rollup.BeatStatus.COVERED:
            print(f"  {outcome.beat_id} {outcome.slug}: {outcome.status.value} — {outcome.reason}")


def cmd_resolve(args) -> int:
    """A department supplies what was missing, and only its check reruns."""
    work = Path(args.workdir)
    # Rights is arithmetic and a recorded decision is arithmetic. No model here.
    run = _build_run(Path(args.corpus), work, _interpreter(args.bedrock, needed=False))

    if args.what == "rights":
        record = RightsRecord(
            record_id="REL-007",
            subject_id=args.subject,
            subject_kind="person",
            document_type="background release",
            scope="all media",
            territory="worldwide",
            expires_on=None,
            status="executed",
        )
        new_package = with_rights_record(run.package, record)
        new_run = run.with_package(new_package)
        new_run.publish(
            EventType.RIGHTS_RECORD_UPDATED,
            {"subject_id": args.subject, "record_id": record.record_id},
        )
        print(
            f"rights.record.updated for {args.subject}. Affected checks: rights. "
            "Coverage, continuity and media identity keep their results."
        )
        from .checks import rights as rights_check

        fresh = rights_check.run(
            new_package, new_run.run_id, policy.POLICY_VERSION
        )
        carried = [
            f
            for f in run.load_findings()
            if f["check_type"] != "rights"
        ]
        new_run.runs.save_findings(new_run.run_id, carried)
        _merge(new_run, fresh)
        print(
            f"Reran {len(fresh)} rights check(s). The other "
            f"{len(carried)} finding(s) still cite digests that have not moved, "
            "so the gate accepts them without a rerun."
        )
        _print_headline(new_run)
        return 0

    # A human decision, not new evidence. The finding stays exactly as written.
    current = next((from_dict(f) for f in run.load_findings() if f["finding_id"] == args.finding_id), None)
    if current is None:
        raise SystemExit(f"No finding {args.finding_id} on this run.")
    decision = policy.HumanDecision(
        decision_id=f"dec-{uuid.uuid4().hex[:8]}",
        finding_id=args.finding_id,
        action=policy.DecisionAction(args.action),
        actor=args.actor,
        role=policy.Role(args.role),
        reason=args.reason,
        finding_sha256=current.record_sha256,
    )
    if not policy.authority_check(
        _check_type_of(run, args.finding_id), decision.action, decision.role
    ):
        print(
            f"Refused: a {decision.role.value} may not {decision.action.value} this "
            "finding. The decision is not recorded, because a decision taken by the "
            "wrong role is not weak evidence, it is no evidence.",
            file=sys.stderr,
        )
        return 1
    run.record_decision(decision.to_dict())
    print(f"Recorded: {decision.actor} ({decision.role.value}) {decision.action.value}.")
    print("The original finding is unchanged and stays visible on the turnover.")
    _print_headline(run)
    return 0


def _check_type_of(run: WrapRun, finding_id: str):
    for raw in run.load_findings():
        if raw["finding_id"] == finding_id:
            return from_dict(raw).check_type
    raise SystemExit(f"No finding {finding_id} on this run.")


def cmd_verify(args) -> int:
    """Re-hash a turnover manifest and say whether it still matches its seal."""
    manifest = json.loads(Path(args.path).read_text(encoding="utf-8"))
    ok = verify_seal(manifest)
    print(f"schema:  {manifest.get('schema')}")
    print(f"scene:   {manifest.get('scene_id')} revision {manifest.get('script_revision')}")
    print(f"counts:  {json.dumps(manifest.get('counts', {}), sort_keys=True)}")
    print(f"seal:    {manifest.get('record_sha256', '(none)')}")
    print(f"verdict: {'intact' if ok else 'DOES NOT MATCH — this record has been altered'}")
    return 0 if ok else 1


def cmd_doctor(args) -> int:
    """Say what this machine and this account can actually do."""
    print(f"python           {sys.version.split()[0]}")
    try:
        import strands

        print(f"strands-agents   {getattr(strands, '__version__', 'installed')}")
    except ImportError:
        print("strands-agents   NOT INSTALLED")
    print(f"AWS_REGION       {os.environ.get('AWS_REGION', '(unset)')}")
    print(f"workdir          {args.workdir}")

    if not args.bedrock:
        print(
            "\nBedrock not checked. Re-run with --bedrock to ask the credentialed "
            "account what it can invoke."
        )
        return 0

    from .adapters.aws.bedrock_interpreter import resolve_available_models

    report = resolve_available_models()
    print(f"\nregion           {report['region']}")
    print(f"configured model {report['configured_model_id']}")
    print(f"is available     {report.get('configured_model_is_available')}")
    for key in ("foundation_models", "inference_profiles"):
        if key in report:
            print(f"\n{key} ({len(report[key])}):")
            for item in report[key][:40]:
                print(f"  {item}")
        if f"{key}_error" in report:
            print(f"\n{key}: {report[f'{key}_error']}")
    return 0 if report.get("configured_model_is_available") else 1


def cmd_events(args) -> int:
    bus = LocalEventBus(_paths(Path(args.workdir))["events"])
    rows = bus.replay()
    print(f"{len(rows)} event(s) on the log.\n")
    for row in rows:
        print(
            f"  {row['occurred_at'][11:19]}  {row['event_type']:<34} "
            f"{row['event_id'][:8]}  parent={str(row.get('parent_event_id'))[:8]}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The whole command surface, separated so it can be tested on its own.

    Kept apart from :func:`main` because the argument grammar is a thing that
    can be wrong by itself, and it was: `--bedrock` parsed in one position and
    not the other, which no test could see while every test used the position
    that worked.
    """
    parser = argparse.ArgumentParser(
        prog="lasttake",
        description="Before you wrap the set, know whether you truly have the scene.",
    )
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--workdir", default=str(DEFAULT_WORK))
    parser.add_argument(
        "--bedrock",
        action="store_true",
        help="Use Amazon Bedrock for the two bounded interpretations. Without it "
        "the offline lexical interpreter runs and says so on every finding.",
    )
    # The same three options again, accepted after the subcommand as well as
    # before it. `lasttake checkpoint --bedrock` is the form a person types and
    # the form the README documents; without this it was an "unrecognized
    # arguments" error, and the README was describing a command that did not
    # exist. `SUPPRESS` is what makes both forms safe: an option absent after
    # the subcommand leaves the attribute unset, so it cannot overwrite a value
    # given before it with the default.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--corpus", default=argparse.SUPPRESS)
    common.add_argument("--workdir", default=argparse.SUPPRESS)
    common.add_argument("--bedrock", action="store_true", default=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "checkpoint", parents=[common], help="run the checks and stop at the 1st AD"
    ).set_defaults(func=cmd_checkpoint)

    approve = sub.add_parser(
        "approve", parents=[common], help="resume a stopped run, in a new process"
    )
    approve.add_argument("--yes", action="store_true", help="the 1st AD approves")
    approve.add_argument("--interrupt-id", default=None)
    approve.add_argument("--hours", default="7.5")
    approve.set_defaults(func=cmd_approve)

    late = sub.add_parser(
        "late-take", parents=[common], help="a take arrives after the checkpoint"
    )
    late.add_argument("--beat", default="B-17")
    late.set_defaults(func=cmd_late_take)

    resolve = sub.add_parser(
        "resolve", parents=[common], help="a department resolves an exception"
    )
    resolve.add_argument("what", choices=["rights", "decision"])
    resolve.add_argument("--subject", default="BG-07")
    resolve.add_argument("--finding-id", default="")
    resolve.add_argument("--action", default="reject_false_positive")
    resolve.add_argument("--actor", default="unnamed")
    resolve.add_argument("--role", default="script_supervisor")
    resolve.add_argument("--reason", default="")
    resolve.set_defaults(func=cmd_resolve)

    verify = sub.add_parser(
        "verify", parents=[common], help="re-hash a turnover manifest"
    )
    verify.add_argument("path")
    verify.set_defaults(func=cmd_verify)

    sub.add_parser(
        "doctor", parents=[common], help="what this machine and account can do"
    ).set_defaults(func=cmd_doctor)
    sub.add_parser(
        "events", parents=[common], help="replay the event log"
    ).set_defaults(func=cmd_events)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
