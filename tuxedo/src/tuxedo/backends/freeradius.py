from __future__ import annotations

from dataclasses import dataclass

from ..config import FreeradiusSchema
from ..sql import SQLStatement


def _parse_duration_seconds(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None

    unit = raw[-1]
    if unit.isdigit():
        unit = "s"
        num = raw
    else:
        num = raw[:-1]

    try:
        n = int(num)
    except ValueError as exc:
        raise ValueError(f"Invalid duration: {value!r}") from exc

    if n < 0:
        raise ValueError(f"Invalid duration: {value!r}")

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if unit not in multipliers:
        raise ValueError(f"Invalid duration unit: {value!r} (use s/m/h/d)")
    return n * multipliers[unit]


@dataclass(frozen=True, slots=True)
class FreeradiusBackend:
    """
    Backend that maps "CLI operations" to SQL for FreeRADIUS/PostgreSQL.

    Idea: the CLI should not contain SQL; it calls backend methods that return a list of SQLStatement objects.
    This allows adding another backend later (different schema/different DB) without rewriting the CLI.

    This is `@dataclass(frozen=True, slots=True)`: fields are read-only after creation and no new attributes can be added.
    """

    schema: FreeradiusSchema

    def migrate(self) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Create vpn_groups table",
                sql=f"""
CREATE TABLE IF NOT EXISTS {self.schema.groups_table} (
  name TEXT PRIMARY KEY,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""".strip(),
            ),
            SQLStatement(
                title="Create vpn_user_blocklist table",
                sql=f"""
CREATE TABLE IF NOT EXISTS {self.schema.blocklist_table} (
  username TEXT PRIMARY KEY,
  reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ
);
""".strip(),
            ),
            SQLStatement(
                title="Create blocklist expires index",
                sql=f"CREATE INDEX IF NOT EXISTS idx_vpn_user_blocklist_expires ON {self.schema.blocklist_table} (expires_at);",
            ),
        ]

    def preflight_user_has_password(self, username: str) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Preflight: user exists (password in radcheck)",
                sql=f"""
SELECT 1
  FROM {self.schema.radcheck_table}
 WHERE username = %s
   AND attribute = 'Cleartext-Password'
   AND op = ':='
 LIMIT 1;
""".strip(),
                params=(username,),
                sensitive_params=frozenset(),
            )
        ]

    def ensure_user_has_any_group(self, username: str, *, groupname: str, priority: int) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Ensure user has at least one group (radusergroup)",
                sql=f"""
INSERT INTO {self.schema.radusergroup_table} (username, groupname, priority)
SELECT %s::text, %s::text, %s::int
WHERE NOT EXISTS (
  SELECT 1
    FROM {self.schema.radusergroup_table}
   WHERE username = %s::text
);
""".strip(),
                params=(username, groupname, int(priority), username),
            )
        ]

    def create_user(self, username: str, password: str) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Upsert user password (radcheck)",
                sql=f"""
WITH desired AS (
  SELECT %s::text AS username, %s::text AS password
),
updated AS (
  UPDATE {self.schema.radcheck_table}
     SET value = (SELECT password FROM desired)
   WHERE username = (SELECT username FROM desired)
     AND attribute = 'Cleartext-Password'
     AND op = ':='
     AND value IS DISTINCT FROM (SELECT password FROM desired)
  RETURNING 1
),
inserted AS (
  INSERT INTO {self.schema.radcheck_table} (username, attribute, op, value)
  SELECT (SELECT username FROM desired), 'Cleartext-Password', ':=', (SELECT password FROM desired)
   WHERE NOT EXISTS (
     SELECT 1
       FROM {self.schema.radcheck_table}
      WHERE username = (SELECT username FROM desired)
        AND attribute = 'Cleartext-Password'
        AND op = ':='
   )
  RETURNING 1
)
SELECT
  CASE
    WHEN EXISTS (SELECT 1 FROM updated) OR EXISTS (SELECT 1 FROM inserted) THEN 1
    ELSE 0
  END AS changed;
""".strip(),
                params=(username, password),
                sensitive_params=frozenset({1}),
            )
        ]

    def delete_user(self, username: str) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Unblock user (vpn_user_blocklist)",
                sql=f"DELETE FROM {self.schema.blocklist_table} WHERE username = %s;",
                params=(username,),
            ),
            SQLStatement(
                title="Remove group memberships (radusergroup)",
                sql=f"DELETE FROM {self.schema.radusergroup_table} WHERE username = %s;",
                params=(username,),
            ),
            SQLStatement(
                title="Remove user credentials (radcheck)",
                sql=f"DELETE FROM {self.schema.radcheck_table} WHERE username = %s;",
                params=(username,),
            ),
        ]

    def change_user(self, username: str, *, password: str | None) -> list[SQLStatement]:
        if password is None:
            raise ValueError("change user: --password is required for now")
        return self.create_user(username=username, password=password)

    def create_group(self, groupname: str, *, description: str | None) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Create group (vpn_groups)",
                sql=f"""
INSERT INTO {self.schema.groups_table} (name, description)
VALUES (%s, %s)
ON CONFLICT (name) DO UPDATE
  SET description = EXCLUDED.description;
""".strip(),
                params=(groupname, description),
            )
        ]

    def delete_group(
        self,
        groupname: str,
        *,
        reassign_orphans_to: str | None = None,
        reassign_priority: int | None = None,
    ) -> list[SQLStatement]:
        target_group = (reassign_orphans_to or self.schema.default_group_name or "").strip()
        if not target_group:
            raise ValueError("delete group: reassign_orphans_to is empty")
        if target_group == groupname:
            raise ValueError("delete group: reassign_orphans_to must differ from the deleted group")
        target_priority = int(self.schema.default_group_priority if reassign_priority is None else reassign_priority)
        return [
            SQLStatement(
                title="Delete group memberships and reassign orphans (radusergroup)",
                sql=f"""
WITH removed AS (
  DELETE FROM {self.schema.radusergroup_table}
   WHERE groupname = %s::text
  RETURNING username
),
affected AS (
  SELECT DISTINCT username FROM removed
),
orphans AS (
  SELECT a.username
    FROM affected a
   WHERE NOT EXISTS (
     SELECT 1
       FROM {self.schema.radusergroup_table} ug
      WHERE ug.username = a.username
   )
),
inserted AS (
  INSERT INTO {self.schema.radusergroup_table} (username, groupname, priority)
  SELECT o.username, %s::text, %s::int
    FROM orphans o
   WHERE NOT EXISTS (
     SELECT 1
       FROM {self.schema.radusergroup_table} ug
      WHERE ug.username = o.username
        AND ug.groupname = %s::text
   )
  RETURNING 1
)
SELECT
  (SELECT COUNT(*) FROM removed) AS removed_rows,
  (SELECT COUNT(*) FROM affected) AS affected_users,
  (SELECT COUNT(*) FROM inserted) AS reassigned_users;
""".strip(),
                params=(groupname, target_group, target_priority, target_group),
            ),
            SQLStatement(
                title="Delete group (vpn_groups)",
                sql=f"DELETE FROM {self.schema.groups_table} WHERE name = %s;",
                params=(groupname,),
            ),
        ]

    def change_group(
        self,
        groupname: str,
        *,
        rename_to: str | None,
        description: str | None,
    ) -> list[SQLStatement]:
        if rename_to is None and description is None:
            raise ValueError("change group: specify --rename or --description")

        statements: list[SQLStatement] = []
        if rename_to is not None:
            statements.extend(
                [
                    SQLStatement(
                        title="Rename group memberships (radusergroup)",
                        sql=f"UPDATE {self.schema.radusergroup_table} SET groupname = %s WHERE groupname = %s;",
                        params=(rename_to, groupname),
                    ),
                    SQLStatement(
                        title="Rename group (vpn_groups)",
                        sql=f"UPDATE {self.schema.groups_table} SET name = %s WHERE name = %s;",
                        params=(rename_to, groupname),
                    ),
                ]
            )

        if description is not None:
            target_name = rename_to or groupname
            statements.append(
                SQLStatement(
                    title="Update group description (vpn_groups)",
                    sql=f"UPDATE {self.schema.groups_table} SET description = %s WHERE name = %s;",
                    params=(description, target_name),
                )
            )

        return statements

    def add_user_to_group(self, username: str, groupname: str, *, priority: int) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Upsert group membership (radusergroup)",
                sql=f"""
WITH desired AS (
  SELECT %s::text AS username, %s::text AS groupname, %s::int AS priority
),
updated AS (
  UPDATE {self.schema.radusergroup_table}
     SET priority = (SELECT priority FROM desired)
   WHERE username = (SELECT username FROM desired)
     AND groupname = (SELECT groupname FROM desired)
     AND priority IS DISTINCT FROM (SELECT priority FROM desired)
  RETURNING 1
),
inserted AS (
  INSERT INTO {self.schema.radusergroup_table} (username, groupname, priority)
  SELECT (SELECT username FROM desired), (SELECT groupname FROM desired), (SELECT priority FROM desired)
   WHERE NOT EXISTS (
     SELECT 1
       FROM {self.schema.radusergroup_table}
      WHERE username = (SELECT username FROM desired)
        AND groupname = (SELECT groupname FROM desired)
   )
  RETURNING 1
)
SELECT
  CASE
    WHEN EXISTS (SELECT 1 FROM updated) OR EXISTS (SELECT 1 FROM inserted) THEN 1
    ELSE 0
  END AS changed;
""".strip(),
                params=(username, groupname, int(priority)),
            ),
        ]

    def remove_user_from_group(
        self,
        username: str,
        groupname: str,
        *,
        ensure_groupname: str | None = None,
        ensure_priority: int | None = None,
    ) -> list[SQLStatement]:
        target_group = (ensure_groupname or self.schema.default_group_name or "").strip()
        if not target_group:
            raise ValueError("remove: ensure_groupname is empty")
        target_priority = int(self.schema.default_group_priority if ensure_priority is None else ensure_priority)
        return [
            SQLStatement(
                title="Remove group membership and prevent orphans (radusergroup)",
                sql=f"""
WITH removed AS (
  DELETE FROM {self.schema.radusergroup_table}
   WHERE username = %s::text
     AND groupname = %s::text
  RETURNING username
),
orphans AS (
  SELECT DISTINCT r.username
    FROM removed r
   WHERE NOT EXISTS (
     SELECT 1
       FROM {self.schema.radusergroup_table} ug
      WHERE ug.username = r.username
   )
),
inserted AS (
  INSERT INTO {self.schema.radusergroup_table} (username, groupname, priority)
  SELECT o.username, %s::text, %s::int
    FROM orphans o
   WHERE NOT EXISTS (
     SELECT 1
       FROM {self.schema.radusergroup_table} ug
      WHERE ug.username = o.username
        AND ug.groupname = %s::text
   )
  RETURNING 1
)
SELECT
  (SELECT COUNT(*) FROM removed) AS removed_rows,
  (SELECT COUNT(*) FROM inserted) AS inserted_fallback;
""".strip(),
                params=(
                    username,
                    groupname,
                    target_group,
                    target_priority,
                    target_group,
                ),
            )
        ]

    def preview_delete_group(self, groupname: str) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Delete group impact (members/orphans)",
                sql=f"""
WITH members AS (
  SELECT DISTINCT username
    FROM {self.schema.radusergroup_table}
   WHERE groupname = %s::text
),
counts AS (
  SELECT m.username, COUNT(DISTINCT ug.groupname) AS groups_total
    FROM members m
    JOIN {self.schema.radusergroup_table} ug
      ON ug.username = m.username
   GROUP BY m.username
)
SELECT
  (SELECT COUNT(*) FROM members) AS members_total,
  (SELECT COUNT(*) FROM counts WHERE groups_total <= 1) AS would_be_orphans;
""".strip(),
                params=(groupname,),
            )
        ]

    def block_user(self, username: str, *, reason: str | None, duration: str | None) -> list[SQLStatement]:
        seconds = _parse_duration_seconds(duration)
        expires_at_expr = "NULL" if seconds is None else f"NOW() + ({seconds} || ' seconds')::interval"
        return [
            SQLStatement(
                title="Upsert user block (vpn_user_blocklist)",
                sql=f"""
INSERT INTO {self.schema.blocklist_table} (username, reason, created_at, expires_at)
VALUES (%s, %s, NOW(), {expires_at_expr})
ON CONFLICT (username) DO UPDATE
  SET reason = EXCLUDED.reason,
      created_at = EXCLUDED.created_at,
      expires_at = EXCLUDED.expires_at;
""".strip(),
                params=(username, reason),
            )
        ]

    def unblock_user(self, username: str) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Delete user block (vpn_user_blocklist)",
                sql=f"DELETE FROM {self.schema.blocklist_table} WHERE username = %s;",
                params=(username,),
            )
        ]

    def show_users(self) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="List users",
                sql=f"""
SELECT username
  FROM (
    SELECT DISTINCT username FROM {self.schema.radcheck_table}
    UNION
    SELECT DISTINCT username FROM {self.schema.radusergroup_table}
    UNION
    SELECT DISTINCT username FROM {self.schema.blocklist_table}
  ) u
 WHERE username IS NOT NULL AND username <> ''
 ORDER BY username;
""".strip(),
            )
        ]

    def show_groups(self) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="List groups",
                sql=f"""
SELECT groupname
  FROM (
    SELECT DISTINCT groupname FROM {self.schema.radusergroup_table}
    UNION
    SELECT DISTINCT name AS groupname FROM {self.schema.groups_table}
  ) g
 WHERE groupname IS NOT NULL AND groupname <> ''
 ORDER BY groupname;
""".strip(),
            )
        ]

    def show_blocks(self, *, all_blocks: bool) -> list[SQLStatement]:
        where = "" if all_blocks else "WHERE expires_at IS NULL OR expires_at > NOW()"
        return [
            SQLStatement(
                title="List blocks",
                sql=f"""
SELECT
  username,
  reason,
  created_at,
  expires_at,
  CASE
    WHEN expires_at IS NULL THEN NULL
    ELSE GREATEST(0, EXTRACT(EPOCH FROM (expires_at - NOW())))::bigint
  END AS expires_in_seconds
FROM {self.schema.blocklist_table}
{where}
ORDER BY created_at DESC, username;
""".strip(),
            )
        ]

    def find_user(self, username: str) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Users",
                sql=f"""
WITH matched AS (
  SELECT username
    FROM (
      SELECT DISTINCT username FROM {self.schema.radcheck_table}
      UNION
      SELECT DISTINCT username FROM {self.schema.radusergroup_table}
      UNION
      SELECT DISTINCT username FROM {self.schema.blocklist_table}
    ) u
   WHERE username IS NOT NULL
     AND username <> ''
     AND username ILIKE %s
)
SELECT
  m.username,
  EXISTS (
    SELECT 1
      FROM {self.schema.radcheck_table}
     WHERE username = m.username
       AND attribute = 'Cleartext-Password'
       AND op = ':='
  ) AS password_set,
  COALESCE(
    string_agg(g.groupname || '(' || g.priority::text || ')', ', ' ORDER BY g.priority, g.groupname),
    ''
  ) AS groups,
  b.reason,
  b.created_at,
  b.expires_at,
  CASE
    WHEN b.expires_at IS NULL THEN NULL
    ELSE GREATEST(0, EXTRACT(EPOCH FROM (b.expires_at - NOW())))::bigint
  END AS expires_in_seconds
FROM matched m
LEFT JOIN {self.schema.radusergroup_table} g
  ON g.username = m.username
LEFT JOIN {self.schema.blocklist_table} b
  ON b.username = m.username
 AND (b.expires_at IS NULL OR b.expires_at > NOW())
GROUP BY m.username, b.reason, b.created_at, b.expires_at
ORDER BY m.username;
""".strip(),
                params=(username,),
            ),
        ]

    def find_group(self, groupname: str) -> list[SQLStatement]:
        return [
            SQLStatement(
                title="Group summary",
                sql=f"""
SELECT
  %s::text AS groupname,
  (SELECT COUNT(*) FROM {self.schema.groups_table} WHERE name = %s) AS defined_in_vpn_groups,
  (SELECT description FROM {self.schema.groups_table} WHERE name = %s) AS description,
  (SELECT COUNT(*) FROM {self.schema.radusergroup_table} WHERE groupname = %s) AS members;
""".strip(),
                params=(groupname, groupname, groupname, groupname),
            ),
            SQLStatement(
                title="Group members",
                sql=f"""
SELECT username, priority
  FROM {self.schema.radusergroup_table}
 WHERE groupname = %s
 ORDER BY priority, username;
""".strip(),
                params=(groupname,),
            ),
        ]
