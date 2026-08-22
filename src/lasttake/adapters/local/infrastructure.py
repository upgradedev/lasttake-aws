"""File-backed event bus, artifact store and run store.

These are the offline half of every port. They run with no network, no
credential and no AWS account, which is what makes the test suite and a
location with no signal the same code path rather than two.

They are deliberately boring. Durability here is ``os.replace`` onto a local
disk, which is enough for one machine and is not enough for the deployed
product; the AWS adapters exist for that.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

from ...domain.events import Event, EventType
from ...ports.infrastructure import Receipt


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class LocalEventBus:
    """In-process bus with a durable log.

    The log is the point. An event-driven claim that leaves no trace is not
    checkable, and the audit view in the UI reads this file.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "events.jsonl"
        self._handlers: list[tuple[tuple[EventType, ...], Callable[[Event], None]]] = []

    def publish(self, event: Event) -> Receipt:
        record = event.to_dict()
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        for types, handler in self._handlers:
            if event.event_type in types:
                handler(event)
        return Receipt(
            accepted=True,
            reference=event.event_id,
            detail=f"appended to {self.log_path.name}",
        )

    def subscribe(
        self, event_types: tuple[EventType, ...], handler: Callable[[Event], None]
    ) -> None:
        self._handlers.append((event_types, handler))

    def health(self) -> str:
        return "ok" if self.root.exists() else "unavailable"

    def replay(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class LocalArtifactStore:
    """Content-addressed files. No update, no delete."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        if path.exists() and path.read_bytes() != data:
            raise ValueError(
                f"{key} already exists with different content. Artifacts are "
                "immutable; write a new revision instead."
            )
        _write_atomic(path, data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def url_for(self, key: str) -> Optional[str]:
        return None


class LocalRunStore:
    """Run state as JSON under one directory per run."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._seen_path = self.root / "handled.json"

    # -- idempotency --------------------------------------------------------

    def _seen(self) -> dict:
        if not self._seen_path.exists():
            return {}
        return json.loads(self._seen_path.read_text(encoding="utf-8"))

    def already_handled(self, idempotency_key: str) -> bool:
        return idempotency_key in self._seen()

    def mark_handled(self, idempotency_key: str, run_id: str) -> None:
        seen = self._seen()
        seen[idempotency_key] = run_id
        _write_atomic(
            self._seen_path, json.dumps(seen, indent=2, sort_keys=True).encode("utf-8")
        )

    # -- run state ----------------------------------------------------------

    def _run_dir(self, run_id: str) -> Path:
        path = self.root / run_id.replace(":", "_")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _read_list(self, run_id: str, name: str) -> list[dict]:
        path = self._run_dir(run_id) / name
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_list(self, run_id: str, name: str, rows: list[dict]) -> None:
        _write_atomic(
            self._run_dir(run_id) / name,
            json.dumps(rows, indent=2, sort_keys=True).encode("utf-8"),
        )

    def save_findings(self, run_id: str, findings: list[dict]) -> None:
        """Replace findings for the checks present, keep the rest.

        A targeted rerun returns findings for some checks only. Overwriting the
        whole set would silently delete results the rerun did not look at, and
        the gate would then see missing results and fail closed for the wrong
        reason. So it merges by finding_id.
        """
        existing = {f["finding_id"]: f for f in self._read_list(run_id, "findings.json")}
        for finding in findings:
            existing[finding["finding_id"]] = finding
        self._write_list(run_id, "findings.json", sorted(existing.values(), key=lambda f: f["finding_id"]))

    def load_findings(self, run_id: str) -> list[dict]:
        return self._read_list(run_id, "findings.json")

    def save_decision(self, run_id: str, decision: dict) -> None:
        rows = self._read_list(run_id, "decisions.json")
        rows.append(decision)
        self._write_list(run_id, "decisions.json", rows)

    def load_decisions(self, run_id: str) -> list[dict]:
        return self._read_list(run_id, "decisions.json")

    def save_packet(self, run_id: str, packet: dict) -> None:
        _write_atomic(
            self._run_dir(run_id) / "packet.json",
            json.dumps(packet, indent=2, sort_keys=True).encode("utf-8"),
        )

    def load_packet(self, run_id: str) -> Optional[dict]:
        path = self._run_dir(run_id) / "packet.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def append_audit(self, run_id: str, entry: dict) -> None:
        rows = self._read_list(run_id, "audit.json")
        rows.append(entry)
        self._write_list(run_id, "audit.json", rows)

    def load_audit(self, run_id: str) -> list[dict]:
        return self._read_list(run_id, "audit.json")
