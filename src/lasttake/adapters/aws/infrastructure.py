"""S3 and EventBridge behind the same three ports the offline adapters implement.

Nothing above these classes knows which one it is talking to. The domain, the
four checks and the deterministic gate are identical in both, which is the
point of the ports: the deployed build is not a different product with the same
name.

Why S3 for run state rather than a database. The whole run is a handful of small
JSON documents keyed by run id, written a few times per checkpoint and read on
each resume. S3 costs nothing at rest, scales to zero with no idle charge and no
cold start, and it is already required for the Strands session store and the
turnover artifacts. Aurora DSQL is in the architecture for the multi-scene,
multi-day case where a query across runs starts to matter, and it is honestly
not needed for one scene. Adding it now would be a service on the diagram rather
than a service doing work.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ...domain.events import Event, EventType
from ...ports.infrastructure import Receipt


def _missing_object(exc) -> bool:
    """Only an explicit object-not-found response is evidence of absence.

    A 403 may hide an existing object. Bucket errors, throttling and transport
    failures must not turn an ownership marker or saved state into a new record.
    Conflicting status/code pairs also fail closed.
    """
    return (exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey")
            and exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") in (None, 404))


class S3ArtifactStore:
    """Content-addressed and write-once. There is no update and no delete.

    A second write of the same key with different bytes raises rather than
    overwriting, because an artifact that can change is not a source a finding
    can cite.
    """

    def __init__(self, bucket: str, prefix: str = "artifacts/", client=None) -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix
        self._s3 = client or boto3.client("s3")

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def put(self, key: str, data: bytes) -> str:
        full = self._key(key)
        if self.exists(key):
            existing = self._s3.get_object(Bucket=self.bucket, Key=full)["Body"].read()
            if existing != data:
                raise ValueError(
                    f"{key} already exists with different content. Artifacts are "
                    "immutable; write a new revision instead."
                )
            return key
        self._s3.put_object(
            Bucket=self.bucket, Key=full, Body=data, ContentType="application/json"
        )
        return key

    def get(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except self._s3.exceptions.ClientError as exc:
            if _missing_object(exc):
                return False
            raise

    def url_for(self, key: str) -> Optional[str]:
        """A time-bounded link, never a public object.

        Turnover packets name people and describe a production. They are read by
        editorial, not by the internet, so the bucket stays private and access is
        a signed URL that expires.
        """
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(key)},
            ExpiresIn=3600,
        )


class S3RunStore:
    """Run state as small JSON documents under one prefix per run."""

    def __init__(self, bucket: str, prefix: str = "runs/", client=None) -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix
        self._s3 = client or boto3.client("s3")

    def _key(self, run_id: str, name: str) -> str:
        return f"{self.prefix}{run_id.replace(':', '_')}/{name}"

    def _read(self, key: str, default):
        try:
            body = self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self._s3.exceptions.ClientError as exc:
            if _missing_object(exc):
                return default
            raise
        return json.loads(body.decode("utf-8"))

    def _write(self, key: str, payload) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )

    # -- idempotency --------------------------------------------------------

    def _handled_key(self) -> str:
        return f"{self.prefix}_handled.json"

    def already_handled(self, idempotency_key: str) -> bool:
        return idempotency_key in self._read(self._handled_key(), {})

    def mark_handled(self, idempotency_key: str, run_id: str) -> None:
        seen = self._read(self._handled_key(), {})
        seen[idempotency_key] = run_id
        self._write(self._handled_key(), seen)

    def claim(self, idempotency_key: str, run_id: str) -> bool:
        if self.already_handled(idempotency_key):
            return False
        try:
            self._s3.put_object(Bucket=self.bucket,
                Key=f"{self.prefix}claims/{idempotency_key}.json",
                Body=json.dumps({"run_id": run_id}).encode(), IfNoneMatch="*")
            return True
        except self._s3.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("PreconditionFailed", "ConditionalRequestConflict", "412", "409"):
                return False
            raise

    def release(self, idempotency_key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=f"{self.prefix}claims/{idempotency_key}.json")

    # -- run state ----------------------------------------------------------

    def save_findings(self, run_id: str, findings: list[dict]) -> None:
        key = self._key(run_id, "findings.json")
        existing = {f["finding_id"]: f for f in self._read(key, [])}
        for finding in findings:
            existing[finding["finding_id"]] = finding
        self._write(key, sorted(existing.values(), key=lambda f: f["finding_id"]))

    def load_findings(self, run_id: str) -> list[dict]:
        return self._read(self._key(run_id, "findings.json"), [])

    def save_decision(self, run_id: str, decision: dict) -> None:
        key = self._key(run_id, "decisions.json")
        rows = self._read(key, [])
        rows.append(decision)
        self._write(key, rows)

    def load_decisions(self, run_id: str) -> list[dict]:
        return self._read(self._key(run_id, "decisions.json"), [])

    def save_packet(self, run_id: str, packet: dict) -> None:
        self._write(self._key(run_id, "packet.json"), packet)

    def load_packet(self, run_id: str) -> Optional[dict]:
        return self._read(self._key(run_id, "packet.json"), None)

    def append_audit(self, run_id: str, entry: dict) -> None:
        key = self._key(run_id, "audit.json")
        rows = self._read(key, [])
        rows.append(entry)
        self._write(key, rows)

    def load_audit(self, run_id: str) -> list[dict]:
        return self._read(self._key(run_id, "audit.json"), [])

    def registration_page(self, owner: str, limit: int, position: Optional[dict]) -> tuple[list[dict], Optional[dict]]:
        from ...domain.history import WINDOW_BYTES, HistoryChanged, HistoryUnavailable, array_end, array_page, page_size
        page_size(limit)
        key = self._key(owner, "audit.json")
        try:
            info = self._s3.head_object(Bucket=self.bucket, Key=key)
        except self._s3.exceptions.ClientError as exc:
            if _missing_object(exc) and position is None:
                return [], None
            raise
        size, version = info["ContentLength"], info["ETag"]
        end = array_end(position, size, version)
        if not end:
            raise HistoryUnavailable("Saved history could not be read.")
        start = max(0, end - WINDOW_BYTES)
        try:
            result = self._s3.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end - 1}", IfMatch=version)
        except self._s3.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("PreconditionFailed", "412"):
                raise HistoryChanged("Saved history changed. Refresh the run list.") from exc
            raise
        body = result["Body"]
        try:
            data = body.read(WINDOW_BYTES + 1)
        finally:
            body.close()
        if (result.get("ContentRange") != f"bytes {start}-{end - 1}/{size}"
                or len(data) != end - start or result.get("ETag") != version):
            raise HistoryUnavailable("Saved history range could not be verified.")
        return array_page(data, start, limit, version)


class EventBridgeBus:
    """Publishes onto a real bus, and keeps a readable copy for the audit view.

    Two things happen per publish and both matter. EventBridge is what makes the
    event claim real: another service can subscribe without this code knowing.
    The S3 copy is what makes it *checkable*, because an event nobody can read
    back is an architecture diagram, not an audit trail.

    A failure to reach EventBridge is reported in the receipt rather than
    swallowed. A silent failure here would make an event-driven system look like
    it worked while nothing was delivered.
    """

    def __init__(
        self,
        bus_name: str,
        bucket: str,
        prefix: str = "events/",
        source: str = "lasttake.orchestrator",
        events_client=None,
        s3_client=None,
    ) -> None:
        import boto3

        self.bus_name = bus_name
        self.bucket = bucket
        self.prefix = prefix
        self.source = source
        self._events = events_client or boto3.client("events")
        self._s3 = s3_client or boto3.client("s3")
        self._handlers: list[tuple[tuple[EventType, ...], Callable[[Event], None]]] = []

    def publish(self, event: Event) -> Receipt:
        record = event.to_dict()
        self._s3.put_object(
            Bucket=self.bucket,
            Key=f"{self.prefix}{event.correlation_id}/{event.occurred_at}-{event.event_id}.json",
            Body=json.dumps(record, indent=2, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )

        detail = json.dumps(record)
        try:
            response = self._events.put_events(
                Entries=[
                    {
                        "EventBusName": self.bus_name,
                        "Source": self.source,
                        "DetailType": event.event_type.value,
                        "Detail": detail,
                    }
                ]
            )
        except Exception as exc:  # noqa: BLE001 - the receipt must carry the truth
            return Receipt(
                accepted=False,
                reference=event.event_id,
                detail="Attempt stored in S3; EventBridge outcome unknown after an interrupted request.",
                status="unknown",
            )

        failed = response.get("FailedEntryCount", 0)
        entries = response.get("Entries", [])
        entry = entries[0] if len(entries) == 1 else {}
        if failed or entry.get("ErrorCode"):
            return Receipt(
                accepted=False,
                reference=event.event_id,
                detail=f"Attempt stored in S3; EventBridge rejected entry ({entry.get('ErrorCode', 'entry-failed')}).",
            )

        if not entry.get("EventId"):
            return Receipt(False, event.event_id, "Attempt stored in S3; no EventBridge acceptance identifier returned.", "unknown")

        for types, handler in self._handlers:
            if event.event_type in types:
                handler(event)
        return Receipt(
            accepted=True,
            reference=entry["EventId"],
            detail=f"Accepted by bus {self.bus_name}; downstream completion is not established.",
        )

    def subscribe(
        self, event_types: tuple[EventType, ...], handler: Callable[[Event], None]
    ) -> None:
        self._handlers.append((event_types, handler))

    def health(self) -> str:
        try:
            self._events.describe_event_bus(Name=self.bus_name)
            return "ok"
        except Exception as exc:  # noqa: BLE001
            return f"unavailable: {type(exc).__name__}"

    def replay(self, correlation_id: str) -> list[dict]:
        """Read the events for one run back, oldest first."""
        paginator = self._s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(
            Bucket=self.bucket, Prefix=f"{self.prefix}{correlation_id}/"
        ):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        keys.sort()
        if len(keys) < 2:
            return [self._read_event(key) for key in keys]
        rows = []
        # Bound both concurrent reads and queued work; map preserves key order.
        with ThreadPoolExecutor(max_workers=8) as reads:
            for start in range(0, len(keys), 8):
                rows.extend(reads.map(self._read_event, keys[start:start + 8]))
        return rows

    def _read_event(self, key: str) -> dict:
        body = self._s3.get_object(Bucket=self.bucket, Key=key)["Body"]
        try:
            return json.loads(body.read().decode("utf-8"))
        finally:
            body.close()


def from_environment():
    """Build the deployed trio from the environment the stack sets.

    Returns ``(bus, artifacts, runs)``. Raises rather than falling back to the
    offline adapters: a deployed process that silently ran on local disk would
    lose every approval the moment the container was recycled, and would look
    fine while doing it.

    Run state goes to Aurora DSQL when ``LASTTAKE_DSQL_ENDPOINT`` is set, and to
    S3 otherwise. The fallback is deliberate and narrow: S3 is a correct store
    for a single scene with one writer, and it is the wrong one the moment two
    approvals of the same pickup arrive together, because the handled-event
    check is read-modify-write. Which one is in use is reported by the API, so a
    reader never has to guess.
    """
    bucket = os.environ.get("LASTTAKE_BUCKET")
    bus_name = os.environ.get("LASTTAKE_EVENT_BUS")
    if not bucket or not bus_name:
        raise RuntimeError(
            "LASTTAKE_BUCKET and LASTTAKE_EVENT_BUS must be set. Refusing to fall "
            "back to local disk, because a deployed run on local disk loses every "
            "approval when the container is recycled."
        )

    endpoint = os.environ.get("LASTTAKE_DSQL_ENDPOINT")
    if endpoint:
        from .dsql import DsqlRunStore

        runs = DsqlRunStore(endpoint=endpoint)
    else:
        runs = S3RunStore(bucket=bucket)

    return (
        EventBridgeBus(bus_name=bus_name, bucket=bucket),
        S3ArtifactStore(bucket=bucket),
        runs,
    )


def run_store_kind() -> str:
    """Which store is actually in use, for the API to report rather than imply."""
    return "aurora-dsql" if os.environ.get("LASTTAKE_DSQL_ENDPOINT") else "s3"
