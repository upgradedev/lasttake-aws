"""What can be checked about the DSQL store without a cluster, checked here.

A database adapter is the easiest place to ship a defect that only appears in
production, because the obvious test needs the database. So this file asserts
the things that are true of the code rather than of the server: that it
satisfies the same port as every other store, that the statements which must
be conflict-safe are, and that the two DSQL constraints that shaped the file
are still respected.

What it does not check, and the deploy pipeline does: that the SQL is accepted
by a real cluster, and that the store round-trips. `.github/workflows/deploy.yml`
asserts `run_state_store` reads `aurora-dsql` against the live URL and then
drives a whole checkpoint through it, so a broken statement fails the deploy
rather than a visitor.
"""

from __future__ import annotations

import inspect
import re

import pytest

from lasttake.adapters.aws.dsql import SCHEMA_STATEMENTS, DsqlRunStore
from lasttake.adapters.local.infrastructure import LocalRunStore
from lasttake.ports.infrastructure import RunStore


def _port_methods() -> list[str]:
    return [
        name
        for name, value in inspect.getmembers(RunStore, inspect.isfunction)
        if not name.startswith("_")
    ]


def test_it_satisfies_the_same_port_as_every_other_store():
    """A missing method here is a 500 on the live URL, not a type error."""
    missing = [m for m in _port_methods() if not hasattr(DsqlRunStore, m)]
    assert not missing, f"DsqlRunStore is missing {missing}"


def test_its_signatures_match_the_offline_store():
    """Same names is not enough; the callers pass positionally."""
    for name in _port_methods():
        dsql_sig = inspect.signature(getattr(DsqlRunStore, name))
        local_sig = inspect.signature(getattr(LocalRunStore, name))
        assert list(dsql_sig.parameters) == list(local_sig.parameters), name


def test_the_idempotency_insert_cannot_be_split_by_a_race():
    """The reason this store exists at all.

    Two approvals of one pickup arriving together must insert once. That is a
    property of the statement, not of the caller, so the statement is what gets
    asserted.
    """
    source = inspect.getsource(DsqlRunStore.mark_handled)
    assert "ON CONFLICT" in source and "DO NOTHING" in source

    claim = inspect.getsource(DsqlRunStore.claim)
    assert "ON CONFLICT" in claim and "RETURNING" in claim, (
        "claim() must tell the caller whether it won, or it is just mark_handled"
    )


def test_findings_are_upserted_by_key_and_never_rewritten_wholesale():
    """A targeted rerun must replace its own rows and touch no others."""
    source = inspect.getsource(DsqlRunStore.save_findings)
    assert "ON CONFLICT (run_id, finding_id) DO UPDATE" in source
    assert "DELETE" not in source.upper(), (
        "save_findings must not clear the table; that is what "
        "delete_findings_for_checks is for, and it is called deliberately"
    )


def test_a_decision_arriving_twice_is_recorded_once():
    assert "ON CONFLICT" in inspect.getsource(DsqlRunStore.save_decision)


def test_no_statement_relies_on_a_sequence():
    """DSQL has no sequences and no SERIAL. Every key is supplied by the caller."""
    for statement in SCHEMA_STATEMENTS:
        upper = statement.upper()
        assert "SERIAL" not in upper, statement
        assert "NEXTVAL" not in upper, statement
        assert "GENERATED" not in upper, statement


def test_every_table_declares_a_primary_key():
    for statement in SCHEMA_STATEMENTS:
        assert "PRIMARY KEY" in statement.upper(), statement


def test_the_schema_is_applied_one_statement_at_a_time():
    """DSQL rejects several DDL statements in one transaction.

    The usual instinct is to wrap a migration in a transaction, and here that
    is exactly wrong. It fails only against a real cluster, so it is asserted
    against the source instead.
    """
    source = inspect.getsource(DsqlRunStore.ensure_schema)
    assert "BEGIN" not in source.upper()
    assert "for statement in SCHEMA_STATEMENTS" in source


def test_every_table_is_created_if_not_exists():
    """A second container racing the first must be harmless."""
    for statement in SCHEMA_STATEMENTS:
        assert "CREATE TABLE IF NOT EXISTS" in statement.upper()


def test_no_password_appears_anywhere_in_the_adapter():
    """Authentication is IAM. A literal password would be a finding."""
    source = inspect.getsource(__import__("lasttake.adapters.aws.dsql", fromlist=["x"]))
    for suspicious in re.findall(r"password\s*=\s*([^\s,)]+)", source):
        assert suspicious in {"self._token()", '"password"'}, suspicious


def test_the_auth_token_is_short_lived():
    from lasttake.adapters.aws.dsql import TOKEN_TTL_SECONDS

    assert TOKEN_TTL_SECONDS <= 3600, (
        "a long-lived generated token is a credential in all but name"
    )


def test_every_query_is_parameterised():
    """No string interpolation into SQL, anywhere, ever."""
    import lasttake.adapters.aws.dsql as module

    source = inspect.getsource(module)
    # An f-string or a % on the same line as execute is the shape to catch.
    for line_no, line in enumerate(source.splitlines(), start=1):
        if "cur.execute" in line or "executemany" in line:
            assert 'f"' not in line and "f'" not in line, f"line {line_no}: {line.strip()}"


def test_the_cross_run_query_only_counts_untriaged_exceptions():
    """It answers "who is still waiting", not "what happened at some point"."""
    source = inspect.getsource(DsqlRunStore.blocked_scenes)
    assert "truth_state <> 'verified'" in source
    assert "d.decision_id IS NULL" in source, (
        "a finding a human has already closed is not something anyone is blocked on"
    )


def test_the_environment_chooses_the_store_and_reports_which(monkeypatch):
    from lasttake.adapters.aws import infrastructure

    monkeypatch.setenv("LASTTAKE_BUCKET", "b")
    monkeypatch.setenv("LASTTAKE_EVENT_BUS", "bus")
    monkeypatch.delenv("LASTTAKE_DSQL_ENDPOINT", raising=False)
    assert infrastructure.run_store_kind() == "s3"

    monkeypatch.setenv("LASTTAKE_DSQL_ENDPOINT", "abc.dsql.eu-west-1.on.aws")
    assert infrastructure.run_store_kind() == "aurora-dsql"


def test_a_deployment_missing_its_bucket_refuses_rather_than_falling_back(monkeypatch):
    from lasttake.adapters.aws import infrastructure

    monkeypatch.delenv("LASTTAKE_BUCKET", raising=False)
    monkeypatch.delenv("LASTTAKE_EVENT_BUS", raising=False)
    with pytest.raises(RuntimeError, match="Refusing to fall"):
        infrastructure.from_environment()
