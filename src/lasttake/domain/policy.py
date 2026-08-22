"""The deterministic eligibility gate.

This module is the one place where results are combined into an answer, and it
contains no model call, no heuristic and no randomness. Given the same findings
and the same decisions it returns the same packet, forever.

That is not an aesthetic preference. A model that can be argued into a pass
under wrap pressure is worse than no check at all, because it produces the
confidence without the evidence. So the model's job ends at the finding, and
the arithmetic starts here.

It fails closed in every direction:

* a check that produced no result is not a pass, it is a missing result
* a check that produced two results is not a pass, it is a contradiction
* a finding written against an older package revision is not reused
* a finding whose seal does not verify is discarded
* an exception that no authorised human has looked at is not a pass

``wrap.eligible`` is an eligibility result. It is not permission to wrap. Only
the 1st AD can do that, and this module has no way to express it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .findings import CheckType, Finding, Role, Severity, TruthState
from .package import ScenePackage
from .sealing import seal, utc_now_iso

#: Bumped whenever the rules below change. Every finding and every packet
#: records the version that judged it, so an old decision stays explainable
#: after the policy moves on.
POLICY_VERSION = "1.0.0"


class DecisionAction(str, Enum):
    """What a human did about a finding.

    ``REJECT_FALSE_POSITIVE`` does not delete or rewrite the finding. The
    original observation stays exactly as the check recorded it and the
    rejection sits beside it, because a supervisor overruling a check is itself
    a fact editorial may need later.
    """

    CONFIRM = "confirm"
    REJECT_FALSE_POSITIVE = "reject_false_positive"
    ACCEPT_EXCEPTION = "accept_exception"


#: Which role may take which action. A DIT may resolve a media identity
#: question and may not accept a rights exception; a coordinator may do the
#: reverse. Least privilege, expressed as a table rather than as an if.
AUTHORITY: dict[CheckType, set[Role]] = {
    CheckType.COVERAGE: {Role.SCRIPT_SUPERVISOR},
    CheckType.CONTINUITY: {Role.SCRIPT_SUPERVISOR},
    CheckType.METADATA: {Role.DIT},
    CheckType.RIGHTS: {Role.PRODUCTION_COORDINATOR},
}

#: Accepting an exception is a stronger act than confirming a finding, so it is
#: restricted further. Nobody may accept away a missing release; that decision
#: belongs to production and counsel, off this system.
MAY_ACCEPT_EXCEPTION: dict[CheckType, set[Role]] = {
    CheckType.COVERAGE: {Role.SCRIPT_SUPERVISOR},
    CheckType.CONTINUITY: {Role.SCRIPT_SUPERVISOR},
    CheckType.METADATA: {Role.DIT},
    CheckType.RIGHTS: set(),
}


@dataclass(frozen=True)
class HumanDecision:
    decision_id: str
    finding_id: str
    action: DecisionAction
    actor: str
    role: Role
    reason: str
    at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "finding_id": self.finding_id,
            "action": self.action.value,
            "actor": self.actor,
            "role": self.role.value,
            "reason": self.reason,
            "at": self.at,
        }


@dataclass(frozen=True)
class ExpectedCheck:
    """A check the gate insists on seeing a result for.

    Derived from the package, not from what the agents happened to return. If
    the coverage agent crashes, its checks still appear here, find no result,
    and the scene is ineligible. An agent cannot make a requirement disappear
    by failing to look at it.
    """

    check_type: CheckType
    requirement_id: str
    severity: Severity


def expected_checks(package: ScenePackage) -> list[ExpectedCheck]:
    """Every check that must have exactly one current result."""
    checks: list[ExpectedCheck] = []
    for beat in package.required_beats:
        checks.append(ExpectedCheck(CheckType.COVERAGE, beat.beat_id, Severity.CRITICAL))
    for ref in package.continuity_refs:
        checks.append(ExpectedCheck(CheckType.CONTINUITY, ref.ref_id, Severity.CRITICAL))
    for take in package.takes:
        checks.append(ExpectedCheck(CheckType.METADATA, take.take_id, Severity.CRITICAL))
    for subject_id, _kind in package.subjects_in_scene():
        checks.append(ExpectedCheck(CheckType.RIGHTS, subject_id, Severity.CRITICAL))
    return checks


@dataclass
class Cause:
    """One reason the scene is not eligible, in a form a human can act on."""

    check_type: CheckType
    requirement_id: str
    reason: str
    truth_state: Optional[TruthState]
    required_role: Role
    finding_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "check_type": self.check_type.value,
            "requirement_id": self.requirement_id,
            "reason": self.reason,
            "truth_state": self.truth_state.value if self.truth_state else None,
            "required_role": self.required_role.value,
            "finding_id": self.finding_id,
        }


@dataclass
class EligibilityPacket:
    """What the gate emits. An eligibility result, never an authority."""

    run_id: str
    scene_id: str
    package_revision: str
    policy_version: str
    eligible: bool
    causes: list[Cause]
    counts: dict
    discarded: list[str]
    at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "scene_id": self.scene_id,
            "package_revision": self.package_revision,
            "policy_version": self.policy_version,
            "eligible": self.eligible,
            "causes": [c.to_dict() for c in self.causes],
            "counts": self.counts,
            "discarded_findings": self.discarded,
            "note": (
                "Eligibility is an arithmetic result over evidence. It is not "
                "approval to wrap, and it is not a statement that the scene is "
                "legally cleared, safe or creatively complete."
            ),
            "at": self.at,
        }

    def sealed(self) -> dict:
        return seal(self.to_dict())


def _admissible(
    findings: list[Finding], package_revision: str
) -> tuple[list[Finding], list[str]]:
    """Drop findings the gate must not rely on, and say which and why."""
    kept: list[Finding] = []
    discarded: list[str] = []
    for finding in findings:
        if finding.package_revision != package_revision:
            discarded.append(
                f"{finding.finding_id}: written against revision "
                f"{finding.package_revision}, current is {package_revision}"
            )
            continue
        if finding.policy_version != POLICY_VERSION:
            discarded.append(
                f"{finding.finding_id}: judged under policy {finding.policy_version}, "
                f"current is {POLICY_VERSION}"
            )
            continue
        kept.append(finding)
    return kept, discarded


def evaluate(
    run_id: str,
    package: ScenePackage,
    findings: list[Finding],
    decisions: list[HumanDecision],
) -> EligibilityPacket:
    """Combine findings and human decisions into an eligibility packet."""
    revision = package.revision_digest()
    admissible, discarded = _admissible(findings, revision)

    by_check: dict[tuple[CheckType, str], list[Finding]] = {}
    for finding in admissible:
        if finding.requirement_id is None:
            continue
        by_check.setdefault((finding.check_type, finding.requirement_id), []).append(finding)

    decisions_by_finding: dict[str, list[HumanDecision]] = {}
    for decision in decisions:
        decisions_by_finding.setdefault(decision.finding_id, []).append(decision)

    causes: list[Cause] = []
    verified_beats = 0
    exception_beats = 0
    rights_gaps = 0
    media_exceptions = 0
    continuity_exceptions = 0

    for check in expected_checks(package):
        key = (check.check_type, check.requirement_id)
        results = by_check.get(key, [])
        role = _role_for(check.check_type)

        if not results:
            causes.append(
                Cause(
                    check.check_type,
                    check.requirement_id,
                    "no current result for a required check. Absent evidence is a "
                    "finding, never a pass.",
                    None,
                    role,
                )
            )
            # Deliberately not tallied as a beat exception as well. It is
            # already a cause, and counting it twice would inflate the headline
            # numbers with the same problem reported under two names.
            continue

        if len(results) > 1:
            causes.append(
                Cause(
                    check.check_type,
                    check.requirement_id,
                    f"{len(results)} current results for one check. Sources disagree "
                    "about what was even measured.",
                    None,
                    role,
                )
            )
            continue

        finding = results[0]
        finding_decisions = decisions_by_finding.get(finding.finding_id, [])

        if finding.truth_state is TruthState.VERIFIED:
            if check.check_type is CheckType.COVERAGE:
                verified_beats += 1
            continue

        # Everything below here is an exception.
        if check.check_type is CheckType.COVERAGE:
            exception_beats += 1
        elif check.check_type is CheckType.CONTINUITY:
            continuity_exceptions += 1
        elif check.check_type is CheckType.METADATA:
            media_exceptions += 1
        elif check.check_type is CheckType.RIGHTS:
            rights_gaps += 1

        resolution = _resolution(finding, finding_decisions)
        if resolution is None:
            causes.append(
                Cause(
                    check.check_type,
                    check.requirement_id,
                    f"{finding.truth_state.value}, and no authorised human has "
                    "triaged it yet",
                    finding.truth_state,
                    finding.required_role,
                    finding.finding_id,
                )
            )
        elif resolution is False:
            causes.append(
                Cause(
                    check.check_type,
                    check.requirement_id,
                    f"{finding.truth_state.value}, confirmed by "
                    f"{finding.required_role.value} and not resolved",
                    finding.truth_state,
                    finding.required_role,
                    finding.finding_id,
                )
            )

    counts = {
        "required_beats": len(package.required_beats),
        "beats_covered_with_evidence": verified_beats,
        "beats_raising_exceptions": exception_beats,
        "subjects_without_release_record": rights_gaps,
        "continuity_exceptions": continuity_exceptions,
        "media_identity_exceptions": media_exceptions,
        "findings_admitted": len(admissible),
        "findings_discarded": len(discarded),
    }

    return EligibilityPacket(
        run_id=run_id,
        scene_id=package.scene_id,
        package_revision=revision,
        policy_version=POLICY_VERSION,
        eligible=not causes,
        causes=causes,
        counts=counts,
        discarded=discarded,
    )


def _role_for(check_type: CheckType) -> Role:
    return {
        CheckType.COVERAGE: Role.SCRIPT_SUPERVISOR,
        CheckType.CONTINUITY: Role.SCRIPT_SUPERVISOR,
        CheckType.METADATA: Role.DIT,
        CheckType.RIGHTS: Role.PRODUCTION_COORDINATOR,
    }[check_type]


def _resolution(finding: Finding, decisions: list[HumanDecision]) -> Optional[bool]:
    """Has an authorised human closed this exception?

    Returns True when it is resolved, False when a human looked and it stands,
    and None when nobody with the authority has looked at all. Unauthorised
    decisions are ignored entirely rather than downgraded, because a decision
    taken by the wrong role is not weak evidence, it is no evidence.
    """
    looked = False
    for decision in decisions:
        allowed = AUTHORITY.get(finding.check_type, set())
        if decision.role not in allowed:
            continue
        looked = True
        if decision.action is DecisionAction.REJECT_FALSE_POSITIVE:
            return True
        if decision.action is DecisionAction.ACCEPT_EXCEPTION:
            if decision.role in MAY_ACCEPT_EXCEPTION.get(finding.check_type, set()):
                return True
            # An accept from a role that may confirm but may not accept counts
            # only as having looked.
            continue
    return False if looked else None


def authority_check(check_type: CheckType, action: DecisionAction, role: Role) -> bool:
    """True when ``role`` may take ``action`` on a finding of ``check_type``."""
    if role not in AUTHORITY.get(check_type, set()):
        return False
    if action is DecisionAction.ACCEPT_EXCEPTION:
        return role in MAY_ACCEPT_EXCEPTION.get(check_type, set())
    return True
