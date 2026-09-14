"""The tools the orchestrator can call, and the two that stop and wait for a human.

Every tool here is bounded, named after a thing a department actually does, and
returns a summary the orchestrator can read. None of them decides anything: the
four check tools record findings, the gate tool runs arithmetic, and the two
approval tools hand the decision to a named human and stop.

**Read this before adding a tool.** On resume, Strands re-enters the tool body
from its first line and ``interrupt()`` returns the stored answer. It is a
replay, not a frozen stack frame. So in any tool that interrupts, everything
before the ``interrupt()`` call runs twice, and the external effect goes
strictly after it, behind an idempotency key. This was found in a spike on
2026-08-22 rather than in production, and the shape of these two functions is
the whole reason that spike was worth a day.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from strands import tool
from strands.interrupt import InterruptException
from strands.types.tools import ToolContext

from ..checks import continuity as continuity_check
from ..checks import coverage as coverage_check
from ..checks import metadata as metadata_check
from ..checks import rights as rights_check
from ..domain import policy, rollup
from ..domain.events import Event, EventType
from ..domain.findings import Finding, from_dict
from ..domain.turnover import generate as generate_turnover
from ..domain.sealing import digest_of
from .runtime import WrapRun


def _record(run: WrapRun, findings: list[Finding]) -> str:
    """Persist findings, publish one event each, and summarise for the model."""
    run.store_findings(findings)
    deliveries = []
    outcomes = []
    for finding in findings:
        deliveries.append(run.publish(
            EventType.FINDING_RECORDED,
            {
                "finding_id": finding.finding_id,
                "check_type": finding.check_type.value,
                "requirement_id": finding.requirement_id,
                "truth_state": finding.truth_state.value,
            }, delivery_batch=outcomes,
        ))
    # Finding notifications cannot authorize a handoff. One persisted batch
    # preserves their actual receipts without two DSQL transactions per finding.
    run.audit("event.delivery.batch", {"outcomes": outcomes})
    exceptions = [f for f in findings if f.truth_state.is_exception]
    lines = [
        f"{len(findings)} {'finding' if len(findings) == 1 else 'findings'} recorded, "
        f"{len(exceptions)} "
        f"{'raising an exception' if len(exceptions) == 1 else 'raising exceptions'}."
    ]
    for finding in exceptions[:8]:
        lines.append(
            f"  {finding.requirement_id}: {finding.truth_state.value}. "
            f"{finding.observation}"
        )
    if len(exceptions) > 8:
        lines.append(f"  ... and {len(exceptions) - 8} more.")
    failed = [r for r in deliveries if not r.accepted]
    if failed:
        lines.append(f"{len(failed)} event delivery outcome(s) need review; findings are saved. No downstream completion is established.")
    return "\n".join(lines)


def _approval_record(run, tool_context, kind):
    """Persist the first review, then reload those exact bytes on tool replay."""
    tool_id = tool_context.tool_use["toolUseId"]
    approval_id = digest_of({"run": run.run_id, "tool": tool_id, "kind": kind})
    key = f"approvals/{run.run_id.replace(':', '_')}/{approval_id}.json"
    if run.artifacts.exists(key):
        return json.loads(run.artifacts.get(key))
    record = {"approval_id": approval_id, "required_role": policy.Role.FIRST_AD.value,
              **run.review_binding()}
    return record


def _await_approval(run, tool_context, kind, reason):
    reviewed = _approval_record(run, tool_context, kind)
    key = f"approvals/{run.run_id.replace(':', '_')}/{reviewed['approval_id']}.json"
    saved = run.artifacts.exists(key)
    try:
        answer = tool_context.interrupt(f"first-ad-{kind}-approval", reason={**reason, **reviewed})
    except InterruptException:
        if not saved:
            run.artifacts.put(key, json.dumps(reviewed, sort_keys=True).encode())
            run.audit(f"{kind}.requested", reviewed)
        raise
    # Never bind today's evidence to an older unbound affirmative response.
    # The old request can still be declined and replaced by a fresh review.
    return answer, reviewed if saved else {}


def _delivery_message(receipt):
    if receipt.accepted:
        return f"Bus accepted. Receipt {receipt.reference}. Downstream completion is not established."
    if receipt.outcome == "rejected":
        return "Bus rejected the request. A safe explicit retry is available in delivery status."
    if receipt.outcome == "refused":
        return f"Refusing: {receipt.detail}"
    return f"Delivery {receipt.outcome}. No success is recorded. Reconcile the saved attempt before any resend."


def _split(csv: str) -> tuple[str, ...] | None:
    """Parse a narrowing argument. Empty means the whole check, not nothing."""
    items = tuple(part.strip() for part in csv.split(",") if part.strip())
    return items or None


def build_tools(run: WrapRun) -> list[Callable[..., Any]]:
    """Bind the toolset to one run. Returned in the order a checkpoint uses them."""

    @tool
    def run_coverage_check(only_beats: str = "") -> str:
        """Check which required beats have viable, evidence-backed coverage.

        Args:
            only_beats: Comma-separated beat ids to narrow a targeted rerun.
                Leave empty to check every required beat.
        """
        findings = coverage_check.run(
            run.package,
            run.run_id,
            run.interpreter,
            policy.POLICY_VERSION,
            only_beats=_split(only_beats),
        )
        if not only_beats:
            findings = findings + coverage_check.orphan_shots(
                run.package, run.run_id, policy.POLICY_VERSION
            )
        return _record(run, findings)

    @tool
    def run_continuity_check(only_refs: str = "") -> str:
        """Check for conflicts between preferred takes that would constrain the edit.

        Args:
            only_refs: Comma-separated continuity reference ids to narrow a rerun.
        """
        return _record(
            run,
            continuity_check.run(
                run.package,
                run.run_id,
                run.interpreter,
                policy.POLICY_VERSION,
                only_refs=_split(only_refs),
            ),
        )

    @tool
    def run_metadata_check(only_takes: str = "") -> str:
        """Reconcile each take's slate, media, lens and roll against the camera report.

        Args:
            only_takes: Comma-separated take ids to narrow a rerun.
        """
        return _record(
            run,
            metadata_check.run(
                run.package,
                run.run_id,
                policy.POLICY_VERSION,
                only_takes=_split(only_takes),
            ),
        )

    @tool
    def run_rights_check(only_subjects: str = "") -> str:
        """Trace every visible person and asset to a release or licence record.

        Args:
            only_subjects: Comma-separated subject ids to narrow a rerun.
        """
        return _record(
            run,
            rights_check.run(
                run.package,
                run.run_id,
                policy.POLICY_VERSION,
                only_subjects=_split(only_subjects),
            ),
        )

    @tool
    def evaluate_wrap_eligibility() -> str:
        """Combine every current finding by deterministic policy.

        Returns the eligibility packet and the headline count. This is
        arithmetic over evidence, not a decision, and it cannot approve a wrap.
        """
        findings = [from_dict(f) for f in run.load_findings()]
        decisions = [policy.decision_from_dict(d) for d in run.load_decisions()]
        packet = policy.evaluate(run.run_id, run.package, findings, decisions)
        run.store_packet(packet.sealed())

        outcomes = rollup.roll_up(run.package, findings, run.load_decisions())
        sentence = rollup.sentence(outcomes)

        if packet.eligible:
            delivery = run.publish(EventType.WRAP_ELIGIBLE, {"counts": packet.counts})
        else:
            delivery = run.publish(
                EventType.APPROVAL_REQUESTED,
                {"causes": [c.to_dict() for c in packet.causes]},
            )

        lines = [sentence, ""]
        lines.append(
            "Eligible for wrap: "
            + ("yes, pending the 1st AD's approval." if packet.eligible else "no.")
        )
        for cause in packet.causes[:10]:
            lines.append(
                f"  {cause.check_type.value} {cause.requirement_id}: {cause.reason} "
                f"(goes to {cause.required_role.value})"
            )
        if len(packet.causes) > 10:
            lines.append(f"  ... and {len(packet.causes) - 10} more causes.")
        lines.append(_delivery_message(delivery))
        return "\n".join(lines)

    @tool(context=True)
    def request_pickup_approval(
        tool_context: ToolContext, beat_id: str, justification: str
    ) -> str:
        """Ask the 1st AD to approve a pickup for one uncovered beat, and WAIT.

        This stops the run. The 1st AD may answer in ninety seconds or at 06:40
        tomorrow; either way the run resumes from this exact point.

        Args:
            beat_id: The required beat with no viable coverage.
            justification: Why the pickup is needed, in the supervisor's terms.
        """
        beat = run.package.beat(beat_id)
        if beat is None:
            return f"No beat {beat_id} in revision {run.package.revision}. Nothing to request."

        # Everything above this line runs again on resume. Nothing above it
        # touches the outside world, and nothing below it may run twice.
        reviewed = _approval_record(run, tool_context, "pickup")
        decision, reviewed = _await_approval(
            run, tool_context, "pickup",
            reason={
                "kind": "pickup",
                **reviewed,
                "scene_id": run.package.scene_id,
                "beat_id": beat_id,
                "slug": beat.slug,
                "page": beat.page,
                "justification": justification,
                "required_role": policy.Role.FIRST_AD.value,
                "note": "Approving records a pickup request. It does not wrap the scene.",
            },
        )

        approved = str(decision).strip().lower() in {"y", "yes", "approve", "approved"}
        if not approved:
            run.audit(
                "pickup.declined", {"beat_id": beat_id, "decision": str(decision)}
            )
            return (
                f"The 1st AD did not approve a pickup for {beat_id}. The gap stands "
                "and remains an exception on the turnover."
            )

        # The external effect, once, keyed so a duplicate delivery is harmless.
        if not reviewed:
            return "Refusing: this older request has no saved evidence binding. Request a fresh approval."
        receipt = run.publish_approved(
            EventType.PICKUP_REQUESTED,
            {
                "beat_id": beat_id,
                "scene_id": run.package.scene_id,
                "justification": justification,
                "approved_by_role": policy.Role.FIRST_AD.value,
                **reviewed,
            },
        )
        if not receipt.accepted:
            return _delivery_message(receipt)
        return (
            f"Pickup approved for {beat_id} by the 1st AD. {_delivery_message(receipt)} The beat stays an "
            "exception until a take arrives for it."
        )

    @tool(context=True)
    def request_wrap_approval(tool_context: ToolContext) -> str:
        """Ask the 1st AD to approve the wrap itself, and WAIT.

        Only call this after evaluate_wrap_eligibility reports eligible. Being
        eligible is arithmetic; wrapping is authority, and it is not yours.
        """
        packet = run.load_packet()
        if packet is None:
            return "No eligibility packet yet. Run evaluate_wrap_eligibility first."
        # A resumed stale request still reaches interrupt() so it can be declined.
        approval_key = f"approvals/{run.run_id.replace(':', '_')}/{digest_of({'run': run.run_id, 'tool': tool_context.tool_use['toolUseId'], 'kind': 'wrap'})}.json"
        replay = run.artifacts.exists(approval_key)
        if not replay and not packet.get("eligible"):
            causes = packet.get("causes", [])
            return (
                f"Not eligible: {len(causes)} unresolved cause(s). Asking the 1st AD "
                "to approve a wrap the evidence does not support is exactly what this "
                "system exists to prevent. Resolve the causes first."
            )

        reviewed = _approval_record(run, tool_context, "wrap")
        if not replay and not run.wrap_guard(reviewed):
            return "Refusing: current evidence is not eligible. Run a fresh checkpoint and review."
        decision, reviewed = _await_approval(
            run, tool_context, "wrap",
            reason={
                "kind": "wrap",
                **reviewed,
                "scene_id": run.package.scene_id,
                "counts": packet.get("counts"),
                "required_role": policy.Role.FIRST_AD.value,
                "note": (
                    "Eligibility is an arithmetic result over evidence. It is not a "
                    "statement that the scene is legally cleared, safe or creatively "
                    "complete. That judgement is yours."
                ),
            },
        )

        approved = str(decision).strip().lower() in {"y", "yes", "approve", "approved"}
        if not approved:
            run.audit("wrap.declined", {"decision": str(decision), **reviewed,
                "required_role": policy.Role.FIRST_AD.value,
                "approval_id": _approval_record(run, tool_context, "wrap")["approval_id"]})
            return "The 1st AD did not approve the wrap. Any earlier wrap approval remains historical, not current authority."

        if not reviewed:
            return "Refusing: this older request has no saved evidence binding. Request a fresh approval."
        receipt = run.publish_approved(
            EventType.WRAP_READY,
            {"scene_id": run.package.scene_id, "approved_by_role": policy.Role.FIRST_AD.value, **reviewed},
        )
        if not receipt.accepted:
            return _delivery_message(receipt)
        return (
            f"Wrap approved by the 1st AD. {_delivery_message(receipt)} "
            "Publish the turnover now."
        )

    @tool
    def publish_turnover() -> str:
        """Generate and publish the versioned packet editorial receives."""
        packet_dict = run.load_packet()
        if packet_dict is None or not packet_dict.get("eligible"):
            return "Refusing: no eligible packet. A turnover without one is a claim with nothing behind it."
        if not run.wrap_approved():
            return (
                "Refusing: no 1st AD wrap approval on record. Eligibility is not "
                "authority and this tool will not stand in for a human."
            )

        findings = [from_dict(f) for f in run.load_findings()]
        decisions = [policy.decision_from_dict(d) for d in run.load_decisions()]
        eligibility = policy.evaluate(run.run_id, run.package, findings, decisions)
        if not eligibility.eligible:
            return "Refusing: current evidence is not eligible. Review the changed findings first."
        key = f"turnover/{run.run_id.replace(':', '_')}.json"
        if run.artifacts.exists(key):
            manifest = json.loads(run.artifacts.get(key))
            if not run.handoff_current(manifest):
                return "Refusing: the saved turnover is historical. Start a new run for a changed review or approval."
            digest = manifest["record_sha256"]
        else:
            turnover = generate_turnover(
                run_id=run.run_id,
                package=run.package,
                findings=findings,
                decisions=decisions,
                eligibility=eligibility,
                approved_by=run.wrap_approver(),
                approved_role=policy.Role.FIRST_AD.value,
                candidate_sha=run.candidate_sha,
                approval_binding={"approval_id": run.current_wrap_approval()["approval_id"], **run.review_binding()},
            )
            key = run.store_turnover(turnover.manifest)
            manifest = turnover.manifest
            digest = turnover.digest
        delivery = run.publish(
            EventType.TURNOVER_GENERATED,
            {"artifact_key": key, "digest": digest, "approval_id": manifest["approval_id"],
             "review_digest": manifest["review_digest"], "package_revision_digest": manifest["package_revision_digest"]},
            idempotent=True,
        )
        if not delivery.accepted:
            return f"Turnover saved as {key}. {_delivery_message(delivery)}"
        return (
            f"Turnover published as {key}, sealed with {digest[:12]}. {_delivery_message(delivery)} "
            "The hash checks bytes, not the truth of the supplied records."
        )

    return [
        run_coverage_check,
        run_continuity_check,
        run_metadata_check,
        run_rights_check,
        evaluate_wrap_eligibility,
        request_pickup_approval,
        request_wrap_approval,
        publish_turnover,
    ]
