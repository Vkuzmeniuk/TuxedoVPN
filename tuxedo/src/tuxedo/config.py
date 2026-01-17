from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path


def _env_str(name: str) -> str | None:
    raw = (os.environ.get(name, "") or "").strip()
    return raw or None


def _env_int(name: str) -> int | None:
    raw = (os.environ.get(name, "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _default_config_paths() -> list[Path]:
    home = Path.home()
    return [
        Path("/etc/tuxedovpn/tuxedo.ini"),
        home / ".config" / "tuxedo" / "config.ini",
    ]


def _is_safe_identifier(value: str) -> bool:
    # Allow schema-qualified identifiers, e.g. "public.radcheck".
    parts = (value or "").split(".")
    if not parts:
        return False
    for part in parts:
        if not part:
            return False
        if not (part[0].isalpha() or part[0] == "_"):
            return False
        for ch in part[1:]:
            if not (ch.isalnum() or ch == "_"):
                return False
    return True


@dataclass(frozen=True, slots=True)
class PostgresConfig:
    """
    PostgreSQL connection settings for executing SQL.

    `dsn` is a libpq-style DSN string (example: `dbname=radius user=radius host=127.0.0.1 port=5432`).
    Timeouts prevent the CLI from hanging on network/DB issues.

    This is `@dataclass(frozen=True, slots=True)`: fields are read-only after creation and no new attributes can be added.
    """

    dsn: str | None
    connect_timeout_seconds: int = 2
    statement_timeout_seconds: int = 5


@dataclass(frozen=True, slots=True)
class FreeradiusSchema:
    """
    "FreeRADIUS schema" in PostgreSQL: table names that `tuxedo` touches.

    This is a separate object so that:
    - tables/schema can be renamed easily via config;
    - identifiers can be validated centrally (so a table name cannot turn into SQL injection).

    This is `@dataclass(frozen=True, slots=True)`: fields are read-only after creation and no new attributes can be added.
    """

    radcheck_table: str = "radcheck"
    radusergroup_table: str = "radusergroup"
    blocklist_table: str = "vpn_user_blocklist"
    groups_table: str = "vpn_groups"
    default_group_name: str = "default"
    default_group_priority: int = 0

    def validate(self) -> None:
        for name in (
            self.radcheck_table,
            self.radusergroup_table,
            self.blocklist_table,
            self.groups_table,
        ):
            if not _is_safe_identifier(name):
                raise ValueError(f"Invalid SQL identifier in config: {name!r}")

        if not (self.default_group_name or "").strip():
            raise ValueError("Invalid config: freeradius.default_group_name is empty")

        if int(self.default_group_priority) < 0:
            raise ValueError("Invalid config: freeradius.default_group_priority must be >= 0")


@dataclass(frozen=True, slots=True)
class TuxedoConfig:
    """
    Combined `tuxedo` config: DB connection + target schema.

    This is `@dataclass(frozen=True, slots=True)`: fields are read-only after creation and no new attributes can be added.
    """

    postgres: PostgresConfig
    freeradius: FreeradiusSchema


def load_config(path: str | None) -> TuxedoConfig:
    explicit_path = Path(path).expanduser() if path else None
    if explicit_path is None:
        cfg_path = _env_str("TUXEDO_CONFIG")
        explicit_path = Path(cfg_path).expanduser() if cfg_path else None

    parser = configparser.ConfigParser()
    if explicit_path is not None:
        if not explicit_path.exists():
            raise FileNotFoundError(f"Config file not found: {explicit_path}")
        if not os.access(explicit_path, os.R_OK):
            raise PermissionError(f"Config file is not readable: {explicit_path}")
        with explicit_path.open("r", encoding="utf-8") as fh:
            parser.read_file(fh, source=str(explicit_path))
    else:
        for candidate in _default_config_paths():
            if not candidate.exists():
                continue
            if not os.access(candidate, os.R_OK):
                continue
            with candidate.open("r", encoding="utf-8") as fh:
                parser.read_file(fh, source=str(candidate))
            break

    pg_dsn = _env_str("TUXEDO_PG_DSN")
    if not pg_dsn:
        pg_dsn = parser.get("postgres", "dsn", fallback=None)

    pg_connect_timeout = _env_int("TUXEDO_PG_CONNECT_TIMEOUT_SECONDS")
    if pg_connect_timeout is None:
        pg_connect_timeout = parser.getint("postgres", "connect_timeout_seconds", fallback=2)

    pg_statement_timeout = _env_int("TUXEDO_PG_STATEMENT_TIMEOUT_SECONDS")
    if pg_statement_timeout is None:
        pg_statement_timeout = parser.getint("postgres", "statement_timeout_seconds", fallback=5)

    default_group_name = _env_str("TUXEDO_DEFAULT_GROUP_NAME")
    if not default_group_name:
        default_group_name = parser.get("freeradius", "default_group_name", fallback="default")

    default_group_priority = _env_int("TUXEDO_DEFAULT_GROUP_PRIORITY")
    if default_group_priority is None:
        default_group_priority = parser.getint("freeradius", "default_group_priority", fallback=0)

    schema = FreeradiusSchema(
        radcheck_table=parser.get("freeradius", "radcheck_table", fallback="radcheck"),
        radusergroup_table=parser.get("freeradius", "radusergroup_table", fallback="radusergroup"),
        blocklist_table=parser.get("freeradius", "blocklist_table", fallback="vpn_user_blocklist"),
        groups_table=parser.get("freeradius", "groups_table", fallback="vpn_groups"),
        default_group_name=str(default_group_name),
        default_group_priority=int(default_group_priority),
    )
    schema.validate()

    return TuxedoConfig(
        postgres=PostgresConfig(
            dsn=pg_dsn,
            connect_timeout_seconds=int(pg_connect_timeout),
            statement_timeout_seconds=int(pg_statement_timeout),
        ),
        freeradius=schema,
    )
