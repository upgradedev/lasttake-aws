"""The receipt a person carries out of the room.

The turnover manifest is for editorial and it is large. This is the other half:
a small sealed document that leaves the page, gets pasted into a production
email or a call sheet note, and still says what it is a week later.

That is the whole design constraint. A packet that travels loses its context by
definition, so every one of these carries, on its own face:

- which run and which scene it is about, and the digest of the package it read
- the version of the policy that produced it and the schema of the packet itself
- what is **still open**, including anything a human accepted rather than fixed
- what the packet does **not** say, spelled out rather than left to be assumed
- that the production in it is invented

An accepted exception is not a closed one. It appears under ``still_open`` with
its decision beside it, because a receipt that lists only the unresolved items
lets an approved problem travel silently, and the person reading it downstream
has no way to know it was ever raised.

Nothing here is written by a model. It is assembled from the sealed record.
"""

from __future__ import annotations

from typing import Optional

from .findings import Finding, Role, TruthState
from .package import ScenePackage
from .policy import (
    DecisionAction,
    HumanDecision,
    _resolution,
    decision_applies,
    evaluate,
    latest_decision,
)
from .sealing import seal, utc_now_iso, verify_seal
from .turnover import RIGHTS_DISCLAIMER, SYNTHETIC_NOTICE

RECEIPT_SCHEMA = "lasttake/receipt/v1"

#: What the packet does not say. Stated on the receipt rather than left to the
#: reader, because a short document that lists problems reads like a clearance
#: to somebody who did not watch it being made.
LIMITS = (
    # Worded to avoid the phrases the prose gate and the live probes forbid.
    # Those checks match on substrings and cannot tell an assertion from its
    # denial, and a receipt is not the place to argue with a safety check: it is
    # the place to say the thing plainly. "Cleared in law" carries the meaning
    # without carrying the banned string.
    "This receipt reports the reconciliation of supplied records. It does not "
    "state that the scene is creatively complete, cleared in law, or safe to "
    "wrap, and it does not judge a performance. Absent evidence is reported as "
    "a gap and is never a pass.",
    "An item under still_open is open. An accepted exception is a known problem "
    "that a named person signed for, not a resolved one.",
    "The counts describe the records that were read. Anything nobody wrote down "
    "cannot appear here.",
    "SHA-256 identifies bytes. It does not prove source authenticity, human identity or factual truth.",
    "Bus acceptance is not downstream delivery or completion. An S3 event copy alone proves only storage.",
)

#: The next action for each kind of exception, phrased for the person who has to
#: take it. The same words the page shows beside a finding, and the receipt's
#: ``next_action`` field carries them, so a receipt read away from the page says
#: the same thing the page said. The receipt's human-readable summary quotes the
#: finding's own ``recommended_action`` when it has one instead, because that is
#: the text the turnover prints for the same finding, and the summary and the
#: turnover sit on one handoff page.
NEXT_ACTION = {
    "coverage": "Shoot one more setup against this beat, while the lighting is up.",
    "continuity": "Take one more take, or write the intent down on the spot.",
    "metadata": "Re-read the card and reconcile the identifier before it is cleared.",
    "rights": "Get the signature while the person is still on set.",
}

#: A finding in the ``unknown`` state is not the same problem as one that failed,
#: and telling somebody to shoot a setup for it would send them after a beat the
#: current revision no longer has. The orphan-shot advisory is a coverage finding
#: with no requirement id at all: it says the shot list and the script have
#: drifted. The page already draws this distinction and a receipt read away from
#: the page has to draw the same one, or the two documents disagree about what to
#: do while claiming the same source.
NEXT_ACTION_UNKNOWN = {
    "coverage": "Ask whether the shot list was rebuilt against the current script revision.",
    "continuity": "Write the intent down on the take, while the setup is still remembered.",
}


#: How each role reads on the page. The labels match the interface's, so a
#: receipt pasted into an email names the role the way the screen did, rather
#: than as a stored identifier like ``dit``. Keyed by the stored value.
ROLE_LABELS = {
    "script_supervisor": "Script supervisor",
    "first_ad": "1st AD",
    "dit": "DIT / data manager",
    "production_coordinator": "Production coordinator",
    "assistant_editor": "Assistant editor",
}

#: A standing decision stated as what happened, not as its stored action value.
DECISION_OUTCOME = {
    "confirm": "Confirmed",
    "reject_false_positive": "Rejected as a false positive",
    "accept_exception": "Exception accepted",
}


def role_label(role: Role | str) -> str:
    """The label a person reads for a role, from the enum or its stored value."""
    value = getattr(role, "value", role)
    return ROLE_LABELS.get(value, str(value).replace("_", " "))


def action_words(action: DecisionAction | str) -> str:
    """A decision action in words: ``accept_exception`` reads ``accept exception``."""
    return str(getattr(action, "value", action)).replace("_", " ")


def decision_phrase(decision: HumanDecision) -> str:
    """Who decided what, by role: ``Exception accepted by Sue (Script supervisor)``."""
    outcome = DECISION_OUTCOME.get(
        decision.action.value, action_words(decision.action).capitalize()
    )
    return f"{outcome} by {decision.actor} ({role_label(decision.role)})"


def _settles(finding: Finding, decision: Optional[HumanDecision]) -> bool:
    """True when this decision stands on the current reading and closes it for the gate.

    The finding still travels under ``still_open`` either way. What changes is
    that nobody is left with something to fix, so an instruction to fix it would
    be stale. A confirmation settles nothing: the role agreed the problem is
    real, and the instruction still stands.
    """
    return decision is not None and _resolution(finding, [decision]) is True


def _settled_statement(decision: HumanDecision) -> str:
    if decision.action is DecisionAction.ACCEPT_EXCEPTION:
        return (
            f"{decision_phrase(decision)}. It stays open on the turnover: an "
            "accepted exception is a known problem, not a fixed one."
        )
    return (
        f"{decision_phrase(decision)}. The original finding stays open on the "
        "record beside that review."
    )


def next_action(finding: Finding, decision: Optional[HumanDecision] = None) -> str:
    """What the responsible role does next, or the decision that settled it.

    Asked about the finding alone, as the page asks, this is the instruction for
    the kind of exception. Given the decision that stands over the finding, and
    when that decision settles it, the answer is the decision: a DIT who accepted
    an identifier mismatch should not then be told to reconcile it.
    """
    if _settles(finding, decision):
        return _settled_statement(decision)
    kind = finding.check_type.value
    if finding.truth_state is TruthState.UNKNOWN and kind in NEXT_ACTION_UNKNOWN:
        return NEXT_ACTION_UNKNOWN[kind]
    return NEXT_ACTION.get(kind, "Route this to the responsible role.")


def _unverified(findings: list[Finding]) -> list[Finding]:
    """The findings a receipt lists as open, in the order it lists them."""
    return [
        f
        for f in sorted(findings, key=lambda f: f.finding_id)
        if f.truth_state is not TruthState.VERIFIED
    ]


def _summary_line(finding: Finding, decisions: list[HumanDecision]) -> str:
    """One open item as it reads pasted into an email.

    The instruction quoted is the finding's own recommended action, the text the
    turnover prints for the same finding, so the receipt and the turnover on one
    handoff page give one next step rather than two. A decision that settles the
    finding replaces the instruction with what was decided and by which role,
    and says the finding is still open.

    Everything on the line is read from the finding and the decisions, never
    from a row built elsewhere, so a line cannot pair one finding's id with
    another's role. The settled wording is the same ``next_action`` call the
    row's field makes, so the field and the line say one thing.
    """
    head = f"{finding.finding_id}: {finding.truth_state.value}; {role_label(finding.required_role)}."
    instruction = finding.recommended_action or next_action(finding)
    decision = latest_decision(finding, decisions)
    if not decision_applies(finding, decision):
        standing = (
            "An earlier decision no longer applies: the evidence changed."
            if decision
            else "No current decision."
        )
        return f"{head} {standing} Next: {instruction}"
    if _settles(finding, decision):
        return f"{head} {next_action(finding, decision)}"
    return f"{head} {decision_phrase(decision)}; the finding is still open. Next: {instruction}"


def _open_items(
    findings: list[Finding], decisions: list[HumanDecision]
) -> list[dict]:
    """Everything not verified, with whatever decision stands over it.

    A decision only counts here if it is about the reading that exists now. The
    same rule the gate applies: an approval is bound to the digest of the
    finding it was taken about, and evidence that has moved since outran it.
    """
    rows = []
    for finding in _unverified(findings):
        decision = latest_decision(finding, decisions)
        applies = decision_applies(finding, decision)
        rows.append(
            {
                "finding_id": finding.finding_id,
                "check_type": finding.check_type.value,
                "truth_state": finding.truth_state.value,
                "requirement_id": finding.requirement_id,
                "what_was_observed": finding.observation,
                "responsible_role": finding.required_role.value,
                "next_action": next_action(finding, decision if applies else None),
                "read_from": [
                    {"artifact_id": s.artifact_id, "sha256": s.sha256}
                    for s in finding.sources
                ],
                "a_human_decided": (
                    {
                        "action": decision.action.value,
                        "decision_id": decision.decision_id,
                        "finding_sha256": decision.finding_sha256,
                        "at": decision.at,
                        "actor": decision.actor,
                        "role": decision.role.value,
                        "reason": decision.reason,
                        "still_open_because": (
                            "an accepted exception is a known problem, not a fixed one"
                            if decision.action.value == "accept_exception"
                            else "the original finding is retained alongside the current human review"
                        ),
                    }
                    if applies and decision
                    else None
                ),
                "an_earlier_decision_no_longer_applies": (
                    bool(decision) and not applies
                ),
            }
        )
    return rows


def build(
    *,
    kind: str,
    run_id: str,
    package: ScenePackage,
    findings: list[Finding],
    decisions: list[HumanDecision],
    policy_version: str,
    approved_by: Optional[str] = None,
    approved_role: Optional[str] = None,
    subject: Optional[dict] = None,
    execution: Optional[dict] = None,
    deliveries: Optional[list[dict]] = None,
    recovery: Optional[dict] = None,
) -> dict:
    """A sealed, portable receipt. ``kind`` is ``pickup`` or ``wrap``."""
    if kind not in ("pickup", "wrap"):
        raise ValueError(f"a receipt is about a pickup or a wrap, not {kind!r}")

    still_open = _open_items(findings, decisions)
    packet = evaluate(run_id, package, findings, decisions)
    sources = [{"artifact_id": aid, "kind": art.kind, "sha256": art.sha256}
               for aid, art in sorted(package.artifacts.items())]
    provenance = [{"finding_id": f.finding_id, "model_id": f.model_id,
                   "has_interpretation": f.inference is not None,
                   "record_sha256": f.record_sha256}
                  for f in sorted(findings, key=lambda f: f.finding_id)]
    lines = [f"LastTake evidence review: {package.scene_id} / {run_id}",
             f"Revision {package.revision}; package SHA-256 {package.revision_digest()}",
             f"Policy {policy_version}; current gate {'eligible' if packet.eligible else 'blocked'}; {len(packet.causes)} cause(s).",
             "Synthetic role selection; no authenticated staff identity.",
             "Sources: " + ", ".join(s["artifact_id"] for s in sources)]
    mode = execution or {}
    lines.append(f"Execution mode: {mode.get('mode', 'not_recorded')}; backend revision: {mode.get('backend_revision') or 'unknown'}.")
    lines.append("Serialized finding model identifiers: " + ", ".join(sorted({p['model_id'] or 'unknown' for p in provenance})))
    lines.extend(f"Source {s['artifact_id']}: SHA-256 {s['sha256']}" for s in sources)
    if recovery and recovery.get("recovery_reason"):
        lines.append(recovery["recovery_reason"])
    lines.append("Recovery: refresh saved state; correct refused evidence; obtain a fresh review after changes. Retry only a definite rejection. Pending or unknown external outcomes require operator reconciliation.")
    lines.append("Human-active time and measured benefits: unknown.")
    lines.extend(_summary_line(finding, decisions) for finding in _unverified(findings))
    for delivery in deliveries or []:
        if delivery.get("event_type") in ("pickup.requested", "wrap.ready", "turnover.generated") or delivery.get("status") != "accepted":
            lines.append(f"Delivery {delivery['event_type']}: {delivery['status']}; receipt {delivery['reference']}.")
    lines.extend(LIMITS)
    return seal(
        {
            "schema": RECEIPT_SCHEMA,
            "kind": kind,
            "synthetic_corpus_notice": SYNTHETIC_NOTICE,
            # The four fields that make it portable. If a copy of this document
            # cannot answer "which run, which scene, which policy, which
            # package", it is an anecdote rather than a record.
            "run_id": run_id,
            "scene_id": package.scene_id,
            "production_id": package.production_id,
            "script_revision": package.revision,
            "package_revision_digest": package.revision_digest(),
            "policy_version": policy_version,
            "generated_at": utc_now_iso(),
            "approved_by": (
                {"actor": approved_by, "role": approved_role}
                if approved_by
                else None
            ),
            "subject": subject or {},
            "still_open": still_open,
            "still_open_count": len(still_open),
            "what_this_does_not_say": list(LIMITS),
            "rights_disclaimer": RIGHTS_DISCLAIMER,
            "human_readable": "\n".join(lines),
            "source_manifest": sources,
            "finding_provenance": provenance,
            "execution": execution or {"mode": "not_recorded", "backend_revision": None},
            "provenance_limit": "Only serialized model identifiers are attributed. Missing identifiers remain unknown; no model is inferred from current configuration.",
            "gate": {"eligible": packet.eligible, "cause_count": len(packet.causes),
                     "discarded_findings": packet.discarded},
            "delivery_outcomes": deliveries or [],
            "recovery": recovery or {},
            "human_active_seconds": None,
            "measured_benefit": None,
        }
    )


def verify(manifest: dict) -> bool:
    return verify_seal(manifest)
