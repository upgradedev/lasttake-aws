"""The EventBridge subscriber records delivery once and has no outward effect."""

from __future__ import annotations

import copy
from io import BytesIO
import inspect
import json
from types import SimpleNamespace
import uuid

from botocore.exceptions import ClientError
import pytest

from lasttake.adapters.aws import event_consumer as consumer
from lasttake.adapters.aws.infrastructure import consumption_prefix
from lasttake.domain.events import Event, EventType


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.puts: list[dict] = []

    def put_object(self, **request):
        self.puts.append(request)
        if request.get("IfNoneMatch") == "*" and request["Key"] in self.objects:
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "PutObject",
            )
        self.objects[request["Key"]] = request["Body"]
        return {"ETag": "receipt"}

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[Key])}

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        client = self

        class Paginator:
            def paginate(self, *, Bucket, Prefix):
                return [{"Contents": [
                    {"Key": key} for key in sorted(client.objects) if key.startswith(Prefix)
                ]}]

        return Paginator()


def delivered_event() -> dict:
    domain = Event(
        event_type=EventType.WRAP_CHECKPOINT_REQUESTED,
        production_id="PROD-042",
        scene_id="SC-042",
        payload={"requested_by_role": "script_supervisor", "scene_id": "SC-042"},
        actor="orchestrator",
        correlation_id="demo-event-proof",
    )
    return {
        "version": "0",
        "id": str(uuid.uuid4()),
        "detail-type": domain.event_type.value,
        "source": consumer.SOURCE,
        "account": "000000000000",
        "time": "2026-09-14T20:00:00Z",
        "region": "eu-west-1",
        "resources": [],
        "detail": domain.to_dict(),
    }


def test_valid_delivery_creates_one_content_bound_receipt(monkeypatch):
    monkeypatch.setenv("LASTTAKE_COMMIT_SHA", "a" * 40)
    event = delivered_event()
    s3 = FakeS3()
    result = consumer.record(
        event,
        SimpleNamespace(aws_request_id="lambda-request-1"),
        bucket="private-data",
        client=s3,
        now=lambda: "2026-09-14T20:00:01+00:00",
    )

    expected_key = (
        consumption_prefix(event["detail"]["correlation_id"])
        + event["detail"]["event_id"]
        + ".json"
    )
    assert len(s3.puts) == 1
    assert s3.puts[0]["Key"] == expected_key
    assert s3.puts[0]["IfNoneMatch"] == "*"
    assert result["write_status"] == "recorded"
    saved = json.loads(s3.objects[expected_key])
    assert saved["schema"] == "lasttake/eventbridge-consumption/v1"
    assert saved["subscriber"] == "eventbridge-delivery-recorder/v1"
    assert saved["event_id"] == event["detail"]["event_id"]
    assert saved["eventbridge_event_id"] == event["id"]
    assert saved["deployed_sha"] == "a" * 40
    assert len(saved["detail_sha256"]) == 64
    assert "payload" not in saved


def test_duplicate_delivery_returns_the_first_receipt_without_overwrite(monkeypatch):
    monkeypatch.setenv("LASTTAKE_COMMIT_SHA", "b" * 40)
    event = delivered_event()
    s3 = FakeS3()
    first = consumer.record(
        event, SimpleNamespace(aws_request_id="first"), bucket="data", client=s3,
        now=lambda: "2026-09-14T20:00:01+00:00",
    )
    key = s3.puts[0]["Key"]
    original = s3.objects[key]

    duplicate = consumer.record(
        event, SimpleNamespace(aws_request_id="second"), bucket="data", client=s3,
        now=lambda: "2026-09-14T20:01:00+00:00",
    )
    assert duplicate["write_status"] == "already-recorded"
    assert duplicate["lambda_request_id"] == "first"
    assert duplicate["consumed_at"] == first["consumed_at"]
    assert s3.objects[key] == original


def test_same_domain_id_with_different_transport_identity_is_not_hidden(monkeypatch):
    monkeypatch.setenv("LASTTAKE_COMMIT_SHA", "c" * 40)
    event = delivered_event()
    s3 = FakeS3()
    consumer.record(event, SimpleNamespace(aws_request_id="first"), bucket="data", client=s3)
    changed = copy.deepcopy(event)
    changed["id"] = str(uuid.uuid4())
    with pytest.raises(ValueError, match="different event bytes"):
        consumer.record(changed, SimpleNamespace(aws_request_id="second"), bucket="data", client=s3)


@pytest.mark.parametrize("fault", [
    "source", "unknown-type", "mismatched-type", "schema", "event-id", "payload", "idempotency",
])
def test_untrusted_or_inconsistent_envelope_is_rejected_before_storage(monkeypatch, fault):
    monkeypatch.setenv("LASTTAKE_COMMIT_SHA", "d" * 40)
    event = delivered_event()
    if fault == "source":
        event["source"] = "untrusted.publisher"
    elif fault == "unknown-type":
        event["detail-type"] = event["detail"]["event_type"] = "unknown.event"
    elif fault == "mismatched-type":
        event["detail-type"] = EventType.TAKE_CAPTURED.value
    elif fault == "schema":
        event["detail"]["schema_version"] = "2.0.0"
    elif fault == "event-id":
        event["detail"]["event_id"] = "../../receipt"
    elif fault == "payload":
        event["detail"]["payload"] = "not-an-object"
    else:
        event["detail"]["idempotency_key"] = "0" * 64
    s3 = FakeS3()
    with pytest.raises(ValueError):
        consumer.record(event, SimpleNamespace(aws_request_id="request"), bucket="data", client=s3)
    assert s3.puts == []


def test_lambda_entrypoint_uses_only_the_configured_bucket(monkeypatch):
    monkeypatch.setenv("LASTTAKE_BUCKET", "configured-data")
    monkeypatch.setenv("LASTTAKE_COMMIT_SHA", "e" * 40)
    s3 = FakeS3()
    monkeypatch.setattr("boto3.client", lambda service: s3 if service == "s3" else None)
    result = consumer.handler(delivered_event(), SimpleNamespace(aws_request_id="lambda"))
    assert result["write_status"] == "recorded"
    assert {request["Bucket"] for request in s3.puts} == {"configured-data"}


def test_terminal_consumer_has_no_event_publish_path():
    source = inspect.getsource(consumer)
    assert "put_events" not in source
    assert 'client("events")' not in source
    assert "build_orchestrator" not in source


def test_aws_bus_reads_only_receipts_for_the_requested_correlation():
    from lasttake.adapters.aws.infrastructure import EventBridgeBus

    s3 = FakeS3()
    event = delivered_event()
    correlation = event["detail"]["correlation_id"]
    wanted = {
        "event_id": event["detail"]["event_id"],
        "subscriber": consumer.SUBSCRIBER,
    }
    wanted_key = consumption_prefix(correlation) + wanted["event_id"] + ".json"
    s3.objects[wanted_key] = json.dumps(wanted).encode()
    s3.objects[consumption_prefix("some-other-run") + "other.json"] = b'{"event_id":"other"}'
    bus = EventBridgeBus(
        "bus", "bucket", events_client=SimpleNamespace(), s3_client=s3
    )
    assert bus.consumption_receipts(correlation) == {wanted["event_id"]: wanted}
