"""Record proof that EventBridge delivered a LastTake event to a subscriber.

This Lambda is deliberately a terminal consumer. It validates the envelope and
writes one immutable receipt; it never publishes an event or starts the
orchestrator. EventBridge and Lambda may both deliver more than once, so the S3
conditional create is the idempotency boundary.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from botocore.exceptions import ClientError

from ...domain.events import EventType, SCHEMA_VERSION
from ...domain.sealing import digest_of
from .infrastructure import consumption_prefix

SOURCE = "lasttake.orchestrator"
RECEIPT_SCHEMA = "lasttake/eventbridge-consumption/v1"
SUBSCRIBER = "eventbridge-delivery-recorder/v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: Any, field: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{field} must be a non-empty string of at most {limit} characters")
    return value


def _uuid(value: Any, field: str) -> str:
    text = _required_text(value, field, 36)
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc
    if str(parsed) != text:
        raise ValueError(f"{field} must use canonical lowercase UUID form")
    return text


def validate(event: dict) -> dict:
    """Return the domain detail only for an internally consistent event."""
    if not isinstance(event, dict) or event.get("source") != SOURCE:
        raise ValueError("EventBridge source is not the LastTake orchestrator")
    _uuid(event.get("id"), "EventBridge event id")
    detail_type = _required_text(event.get("detail-type"), "detail-type")
    try:
        EventType(detail_type)
    except ValueError as exc:
        raise ValueError("detail-type is not a LastTake event type") from exc

    detail = event.get("detail")
    if not isinstance(detail, dict):
        raise ValueError("EventBridge detail must be an object")
    if detail.get("event_type") != detail_type:
        raise ValueError("detail-type does not match detail.event_type")
    if detail.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported LastTake event schema")
    _uuid(detail.get("event_id"), "detail.event_id")
    for field in ("production_id", "scene_id", "correlation_id", "actor"):
        _required_text(detail.get(field), f"detail.{field}")
    if not isinstance(detail.get("payload"), dict):
        raise ValueError("detail.payload must be an object")

    expected = digest_of({
        "event_type": detail_type,
        "production_id": detail["production_id"],
        "scene_id": detail["scene_id"],
        "payload": detail["payload"],
        "correlation_id": detail["correlation_id"],
    })
    supplied = detail.get("idempotency_key")
    if not isinstance(supplied, str) or not SHA256.fullmatch(supplied) or supplied != expected:
        raise ValueError("detail.idempotency_key does not match the event content")
    return detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_receipt(client, bucket: str, key: str) -> dict:
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    try:
        return json.loads(body.read().decode("utf-8"))
    finally:
        body.close()


def record(
    event: dict,
    context: Any,
    *,
    bucket: str,
    client,
    now: Callable[[], str] = _now,
) -> dict:
    """Validate and conditionally create one immutable consumption receipt."""
    detail = validate(event)
    key = f"{consumption_prefix(detail['correlation_id'])}{detail['event_id']}.json"
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "subscriber": SUBSCRIBER,
        "event_id": detail["event_id"],
        "event_type": detail["event_type"],
        "correlation_id": detail["correlation_id"],
        "eventbridge_event_id": event["id"],
        "eventbridge_time": _required_text(event.get("time"), "EventBridge time"),
        "detail_sha256": digest_of(detail),
        "consumed_at": now(),
        "lambda_request_id": _required_text(
            getattr(context, "aws_request_id", None), "Lambda request id"
        ),
        "deployed_sha": _required_text(
            os.environ.get("LASTTAKE_COMMIT_SHA"), "deployed SHA", 64
        ),
    }
    data = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code not in {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"} \
                or status not in {409, 412}:
            raise
        previous = _read_receipt(client, bucket, key)
        identity = ("event_id", "event_type", "correlation_id", "eventbridge_event_id", "detail_sha256")
        if any(previous.get(field) != receipt[field] for field in identity):
            raise ValueError("existing consumption receipt belongs to different event bytes") from exc
        return {**previous, "write_status": "already-recorded"}
    return {**receipt, "write_status": "recorded"}


def handler(event: dict, context: Any) -> dict:
    """AWS Lambda entry point for the EventBridge target."""
    bucket = os.environ.get("LASTTAKE_BUCKET")
    if not bucket:
        raise RuntimeError("LASTTAKE_BUCKET must be set for the EventBridge consumer")
    import boto3

    return record(event, context, bucket=bucket, client=boto3.client("s3"))
