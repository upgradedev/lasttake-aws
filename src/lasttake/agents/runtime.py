"""The run: one scene package, one correlation id, and everywhere state goes.

Holds no policy and makes no decisions. It exists so the tools stay short and
so that swapping the local adapters for the AWS ones changes one constructor
call rather than eight tool bodies.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from ..domain.events import Event, EventType
from ..domain.findings import Finding
from ..domain.package import ScenePackage
from ..domain import policy
from ..domain.findings import from_dict
from ..domain.sealing import digest_of, utc_now_iso
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
        self, event_type: EventType, payload: dict, idempotent: bool = False,
        delivery_batch: Optional[list[dict]] = None,
    ) -> Receipt:
        """Persist accepted receipts; retain ambiguous claims and retry rejections.

        A claim excludes concurrent publishers. It says nothing about delivery.
        The bus may accept a request without any downstream consumer completing it.
        """
        if delivery_batch is not None and (idempotent or event_type is not EventType.FINDING_RECORDED):
            raise ValueError("Only non-consequential finding notifications may batch receipts")
        started = time.perf_counter()
        event = self.build_event(event_type, payload)
        key = event.idempotency_key
        saved_key = f"delivery/{self.run_id.replace(':', '_')}/{key}.json"
        if idempotent and not self.runs.claim(key, self.run_id):
            if self.artifacts.exists(saved_key):
                return Receipt(**json.loads(self.artifacts.get(saved_key)))
            previous = next((d for d in self.delivery_states() if d["idempotency_key"] == key), None)
            status = "unknown" if previous and previous["status"] == "unknown" else "pending"
            return Receipt(False, key, "No saved acceptance receipt. Do not resend; reconcile this attempt.", status)
        detail = {"idempotency_key": key, "event_id": event.event_id,
                  "event_type": event_type.value, "payload": payload,
                  "package_revision_digest": self.package.revision_digest(),
                  "retry_supported": idempotent}
        if idempotent:
            self.audit("event.delivery", {**detail, "status": "pending", "accepted": False,
                                           "reference": event.event_id})
        try:
            receipt = self.bus.publish(event)
        except Exception:
            receipt = Receipt(False, event.event_id,
                              "External outcome unknown after an interrupted publish. Reconcile before any resend.", "unknown")
        if receipt.accepted and idempotent:
            try:
                self.artifacts.put(saved_key, json.dumps(receipt.to_dict(), sort_keys=True).encode())
            except Exception:
                receipt = Receipt(False, receipt.reference,
                                  "Bus response received but its receipt could not be saved. Reconcile before any resend.", "unknown")
        outcome = {**detail, **receipt.to_dict(),
                   "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}
        if delivery_batch is not None:
            delivery_batch.append(outcome)
        else:
            self.audit("event.delivery", outcome)
        if idempotent and receipt.outcome == "rejected":
            self.runs.release(key)
        return receipt

    def delivery_states(self) -> list[dict]:
        current = {}
        for entry in self.runs.load_audit(self.run_id):
            if entry.get("kind") == "event.delivery":
                current[entry["idempotency_key"]] = entry
            elif entry.get("kind") == "event.delivery.batch":
                for outcome in entry["outcomes"]:
                    current[outcome["idempotency_key"]] = {"at": entry["at"], **outcome}
        return list(current.values())

    def retry_delivery(self, key: str) -> Receipt:
        previous = next((row for row in self.delivery_states() if row["idempotency_key"] == key), None)
        if not previous or not previous.get("retry_supported"):
            raise ValueError("No retryable consequential attempt with that key on this run")
        if previous["status"] not in {"rejected", "accepted"}:
            raise ValueError("Pending or unknown delivery must be reconciled; do not resend")
        event_type = EventType(previous["event_type"])
        payload = previous["payload"]
        if event_type in {EventType.WRAP_READY, EventType.PICKUP_REQUESTED}:
            return self.publish_approved(event_type, payload)
        if event_type is EventType.TURNOVER_GENERATED:
            if not self.wrap_approved() or not self.wrap_guard(self.current_wrap_approval() or {}):
                raise ValueError("The current wrap approval is required before retrying a handoff")
            if previous["package_revision_digest"] != self.package.revision_digest():
                raise ValueError("The saved handoff belongs to a historical revision")
            return self.publish(event_type, payload, idempotent=True)
        raise ValueError("This event does not support explicit retry")

    def review_binding(self) -> dict:
        """The package, findings and decisions actually presented for review."""
        package_digest = self.package.revision_digest()
        return {"package_revision_digest": package_digest, "review_digest": digest_of({
            "package": package_digest, "policy": policy.POLICY_VERSION,
            "findings": sorted(self.load_findings(), key=lambda f: f["finding_id"]),
            "decisions": sorted(self.load_decisions(), key=lambda d: (d["at"], d["decision_id"])),
        })}

    def wrap_guard(self, reviewed: dict) -> bool:
        if reviewed.get("required_role") != policy.Role.FIRST_AD.value:
            return False
        binding = self.review_binding()
        if any(reviewed.get(key) != value for key, value in binding.items()):
            return False
        return policy.evaluate(self.run_id, self.package,
                               [from_dict(f) for f in self.load_findings()],
                               [policy.decision_from_dict(d) for d in self.load_decisions()]).eligible

    def publish_approved(self, event_type: EventType, payload: dict) -> Receipt:
        """Shared last check for a resumed tool and an explicit rejected retry."""
        if payload.get("approved_by_role") != policy.Role.FIRST_AD.value:
            return Receipt(False, "", "Only the 1st AD may answer this approval.", "refused")
        if event_type is EventType.WRAP_READY and not self.wrap_guard(payload):
            return Receipt(False, "", "Evidence changed. Decline the stale request and obtain a fresh review.", "refused")
        if event_type is EventType.WRAP_READY:
            latest = self.latest_wrap_review()
            if latest and (latest.get("kind") == "wrap.declined" or
                           latest.get("approval_id") != payload.get("approval_id")):
                return Receipt(False, "", "A later wrap review superseded this approval. Request a fresh review.", "refused")
        receipt = self.publish(event_type, payload, idempotent=True)
        if receipt.accepted:
            kind = "wrap.approved" if event_type is EventType.WRAP_READY else "pickup.approved"
            self.audit(kind, {**payload, "receipt": receipt.reference, "accepted": True})
        return receipt

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
        self.runs.append_audit(self.run_id, {"kind": kind, "at": utc_now_iso(), **detail})

    def wrap_approved(self) -> bool:
        return self.current_wrap_approval() is not None

    def current_wrap_approval(self) -> Optional[dict]:
        binding = self.review_binding()
        entry = self.latest_wrap_review()
        # Pending and declined reviews supersede authority, never history.
        if entry and entry.get("kind") == "wrap.approved":
            if all(entry.get(key) == value for key, value in binding.items()) and entry.get("accepted") is True:
                return entry
        return None

    def latest_wrap_review(self) -> Optional[dict]:
        for entry in reversed(self.runs.load_audit(self.run_id)):
            if entry.get("kind") in {"wrap.requested", "wrap.approved", "wrap.declined"}:
                return entry
        return None

    def wrap_approver(self) -> str:
        return (self.current_wrap_approval() or {}).get("actor", "1st AD")

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
