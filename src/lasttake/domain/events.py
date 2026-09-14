"""The event envelope, and the twelve event types this system speaks.

The product's first architectural claim is that a real event starts the work,
not a button. That only means something if the envelope carries enough to make
a duplicate delivery harmless, so idempotency is in the shape of the event
rather than in the memory of whatever receives it.

On AWS these become EventBridge events. Nothing in this module knows that.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .sealing import digest_of, utc_now_iso

SCHEMA_VERSION = "1.0.0"


class EventType(str, Enum):
    #: ingest -> orchestrator. Establishes source identity and revision.
    SCENE_PACKAGE_REGISTERED = "scene.package.registered"
    #: capture -> orchestrator. New evidence, and the checks it affects.
    TAKE_CAPTURED = "take.captured"
    #: supervisor -> orchestrator. The primary trigger.
    WRAP_CHECKPOINT_REQUESTED = "scene.wrap-checkpoint.requested"
    #: adapter -> orchestrator. Late or fallback trigger.
    DAILIES_UPLOADED = "dailies.uploaded"
    #: orchestrator -> agents. Launches a versioned run.
    ANALYSIS_REQUESTED = "analysis.requested"
    #: each check -> gate, UI, audit.
    FINDING_RECORDED = "finding.recorded"
    #: gate -> role workflow. Asks one named human for one bounded decision.
    APPROVAL_REQUESTED = "approval.requested"
    #: approved tool -> adapter. A human-approved pickup.
    PICKUP_REQUESTED = "pickup.requested"
    #: rights flow -> orchestrator. Reruns only the affected checks.
    RIGHTS_RECORD_UPDATED = "rights.record.updated"
    #: gate -> 1st AD UI. An eligibility result, not final authority.
    WRAP_ELIGIBLE = "wrap.eligible"
    #: approved tool -> turnover service. Explicit human wrap approval.
    WRAP_READY = "wrap.ready"
    #: turnover -> editorial, audit.
    TURNOVER_GENERATED = "turnover.generated"


@dataclass
class Event:
    """One thing that happened, addressed so it can happen twice safely.

    ``idempotency_key`` is derived from the payload rather than generated, so
    the same take delivered twice by a flaky adapter collapses to one unit of
    work. ``causation_id`` and ``parent_event_id`` make the chain from trigger
    to turnover walkable after the fact, which is what an audit actually is.

    Nothing secret, no raw credential and no unnecessary personal data goes in
    here. Subjects are referenced by identifier and resolved elsewhere.
    """

    event_type: EventType
    production_id: str
    scene_id: str
    payload: dict
    actor: str
    correlation_id: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = SCHEMA_VERSION
    occurred_at: str = field(default_factory=utc_now_iso)
    ingested_at: Optional[str] = None
    parent_event_id: Optional[str] = None
    causation_id: Optional[str] = None
    source_digests: dict[str, str] = field(default_factory=dict)

    @property
    def idempotency_key(self) -> str:
        """Derived from what happened, not from when it was delivered."""
        return digest_of(
            {
                "event_type": self.event_type.value,
                "production_id": self.production_id,
                "scene_id": self.scene_id,
                "payload": self.payload,
                "correlation_id": self.correlation_id,
            }
        )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "schema_version": self.schema_version,
            "production_id": self.production_id,
            "scene_id": self.scene_id,
            "correlation_id": self.correlation_id,
            "actor": self.actor,
            "payload": self.payload,
            "occurred_at": self.occurred_at,
            "ingested_at": self.ingested_at,
            "parent_event_id": self.parent_event_id,
            "causation_id": self.causation_id,
            "source_digests": self.source_digests,
            "idempotency_key": self.idempotency_key,
        }

    def child(self, event_type: EventType, payload: dict, actor: str) -> "Event":
        """A follow-on event that keeps the chain intact."""
        return Event(
            event_type=event_type,
            production_id=self.production_id,
            scene_id=self.scene_id,
            payload=payload,
            actor=actor,
            correlation_id=self.correlation_id,
            parent_event_id=self.event_id,
            causation_id=self.event_id,
            source_digests=dict(self.source_digests),
        )


#: Which checks a given event can possibly have changed.
#:
#: This table is what makes the rerun targeted instead of total. A new release
#: record cannot change whether a beat was shot, so re-running coverage after
#: one is wasted model spend and wasted wall clock at the exact moment the crew
#: is standing around waiting.
AFFECTED_CHECKS: dict[EventType, tuple[str, ...]] = {
    EventType.TAKE_CAPTURED: ("coverage", "continuity", "metadata", "rights"),
    EventType.RIGHTS_RECORD_UPDATED: ("rights",),
    EventType.DAILIES_UPLOADED: ("metadata",),
    EventType.WRAP_CHECKPOINT_REQUESTED: ("coverage", "continuity", "metadata", "rights"),
    EventType.SCENE_PACKAGE_REGISTERED: ("coverage", "continuity", "metadata", "rights"),
}


def affected_by(event: Event) -> tuple[str, ...]:
    """Checks that must rerun because of this event. Empty means none."""
    return AFFECTED_CHECKS.get(event.event_type, ())
