"""Source-only authority/configuration controls, not effective Aurora IAM probes."""
import inspect
import json
from pathlib import Path
import re
import sys
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import boto3
from botocore.exceptions import ClientError
import pytest

from lasttake.adapters.aws import infrastructure as I
from lasttake.adapters.aws.dsql import DsqlRunStore, SCHEMA_STATEMENTS
from lasttake.adapters.aws.dsql_config import AUTH_KEYS, DsqlConfig, DsqlConfigurationError, from_environment
from lasttake.app import handler as H
from lasttake.ports.infrastructure import RunStore
from infra.dsql_runtime_authority import TABLE_PERMISSIONS, prepare, main
from .test_handler import offline_backends, post, get

ENDPOINT = "example.dsql.eu-west-1.on.aws"
CUSTOM = {"LASTTAKE_DSQL_ENDPOINT": ENDPOINT, "LASTTAKE_DSQL_USER": "lasttake_runtime",
          "LASTTAKE_DSQL_AUTH_MODE": "runtime", "LASTTAKE_DSQL_BOOTSTRAP": "disabled"}
CLUSTER = "arn:aws:dsql:eu-west-1:123456789012:cluster/example"
ROLE = "arn:aws:iam::123456789012:role/example-runtime"


@pytest.fixture(autouse=True)
def isolated_authority_env(monkeypatch):
    for key in (*AUTH_KEYS, "LASTTAKE_DSQL_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(H, "_SCHEMA_READY", False)


def configure(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def runtime():
    return DsqlRunStore(ENDPOINT, user="lasttake_runtime", auth_mode="runtime", bootstrap=False)


def test_legacy_defaults_and_explicit_disabled_admin_bootstrap_are_preserved():
    assert from_environment({}) is None
    config = from_environment({"LASTTAKE_DSQL_ENDPOINT": ENDPOINT})
    assert config == DsqlConfig(ENDPOINT, "admin", "admin", True)
    assert DsqlRunStore(ENDPOINT).schema_bootstrap_enabled is True
    assert DsqlRunStore(ENDPOINT, bootstrap=False).schema_bootstrap_enabled is False
    assert from_environment(CUSTOM) == DsqlConfig(ENDPOINT, "lasttake_runtime", "runtime", False)


@pytest.mark.parametrize("missing", list(CUSTOM))
def test_partial_runtime_config_refuses_before_any_sdk_or_fallback(missing, monkeypatch):
    configure(monkeypatch, {k: v for k, v in CUSTOM.items() if k != missing})
    sdk = MagicMock(side_effect=AssertionError("No client before validation"))
    monkeypatch.setattr(boto3, "client", sdk)
    fallback = MagicMock(side_effect=AssertionError("No S3 fallback"))
    monkeypatch.setattr(I, "S3RunStore", fallback)
    with pytest.raises(DsqlConfigurationError): I.from_environment()
    with pytest.raises(DsqlConfigurationError): I.run_store_kind()
    sdk.assert_not_called(); fallback.assert_not_called()


@pytest.mark.parametrize("key,value", [("LASTTAKE_DSQL_USER", "admin"),
    ("LASTTAKE_DSQL_USER", "dbowner"),
    ("LASTTAKE_DSQL_USER", ""), ("LASTTAKE_DSQL_USER", " admin"),
    ("LASTTAKE_DSQL_USER", "pg_read_all_data"), ("LASTTAKE_DSQL_USER", "aws_role"),
    ("LASTTAKE_DSQL_USER", "public"), ("LASTTAKE_DSQL_USER", 'role"; SELECT 1;--'),
    ("LASTTAKE_DSQL_USER", "x" * 64), ("LASTTAKE_DSQL_AUTH_MODE", "admin"),
    ("LASTTAKE_DSQL_AUTH_MODE", "Runtime"), ("LASTTAKE_DSQL_AUTH_MODE", ""),
    ("LASTTAKE_DSQL_BOOTSTRAP", "enabled"), ("LASTTAKE_DSQL_BOOTSTRAP", "false"),
    ("LASTTAKE_DSQL_BOOTSTRAP", "disabled "), ("LASTTAKE_DSQL_ENDPOINT", ""),
    ("LASTTAKE_DSQL_ENDPOINT", "https://" + ENDPOINT), ("LASTTAKE_DSQL_ENDPOINT", " " + ENDPOINT)])
def test_invalid_authority_combinations_fail_closed(key, value):
    with pytest.raises(DsqlConfigurationError): from_environment({**CUSTOM, key: value})


@pytest.mark.parametrize("kwargs", [{"user":"lasttake_runtime"}, {"auth_mode":"runtime"},
    {"user":"lasttake_runtime", "auth_mode":"runtime"}, {"bootstrap":"disabled"},
    {"bootstrap":0}, {"auth_mode":"unknown"}, {"user":None}, {"endpoint":""}])
def test_direct_constructor_cannot_reinterpret_custom_user_as_admin(kwargs):
    with pytest.raises(DsqlConfigurationError): DsqlRunStore(**{"endpoint":ENDPOINT, **kwargs})


@pytest.mark.parametrize("custom", [False, True])
def test_connection_uses_exact_user_and_matching_short_lived_token_without_admin_fallback(custom, monkeypatch):
    client = MagicMock()
    expected = "generate_db_connect_auth_token" if custom else "generate_db_connect_admin_auth_token"
    forbidden = "generate_db_connect_admin_auth_token" if custom else "generate_db_connect_auth_token"
    getattr(client, expected).return_value = "short-lived-fixture-token"
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: client)
    connect = MagicMock()
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    store = runtime() if custom else DsqlRunStore(ENDPOINT)
    store._connect()
    getattr(client, expected).assert_called_once_with(Hostname=ENDPOINT, Region="eu-west-1", ExpiresIn=900)
    getattr(client, forbidden).assert_not_called()
    assert connect.call_args.kwargs == {"host":ENDPOINT,"dbname":"postgres","user":store.user,
        "password":"short-lived-fixture-token","sslmode":"require","autocommit":True}
    getattr(client, expected).side_effect = ClientError({"Error":{"Code":"AccessDenied","Message":"fixture"}}, "Token")
    with pytest.raises(ClientError): store._connect()
    getattr(client, forbidden).assert_not_called(); assert connect.call_count == 1
    getattr(client, expected).side_effect = None
    connect.side_effect = RuntimeError("authentication rejected")
    with pytest.raises(RuntimeError, match="authentication rejected"): store._connect()
    getattr(client, forbidden).assert_not_called()


def test_runtime_factory_never_constructs_fallback_and_failed_config_is_safe_on_health_and_api(monkeypatch, offline_backends):
    bus, artifacts, _ = offline_backends
    configure(monkeypatch, CUSTOM)
    monkeypatch.setattr(I, "S3RunStore", MagicMock(side_effect=AssertionError("fallback")))
    monkeypatch.setattr(I, "S3ArtifactStore", lambda **kw: artifacts)
    monkeypatch.setattr(I, "EventBridgeBus", lambda **kw: bus)
    monkeypatch.setattr(H, "from_environment", I.from_environment)
    store = I.from_environment()[2]
    assert store.user == "lasttake_runtime" and not store.schema_bootstrap_enabled
    monkeypatch.delenv("LASTTAKE_DSQL_ENDPOINT")
    for response in [get("/healthz"), get("/api/blocked")]:
        assert response["statusCode"] == 503
        assert "lasttake_runtime" not in response["body"]
    assert post("/api/state", {"run_id":"demo-authority"})["status"] == 503
    I.S3RunStore.assert_not_called()


@pytest.mark.parametrize("path", ["/api/state", "/api/evaluate", "/api/checkpoint", "/api/blocked"])
def test_runtime_token_denial_never_retries_admin_or_reaches_a_write(path, monkeypatch, offline_backends):
    bus, artifacts, _ = offline_backends
    client = MagicMock()
    client.generate_db_connect_auth_token.side_effect = ClientError(
        {"Error":{"Code":"AccessDenied","Message":"private diagnostic"}}, "Token")
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: client)
    connect = MagicMock(side_effect=AssertionError("Token refusal must precede connection"))
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=connect))
    monkeypatch.setattr(H, "from_environment", lambda: (bus, artifacts, runtime()))
    response = get(path) if path == "/api/blocked" else post(path, {"run_id":"demo-authority"})
    assert response.get("statusCode", response.get("status")) == 503
    assert "private diagnostic" not in json.dumps(response)
    assert client.generate_db_connect_auth_token.call_count == 1
    client.generate_db_connect_admin_auth_token.assert_not_called(); connect.assert_not_called()


class RecordingDatabase:
    """Independent deny-list-free permission simulation, not a PostgreSQL/IAM engine."""
    def __init__(self, permissions, *, schema=False, ddl=False):
        self.permissions, self.schema, self.ddl = permissions, schema, ddl
        self.statements = []
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def cursor(self): return self
    def execute(self, sql, args=()):
        self.statements.append(sql)
        words = " ".join(sql.split())
        if words.startswith("CREATE TABLE"):
            assert self.ddl, "Runtime may not run DDL"
            self.schema = True
            return
        assert self.schema, "Schema must be prepared independently"
        required = set()
        for table in re.findall(r"(?:FROM|JOIN) (\w+)", words):
            required.add((table, "DELETE" if words.startswith("DELETE") else "SELECT"))
        inserted = re.match(r"INSERT INTO (\w+)", words)
        if inserted:
            required.add((inserted[1], "INSERT"))
            if "DO UPDATE" in words: required.add((inserted[1], "UPDATE"))
        assert required, "Unclassified SQL must not bypass permission map"
        for table, action in required:
            if action not in self.permissions.get(table, ()):
                raise PermissionError(f"{action} denied on {table}")
    def executemany(self, sql, rows):
        for row in rows: self.execute(sql, row)
    def fetchone(self): return ('{}',)
    def fetchall(self): return []
    def fetchmany(self, count): return []
    rowcount = 1


def all_runtime_calls(store):
    return {
        "already_handled": lambda: store.already_handled("key"),
        "mark_handled": lambda: store.mark_handled("key", "run"),
        "claim": lambda: store.claim("key", "run"),
        "release": lambda: store.release("key"),
        "save_findings": lambda: store.save_findings("run", [{"finding_id":"f","check_type":"coverage","truth_state":"unknown"}]),
        "load_findings": lambda: store.load_findings("run"),
        "delete_findings_for_checks": lambda: store.delete_findings_for_checks("run", ("coverage",)),
        "save_decision": lambda: store.save_decision("run", {"decision_id":"d","finding_id":"f"}),
        "load_decisions": lambda: store.load_decisions("run"),
        "save_packet": lambda: store.save_packet("run", {}),
        "load_packet": lambda: store.load_packet("run"),
        "append_audit": lambda: store.append_audit("run", {"kind":"ui.run.created"}),
        "load_audit": lambda: store.load_audit("run"),
        "registration_page": lambda: store.registration_page("owner", 10, None),
        "blocked_scenes": store.blocked_scenes,
    }


def test_exact_permission_map_covers_all_actual_runtime_queries_and_keeps_legitimate_deletes(monkeypatch):
    expected = {"audit":("SELECT","INSERT"),"decisions":("SELECT","INSERT"),
        "findings":("SELECT","INSERT","UPDATE","DELETE"),
        "handled_events":("SELECT","INSERT","DELETE"),"packets":("SELECT","INSERT","UPDATE")}
    assert TABLE_PERMISSIONS == expected
    db = RecordingDatabase(expected, schema=True)
    store = runtime(); monkeypatch.setattr(store, "_connect", lambda: db)
    calls = all_runtime_calls(store)
    port = {name for name, _ in inspect.getmembers(RunStore, inspect.isfunction) if not name.startswith("_")}
    assert port <= set(calls), "A new port method needs a permission-map control"
    for call in calls.values(): call()
    assert len(db.statements) == len(calls)
    assert sum(sql.startswith("DELETE") for sql in db.statements) == 2
    for forbidden in ["TRUNCATE findings", "ALTER TABLE audit ADD COLUMN extra TEXT", "GRANT SELECT ON audit TO public"]:
        with pytest.raises(AssertionError, match="Unclassified SQL"): db.execute(forbidden)


@pytest.mark.parametrize("table,method", [("findings","delete_findings_for_checks"),("handled_events","release")])
def test_permission_guard_rejects_a_map_that_breaks_required_delete(table, method, monkeypatch):
    narrowed = {name:tuple(p for p in values if name != table or p != "DELETE") for name,values in TABLE_PERMISSIONS.items()}
    db = RecordingDatabase(narrowed, schema=True); store = runtime()
    monkeypatch.setattr(store, "_connect", lambda: db)
    with pytest.raises(PermissionError, match="DELETE denied"): all_runtime_calls(store)[method]()


def test_fresh_legacy_schema_and_separately_bootstrapped_runtime_keep_cold_start_contract(monkeypatch, offline_backends):
    bus, artifacts, _ = offline_backends
    db = RecordingDatabase(TABLE_PERMISSIONS, ddl=True)
    admin = DsqlRunStore(ENDPOINT); monkeypatch.setattr(admin, "_connect", lambda: db)
    monkeypatch.setattr(H, "from_environment", lambda: (bus, artifacts, admin))
    H.build_run("demo-freshone"); H.build_run("demo-freshtwo")
    assert db.statements == list(SCHEMA_STATEMENTS)
    assert H._SCHEMA_READY is True
    # Same schema, separate connection authority, fresh process state.
    custom = runtime(); db.ddl = False
    monkeypatch.setattr(custom, "_connect", lambda: db)
    monkeypatch.setattr(H, "_SCHEMA_READY", False)
    monkeypatch.setattr(H, "from_environment", lambda: (bus, artifacts, custom))
    H.build_run("demo-runtime"); assert H._SCHEMA_READY is False
    assert db.statements == list(SCHEMA_STATEMENTS)
    with pytest.raises(DsqlConfigurationError): custom.ensure_schema()
    for call in all_runtime_calls(custom).values(): call()
    # A fresh custom runtime cannot repair an absent schema by elevating itself.
    db.schema = False
    with pytest.raises(AssertionError, match="prepared independently"): custom.load_findings("run")
    assert db.statements.count(SCHEMA_STATEMENTS[0]) == 1


def test_failed_legacy_bootstrap_does_not_mark_schema_ready(monkeypatch, offline_backends):
    bus, artifacts, _ = offline_backends
    admin = DsqlRunStore(ENDPOINT)
    monkeypatch.setattr(admin, "_connect", MagicMock(side_effect=RuntimeError("bootstrap refused")))
    monkeypatch.setattr(H, "from_environment", lambda: (bus, artifacts, admin))
    with pytest.raises(RuntimeError): H.build_run("demo-freshone")
    assert H._SCHEMA_READY is False


def test_preparation_is_inert_exactly_scoped_and_reversible_without_drops(monkeypatch, capsys):
    monkeypatch.setattr(boto3, "client", MagicMock(side_effect=AssertionError("Preparation cannot use AWS")))
    with pytest.raises(SystemExit): main(["--cluster-arn",CLUSTER,"--runtime-iam-role-arn",ROLE])
    main(["--prepare","--cluster-arn",CLUSTER,"--runtime-iam-role-arn",ROLE])
    packet = json.loads(capsys.readouterr().out)
    assert packet == prepare(CLUSTER, ROLE)
    assert packet["status"] == "PREPARATION_ONLY_NOT_APPLIED"
    assert packet["runtime_probes"] == "NOT_RUN_SECOND_APPROVAL_REQUIRED"
    assert from_environment(packet["runtime_environment_patch"]) == DsqlConfig(ENDPOINT,"lasttake_runtime","runtime",False)
    assert packet["runtime_connection_policy"]["Statement"] == [{"Effect":"Allow","Action":"dsql:DbConnect","Resource":CLUSTER}]
    assert packet["bootstrap_schema_sql"] == [s.strip()+";" for s in SCHEMA_STATEMENTS]
    assert packet["custom_role_sql"][0] == "CREATE ROLE lasttake_runtime WITH LOGIN;"
    for table, privileges in TABLE_PERMISSIONS.items():
        assert f"GRANT {', '.join(privileges)} ON TABLE public.{table} TO lasttake_runtime;" in packet["custom_role_sql"]
    assert packet["custom_role_sql"][-1] == f"AWS IAM GRANT lasttake_runtime TO '{ROLE}';"
    assert packet["rollback_order"][0]["connection_policy"]["Statement"][0]["Action"] == "dsql:DbConnectAdmin"
    assert "old environment/code" in packet["rollback_order"][0]["action"]
    assert "REVOKE" not in json.dumps(packet["rollback_order"])
    assert all("sql" not in step for step in packet["rollback_order"])
    assert packet["optional_cleanup"]["status"] == "NOT_AUTHORIZED"
    assert packet["optional_cleanup"]["approval"] == "SECOND_SEPARATE_OWNER_APPROVAL_REQUIRED"
    assert "AWS IAM REVOKE" in packet["optional_cleanup"]["sql"][0]
    sql = " ".join(packet["custom_role_sql"] + packet["optional_cleanup"]["sql"])
    for forbidden in ["DROP ","TRUNCATE ","ALL TABLES","ALL PRIVILEGES","GRANT OPTION","TO admin"]:
        assert forbidden not in sql
    boto3.client.assert_not_called()


def assert_staged_authority_contract(packet):
    # Independent literals: the generator's own permission map is NOT this oracle.
    assert packet["custom_role_sql"] == [
        "CREATE ROLE lasttake_runtime WITH LOGIN;",
        "GRANT USAGE ON SCHEMA public TO lasttake_runtime;",
        "GRANT SELECT, INSERT ON TABLE public.audit TO lasttake_runtime;",
        "GRANT SELECT, INSERT ON TABLE public.decisions TO lasttake_runtime;",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.findings TO lasttake_runtime;",
        "GRANT SELECT, INSERT, DELETE ON TABLE public.handled_events TO lasttake_runtime;",
        "GRANT SELECT, INSERT, UPDATE ON TABLE public.packets TO lasttake_runtime;",
        "AWS IAM GRANT lasttake_runtime TO 'arn:aws:iam::123456789012:role/example-runtime';",
    ]
    assert packet["runtime_connection_policy"] == {"Version":"2012-10-17","Statement":[{
        "Effect":"Allow","Action":"dsql:DbConnect","Resource":"arn:aws:dsql:eu-west-1:123456789012:cluster/example"}]}
    assert "REVOKE" not in json.dumps(packet["rollback_order"])
    assert packet["optional_cleanup"]["status"] == "NOT_AUTHORIZED"


@pytest.mark.parametrize("defect", ["all_tables","grant_option","missing_delete","admin_token","wildcard_cluster","rollback_revoke","cleanup_authorized"])
def test_independent_staged_contract_rejects_widened_authority_and_unapproved_cleanup(defect):
    packet = prepare(CLUSTER, ROLE); assert_staged_authority_contract(packet)
    if defect == "all_tables": packet["custom_role_sql"][2] = "GRANT ALL ON ALL TABLES IN SCHEMA public TO lasttake_runtime;"
    elif defect == "grant_option": packet["custom_role_sql"][2] += " WITH GRANT OPTION;"
    elif defect == "missing_delete": packet["custom_role_sql"][4] = "GRANT SELECT, INSERT, UPDATE ON TABLE public.findings TO lasttake_runtime;"
    elif defect == "admin_token": packet["runtime_connection_policy"]["Statement"][0]["Action"] = "dsql:DbConnectAdmin"
    elif defect == "wildcard_cluster": packet["runtime_connection_policy"]["Statement"][0]["Resource"] = "*"
    elif defect == "rollback_revoke": packet["rollback_order"][2]["sql"] = ["AWS IAM REVOKE lasttake_runtime FROM 'example';"]
    else: packet["optional_cleanup"]["status"] = "AUTHORIZED"
    with pytest.raises(AssertionError): assert_staged_authority_contract(packet)


@pytest.mark.parametrize("cluster,role", [(CLUSTER+"*",ROLE),(CLUSTER,ROLE+"'"),
    (CLUSTER,ROLE.replace("123456789012","999999999999")),(CLUSTER,"arn:aws:sts::123456789012:assumed-role/example/session"),
    ("",ROLE),(CLUSTER,ROLE+"/")])
def test_staged_identifiers_refuse_injection_wildcards_and_unsupported_cross_account(cluster, role):
    with pytest.raises(ValueError): prepare(cluster, role)


def test_active_dsql_authority_and_no_branch_deployment_remain_unchanged():
    root = Path(__file__).resolve().parents[1]
    stack = (root/"infra/stack.yaml").read_text()
    assert "Action: dsql:DbConnectAdmin" in stack
    for key in AUTH_KEYS: assert key not in stack
    assert "dsql_runtime_authority" not in stack
    baseline = subprocess.check_output(["git","show","fbb901caf41e624d4b200f6062794d101738236c:infra/stack.yaml"],
                                       cwd=root, text=True)
    without_comments = lambda source: [line for line in source.splitlines() if not line.lstrip().startswith("#")]
    block = lambda source,start,end: source.split(start,1)[1].split(end,1)[0]
    assert without_comments(block(stack, "  Database:", "  EventBus:")) == without_comments(
        block(baseline, "  Database:", "  EventBus:"))
    assert without_comments(block(stack, "              - Sid: ConnectToOurClusterOnly", "              - Sid: BedrockInferenceOnly")) == without_comments(
        block(baseline, "              - Sid: ConnectToOurClusterOnly", "              - Sid: BedrockInferenceOnly"))
    for workflow in ["deploy.yml","frontend-deploy.yml","live-surface.yml"]:
        source = (root/".github/workflows"/workflow).read_text()
        assert re.search(r"push:\s+branches: \[main\]", source)
        assert "codex/dsql-runtime-authority" not in source
    deploy = (root/".github/workflows/deploy.yml").read_text()
    assert "if: github.event_name == 'workflow_dispatch' && inputs.action == 'deploy'" in deploy
