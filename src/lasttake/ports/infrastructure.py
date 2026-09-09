"""Event bus, artifact store and run state. Three ports, no vendor in sight.

``EventBus.publish`` returns a receipt rather than None on purpose. An external
effect with no receipt cannot be audited, and every external effect in this
system has to be.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from ..domain.events import Event, EventType


@dataclass(frozen=True)
class Receipt:
    """A bus response, never proof that a downstream target completed work."""

    accepted: bool
    reference: str
    detail: str = ""
    status: str = ""

    @property
    def outcome(self) -> str:
        return self.status or ("accepted" if self.accepted else "rejected")

    def to_dict(self) -> dict:
        return {"accepted": self.accepted, "reference": self.reference,
                "detail": self.detail, "status": self.outcome}


class EventBus(Protocol):
    def publish(self, event: Event) -> Receipt: ...

    def subscribe(self, event_types: tuple[EventType, ...], handler: Callable[[Event], None]) -> None: ...

    def health(self) -> str: ...


class ArtifactStore(Protocol):
    """Immutable, content-addressed. There is no update and no delete.

    Original media is never written by this system and never deleted by it.
    The store holds packages, findings, packets and turnovers.
    """

    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def url_for(self, key: str) -> Optional[str]: ...


class RunStore(Protocol):
    """Durable run state: findings, decisions, packets, and the seen-event set.

    ``already_handled`` is what makes duplicate delivery harmless. It is keyed
    on the event's derived idempotency key, not on its event_id, so the same
    fact delivered twice with two ids still collapses to one unit of work.
    """

    def already_handled(self, idempotency_key: str) -> bool: ...

    def mark_handled(self, idempotency_key: str, run_id: str) -> None: ...

    def claim(self, idempotency_key: str, run_id: str) -> bool:
        """Record the key and say whether *this* caller was the one that did it.

        One atomic step. ``already_handled`` followed by ``mark_handled`` is a
        check-then-set and two callers can both read false, however well the
        storage behaves, so a real assistant director gets the same pickup
        request twice.
        """
        ...

    def release(self, idempotency_key: str) -> None:
        """Give a claim back, for a caller that claimed and then failed to publish.

        Without this the pair is not idempotency, it is loss: the key is on
        file, the event never reached the bus, and no retry can ever send it.
        """
        ...

    def save_findings(self, run_id: str, findings: list[dict]) -> None: ...

    def load_findings(self, run_id: str) -> list[dict]: ...

    def save_decision(self, run_id: str, decision: dict) -> None: ...

    def load_decisions(self, run_id: str) -> list[dict]: ...

    def save_packet(self, run_id: str, packet: dict) -> None: ...

    def load_packet(self, run_id: str) -> Optional[dict]: ...

    def append_audit(self, run_id: str, entry: dict) -> None: ...

    def load_audit(self, run_id: str) -> list[dict]: ...
