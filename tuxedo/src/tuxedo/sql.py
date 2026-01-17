from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class SQLStatement:
    """
    Description of a single SQL statement to execute/print.

    `@dataclass(...)` automatically generates `__init__`, `__repr__`, comparisons, etc.

    Decorator parameters:
    - `frozen=True`: makes the object immutable (fields can't be changed after creation) — handy for configs/DTOs.
    - `slots=True`: enables `__slots__` (less memory, faster attribute access, prevents accidental new fields).

    `sensitive_params` are 0-based indices of parameters to redact in output (`***`).
    """

    title: str
    sql: str
    params: tuple[Any, ...] = ()
    sensitive_params: frozenset[int] = frozenset()

    def as_dict(self, *, show_secrets: bool = False) -> Mapping[str, Any]:
        return {
            "title": self.title,
            "sql": self.sql,
            "params": _render_params(self.params, self.sensitive_params, show_secrets=show_secrets),
        }


def _render_params(params: tuple[Any, ...], sensitive: frozenset[int], *, show_secrets: bool) -> list[Any]:
    if show_secrets or not params or not sensitive:
        return list(params)
    rendered: list[Any] = []
    for idx, value in enumerate(params):
        rendered.append("***" if idx in sensitive else value)
    return rendered


def render_program(statements: Sequence[SQLStatement], *, show_secrets: bool = False) -> str:
    lines: list[str] = []
    for idx, stmt in enumerate(statements, start=1):
        lines.append(f"-- {idx}/{len(statements)}: {stmt.title}")
        lines.append(stmt.sql.rstrip())
        if stmt.params:
            params = _render_params(stmt.params, stmt.sensitive_params, show_secrets=show_secrets)
            lines.append(f"-- params: {params!r}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def merge_statements(chunks: Iterable[Sequence[SQLStatement]]) -> list[SQLStatement]:
    merged: list[SQLStatement] = []
    for chunk in chunks:
        merged.extend(chunk)
    return merged
