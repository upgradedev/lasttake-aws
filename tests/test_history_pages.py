"""Bounded source-only history queries, historical bytes and ownership controls."""
from datetime import datetime, timezone
from io import BytesIO
import json
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lasttake.adapters.aws.dsql import DsqlRunStore
from lasttake.adapters.aws.infrastructure import S3RunStore
from lasttake.app import handler as H, workspace as W
from lasttake.domain.history import (HistoryChanged, HistoryUnavailable, WINDOW_BYTES,
    array_page, decode_cursor, encode_cursor)
from .test_handler import offline_backends, post
from .test_security_boundaries import s3_error


def registration(index):
    return {"kind": "ui.run.created", "run_id": f"demo-history-{index:04d}",
            "created_at": "2026-09-10T10:00:00+00:00"}


@pytest.fixture
def query_store(monkeypatch):
    # Execute the adapter's actual parameterized SQL against an independent SQL
    # engine. This verifies query shape/semantics, not Aurora's service behavior.
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE audit(run_id TEXT, entry_id TEXT, kind TEXT, body TEXT, recorded_at TEXT)")
    calls = []
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_): self.cur.close()
        def execute(self, sql, args):
            calls.append((sql, args))
            self.cur = db.execute(sql.replace("%s", "?"),
                                  tuple(str(value) if isinstance(value, datetime) else value for value in args))
        def fetchmany(self, count):
            assert count <= 21
            return [(row[0], datetime.fromisoformat(row[1]), row[2]) for row in self.cur.fetchmany(count)]
        def fetchall(self): raise AssertionError("Unbounded fetch")
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def cursor(self): return Cursor()
    store = object.__new__(DsqlRunStore)
    monkeypatch.setattr(store, "_connect", lambda: Connection())
    def add(owner, index, *, at="2026-09-10 10:00:00+00:00", kind="ui.run.created"):
        db.execute("INSERT INTO audit VALUES(?,?,?,?,?)",
                   (owner, f"entry-{index:04d}", kind, json.dumps(registration(index)), at))
    yield store, add, calls
    db.close()


def test_actual_dsql_keyset_limit_preserves_all_pages_ties_owner_and_concurrent_insert(query_store):
    store, add, calls = query_store
    for index in range(31): add("owner-a", index)
    for index in range(70, 91): add("owner-b", index)
    add("owner-a", 99, kind="not-a-registration")
    rows, cursor = store.registration_page("owner-a", 10, None)
    assert [row["run_id"] for row in rows] == [registration(i)["run_id"] for i in range(30, 20, -1)]
    assert cursor == {"kind": "dsql", "at": "2026-09-10T10:00:00+00:00", "id": "entry-0021"}
    add("owner-a", 100, at="2026-09-11 10:00:00+00:00")
    seen = rows[:]
    while cursor:
        rows, cursor = store.registration_page("owner-a", 10, cursor)
        assert len(rows) <= 10
        seen.extend(rows)
    assert [row["run_id"] for row in seen] == [registration(i)["run_id"] for i in range(30, -1, -1)]
    assert len(calls) == 4
    for sql, args in calls:
        assert "WHERE run_id = %s AND kind = %s" in sql
        assert "ORDER BY recorded_at DESC, entry_id DESC LIMIT %s" in sql
        assert args[:2] == ("owner-a", "ui.run.created") and args[-1] == 11
        assert "OFFSET" not in sql and "owner-a" not in sql
    assert "AND (recorded_at, entry_id) < (%s, %s)" in calls[1][0]
    assert store.registration_page("owner-a", 10, None)[0][0]["run_id"] == registration(100)["run_id"]
    assert store.registration_page("empty-owner", 10, None) == ([], None)


@pytest.mark.parametrize("position", [{}, {"kind":"array","before":1,"version":"v"},
    {"kind":"dsql","at":"not-a-date","id":"ok"},
    {"kind":"dsql","at":"2026-09-10","id":"ok"},
    {"kind":"dsql","at":"2026-09-10T00:00:00Z","id":"' OR 1=1--"}])
def test_bad_dsql_position_refuses_before_query(query_store, position):
    store, _, calls = query_store
    with pytest.raises(ValueError): store.registration_page("owner", 10, position)
    assert calls == []


class RangeS3:
    exceptions = SimpleNamespace(ClientError=type(s3_error("404")))
    def __init__(self, data):
        self.data, self.version, self.calls = data, '"version-one"', []
        self.failure = None
    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs))
        if self.failure: raise self.failure
        return {"ContentLength": len(self.data), "ETag": self.version}
    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        assert kwargs["IfMatch"] == self.version
        start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", kwargs["Range"]).groups())
        assert end - start + 1 <= 65_536
        self.body = BytesIO(self.data[start:end+1])
        return {"Body": self.body, "ETag": self.version,
                "ContentRange": f"bytes {start}-{end}/{len(self.data)}"}


@pytest.mark.parametrize("indent", [None, 2])
def test_old_s3_arrays_page_with_bounded_ranges_and_no_rewrite(indent):
    records = [registration(i) for i in range(1000)]
    records[992]["old_note"] = 'Unicode 🎬 braces } { [ ] quote " slash \\ and nested'
    records[992]["old_extra"] = {"nested": ["} escaped\\\"", {"value": 2}]}
    data = json.dumps(records, indent=indent, ensure_ascii=False).encode()
    assert len(data) > 65_536
    client = RangeS3(data)
    store = S3RunStore("bucket", client=client)
    rows, position = store.registration_page("visitor-owner", 10, None)
    assert rows == list(reversed(records[-10:]))
    assert client.body.closed
    seen = rows[:]
    while position:
        rows, position = store.registration_page("visitor-owner", 10, position)
        seen.extend(rows)
    assert seen == list(reversed(records))
    assert client.data == data and all(op in {"head", "get"} for op, _ in client.calls)
    assert len(client.calls) == 200


def test_s3_cursor_change_range_mismatch_and_read_failure_never_become_empty_history(monkeypatch):
    client = RangeS3(json.dumps([registration(i) for i in range(12)]).encode())
    store = S3RunStore("bucket", client=client)
    _, position = store.registration_page("owner", 10, None)
    client.version = '"changed"'
    with pytest.raises(HistoryChanged): store.registration_page("owner", 10, position)
    original_get = client.get_object
    def invalid_range(**kwargs):
        return {**original_get(**kwargs), "ContentRange": "unverified"}
    monkeypatch.setattr(client, "get_object", invalid_range)
    with pytest.raises(HistoryUnavailable): store.registration_page("owner", 10, None)
    assert client.body.closed
    for code, status in [("AccessDenied",403), ("SlowDown",503), ("Throttling",429)]:
        client.failure = s3_error(code, status)
        with pytest.raises(client.exceptions.ClientError): store.registration_page("owner", 10, None)
    client.failure = s3_error("404")
    assert store.registration_page("owner", 10, None) == ([], None)
    with pytest.raises(client.exceptions.ClientError): store.registration_page("owner", 10, position)


def test_oversized_old_record_is_not_silently_skipped_or_removed():
    records = [registration(1), {**registration(2), "old_note": "x" * 70_000}]
    client = RangeS3(json.dumps(records).encode())
    with pytest.raises(HistoryUnavailable): S3RunStore("bucket", client=client).registration_page("owner",10,None)
    assert json.loads(client.data) == records
    assert array_page(b"[]", 0, 10, "v") == ([], None)
    with pytest.raises(HistoryUnavailable): array_page(b"x" * (WINDOW_BYTES + 1), 0, 10, "v")


def make_history(artifacts, runs, count=23):
    handle = "a" * 64
    owner = W.owner_id(handle)
    artifacts.put(f"visitors/{owner}.json", b"{}")
    for index in range(count):
        row = registration(index)
        artifacts.put(f"owners/{row['run_id']}.json", json.dumps({"owner": owner}).encode())
        runs.append_audit(owner, row)
    return handle, owner


def test_owned_api_pages_reconstruct_only_selected_runs_and_preserve_historical_bytes(offline_backends, monkeypatch, tmp_path):
    _, artifacts, runs = offline_backends
    handle, owner = make_history(artifacts, runs)
    original = (tmp_path / "runs" / owner / "audit.json").read_bytes()
    build = MagicMock(wraps=H.build_run)
    monkeypatch.setattr(H, "build_run", build)
    monkeypatch.setattr(runs, "load_audit", lambda run: [] if run != owner else (_ for _ in ()).throw(AssertionError("unbounded owner load")))
    page = post("/api/session", {"session_id": handle})
    assert page["status"] == 200 and page["page_size"] == 10 and page["has_more"]
    assert len(page["runs"]) == build.call_count == 10
    seen = page["runs"][:]
    while page["next_cursor"]:
        build.reset_mock()
        page = post("/api/session", {"session_id": handle, "cursor": page["next_cursor"]})
        assert page["status"] == 200 and len(page["runs"]) == build.call_count <= 10
        seen.extend(page["runs"])
    assert [row["run_id"] for row in seen] == [registration(i)["run_id"] for i in range(22,-1,-1)]
    assert (tmp_path / "runs" / owner / "audit.json").read_bytes() == original
    assert post("/api/state", {"run_id": registration(0)["run_id"], "session_id": handle})["status"] == 200
    assert post("/api/state", {"run_id": registration(0)["run_id"]})["status"] == 403


@pytest.mark.parametrize("size", [0,21,-1,True,"10",None])
def test_bad_page_size_refuses_before_storage(size, monkeypatch):
    environment = MagicMock(side_effect=AssertionError("invalid input reached storage"))
    monkeypatch.setattr(H,"from_environment",environment)
    assert post("/api/session", {"page_size":size})["status"] == 400
    environment.assert_not_called()


def test_cursor_owner_binding_bad_encoding_and_session_change(offline_backends):
    _, artifacts, runs = offline_backends
    handle, owner = make_history(artifacts, runs)
    page = post("/api/session", {"session_id": handle})
    cursor = page["next_cursor"]
    assert decode_cursor(cursor, owner)["kind"] == "array"
    other = post("/api/session", {})["session_id"]
    for body in ({"session_id": other,"cursor":cursor}, {"cursor":cursor},
                 {"session_id":handle,"cursor":"bad!"}, {"session_id":handle,"cursor":"A"*1025}):
        assert post("/api/session",body)["status"] == 400
    assert len(post("/api/session", {"session_id": handle,"page_size":20})["runs"]) == 20
    runs.append_audit(owner, registration(99))
    changed = post("/api/session", {"session_id":handle,"cursor":cursor})
    assert changed["status"] == 409 and "runs" not in changed
    assert post("/api/session", {"session_id":handle})["status"] == 403
    # Register the corresponding marker; refresh now includes the newly created run.
    artifacts.put(f"owners/{registration(99)['run_id']}.json", json.dumps({"owner":owner}).encode())
    assert post("/api/session", {"session_id":handle})["runs"][0]["run_id"] == registration(99)["run_id"]


def test_page_registration_cannot_reconstruct_a_foreign_owned_run(offline_backends, monkeypatch):
    _, artifacts, runs = offline_backends
    handle, owner = make_history(artifacts,runs,1)
    runs.append_audit(owner, registration(99))
    artifacts.put(f"owners/{registration(99)['run_id']}.json", json.dumps({"owner":W.owner_id("b"*64)}).encode())
    build = MagicMock(side_effect=AssertionError("foreign run reconstructed"))
    monkeypatch.setattr(H,"build_run",build)
    assert post("/api/session", {"session_id":handle})["status"] == 403
    build.assert_not_called()
