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


def _note_in_sentence(note: str | None) -> str:
    """A take note as quoted inside the observation, which closes it with a period.

    Supervisors end their notes with a full stop, and the observation adds its
    own after the quote, so a note read ``Good on the sit..`` on every surface
    that shows the finding. One trailing period is dropped, never more, so an
    ellipsis the supervisor wrote still reads as one.
    """
    text = (note or "").rstrip()
    if not text:
        return "no note"
    return text[:-1] if text.endswith(".") else text


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

        # Compare preferred takes of the SAME beat, never across beats.
        #
        # A continuity reference spans the beats where the thing is on screen,
        # and across those beats the state is *supposed* to change: she takes
        # the mug, she holds it, she drinks. Comparing a take of "she takes the
        # mug" against a take of "she puts it down" reports the scene working
        # as written as a continuity error, and a check that does that gets
        # switched off inside one shoot day.
        #
        # The conflict that actually constrains the edit is two preferred takes
        # of one beat that disagree, because whoever cuts it has to choose.
        pairs: list[tuple] = []
        unique: list = []
        for beat_id in ref.beat_ids:
            in_beat = [
                take
                for take in package.takes_for_beat(beat_id)
                if take.preferred and take.usable
            ]
            for take in in_beat:
                if take.take_id not in {t.take_id for t in unique}:
                    unique.append(take)
            pairs.extend(combinations(in_beat, 2))

        if not pairs:
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
                        f"{ref.subject}: no beat across {', '.join(ref.beat_ids)} "
                        f"has two preferred takes ({len(unique)} preferred in "
                        "total). The edit is never forced to choose."
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
        for take_a, take_b in pairs:
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
                        f"{ref.subject}: every pair of preferred takes of the same "
                        "beat reads as the same state against the established "
                        "reference."
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
                    f"{take_a.take_id} notes: {_note_in_sentence(take_a.note)}. "
                    f"{take_b.take_id} notes: {_note_in_sentence(take_b.note)}."
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
        if finding.inference is not None:
            finding.model_id = interpreter.model_id
        validate(finding)
    return findings
