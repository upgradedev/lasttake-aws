"""Join stored domain events to independently written subscriber receipts."""

from __future__ import annotations

from ..domain.sealing import digest_of


def _matches(row: dict, receipt: dict | None) -> bool:
    """A file in the receipt prefix is not enough to claim consumption."""
    return bool(
        isinstance(receipt, dict)
        and receipt.get("schema") == "lasttake/eventbridge-consumption/v1"
        and receipt.get("subscriber") == "eventbridge-delivery-recorder/v1"
        and receipt.get("event_id") == row.get("event_id")
        and receipt.get("event_type") == row.get("event_type")
        and receipt.get("correlation_id") == row.get("correlation_id")
        and receipt.get("detail_sha256") == digest_of(row)
        and isinstance(receipt.get("consumed_at"), str)
        and isinstance(receipt.get("eventbridge_event_id"), str)
        and isinstance(receipt.get("deployed_sha"), str)
    )


def view(rows: list[dict], receipts: dict[str, dict]) -> dict:
    """Build the public history without inferring failure from an absent receipt."""
    events = []
    consumed = 0
    for row in rows:
        receipt = receipts.get(row["event_id"])
        if _matches(row, receipt):
            consumed += 1
            delivery = {
                "status": "consumed",
                "subscriber": receipt["subscriber"],
                "consumed_at": receipt["consumed_at"],
                "eventbridge_event_id": receipt["eventbridge_event_id"],
                "deployed_sha": receipt["deployed_sha"],
            }
        else:
            # EventBridge is asynchronous. Absence is not evidence of failure.
            delivery = {"status": "not_observed"}
        events.append({
            "event_type": row["event_type"],
            "event_id": row["event_id"],
            "parent_event_id": row.get("parent_event_id"),
            "occurred_at": row["occurred_at"],
            "idempotency_key": row["idempotency_key"][:16],
            "payload": row["payload"],
            "eventbridge_delivery": delivery,
        })
    return {
        "events": events,
        "eventbridge_delivery": {
            "stored_event_count": len(events),
            "consumed_receipt_count": consumed,
            "scope": "current-correlation",
        },
    }
