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

from .findings import Finding, TruthState
from .package import ScenePackage
from .policy import HumanDecision, latest_decision, decision_applies
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
)

#: The next action for each kind of exception, phrased for the person who has to
#: take it. The same words the page shows, kept here so a receipt read away from
#: the page says the same thing the page said.
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


def next_action(finding: Finding) -> str:
    kind = finding.check_type.value
    if finding.truth_state is TruthState.UNKNOWN and kind in NEXT_ACTION_UNKNOWN:
        return NEXT_ACTION_UNKNOWN[kind]
    return NEXT_ACTION.get(kind, "Route this to the responsible role.")


def _open_items(
    findings: list[Finding], decisions: list[HumanDecision]
) -> list[dict]:
    """Everything not verified, with whatever decision stands over it.

    A decision only counts here if it is about the reading that exists now. The
    same rule the gate applies: an approval is bound to the digest of the
    finding it was taken about, and evidence that has moved since outran it.
    """
    rows = []
    for finding in sorted(findings, key=lambda f: f.finding_id):
        if finding.truth_state is TruthState.VERIFIED:
            continue
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
                "next_action": next_action(finding),
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
                            "the original finding is retained alongside the current human review"
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
) -> dict:
    """A sealed, portable receipt. ``kind`` is ``pickup`` or ``wrap``."""
    if kind not in ("pickup", "wrap"):
        raise ValueError(f"a receipt is about a pickup or a wrap, not {kind!r}")

    still_open = _open_items(findings, decisions)
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
        }
    )


def verify(manifest: dict) -> bool:
    return verify_seal(manifest)
