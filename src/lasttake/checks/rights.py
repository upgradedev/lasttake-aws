"""Rights and consent records: is every visible subject traceable to a record.

Record linkage, not legal reasoning. This check answers whether the expected
record exists, whether its structured fields satisfy the configured policy, and
whether it has expired. It does not answer whether a use is lawful, and there
is no code path in this repository that can produce that answer.

``verified`` here has a narrow, stated meaning, repeated on the face of the
turnover packet so a reader cannot pick it up as something larger: the record
was found and its fields matched. Counsel determines sufficiency.

No model touches this file either. Whether a ledger contains a row for BG-07 is
a lookup, and a lookup that sometimes hallucinates a row is a liability.
"""

from __future__ import annotations

from datetime import date

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

AGENT_VERSION = "rights/1.0.0"

#: What a record has to say before this check will call it verified. Widening
#: this set is a policy change and moves POLICY_VERSION, never a quiet edit.
REQUIRED_SCOPE = "all media"
ACCEPTED_STATUS = {"executed"}


def run(
    package: ScenePackage,
    run_id: str,
    policy_version: str,
    as_of: date | None = None,
    only_subjects: tuple[str, ...] | None = None,
) -> list[Finding]:
    revision = package.revision_digest()
    today = as_of or date(2026, 8, 19)
    sources = [
        Source(
            artifact_id="rights_ledger",
            sha256=package.artifacts["rights_ledger"].sha256,
            kind="ledger",
        ),
        Source(artifact_id="takes", sha256=package.artifacts["takes"].sha256, kind="takes"),
    ]
    findings: list[Finding] = []

    for subject_id, subject_kind in package.subjects_in_scene():
        if only_subjects is not None and subject_id not in only_subjects:
            continue

        appears_in = [
            t.take_id
            for t in package.takes
            if t.usable
            and (subject_id in t.visible_people or subject_id in t.visible_assets)
        ]
        records = package.rights_for(subject_id)

        if not records:
            findings.append(
                _finding(
                    subject_id,
                    run_id,
                    package,
                    TruthState.MISSING,
                    f"{subject_kind} {subject_id} is visible in "
                    f"{', '.join(appears_in)} and has no record in the rights "
                    "ledger. Absent evidence is a finding, not a pass.",
                    [Locator("take", t) for t in appears_in]
                    + [Locator("ledger_subject", subject_id)],
                    sources,
                    policy_version,
                    revision,
                    "Route to the production coordinator. Counsel determines legal "
                    "sufficiency; this system only reports that the record is absent.",
                )
            )
            continue

        usable_records = []
        problems = []
        for record in records:
            if record.status not in ACCEPTED_STATUS:
                problems.append(f"{record.record_id} status is {record.status}")
                continue
            if record.scope != REQUIRED_SCOPE:
                problems.append(
                    f"{record.record_id} scope is {record.scope}, policy requires "
                    f"{REQUIRED_SCOPE}"
                )
                continue
            if record.expires_on and date.fromisoformat(record.expires_on) < today:
                problems.append(f"{record.record_id} expired on {record.expires_on}")
                continue
            usable_records.append(record)

        if not usable_records:
            findings.append(
                _finding(
                    subject_id,
                    run_id,
                    package,
                    TruthState.CONFLICTING,
                    f"{subject_kind} {subject_id} has {len(records)} record(s), none "
                    "of which satisfy the configured policy: " + "; ".join(problems) + ".",
                    [Locator("ledger_record", r.record_id) for r in records],
                    sources,
                    policy_version,
                    revision,
                    "Route to the production coordinator.",
                )
            )
            continue

        record = usable_records[0]
        findings.append(
            _finding(
                subject_id,
                run_id,
                package,
                TruthState.VERIFIED,
                f"{subject_kind} {subject_id}: record {record.record_id}, "
                f"{record.document_type}, scope {record.scope}, territory "
                f"{record.territory}, status {record.status}. Found and matched "
                "the configured fields. This is not a legal opinion.",
                [
                    Locator("ledger_record", record.record_id),
                    Locator("ledger_subject", subject_id),
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
    subject_id: str,
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
        finding_id=f"{run_id}:rights:{subject_id}",
        run_id=run_id,
        scene_id=package.scene_id,
        requirement_id=subject_id,
        check_type=CheckType.RIGHTS,
        truth_state=state,
        severity=Severity.CRITICAL,
        observation=observation,
        sources=sources,
        locators=locators,
        required_role=Role.PRODUCTION_COORDINATOR,
        agent_version=AGENT_VERSION,
        policy_version=policy_version,
        package_revision=revision,
        confidence=1.0,
        recommended_action=action,
    )
