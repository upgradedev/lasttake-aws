"""Explicit DSQL authority selection. No SDK calls, role grants or fallback here."""
from dataclasses import dataclass
from collections.abc import Mapping
import re


class DsqlConfigurationError(RuntimeError):
    """Refuse an inconsistent server configuration before constructing adapters."""


AUTH_KEYS = ("LASTTAKE_DSQL_USER", "LASTTAKE_DSQL_AUTH_MODE", "LASTTAKE_DSQL_BOOTSTRAP")


@dataclass(frozen=True)
class DsqlConfig:
    endpoint: str
    user: str = "admin"
    auth_mode: str = "admin"
    bootstrap: bool = True

    def __post_init__(self):
        if not isinstance(self.endpoint, str) or not re.fullmatch(
            r"[a-z0-9-]+\.dsql\.[a-z0-9-]+\.on\.aws", self.endpoint
        ):
            raise DsqlConfigurationError("A DSQL hostname is required.")
        if type(self.bootstrap) is not bool:
            raise DsqlConfigurationError("DSQL bootstrap must be an explicit boolean.")
        if self.auth_mode == "admin":
            if self.user != "admin":
                raise DsqlConfigurationError("Admin authentication requires the admin database user.")
        elif self.auth_mode == "runtime":
            if (not isinstance(self.user, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.user)
                    or self.user in {"admin", "dbowner", "public", "postgres"}
                    or self.user.startswith(("pg_", "aws_")) or self.bootstrap):
                raise DsqlConfigurationError("Runtime authentication requires a custom user and disabled bootstrap.")
        else:
            raise DsqlConfigurationError("Unknown DSQL authentication mode.")


def from_environment(env: Mapping[str, str]) -> DsqlConfig | None:
    """No new keys: retain the old admin/DDL or endpoint-absent S3 choice.

    Any new authority key opts into full validation. Partial/blank configuration
    is never interpreted as legacy mode or as permission to use S3/local storage.
    """
    endpoint = env.get("LASTTAKE_DSQL_ENDPOINT")
    if not any(key in env for key in AUTH_KEYS):
        return DsqlConfig(endpoint) if endpoint else None
    if not endpoint or not all(key in env for key in AUTH_KEYS):
        raise DsqlConfigurationError("DSQL authority configuration must include endpoint, user, auth mode and bootstrap.")
    bootstrap = env[AUTH_KEYS[2]]
    if bootstrap not in {"enabled", "disabled"}:
        raise DsqlConfigurationError("DSQL bootstrap must be enabled or disabled.")
    return DsqlConfig(endpoint, env[AUTH_KEYS[0]], env[AUTH_KEYS[1]], bootstrap == "enabled")
