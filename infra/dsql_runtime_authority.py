"""Render staged authority preparation only. Never connects, applies SQL or deploys.

The active stack deliberately does not import this module. Real identifiers and
the generated preparation packet belong in the operator's private change record.
"""
from __future__ import annotations

import argparse
import json
import re

from lasttake.adapters.aws.dsql import SCHEMA_STATEMENTS
from lasttake.adapters.aws.dsql_config import DsqlConfig

RUNTIME_USER = "lasttake_runtime"
TABLE_PERMISSIONS = {
    "audit": ("SELECT", "INSERT"),
    "decisions": ("SELECT", "INSERT"),
    "findings": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "handled_events": ("SELECT", "INSERT", "DELETE"),
    "packets": ("SELECT", "INSERT", "UPDATE"),
}


def prepare(cluster_arn: str, runtime_iam_role_arn: str) -> dict:
    cluster = re.fullmatch(r"arn:(aws):dsql:([a-z0-9-]+):(\d{12}):cluster/([a-z0-9]+)", cluster_arn)
    role = re.fullmatch(r"arn:(aws):iam::(\d{12}):role/([A-Za-z0-9+=,.@_/-]{1,512})", runtime_iam_role_arn)
    if (not cluster or not role or role[1] != cluster[1] or role[2] != cluster[3]
            or role[3].endswith("/")):
        raise ValueError("Require exact same-account commercial AWS cluster and IAM role ARNs, without wildcards.")
    endpoint = f"{cluster[4]}.dsql.{cluster[2]}.on.aws"
    DsqlConfig(endpoint, RUNTIME_USER, "runtime", False)
    grants = [f"GRANT {', '.join(privileges)} ON TABLE public.{table} TO {RUNTIME_USER};"
              for table, privileges in TABLE_PERMISSIONS.items()]
    revokes = [f"REVOKE {', '.join(privileges)} ON TABLE public.{table} FROM {RUNTIME_USER};"
               for table, privileges in TABLE_PERMISSIONS.items()]
    policy = lambda action: {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": action, "Resource": cluster_arn}]}
    return {
        "schema": "lasttake/dsql-authority-preparation/v1",
        "status": "PREPARATION_ONLY_NOT_APPLIED",
        "runtime_probes": "NOT_RUN_SECOND_APPROVAL_REQUIRED",
        "constraints": ["No implicit execution or active-stack import.",
            "Use separate operator bootstrap authority; never give runtime schema ownership or role administration.",
            "Check existing role/mapping/catalog first. CREATE ROLE deliberately refuses an existing name.",
            "Each SQL statement is a separate committed operation, not one DDL transaction.",
            "Review inherited/public privileges too; these grants alone do not prove effective least privilege.",
            "Keep existing admin IAM until the candidate runtime is active and independently verified.",
            "Environment values below are a PATCH, never a replacement for the complete Lambda environment."],
        "bootstrap_schema_sql": [statement.strip() + ";" for statement in SCHEMA_STATEMENTS],
        "custom_role_sql": [f"CREATE ROLE {RUNTIME_USER} WITH LOGIN;",
            f"GRANT USAGE ON SCHEMA public TO {RUNTIME_USER};", *grants,
            f"AWS IAM GRANT {RUNTIME_USER} TO '{runtime_iam_role_arn}';"],
        "runtime_connection_policy": policy("dsql:DbConnect"),
        "runtime_environment_patch": {"LASTTAKE_DSQL_ENDPOINT": endpoint,
            "LASTTAKE_DSQL_USER": RUNTIME_USER, "LASTTAKE_DSQL_AUTH_MODE": "runtime",
            "LASTTAKE_DSQL_BOOTSTRAP": "disabled"},
        "rollback_order": [
            {"step": 1, "action": "Restore and verify old admin IAM authorization BEFORE old environment/code.",
             "connection_policy": policy("dsql:DbConnectAdmin")},
            {"step": 2, "action": "Restore the retained complete environment and exact old code; verify identity and acceptance."},
            {"step": 3, "action": "Verify restored health and acceptance, then stop. Preserve custom role, mappings and grants for recovery."},
        ],
        "optional_cleanup": {"status": "NOT_AUTHORIZED", "approval": "SECOND_SEPARATE_OWNER_APPROVAL_REQUIRED",
            "note": "Not part of rollback. Review exact mapping/grants again before any cleanup; retain tables, data and role.",
            "sql": [f"AWS IAM REVOKE {RUNTIME_USER} FROM '{runtime_iam_role_arn}';", *revokes,
                    f"REVOKE USAGE ON SCHEMA public FROM {RUNTIME_USER};"]},
        "sources": ["https://docs.aws.amazon.com/aurora-dsql/latest/userguide/using-database-and-iam-roles.html",
                    "https://docs.aws.amazon.com/aurora-dsql/latest/userguide/authentication-authorization.html"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Render only, with no AWS or SQL execution")
    parser.add_argument("--cluster-arn", required=True)
    parser.add_argument("--runtime-iam-role-arn", required=True)
    args = parser.parse_args(argv)
    if not args.prepare:
        parser.error("Explicit --prepare is required; this command cannot apply changes.")
    print(json.dumps(prepare(args.cluster_arn, args.runtime_iam_role_arn), indent=2))


if __name__ == "__main__":
    main()
