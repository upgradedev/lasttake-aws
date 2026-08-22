"""Continuity: differences between preferred takes that would constrain the edit.

This check only looks where a conflict can actually hurt. Two takes that
disagree are not a problem if only one of them is preferred, because the edit
will use the preferred one. Two *preferred* takes that disagree are a problem,
because whoever cuts the scene has to pick, and picking in the edit is exactly
the choice this product exists to move forward to while the set is standing.

Intentional variation is treated as a real possibility rather than an
inconvenience. A director who changed the mug on purpose has not made a
mistake, and a system that calls it one gets ignored within a day.
"""

from __future__ import annotations

from itertools import combinations

from ..domain.findings import (
    CheckType,
    Finding,
    Locator,
    Role,
    Severity,
    Source,
    TruthState,
    validate,
)
from ..domain.package import ScenePackage
from ..ports.interpreter import Interpreter

AGENT_VERSION = "continuity/1.0.0"

#: Below this the disagreement is not solid enough to call conflicting, and
#: the reference becomes ``unknown`` instead. Still an exception either way.
MIN_CONFLICT_CONFIDENCE = 0.6


def run(
    package: ScenePackage,
    run_id: str,
    interpreter: Interpreter,
    policy_version: str,
    only_refs: tuple[str, ...] | None = None,
) -> list[Finding]:
    revision = package.revision_digest()
    sources = [
        Source(
            artifact_id="continuity_refs",
            sha256=package.artifacts["continuity_refs"].sha256,
            kind="reference",
        ),
        Source(
            artifact_id="script_notes",
            sha256=package.artifacts["script_notes"].sha256,
            kind="notes",
        ),
        Source(artifact_id="takes", sha256=package.artifacts["takes"].sha256, kind="takes"),
    ]
    findings: list[Finding] = []

    for ref in package.continuity_refs:
        if only_refs is not None and ref.ref_id not in only_refs:
            continue

        preferred = [
            take
            for beat_id in ref.beat_ids
            for take in package.takes_for_beat(beat_id)
            if take.preferred and take.usable
        ]
        # Same take can cover two beats of the reference. Deduplicate by id and
        # keep script order, so the pair reported is stable between runs.
        unique: list = []
        for take in preferred:
            if take.take_id not in {t.take_id for t in unique}:
                unique.append(take)

        if len(unique) < 2:
            findings.append(
                Finding(
                    finding_id=f"{run_id}:con:{ref.ref_id}",
                    run_id=run_id,
                    scene_id=package.scene_id,
                    requirement_id=ref.ref_id,
                    check_type=CheckType.CONTINUITY,
                    truth_state=TruthState.VERIFIED,
                    severity=Severity.CRITICAL,
                    observation=(
                        f"{ref.subject}: {len(unique)} preferred take(s) across "
                        f"{', '.join(ref.beat_ids)}. Nothing for the edit to "
                        "reconcile."
                    ),
                    sources=sources,
                    locators=[Locator("continuity_ref", ref.ref_id)]
                    + [Locator("take", t.take_id) for t in unique],
                    required_role=Role.SCRIPT_SUPERVISOR,
                    agent_version=AGENT_VERSION,
                    policy_version=policy_version,
                    package_revision=revision,
                )
            )
            continue

        worst = None
        for take_a, take_b in combinations(unique, 2):
            note_a = take_a.note or package.script_notes.get(take_a.take_id, "")
            note_b = take_b.note or package.script_notes.get(take_b.take_id, "")
            opinion = interpreter.compare_continuity(
                subject=ref.subject,
                established_state=ref.established_state,
                note_a=note_a,
                note_b=note_b,
            )
            if opinion.states_agree:
                continue
            if worst is None or opinion.confidence > worst[2].confidence:
                worst = (take_a, take_b, opinion)

        if worst is None:
            findings.append(
                Finding(
                    finding_id=f"{run_id}:con:{ref.ref_id}",
                    run_id=run_id,
                    scene_id=package.scene_id,
                    requirement_id=ref.ref_id,
                    check_type=CheckType.CONTINUITY,
                    truth_state=TruthState.VERIFIED,
                    severity=Severity.CRITICAL,
                    observation=(
                        f"{ref.subject}: {len(unique)} preferred takes read as the "
                        "same state against the established reference."
                    ),
                    sources=sources,
                    locators=[Locator("continuity_ref", ref.ref_id)]
                    + [Locator("take", t.take_id) for t in unique],
                    required_role=Role.SCRIPT_SUPERVISOR,
                    agent_version=AGENT_VERSION,
                    policy_version=policy_version,
                    package_revision=revision,
                )
            )
            continue

        take_a, take_b, opinion = worst
        conflicting = opinion.confidence >= MIN_CONFLICT_CONFIDENCE
        intentional = (
            " The variation may be intentional; that is a creative call and "
            "this check does not make it."
            if opinion.possibly_intentional
            else ""
        )
        findings.append(
            Finding(
                finding_id=f"{run_id}:con:{ref.ref_id}",
                run_id=run_id,
                scene_id=package.scene_id,
                requirement_id=ref.ref_id,
                check_type=CheckType.CONTINUITY,
                truth_state=(
                    TruthState.CONFLICTING if conflicting else TruthState.UNKNOWN
                ),
                severity=Severity.CRITICAL,
                observation=(
                    f"{ref.subject}: takes {take_a.take_id} and {take_b.take_id} are "
                    f"both flagged preferred and do not describe the same state. "
                    f"Established reference is: {ref.established_state}. "
                    f"{take_a.take_id} notes: {take_a.note or 'no note'}. "
                    f"{take_b.take_id} notes: {take_b.note or 'no note'}."
                ),
                inference=opinion.rationale + intentional,
                confidence=round(opinion.confidence, 3),
                sources=sources,
                locators=[
                    Locator("continuity_ref", ref.ref_id),
                    Locator("take", take_a.take_id),
                    Locator("take", take_b.take_id),
                ],
                required_role=Role.SCRIPT_SUPERVISOR,
                agent_version=AGENT_VERSION,
                policy_version=policy_version,
                package_revision=revision,
                recommended_action=(
                    "Decide which take is preferred, or confirm the variation was "
                    "intentional. Either way the edit stops being forced to guess."
                ),
            )
        )

    for finding in findings:
        validate(finding)
    return findings
