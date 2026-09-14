"""The turnover packet available for editorial review in Handoff.

Generated deterministically from the sealed record, not written by a model.
An assistant editor opening this at 08:00 needs to know four things: what was
shot, what is missing, who decided what, and whether any of it has moved since.
The manifest answers all four and seals itself so the fourth is checkable.

Accepted exceptions stay visible. A known problem that somebody signed off is
still a known problem downstream, and burying it in an approval log is how it
reaches the edit as a surprise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .findings import Finding, TruthState
from .package import ScenePackage
from .policy import EligibilityPacket, HumanDecision, latest_decision, decision_applies, _resolution
from . import rollup
from .sealing import seal, utc_now_iso, verify_seal

TURNOVER_SCHEMA = "lasttake/turnover/v2"

#: The packet travels. Somebody will open it away from the page that made it,
#: possibly after the deadline, possibly without the context of what this corpus
#: is, so it says on its own face that the shoot day in it is invented. A packet
#: that could be mistaken for a record of a real production is a worse artifact
#: than no packet.
SYNTHETIC_NOTICE = (
    "THE LAST FERRY is a fictional production. Every person, place, identifier "
    "and record in this packet is invented for demonstration. No real production "
    "data and no real footage was read to produce it."
)

#: Stated on the face of every packet. The system reconciles records; it does
#: not render a legal opinion, and a reader must not infer one from a
#: ``verified`` rights row.
RIGHTS_DISCLAIMER = (
    "A rights row reading verified means the expected record was found and its "
    "structured fields matched the configured policy. It is not a legal opinion "
    "and it does not state that a use is lawful. Counsel determines legal "
    "sufficiency."
)


@dataclass
class Turnover:
    manifest: dict

    @property
    def digest(self) -> str:
        return self.manifest["record_sha256"]

    def verify(self) -> bool:
        return verify_seal(self.manifest)


def _source_manifest(package: ScenePackage) -> list[dict]:
    return [
        {"artifact_id": aid, "kind": art.kind, "sha256": art.sha256}
        for aid, art in sorted(package.artifacts.items())
    ]


def _take_map(package: ScenePackage) -> list[dict]:
    rows = []
    for beat in package.required_beats:
        takes = package.takes_for_beat(beat.beat_id)
        rows.append(
            {
                "beat_id": beat.beat_id,
                "slug": beat.slug,
                "page": beat.page,
                "takes": [
                    {
                        "take_id": t.take_id,
                        "slate": t.slate,
                        "preferred": t.preferred,
                        "usable": t.usable,
                        "timecode_in": t.timecode_in,
                        "media_id": t.media_id,
                    }
                    for t in takes
                ],
            }
        )
    return rows


def _technical_report(package: ScenePackage) -> list[dict]:
    """Side-by-side of what the take says and what the camera report says."""
    rows = []
    for take in package.takes:
        row = package.camera_row(take.take_id)
        rows.append(
            {
                "take_id": take.take_id,
                "sidecar_media_id": take.media_id,
                "camera_report_media_id": row.media_id if row else None,
                "reconciles": bool(row and row.media_id == take.media_id),
                "camera_roll": take.camera_roll,
                "sound_roll": take.sound_roll,
                "lens_mm": take.lens_mm,
            }
        )
    return rows


def generate(
    run_id: str,
    package: ScenePackage,
    findings: list[Finding],
    decisions: list[HumanDecision],
    eligibility: EligibilityPacket,
    approved_by: str,
    approved_role: str,
    candidate_sha: Optional[str] = None,
    approval_binding: Optional[dict] = None,
) -> Turnover:
    """Build the versioned packet. Deterministic given its inputs."""
    outstanding = [
        f.to_dict()
        for f in sorted(findings, key=lambda f: f.finding_id)
        if f.truth_state is not TruthState.VERIFIED
    ]
    outcomes = rollup.roll_up(package, findings, [d.to_dict() for d in decisions])
    # What each required beat rests on, carried into the packet rather than
    # collapsed into one word. An assistant editor opening this at 08:00 needs
    # the difference between a beat the production declared and a beat a reader
    # corroborated, because the second is evidence and the first is an assertion
    # by people who are no longer on the set.
    basis = {
        "summary": rollup.headline(outcomes)["basis"],
        "legend": {
            "declared_by_the_production": (
                "a take names this beat. The people who were there said so, and "
                "nothing has independently agreed"
            ),
            "corroborated_by_the_interpreter": (
                "a second reader agreed the take contains the beat. The interpreter "
                "that read it is named on each finding"
            ),
            "confirmed_by_a_named_human": (
                "the role the policy names looked at it and said so. This outranks "
                "both readings"
            ),
            "insufficient_evidence": (
                "no take, or a reader that could not tell. Never a pass"
            ),
        },
        "per_beat": [
            {
                "beat_id": o.beat_id,
                "slug": o.slug,
                "status": o.status.value,
                "basis": o.basis.value,
                "evidence_take_id": o.evidence_take_id,
            }
            for o in outcomes
        ],
    }
    unresolved = [
        {
            "finding_id": f.finding_id,
            "check_type": f.check_type.value,
            "truth_state": f.truth_state.value,
            "requirement_id": f.requirement_id,
            "required_role": f.required_role.value,
            "still_open": _resolution(f, decisions) is not True,
            "current_decision": (latest_decision(f, decisions).to_dict()
                                 if decision_applies(f, latest_decision(f, decisions)) else None),
        }
        for f in sorted(findings, key=lambda f: f.finding_id)
        if f.truth_state is not TruthState.VERIFIED
    ]
    manifest = {
        **(approval_binding or {}),
        "schema": TURNOVER_SCHEMA,
        "synthetic_corpus_notice": SYNTHETIC_NOTICE,
        "evidence_basis": basis,
        "unresolved_at_handover": unresolved,
        "run_id": run_id,
        "production_id": package.production_id,
        "scene_id": package.scene_id,
        "script_revision": package.revision,
        "package_revision_digest": package.revision_digest(),
        "policy_version": eligibility.policy_version,
        "generated_at": utc_now_iso(),
        "candidate_sha": candidate_sha,
        "wrap_approved_by": {"actor": approved_by, "role": approved_role},
        "counts": eligibility.counts,
        "source_manifest": _source_manifest(package),
        "finding_provenance": [{"finding_id": f.finding_id, "model_id": f.model_id,
                                "record_sha256": f.record_sha256} for f in findings],
        "provenance_limit": "Missing serialized model identifiers remain unknown. A hash identifies bytes, not factual truth.",
        "beat_to_take_map": _take_map(package),
        "technical_identity_report": _technical_report(package),
        "outstanding_and_accepted_exceptions": outstanding,
        "human_decisions": [d.to_dict() for d in decisions],
        "eligibility_packet": eligibility.to_dict(),
        "rights_disclaimer": RIGHTS_DISCLAIMER,
    }
    return Turnover(manifest=seal(manifest))
