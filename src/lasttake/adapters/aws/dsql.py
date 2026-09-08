"""Run state on Aurora DSQL, behind the same ``RunStore`` port as everything else.

Why a database at all, when S3 held this fine for one scene. Three things a
scene package cannot give you and a shoot cannot do without:

* **The idempotency set has to be transactional.** ``already_handled`` then
  ``mark_handled`` is read-modify-write, and on S3 two concurrent approvals of
  the same pickup can both read "not handled" and both write. That is a
  duplicate pickup request on a real assistant director's board. Here it is one
  ``INSERT ... ON CONFLICT DO NOTHING`` and the database decides.
* **Findings are updated by key, not rewritten wholesale.** The S3 store loads
  every finding, merges in memory and writes the lot back, so a targeted rerun
  and a human decision landing together lose one of the two. An upsert does not
  have that shape.
* **A day has more than one scene.** "Which scenes are still blocked, and on
  whom" is one query here and a bucket scan there.

DSQL specifically, rather than a Postgres you have to keep alive: it scales to
zero, there is no idle charge, there is no instance to size, and it speaks
ordinary Postgres so the queries below are just SQL.

**Two DSQL constraints shape this file and are not incidental.** There are no
sequences and no ``SERIAL``, so every key is supplied by the caller. And DDL
runs one statement per transaction, so :func:`ensure_schema` deliberately does
not wrap the whole thing in a transaction the way you normally would.

Authentication is IAM. There is no password anywhere in this repository or in
the deployed configuration: a short-lived token is generated per connection
from the Lambda's own role.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

#: How long a generated auth token stays valid. Short on purpose: it is minted
#: per connection, and a long-lived one would be a credential in all but name.
TOKEN_TTL_SECONDS = 900

SCHEMA_STATEMENTS = (
    # Every key is supplied by the caller. DSQL has no sequences.
    """
    CREATE TABLE IF NOT EXISTS findings (
        run_id      TEXT NOT NULL,
        finding_id  TEXT NOT NULL,
        check_type  TEXT NOT NULL,
        requirement_id TEXT,
        truth_state TEXT NOT NULL,
        body        TEXT NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (run_id, finding_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        run_id      TEXT NOT NULL,
        decision_id TEXT NOT NULL,
        finding_id  TEXT NOT NULL,
        body        TEXT NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (run_id, decision_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS packets (
        run_id      TEXT PRIMARY KEY,
        eligible    BOOLEAN NOT NULL,
        body        TEXT NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit (
        run_id      TEXT NOT NULL,
        entry_id    TEXT NOT NULL,
        kind        TEXT NOT NULL,
        body        TEXT NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (run_id, entry_id)
    )
    """,
    # The table that has to be a database. An approval arriving twice inserts
    # once, and the second caller is told so rather than finding out later.
    """
    CREATE TABLE IF NOT EXISTS handled_events (
        idempotency_key TEXT PRIMARY KEY,
        run_id          TEXT NOT NULL,
        handled_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
)


class DsqlRunStore:
    """Implements :class:`lasttake.ports.infrastructure.RunStore`.

    Connections are made per call and closed. A Lambda that holds one open
    across invocations is holding a socket the platform may freeze mid-flight,
    and the reconnect cost on DSQL is small enough that the simple thing is
    also the right one.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        region: Optional[str] = None,
        database: str = "postgres",
        user: str = "admin",
    ) -> None:
        self.endpoint = endpoint or os.environ["LASTTAKE_DSQL_ENDPOINT"]
        self.region = region or os.environ.get("AWS_REGION", "eu-west-1")
        self.database = database
        self.user = user

    # -- connection ---------------------------------------------------------

    def _token(self) -> str:
        import boto3

        client = boto3.client("dsql", region_name=self.region)
        return client.generate_db_connect_admin_auth_token(
            Hostname=self.endpoint, Region=self.region, ExpiresIn=TOKEN_TTL_SECONDS
        )

    def _connect(self):
        import psycopg

        return psycopg.connect(
            host=self.endpoint,
            dbname=self.database,
            user=self.user,
            password=self._token(),
            sslmode="require",
            autocommit=True,
        )

    def ensure_schema(self) -> None:
        """Create the tables if they are absent.

        One statement per transaction, deliberately. DSQL rejects multiple DDL
        statements in one transaction, so the usual "wrap the migration in a
        BEGIN" is exactly wrong here and fails only once you point it at a real
        cluster.
        """
        with self._connect() as conn:
            for statement in SCHEMA_STATEMENTS:
                with conn.cursor() as cur:
                    cur.execute(statement)

    # -- idempotency --------------------------------------------------------

    def already_handled(self, idempotency_key: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM handled_events WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            return cur.fetchone() is not None

    def mark_handled(self, idempotency_key: str, run_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO handled_events (idempotency_key, run_id) VALUES (%s, %s) "
                "ON CONFLICT (idempotency_key) DO NOTHING",
                (idempotency_key, run_id),
            )

    def claim(self, idempotency_key: str, run_id: str) -> bool:
        """Mark handled and say whether *this* caller was the one that did it.

        The check-then-set pair above is still racy by construction, however
        the storage behaves: two callers can both read false. This is the
        version without that gap, and it is what an approved action should use
        when the difference matters. Returns True exactly once per key, no
        matter how many callers arrive together.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO handled_events (idempotency_key, run_id) VALUES (%s, %s) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING idempotency_key",
                (idempotency_key, run_id),
            )
            return cur.fetchone() is not None

    def release(self, idempotency_key: str) -> None:
        """Give the claim back when the publish that followed it failed.

        Without this the pair is not idempotency, it is loss: the key is on
        file, the event never reached the bus, and no retry can ever send it.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM handled_events WHERE idempotency_key = %s",
                (idempotency_key,),
            )

    # -- findings -----------------------------------------------------------

    def save_findings(self, run_id: str, findings: list[dict]) -> None:
        """Upsert by ``finding_id``. A rerun replaces its own rows and no others."""
        if not findings:
            return
        rows = [
            (
                run_id,
                f["finding_id"],
                f["check_type"],
                f.get("requirement_id"),
                f["truth_state"],
                json.dumps(f, sort_keys=True),
            )
            for f in findings
        ]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO findings "
                "(run_id, finding_id, check_type, requirement_id, truth_state, body) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (run_id, finding_id) DO UPDATE SET "
                "check_type = EXCLUDED.check_type, "
                "requirement_id = EXCLUDED.requirement_id, "
                "truth_state = EXCLUDED.truth_state, "
                "body = EXCLUDED.body, "
                "recorded_at = now()",
                rows,
            )

    def load_findings(self, run_id: str) -> list[dict]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT body FROM findings WHERE run_id = %s ORDER BY finding_id",
                (run_id,),
            )
            return [json.loads(row[0]) for row in cur.fetchall()]

    def delete_findings_for_checks(self, run_id: str, check_types: tuple[str, ...]) -> int:
        """Drop the results of named checks before a targeted rerun writes new ones.

        Without this, a check that used to produce a finding for a requirement
        that no longer exists leaves the old row behind, and the gate sees a
        result for something nobody looked at.
        """
        if not check_types:
            return 0
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM findings WHERE run_id = %s AND check_type = ANY(%s)",
                (run_id, list(check_types)),
            )
            return cur.rowcount

    # -- decisions ----------------------------------------------------------

    def save_decision(self, run_id: str, decision: dict) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO decisions (run_id, decision_id, finding_id, body) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (run_id, decision_id) DO NOTHING",
                (
                    run_id,
                    decision["decision_id"],
                    decision["finding_id"],
                    json.dumps(decision, sort_keys=True),
                ),
            )

    def load_decisions(self, run_id: str) -> list[dict]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT body FROM decisions WHERE run_id = %s ORDER BY recorded_at, decision_id",
                (run_id,),
            )
            return [json.loads(row[0]) for row in cur.fetchall()]

    # -- packets ------------------------------------------------------------

    def save_packet(self, run_id: str, packet: dict) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO packets (run_id, eligible, body) VALUES (%s, %s, %s) "
                "ON CONFLICT (run_id) DO UPDATE SET "
                "eligible = EXCLUDED.eligible, body = EXCLUDED.body, recorded_at = now()",
                (run_id, bool(packet.get("eligible")), json.dumps(packet, sort_keys=True)),
            )

    def load_packet(self, run_id: str) -> Optional[dict]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT body FROM packets WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

    # -- audit --------------------------------------------------------------

    def append_audit(self, run_id: str, entry: dict) -> None:
        import uuid

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit (run_id, entry_id, kind, body) VALUES (%s, %s, %s, %s)",
                (
                    run_id,
                    entry.get("entry_id") or uuid.uuid4().hex,
                    entry.get("kind", "unknown"),
                    json.dumps(entry, sort_keys=True),
                ),
            )

    def load_audit(self, run_id: str) -> list[dict]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT body FROM audit WHERE run_id = %s ORDER BY recorded_at, entry_id",
                (run_id,),
            )
            return [json.loads(row[0]) for row in cur.fetchall()]

    # -- the query S3 could not answer -------------------------------------

    def blocked_scenes(self) -> list[dict]:
        """Every run with an open exception, and who each one is waiting on.

        This is the reason the state lives in a database. On a two-unit day a
        1st AD wants one list across every scene, not a bucket scan per scene,
        and a producer wants it without opening the tool at all.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.run_id,
                       COUNT(*) AS open_exceptions,
                       COUNT(DISTINCT f.check_type) AS departments,
                       MAX(f.recorded_at) AS last_seen
                FROM findings f
                LEFT JOIN decisions d
                       ON d.run_id = f.run_id AND d.finding_id = f.finding_id
                WHERE f.truth_state <> 'verified'
                  AND d.decision_id IS NULL
                GROUP BY f.run_id
                ORDER BY open_exceptions DESC, f.run_id
                """
            )
            return [
                {
                    "run_id": row[0],
                    "open_exceptions": row[1],
                    "departments_involved": row[2],
                    "last_seen": row[3].isoformat() if row[3] else None,
                }
                for row in cur.fetchall()
            ]
