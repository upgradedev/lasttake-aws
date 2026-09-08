"""The run: one scene package, one correlation id, and everywhere state goes.

Holds no policy and makes no decisions. It exists so the tools stay short and
so that swapping the local adapters for the AWS ones changes one constructor
call rather than eight tool bodies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from ..domain.events import Event, EventType
from ..domain.findings import Finding
from ..domain.package import ScenePackage
from ..ports.infrastructure import ArtifactStore, EventBus, Receipt, RunStore
from ..ports.interpreter import Interpreter


@dataclass
class WrapRun:
    run_id: str
    correlation_id: str
    package: ScenePackage
    bus: EventBus
    artifacts: ArtifactStore
    runs: RunStore
    interpreter: Interpreter
    actor: str = "orchestrator"
    candidate_sha: Optional[str] = None

    # -- events -------------------------------------------------------------

    def build_event(self, event_type: EventType, payload: dict) -> Event:
        """One event on this run's correlation, not yet published."""
        return Event(
            event_type=event_type,
            production_id=self.package.production_id,
            scene_id=self.package.scene_id,
            payload=payload,
            actor=self.actor,
            correlation_id=self.correlation_id,
            source_digests={
                aid: art.sha256 for aid, art in sorted(self.package.artifacts.items())
            },
        )

    def publish(
        self, event_type: EventType, payload: dict, idempotent: bool = False
    ) -> Receipt:
        """Publish one event on this run's correlation.

        ``idempotent`` guards effects that must not happen twice. A tool that
        replays after an interrupt calls this again with the same payload; the
        derived key matches, and the second call returns the first receipt
        rather than firing a second pickup request at a tired 1st AD.
        """
        event = self.build_event(event_type, payload)
        if not idempotent:
            return self.bus.publish(event)

        # Claim, then publish, then give the claim back if the publish failed.
        #
        # The previous version asked `already_handled` and then `mark_handled`,
        # which is a check-then-set: two Lambdas resuming the same approval can
        # both read false and a real assistant director gets the pickup request
        # twice. It also marked the key *before* publishing, so a bus failure
        # left the key on file with nothing on the bus and no retry able to send
        # it. One lost event is worse than two duplicates on a set.
        #
        # This is at-most-once *claiming*. EventBridge delivery itself is
        # at-least-once and nothing here changes that, so a consumer still has
        # to be idempotent. What this guarantees is that exactly one caller
        # publishes a given event, and that a failure leaves the system able to
        # try again rather than silently short of one event.
        if not self.runs.claim(event.idempotency_key, self.run_id):
            return Receipt(
                accepted=True,
                reference=event.idempotency_key[:16],
                detail="already handled; not republished",
            )
        try:
            return self.bus.publish(event)
        except Exception:
            self.runs.release(event.idempotency_key)
            raise

    # -- findings and decisions --------------------------------------------

    def store_findings(self, findings: list[Finding]) -> None:
        self.runs.save_findings(self.run_id, [f.sealed() for f in findings])

    def load_findings(self) -> list[dict]:
        return self.runs.load_findings(self.run_id)

    def load_decisions(self) -> list[dict]:
        return self.runs.load_decisions(self.run_id)

    def record_decision(self, decision: dict) -> None:
        self.runs.save_decision(self.run_id, decision)

    # -- packets, turnover, audit ------------------------------------------

    def store_packet(self, packet: dict) -> None:
        self.runs.save_packet(self.run_id, packet)

    def load_packet(self) -> Optional[dict]:
        return self.runs.load_packet(self.run_id)

    def store_turnover(self, manifest: dict) -> str:
        key = f"turnover/{self.run_id.replace(':', '_')}.json"
        self.artifacts.put(
            key, json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        )
        return key

    def audit(self, kind: str, detail: dict) -> None:
        self.runs.append_audit(self.run_id, {"kind": kind, **detail})

    def wrap_approved(self) -> bool:
        return any(e.get("kind") == "wrap.approved" for e in self.runs.load_audit(self.run_id))

    def wrap_approver(self) -> str:
        for entry in self.runs.load_audit(self.run_id):
            if entry.get("kind") == "wrap.approved":
                return entry.get("actor", "1st AD")
        return "1st AD"

    def with_package(self, package: ScenePackage) -> "WrapRun":
        """A run over a new package revision, keeping the same correlation."""
        return WrapRun(
            run_id=self.run_id,
            correlation_id=self.correlation_id,
            package=package,
            bus=self.bus,
            artifacts=self.artifacts,
            runs=self.runs,
            interpreter=self.interpreter,
            actor=self.actor,
            candidate_sha=self.candidate_sha,
        )
