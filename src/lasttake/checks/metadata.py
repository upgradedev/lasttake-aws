"""Metadata integrity: does the technical record reconcile with itself.

No model touches this file. Identifier equality, lens comparison and roll
matching are arithmetic, and arithmetic done by a language model is arithmetic
done badly and expensively. Every finding here carries confidence 1.0 because
a string either equals another string or it does not.

Where the take's sidecar and the camera report disagree, this check reports the
disagreement and stops. It does not decide which is authoritative. A DIT does
that, because the answer depends on what happened on the cart, and nothing in
these files records what happened on the cart.
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

AGENT_VERSION = "metadata/1.0.0"


def run(
    package: ScenePackage,
    run_id: str,
    policy_version: str,
    only_takes: tuple[str, ...] | None = None,
) -> list[Finding]:
    revision = package.revision_digest()
    sources = [
        Source(artifact_id="takes", sha256=package.artifacts["takes"].sha256, kind="takes"),
        Source(
            artifact_id="camera_report",
            sha256=package.artifacts["camera_report"].sha256,
            kind="report",
        ),
    ]
    findings: list[Finding] = []

    for take in package.takes:
        if only_takes is not None and take.take_id not in only_takes:
            continue
        row = package.camera_row(take.take_id)

        if row is None:
            findings.append(
                _finding(
                    take.take_id,
                    run_id,
                    package,
                    TruthState.MISSING,
                    f"Take {take.take_id} has no row in camera report "
                    f"{package.artifacts['camera_report'].payload.get('report_id')}. "
                    "There is no second record to reconcile against.",
                    [Locator("take", take.take_id)],
                    sources,
                    policy_version,
                    revision,
                    "Ask the DIT for the report row, or confirm the take was never carded.",
                )
            )
            continue

        mismatches = []
        if row.media_id != take.media_id:
            mismatches.append(
                f"media identifier: sidecar says {take.media_id}, camera report "
                f"says {row.media_id}"
            )
        if row.lens_mm != take.lens_mm:
            mismatches.append(
                f"lens: sidecar says {take.lens_mm}mm, camera report says {row.lens_mm}mm"
            )
        if row.camera_roll != take.camera_roll:
            mismatches.append(
                f"camera roll: sidecar says {take.camera_roll}, camera report "
                f"says {row.camera_roll}"
            )

        if mismatches:
            findings.append(
                _finding(
                    take.take_id,
                    run_id,
                    package,
                    TruthState.CONFLICTING,
                    f"Take {take.take_id} does not reconcile with its camera report "
                    f"row. " + "; ".join(mismatches) + ".",
                    [
                        Locator("take", take.take_id),
                        Locator("metadata_field", "media_id"),
                        Locator("camera_report_row", take.take_id),
                    ],
                    sources,
                    policy_version,
                    revision,
                    "The DIT confirms which record is authoritative. Until then the "
                    "media behind this take cannot be traced.",
                )
            )
            continue

        findings.append(
            _finding(
                take.take_id,
                run_id,
                package,
                TruthState.VERIFIED,
                f"Take {take.take_id} reconciles: media {take.media_id}, "
                f"{take.lens_mm}mm, roll {take.camera_roll}, sound {take.sound_roll}, "
                f"timecode {take.timecode_in}.",
                [
                    Locator("take", take.take_id),
                    Locator("media_id", take.media_id),
                    Locator("timecode", take.timecode_in),
                ],
                sources,
                policy_version,
                revision,
                None,
            )
        )

    for finding in findings:
        validate(finding)
    return findings


def _finding(
    take_id: str,
    run_id: str,
    package: ScenePackage,
    state: TruthState,
    observation: str,
    locators: list[Locator],
    sources: list[Source],
    policy_version: str,
    revision: str,
    action: str | None,
) -> Finding:
    return Finding(
        finding_id=f"{run_id}:meta:{take_id}",
        run_id=run_id,
        scene_id=package.scene_id,
        requirement_id=take_id,
        check_type=CheckType.METADATA,
        truth_state=state,
        severity=Severity.CRITICAL,
        observation=observation,
        sources=sources,
        locators=locators,
        required_role=Role.DIT,
        agent_version=AGENT_VERSION,
        policy_version=policy_version,
        package_revision=revision,
        # Deterministic comparison. There is no interpretation to record and
        # therefore no confidence below 1.0 to report.
        confidence=1.0,
        recommended_action=action,
    )
