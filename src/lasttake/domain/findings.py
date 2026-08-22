"""The finding contract, and the four truth states the whole product turns on.

A finding is what one bounded check observed about one requirement, tied to the
immutable sources it read. It is not an opinion and it is not a decision.

The four states are deliberately not two. ``pass`` and ``fail`` would let an
absent camera report and a reconciled one collapse into the same answer, and
that collapse is the failure this product exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .sealing import seal, utc_now_iso


class TruthState(str, Enum):
    """What a check concluded. Never ``pass``, ``clear`` or ``safe``.

    ``VERIFIED`` means the configured, bounded check was satisfied by evidence
    that is cited. It does not mean the scene is legally cleared, creatively
    complete or safe, and no code path may treat it as such.
    """

    VERIFIED = "verified"
    MISSING = "missing"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"

    @property
    def is_exception(self) -> bool:
        """Everything that is not ``verified`` is an exception.

        There is no fifth state meaning "probably fine". A timeout produces
        ``unknown``, which is an exception, not a success.
        """
        return self is not TruthState.VERIFIED


class CheckType(str, Enum):
    COVERAGE = "coverage"
    CONTINUITY = "continuity"
    METADATA = "metadata"
    RIGHTS = "rights"


class Severity(str, Enum):
    """Assigned by deterministic policy, never by a model."""

    CRITICAL = "critical"
    ADVISORY = "advisory"


class Role(str, Enum):
    SCRIPT_SUPERVISOR = "script_supervisor"
    FIRST_AD = "first_ad"
    DIT = "dit"
    PRODUCTION_COORDINATOR = "production_coordinator"
    ASSISTANT_EDITOR = "assistant_editor"


@dataclass(frozen=True)
class Source:
    """An immutable thing a check actually read.

    ``sha256`` is the digest of the artifact's bytes at the moment it was read.
    If the artifact changes, findings citing the old digest are stale and the
    gate rejects them rather than silently using them.
    """

    artifact_id: str
    sha256: str
    kind: str

    def to_dict(self) -> dict:
        return {"artifact_id": self.artifact_id, "sha256": self.sha256, "kind": self.kind}


@dataclass(frozen=True)
class Locator:
    """Where inside a source the observation sits.

    A finding without a locator is an assertion. With one, a script supervisor
    can open the page and look. ``value`` is free text because a locator is a
    line number in a script, a timecode in a take, a field name in a report and
    a clause in a ledger, and forcing those into one shape loses the meaning.
    """

    kind: str
    value: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "value": self.value}


@dataclass
class Finding:
    """One bounded observation about one requirement.

    ``observation`` is what was directly read from a source. ``inference`` is a
    model's bounded interpretation and is kept in a separate field on purpose,
    so a reader can always tell which is which. A finding may carry an
    observation and no inference; it may never carry an inference presented as
    an observation.
    """

    finding_id: str
    run_id: str
    scene_id: str
    requirement_id: Optional[str]
    check_type: CheckType
    truth_state: TruthState
    severity: Severity
    observation: str
    sources: list[Source]
    locators: list[Locator]
    required_role: Role
    agent_version: str
    policy_version: str
    package_revision: str
    inference: Optional[str] = None
    confidence: float = 1.0
    recommended_action: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "run_id": self.run_id,
            "scene_id": self.scene_id,
            "requirement_id": self.requirement_id,
            "check_type": self.check_type.value,
            "truth_state": self.truth_state.value,
            "severity": self.severity.value,
            "observation": self.observation,
            "inference": self.inference,
            "confidence": self.confidence,
            "sources": [s.to_dict() for s in self.sources],
            "locators": [locator.to_dict() for locator in self.locators],
            "recommended_action": self.recommended_action,
            "required_role": self.required_role.value,
            "agent_version": self.agent_version,
            "policy_version": self.policy_version,
            "package_revision": self.package_revision,
            "created_at": self.created_at,
        }

    def sealed(self) -> dict:
        return seal(self.to_dict())


class FindingContractError(ValueError):
    """A finding that does not meet the contract. It is dropped, never used."""


def validate(finding: Finding) -> None:
    """Reject a finding that cannot be traced back to something a human can open.

    This runs before the gate sees anything. A check that returns an
    unsupported claim is a defective check, and the right response is to drop
    the claim and let the gate see a missing result, which fails closed.
    """
    if not finding.finding_id or not finding.run_id:
        raise FindingContractError("finding_id and run_id are required")
    if not finding.sources:
        raise FindingContractError(
            f"{finding.finding_id}: no sources. A finding with nothing behind it "
            "is an opinion, and opinions do not reach the gate."
        )
    for source in finding.sources:
        if len(source.sha256) != 64:
            raise FindingContractError(
                f"{finding.finding_id}: source {source.artifact_id} has no usable digest"
            )
    # A verified state has to point at what satisfied it. Exceptions may lack a
    # locator, because the whole complaint can be that there is nothing to point at.
    if finding.truth_state is TruthState.VERIFIED and not finding.locators:
        raise FindingContractError(
            f"{finding.finding_id}: verified with no locator. Nothing to open."
        )
    if not 0.0 <= finding.confidence <= 1.0:
        raise FindingContractError(f"{finding.finding_id}: confidence out of range")
    if finding.inference is not None and finding.confidence == 1.0:
        raise FindingContractError(
            f"{finding.finding_id}: a model inference may not claim certainty. "
            "Deterministic results carry 1.0; interpretations do not."
        )


def from_dict(data: dict) -> Finding:
    """Rebuild a finding from storage. Used by the targeted rerun path."""
    return Finding(
        finding_id=data["finding_id"],
        run_id=data["run_id"],
        scene_id=data["scene_id"],
        requirement_id=data.get("requirement_id"),
        check_type=CheckType(data["check_type"]),
        truth_state=TruthState(data["truth_state"]),
        severity=Severity(data["severity"]),
        observation=data["observation"],
        sources=[Source(**s) for s in data["sources"]],
        locators=[Locator(**locator) for locator in data["locators"]],
        required_role=Role(data["required_role"]),
        agent_version=data["agent_version"],
        policy_version=data["policy_version"],
        package_revision=data["package_revision"],
        inference=data.get("inference"),
        confidence=data.get("confidence", 1.0),
        recommended_action=data.get("recommended_action"),
        created_at=data["created_at"],
    )
