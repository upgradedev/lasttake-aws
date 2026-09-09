"""Coverage: which required beats have viable, evidence-backed footage.

The deterministic half asks whether any take claims this beat and whether that
take is usable. The model's half asks whether the take's slate, note and shot
description are plausibly *about* the beat, which is a language question a
regular expression cannot answer and a script supervisor answers instantly.

Where they disagree, the deterministic half wins on existence and the model's
half only downgrades. A model may turn a claimed cover into ``unknown``. It may
never turn an absent take into a cover. That asymmetry is the spine of the
product expressed as a control flow.
"""

from __future__ import annotations

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

AGENT_VERSION = "coverage/1.0.0"

#: Below this, the model is not confident enough for its opinion to stand as
#: evidence, and the beat becomes ``unknown``. Pinned here and asserted by a
#: fixture in the tests, so moving it moves both or fails.
MIN_MATCH_CONFIDENCE = 0.55


def _sources(package: ScenePackage) -> list[Source]:
    return [
        Source(
            artifact_id="script_revision",
            sha256=package.artifacts["script_revision"].sha256,
            kind="script",
        ),
        Source(
            artifact_id="takes", sha256=package.artifacts["takes"].sha256, kind="takes"
        ),
        Source(
            artifact_id="shot_plan",
            sha256=package.artifacts["shot_plan"].sha256,
            kind="plan",
        ),
    ]


def run(
    package: ScenePackage,
    run_id: str,
    interpreter: Interpreter,
    policy_version: str,
    only_beats: tuple[str, ...] | None = None,
) -> list[Finding]:
    """One finding per required beat. ``only_beats`` narrows a targeted rerun."""
    revision = package.revision_digest()
    sources = _sources(package)
    findings: list[Finding] = []

    for beat in package.required_beats:
        if only_beats is not None and beat.beat_id not in only_beats:
            continue

        takes = [t for t in package.takes_for_beat(beat.beat_id) if t.usable]
        planned = package.shots_for_beat(beat.beat_id)

        if not takes:
            planned_note = (
                "and it was never on the shot plan either"
                if not planned
                else f"although {planned[0].shot_id} planned for it"
            )
            findings.append(
                Finding(
                    finding_id=f"{run_id}:cov:{beat.beat_id}",
                    run_id=run_id,
                    scene_id=package.scene_id,
                    requirement_id=beat.beat_id,
                    check_type=CheckType.COVERAGE,
                    truth_state=TruthState.MISSING,
                    severity=Severity.CRITICAL,
                    observation=(
                        f"No usable take names beat {beat.beat_id} "
                        f"({beat.slug}), {planned_note}."
                    ),
                    sources=sources,
                    locators=[
                        Locator("script_page", beat.page),
                        Locator("script_line", str(beat.line)),
                    ],
                    required_role=Role.SCRIPT_SUPERVISOR,
                    agent_version=AGENT_VERSION,
                    policy_version=policy_version,
                    package_revision=revision,
                    recommended_action=(
                        f"Draft a pickup request for {beat.beat_id} while the set "
                        "is still standing. The 1st AD decides."
                    ),
                )
            )
            continue

        best = None
        for take in takes:
            shot = package.shots_for_beat(beat.beat_id)
            shot_description = shot[0].description if shot else ""
            match = interpreter.match_beat_to_take(
                beat_description=beat.description,
                take_slate=take.slate,
                take_note=take.note or package.script_notes.get(take.take_id, ""),
                shot_description=shot_description,
            )
            if match.covers and (best is None or match.confidence > best[1].confidence):
                best = (take, match)

        if best is None or best[1].confidence < MIN_MATCH_CONFIDENCE:
            take = takes[0]
            reading = best[1].rationale if best else "no take read as covering this beat"
            findings.append(
                Finding(
                    finding_id=f"{run_id}:cov:{beat.beat_id}",
                    run_id=run_id,
                    scene_id=package.scene_id,
                    requirement_id=beat.beat_id,
                    check_type=CheckType.COVERAGE,
                    truth_state=TruthState.UNKNOWN,
                    severity=Severity.CRITICAL,
                    observation=(
                        f"{len(takes)} take(s) name beat {beat.beat_id}, but the "
                        "match could not be established with enough confidence to "
                        "stand as evidence."
                    ),
                    inference=reading,
                    confidence=round(best[1].confidence, 3) if best else 0.0,
                    sources=sources,
                    locators=[Locator("take", take.take_id)],
                    required_role=Role.SCRIPT_SUPERVISOR,
                    agent_version=AGENT_VERSION,
                    policy_version=policy_version,
                    package_revision=revision,
                    recommended_action="Confirm by eye, or reject this as a false positive.",
                )
            )
            continue

        take, match = best
        findings.append(
            Finding(
                finding_id=f"{run_id}:cov:{beat.beat_id}",
                run_id=run_id,
                scene_id=package.scene_id,
                requirement_id=beat.beat_id,
                check_type=CheckType.COVERAGE,
                truth_state=TruthState.VERIFIED,
                severity=Severity.CRITICAL,
                observation=(
                    f"Take {take.take_id}, slate {take.slate}, "
                    f"{take.timecode_in} to {take.timecode_out}, covers "
                    f"beat {beat.beat_id}."
                ),
                inference=match.rationale,
                confidence=round(match.confidence, 3),
                sources=sources,
                locators=[
                    Locator("take", take.take_id),
                    Locator("timecode", take.timecode_in),
                    Locator("script_page", beat.page),
                ],
                required_role=Role.SCRIPT_SUPERVISOR,
                agent_version=AGENT_VERSION,
                policy_version=policy_version,
                package_revision=revision,
            )
        )

    for finding in findings:
        if finding.inference is not None:
            finding.model_id = interpreter.model_id
        validate(finding)
    return findings


def orphan_shots(package: ScenePackage, run_id: str, policy_version: str) -> list[Finding]:
    """Shots planned against beats the current revision no longer has.

    Advisory, not critical. An orphan shot does not stop a wrap; it tells the
    supervisor that the plan and the script have drifted, which is usually the
    first visible symptom of a revision nobody circulated.
    """
    revision = package.revision_digest()
    known = {b.beat_id for b in package.beats}
    findings: list[Finding] = []
    for shot in package.shots:
        missing = [b for b in shot.beat_ids if b not in known]
        if not missing:
            continue
        findings.append(
            Finding(
                finding_id=f"{run_id}:cov:orphan:{shot.shot_id}",
                run_id=run_id,
                scene_id=package.scene_id,
                requirement_id=None,
                check_type=CheckType.COVERAGE,
                truth_state=TruthState.UNKNOWN,
                severity=Severity.ADVISORY,
                observation=(
                    f"Shot {shot.shot_id} plans for {', '.join(missing)}, which the "
                    f"current revision {package.revision} does not contain."
                ),
                sources=_sources(package),
                locators=[Locator("shot", shot.shot_id)],
                required_role=Role.SCRIPT_SUPERVISOR,
                agent_version=AGENT_VERSION,
                policy_version=policy_version,
                package_revision=revision,
                recommended_action="Check the plan was rebuilt against the current revision.",
            )
        )
    for finding in findings:
        validate(finding)
    return findings
