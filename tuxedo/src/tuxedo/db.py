from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .config import PostgresConfig
from .sql import SQLStatement


@dataclass(frozen=True, slots=True)
class ExecResult:
    """
    Result of executing a single SQLStatement.

    - `rowcount`: number of affected rows (as reported by the driver).
    - `rows`: `fetchall()` data for queries that return rows (SELECT/RETURNING).

    This is `@dataclass(frozen=True, slots=True)`: fields are read-only after creation and no new attributes can be added.
    """

    title: str
    rowcount: int
    rows: list[tuple[Any, ...]] | None = None


class PostgresExecutor:
    """
    Executes SQLStatements in PostgreSQL (one transaction per command).

    This class exists so the CLI layer doesn't have to know psycopg2 details:
    - how to connect;
    - how to set `statement_timeout`;
    - when to call `fetchall()`.
    """

    def __init__(self, pg: PostgresConfig):
        self._pg = pg

    def run(self, statements: Sequence[SQLStatement]) -> list[ExecResult]:
        try:
            import psycopg2  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "psycopg2 is required to execute SQL. Install with: pip install ./tuxedo[postgres] "
                "or apt install python3-psycopg2 (or run with --sql)."
            ) from exc

        conn = psycopg2.connect(self._pg.dsn or "", connect_timeout=self._pg.connect_timeout_seconds)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SET statement_timeout TO %s;", (int(self._pg.statement_timeout_seconds * 1000),))
                    results: list[ExecResult] = []
                    for stmt in statements:
                        cur.execute(stmt.sql, stmt.params)
                        rows = None
                        if cur.description is not None:
                            rows = cur.fetchall()
                        results.append(ExecResult(title=stmt.title, rowcount=int(cur.rowcount), rows=rows))
            return results
        finally:
            conn.close()
