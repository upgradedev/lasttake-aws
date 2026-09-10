"""Offline reproductions through the real S3 adapter and gateway handler.

DSQL remains available when S3 fails: one dependency's refusal must not become
permission to read another. No AWS connection or production record is used.
"""
import base64
import copy
from dataclasses import replace
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from botocore.exceptions import ClientError, EndpointConnectionError
import pytest

from lasttake.adapters.aws.dsql import DsqlRunStore
from lasttake.adapters.aws.infrastructure import S3ArtifactStore, S3RunStore
from lasttake.app import handler as H, workspace as W
from lasttake.app.ingest import MAX_ARRAY_ITEMS, perform_ingest, shape_error
from lasttake.app.request_body import MAX_BODY_BYTES, BodyError, parse_body
from lasttake.app.scene_view import scene_view
from lasttake.domain.package import Take, with_extra_take
from .test_handler import A_TAKE, RUN, get, offline_backends, post
from .test_workspace import owned


def s3_error(code, status=404):
    response = {"Error": {"Code": code, "Message": "private-bucket/owners/hidden-run.json"}}
    if status is not None:
        response["ResponseMetadata"] = {"HTTPStatusCode": status}
    return ClientError(response, "HeadObject")


class FakeS3:
    exceptions = SimpleNamespace(ClientError=ClientError)

    def __init__(self, failures=None):
        self.failures = failures or {}
        self.objects = {}
        self.calls = []

    def check(self, operation, key):
        self.calls.append((operation, key))
        failure = self.failures.get((operation, key))
        if failure is not None:
            raise failure

    def head_object(self, *, Bucket, Key):
        self.check("head", Key)
        if Key not in self.objects:
            raise s3_error("404")
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_object(self, *, Bucket, Key):
        self.check("get", Key)
        if Key not in self.objects:
            raise s3_error("NoSuchKey")
        return {"Body": BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.check("put", Key)
        self.objects[Key] = Body
        return {}


FAILURES = [
    ("AccessDenied", 403), ("403", 403), ("Throttling", 429),
    ("SlowDown", 503), ("InternalError", 500), ("ServiceUnavailable", 503),
    ("NoSuchBucket", 404), ("UnknownError", 404),
    ("NoSuchKey", 403), ("404", 500), ("UnknownError", None),
]


@pytest.mark.parametrize("code,status", FAILURES)
def test_s3_exists_propagates_uncertain_state_and_put_never_overwrites(code, status):
    failure = s3_error(code, status)
    client = FakeS3({("head", "artifacts/owner"): failure})
    client.objects["artifacts/owner"] = b"original ownership"
    store = S3ArtifactStore("private-bucket", client=client)
    with pytest.raises(ClientError) as raised:
        store.exists("owner")
    assert raised.value is failure
    with pytest.raises(ClientError):
        store.put("owner", b"replacement")
    assert client.objects["artifacts/owner"] == b"original ownership"
    assert client.calls == [("head", "artifacts/owner")] * 2


@pytest.mark.parametrize("code,status", [("404", 404), ("NoSuchKey", 404),
                                         ("404", None), ("NoSuchKey", None)])
def test_only_known_missing_objects_have_the_legacy_absence_result(code, status):
    client = FakeS3({("head", "artifacts/missing"): s3_error(code, status),
                     ("get", "runs/example/findings.json"): s3_error(code, status)})
    assert S3ArtifactStore("private-bucket", client=client).exists("missing") is False
    assert S3RunStore("private-bucket", client=client).load_findings("example") == []


@pytest.mark.parametrize("code,status", FAILURES)
def test_saved_s3_state_does_not_fall_back_to_empty_or_allow_follow_on_writes(code, status):
    failure = s3_error(code, status)
    client = FakeS3({("get", "runs/example/findings.json"): failure,
                     ("get", "runs/_handled.json"): failure})
    store = S3RunStore("private-bucket", client=client)
    with pytest.raises(ClientError):
        store.load_findings("example")
    with pytest.raises(ClientError):
        store.save_findings("example", [{"finding_id": "retained"}])
    with pytest.raises(ClientError):
        store.claim("action-key", "example")
    with pytest.raises(ClientError):
        store.mark_handled("action-key", "example")
    assert all(operation == "get" for operation, _ in client.calls)
    assert client.objects == {}


def available_dsql():
    runs = MagicMock(spec=DsqlRunStore)
    for name in ("load_findings", "load_decisions", "load_audit", "blocked_scenes"):
        getattr(runs, name).return_value = []
    runs.load_packet.return_value = None
    return runs


OWNED_PATHS = [path for path in H.ROUTES if path != "/api/reset"]


@pytest.mark.parametrize("path", OWNED_PATHS)
@pytest.mark.parametrize("failure", [s3_error("AccessDenied", 403), s3_error("Throttling", 429),
                                    s3_error("SlowDown", 503), s3_error("InternalError", 500),
                                    EndpointConnectionError(endpoint_url="https://private-bucket.invalid")])
def test_owner_lookup_failure_stops_before_independently_available_dsql(path, failure, monkeypatch):
    client = FakeS3({("head", f"artifacts/owners/{RUN}.json"): failure})
    client.objects[f"artifacts/owners/{RUN}.json"] = b'{"owner":"retained"}'
    artifacts = S3ArtifactStore("private-bucket", client=client)
    runs = available_dsql()
    bus = MagicMock()
    monkeypatch.setattr(H, "from_environment", lambda: (bus, artifacts, runs))
    monkeypatch.setattr(H, "_SCHEMA_READY", False)
    result = post(path, {"run_id": RUN, "kind": "take", "document": A_TAKE})
    assert result["status"] == 503
    assert result["error"] == "Saved state is temporarily unavailable."
    assert "Refresh saved state" in result["detail"]
    assert result["served_by"]["lambda_request_id"]
    assert runs.mock_calls == [], "no schema, findings, decisions or audit read/write after failed ownership"
    assert bus.mock_calls == []
    assert client.calls == [("head", f"artifacts/owners/{RUN}.json")]
    assert "private-bucket" not in json.dumps(result)
    assert "ClientError" not in json.dumps(result)


@pytest.mark.parametrize("code,status", [("AccessDenied", 403), ("SlowDown", 503), ("NoSuchKey", 404)])
def test_owner_get_failure_after_successful_head_is_not_legacy_access(code, status, monkeypatch):
    key = f"artifacts/owners/{RUN}.json"
    client = FakeS3({("get", key): s3_error(code, status)})
    handle = "a" * 64
    client.objects[key] = json.dumps({"owner": W.owner_id(handle)}).encode()
    runs = available_dsql()
    monkeypatch.setattr(H, "from_environment", lambda: (MagicMock(), S3ArtifactStore("b", client=client), runs))
    result = post("/api/state", {"run_id": RUN, "session_id": handle})
    assert result["status"] == 503
    assert runs.mock_calls == []


@pytest.mark.parametrize("path", ["/api/session", "/api/reset"])
def test_session_storage_failure_never_creates_a_visitor_or_run(path, monkeypatch):
    handle = "a" * 64
    key = f"artifacts/visitors/{W.owner_id(handle)}.json"
    client = FakeS3({("head", key): s3_error("AccessDenied", 403)})
    runs = available_dsql()
    monkeypatch.setattr(H, "from_environment", lambda: (MagicMock(), S3ArtifactStore("b", client=client), runs))
    assert post(path, {"session_id": handle})["status"] == 503
    assert runs.mock_calls == []
    assert client.objects == {}


@pytest.mark.parametrize("code,status", [("AccessDenied", 403), ("Throttling", 429), ("InternalError", 500)])
def test_blocked_query_returns_no_partial_list_when_s3_ownership_fails(code, status, monkeypatch):
    client = FakeS3({("head", "artifacts/owners/owned-private.json"): s3_error(code, status)})
    runs = available_dsql()
    runs.blocked_scenes.return_value = [{"run_id": "legacy-visible"}, {"run_id": "owned-private"},
                                      {"run_id": "unread-third"}]
    monkeypatch.setattr(H, "from_environment", lambda: (MagicMock(), S3ArtifactStore("b", client=client), runs))
    response = get("/api/blocked")
    assert response["statusCode"] == 503
    assert "blocked" not in json.loads(response["body"])
    assert all(row["run_id"] not in response["body"] for row in runs.blocked_scenes.return_value)
    assert [call[0] for call in runs.mock_calls] == ["blocked_scenes"]
    assert client.calls == [("head", "artifacts/owners/legacy-visible.json"),
                            ("head", "artifacts/owners/owned-private.json")]


def test_blocked_query_storage_or_database_failure_has_safe_http_envelope(monkeypatch):
    runs = available_dsql()
    runs.blocked_scenes.side_effect = RuntimeError("private SQL connection details")
    monkeypatch.setattr(H, "from_environment", lambda: (MagicMock(), MagicMock(), runs))
    response = get("/api/blocked")
    assert response["statusCode"] == 503
    assert "private SQL" not in response["body"]


def test_known_404_legacy_runs_work_and_owned_runs_stay_hidden(offline_backends, monkeypatch):
    bus, _, runs = offline_backends
    client = FakeS3()
    artifacts = S3ArtifactStore("b", client=client)
    monkeypatch.setattr(H, "from_environment", lambda: (bus, artifacts, runs))
    assert post("/api/state", {"run_id": RUN})["status"] == 200
    assert post("/api/ingest", {"run_id": RUN, "kind": "take", "document": A_TAKE})["status"] == 200
    assert post("/api/scene", {"run_id": RUN})["take_count"] == 41
    handle = "a" * 64
    client.objects[f"artifacts/owners/{RUN}.json"] = json.dumps({"owner": W.owner_id(handle)}).encode()
    assert post("/api/state", {"run_id": RUN})["status"] == 403
    assert post("/api/state", {"run_id": RUN, "session_id": "b" * 64})["status"] == 403
    assert post("/api/state", {"run_id": RUN, "session_id": handle})["status"] == 200
    monkeypatch.setattr(runs, "blocked_scenes", lambda: [{"run_id": RUN}, {"run_id": "legacy-visible"}], raising=False)
    response = get("/api/blocked")
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["blocked"] == [{"run_id": "legacy-visible"}]


def test_negative_control_reinstates_the_original_conditional_fail_open(monkeypatch):
    from lasttake.adapters.aws import infrastructure

    client = FakeS3({("head", f"artifacts/owners/{RUN}.json"): s3_error("AccessDenied", 403)})
    client.objects[f"artifacts/owners/{RUN}.json"] = b'{"owner":"private-owner"}'
    runs = available_dsql()
    monkeypatch.setattr(H, "from_environment", lambda: (MagicMock(), S3ArtifactStore("b", client=client), runs))
    assert post("/api/state", {"run_id": RUN})["status"] == 503
    assert runs.mock_calls == []
    # Deliberately restore the original "any ClientError is missing" decision.
    # The same otherwise-available DSQL path must now be reachable, proving this
    # fixture is not passing only because the whole environment is unavailable.
    monkeypatch.setattr(infrastructure, "_missing_object", lambda exc: True)
    assert post("/api/state", {"run_id": RUN})["status"] == 200
    assert runs.load_findings.called


def files_below(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("field", ["beat_ids", "visible_people", "visible_assets"])
@pytest.mark.parametrize("values", [["B-17", "B-17"], [f"ID-{i}" for i in range(65)]])
def test_duplicate_or_oversized_arrays_leave_owned_state_and_all_bytes_unchanged(field, values, tmp_path):
    body = owned()
    before = post("/api/state", body)["package_revision_digest"]
    original = files_below(tmp_path)
    result = post("/api/ingest", {**body, "kind": "take", "document": {**A_TAKE, field: values}})
    assert result["status"] == 400
    assert field in result["error"]
    assert files_below(tmp_path) == original
    assert post("/api/state", body)["package_revision_digest"] == before


@pytest.mark.parametrize("field", ["beat_ids", "visible_people", "visible_assets"])
def test_shared_ingest_boundary_rejects_before_any_package_read_or_write(field):
    rebuild = MagicMock()
    with pytest.raises(ValueError, match="unique identifiers"):
        perform_ingest(object(), "take", {**A_TAKE, field: ["ID-1", "ID-1"]}, rebuild, None, None)
    rebuild.assert_not_called()


def test_invalid_ingest_does_not_build_a_run_or_initialize_database(monkeypatch):
    body = owned()
    build = MagicMock(side_effect=AssertionError("validation must precede run construction"))
    monkeypatch.setattr(H, "build_run", build)
    assert post("/api/ingest", {**body, "kind": "take", "document": {**A_TAKE, "beat_ids": ["B-17"] * 2}})["status"] == 400
    build.assert_not_called()


def test_small_request_cannot_persist_duplicate_array_amplification(tmp_path):
    body = owned()
    request = {**body, "kind": "take", "document": {**A_TAKE,
               "beat_ids": ["B-17"] * 5000, "visible_people": ["P-1"] * 5000}}
    assert len(json.dumps(request).encode()) < 128_000
    original = files_below(tmp_path)
    assert post("/api/ingest", request)["status"] == 400
    assert files_below(tmp_path) == original


@pytest.mark.parametrize("field", ["beat_ids", "visible_people", "visible_assets"])
def test_distinct_ids_at_the_exact_limit_remain_valid_and_unknown_beats_are_not_removed(field):
    assert MAX_ARRAY_ITEMS == 64  # independent literal, not a fixture built from the implementation limit
    document = {**A_TAKE, field: [f"ID-{i}" for i in range(64)]}
    assert shape_error("take", document) is None
    assert shape_error("take", {**A_TAKE, field: []}) is None
    assert post("/api/ingest", {"run_id": RUN, "kind": "take", "document": document})["status"] == 200
    assert getattr(H.build_run(RUN).package.take("T-900"), field) == document[field]


@pytest.mark.parametrize("encoded", [False, True])
@pytest.mark.parametrize("extra", [0, 1])
def test_request_boundary_counts_decoded_bytes_before_any_storage(encoded, extra, monkeypatch):
    assert MAX_BODY_BYTES == 128_000
    raw = '{"run_id":"demo-testrun0001"}'
    raw += " " * (128_000 + extra - len(raw))
    event = {"requestContext": {"http": {"path": "/api/state", "method": "POST"}},
             "body": base64.b64encode(raw.encode()).decode() if encoded else raw,
             "isBase64Encoded": encoded}
    if extra:
        environment = MagicMock(side_effect=AssertionError("oversized input reached storage"))
        monkeypatch.setattr(H, "from_environment", environment)
        assert H.handler(event, None)["statusCode"] == 413
        environment.assert_not_called()
    else:
        assert H.handler(event, None)["statusCode"] == 200


@pytest.mark.parametrize("event", [
    {"body": "!!!!", "isBase64Encoded": True},
    {"body": "/w==", "isBase64Encoded": True},
    {"body": "e30=trailing!", "isBase64Encoded": True},
    {"body": "{}", "isBase64Encoded": "false"}, {"body": []}, {"body": 0},
    {"body": "[]"}, {"body": "\ud800"}, {"body": "[" * 2000 + "]" * 2000},
])
def test_malformed_gateway_representations_refuse_before_storage(event, monkeypatch):
    environment = MagicMock(side_effect=AssertionError("malformed input reached storage"))
    monkeypatch.setattr(H, "from_environment", environment)
    response = H.handler({**event, "requestContext": {"http": {"path": "/api/state", "method": "POST"}}}, None)
    assert response["statusCode"] == 400
    environment.assert_not_called()


def test_utf8_and_base64_bounds_and_equivalent_duplicate_json_encodings():
    with pytest.raises(BodyError) as raised:
        parse_body({"body": '{"note":"' + "\U0001f3ac" * 32000 + '"}'})
    assert raised.value.status == 413
    with pytest.raises(BodyError) as raised:
        parse_body({"body": "A" * 170669, "isBase64Encoded": True})
    assert raised.value.status == 413
    raw = json.dumps({"run_id": RUN, "kind": "take", "document": {**A_TAKE, "beat_ids": ["B-17", "B-17"]}})
    raw = raw.replace('"B-17", "B-17"', '"B-17", "B-\\u00317"')
    event = {"requestContext": {"http": {"path": "/api/ingest", "method": "POST"}},
             "body": base64.b64encode(raw.encode()).decode(), "isBase64Encoded": True}
    assert H.handler(event, None)["statusCode"] == 400


def test_historical_duplicate_arrays_cannot_multiply_full_scene_rows_or_mutate_evidence():
    doc = {key: value for key, value in A_TAKE.items() if key != "camera_report_row"}
    doc.update(beat_ids=["B-17"] * 5000 + ["B-18", "unknown-beat"],
               visible_people=["PERSON-X"] * 4000 + ["PERSON-Y"],
               visible_assets=["ASSET-X"] * 4000)
    package = with_extra_take(H.scene_package(), Take(**doc), None)
    original = copy.deepcopy(package)
    result = scene_view(package)
    linked = [take for beat in result["beats"] for take in beat["takes"] if take["take_id"] == "T-900"]
    assert len(linked) == 2
    assert all(take["visible_people"] == ["PERSON-X", "PERSON-Y"] for take in linked)
    assert all(take["visible_assets"] == ["ASSET-X"] for take in linked)
    assert "visible on 1 take" in result["locations"]["PERSON-X"]
    compact = replace(package, takes=[*package.takes[:-1], replace(package.takes[-1],
                      beat_ids=["B-17", "B-18", "unknown-beat"],
                      visible_people=["PERSON-X", "PERSON-Y"], visible_assets=["ASSET-X"])])
    assert result == scene_view(compact), "duplicates must not multiply response bytes"
    assert package == original
    assert package.revision_digest() == original.revision_digest()


def test_subject_projection_indexes_membership_once_instead_of_rescanning_arrays():
    class NoMembershipScan(list):
        def __contains__(self, item):
            raise AssertionError("quadratic membership scan")

    package = copy.deepcopy(H.scene_package())
    package.takes = [replace(take, visible_people=NoMembershipScan(take.visible_people),
                             visible_assets=NoMembershipScan(take.visible_assets)) for take in package.takes]
    assert scene_view(package) == scene_view(H.scene_package())
