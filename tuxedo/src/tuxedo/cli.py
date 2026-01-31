from __future__ import annotations

import argparse
import getpass
import json
import sys

from .backends import FreeradiusBackend
from .config import load_config
from .db import PostgresExecutor
from .sql import render_program


def _to_ilike_pattern(query: str) -> str:
    raw = (query or "").strip()
    if not raw:
        return "%"

    if "*" in raw or "?" in raw:
        return raw.replace("*", "%").replace("?", "_")

    if "%" in raw or "_" in raw:
        return raw

    return raw + "%"


def _print_find_users_text(results) -> None:
    if not results:
        sys.stdout.write("No users found.\n")
        return

    rows = results[0].rows or []
    if not rows:
        sys.stdout.write("No users found.\n")
        return

    for idx, row in enumerate(rows):
        username, password_set, groups, reason, created_at, expires_at, expires_in = row
        if idx:
            sys.stdout.write("\n")
        sys.stdout.write(f"{username}\n")
        sys.stdout.write(f"  password_set: {'yes' if bool(password_set) else 'no'}\n")
        groups_str = str(groups or "").strip()
        sys.stdout.write(f"  groups: {groups_str or '-'}\n")
        if reason is None:
            sys.stdout.write("  block: -\n")
            continue
        expires_at_str = "permanent" if expires_at is None else str(expires_at)
        expires_in_str = "-" if expires_in is None else f"{int(expires_in)}s"
        sys.stdout.write(f"  block: reason={reason} expires_at={expires_at_str} expires_in={expires_in_str}\n")


def _first_row(results):
    if not results:
        return None
    r0 = results[0]
    if r0.rows is None or not r0.rows:
        return None
    return tuple(r0.rows[0])


def _is_tty() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _build_parser() -> argparse.ArgumentParser:
    global_args = argparse.ArgumentParser(add_help=False)
    global_args.add_argument("--config", help="Path to tuxedo.ini (optional).")
    global_args.add_argument("--sql", action="store_true", help="Print SQL only (do not execute).")
    global_args.add_argument(
        "--show-secrets",
        action="store_true",
        help="Do not redact sensitive params (e.g., passwords) when printing SQL (--sql).",
    )
    global_args.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format for generated SQL / execution results.",
    )

    p = argparse.ArgumentParser(
        prog="tuxedo",
        description="Manage VPN users/groups via SQL (FreeRADIUS/PostgreSQL).",
        parents=[global_args],
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    migrate = sub.add_parser("migrate", help="Create/upgrade required helper tables (idempotent).", parents=[global_args])
    migrate.set_defaults(action="migrate")

    create = sub.add_parser("create", help="Create a user or a group.", parents=[global_args])
    create_sub = create.add_subparsers(dest="entity", required=True)
    create_user = create_sub.add_parser("user", help="Create user (radcheck).", parents=[global_args])
    create_user.add_argument("name")
    create_user.add_argument("--password", help="User password (Cleartext-Password). If omitted, prompt.")
    create_user.set_defaults(action="create_user")
    create_group = create_sub.add_parser("group", help="Create group (vpn_groups).", parents=[global_args])
    create_group.add_argument("name")
    create_group.add_argument("--description")
    create_group.set_defaults(action="create_group")

    delete = sub.add_parser("delete", help="Delete a user or a group.", parents=[global_args])
    delete_sub = delete.add_subparsers(dest="entity", required=True)
    delete_user = delete_sub.add_parser("user", help="Delete user (radcheck, radusergroup, blocklist).", parents=[global_args])
    delete_user.add_argument("name")
    delete_user.set_defaults(action="delete_user")
    delete_group = delete_sub.add_parser("group", help="Delete group (vpn_groups) and remove memberships.", parents=[global_args])
    delete_group.add_argument("name")
    delete_group.add_argument(
        "--reassign-orphans-to",
        metavar="GROUP",
        help="If group deletion would leave users with no groups, reassign them to this group (default: freeradius.default_group_name).",
    )
    delete_group.set_defaults(action="delete_group")

    change = sub.add_parser("change", help="Change a user or a group.", parents=[global_args])
    change_sub = change.add_subparsers(dest="entity", required=True)
    change_user = change_sub.add_parser("user", help="Change user (currently: password only).", parents=[global_args])
    change_user.add_argument("name")
    change_user.add_argument("--password", help="New password. If omitted, prompt.")
    change_user.set_defaults(action="change_user")
    change_group = change_sub.add_parser("group", help="Change group (rename/description).", parents=[global_args])
    change_group.add_argument("name")
    change_group.add_argument("--rename")
    change_group.add_argument("--description")
    change_group.set_defaults(action="change_group")

    add = sub.add_parser("add", help="Add user to group (radusergroup).", parents=[global_args])
    add.add_argument("user")
    add.add_argument("group")
    add.add_argument("--priority", type=int, default=0)
    add.set_defaults(action="add")

    remove = sub.add_parser("remove", help="Remove user from group (radusergroup).", parents=[global_args])
    remove.add_argument("user")
    remove.add_argument("group")
    remove.set_defaults(action="remove")

    block = sub.add_parser("block", help="Block user (vpn_user_blocklist).", parents=[global_args])
    block.add_argument("user")
    block.add_argument("--reason", default="MANUAL")
    block.add_argument("--for", dest="duration", help="Duration like 15m/2h/1d. Omit for permanent block.")
    block.set_defaults(action="block")

    unblock = sub.add_parser("unblock", help="Unblock user (vpn_user_blocklist).", parents=[global_args])
    unblock.add_argument("user")
    unblock.set_defaults(action="unblock")

    show = sub.add_parser("show", help="Show users/groups/blocks (read-only).", parents=[global_args])
    show_sub = show.add_subparsers(dest="entity", required=True)
    show_users = show_sub.add_parser("users", help="List users.", parents=[global_args])
    show_users.set_defaults(action="show_users")
    show_groups = show_sub.add_parser("groups", help="List groups.", parents=[global_args])
    show_groups.set_defaults(action="show_groups")
    show_blocks = show_sub.add_parser("blocks", help="List blocks.", parents=[global_args])
    show_blocks.add_argument("--all", action="store_true", help="Include expired blocks.")
    show_blocks.set_defaults(action="show_blocks")

    find = sub.add_parser("find", help="Find a user (LIKE search) or show a group (exact name).", parents=[global_args])
    find_sub = find.add_subparsers(dest="entity", required=True)
    find_user = find_sub.add_parser(
        "user",
        help="Find users and show groups + block status (supports '*' wildcards).",
        parents=[global_args],
    )
    find_user.add_argument("name")
    find_user.set_defaults(action="find_user")
    find_group = find_sub.add_parser("group", help="Show group details (members).", parents=[global_args])
    find_group.add_argument("name")
    find_group.set_defaults(action="find_group")

    return p


def _print_results_text(results):
    multi = len(results) > 1
    for r in results:
        if r.rows is None:
            sys.stdout.write(f"{r.title}: rowcount={r.rowcount}\n")
            continue
        simple_list = (not multi) and (len(r.rows) > 1) and all(len(row) == 1 for row in r.rows)
        if multi or not simple_list:
            sys.stdout.write(f"{r.title}\n")
        for row in r.rows:
            if len(row) == 1:
                sys.stdout.write(f"{row[0]}\n")
            else:
                sys.stdout.write("\t".join("" if v is None else str(v) for v in row) + "\n")


def _main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if bool(getattr(args, "show_secrets", False)) and not bool(getattr(args, "sql", False)):
        sys.stderr.write("warning: --show-secrets has effect only with --sql; ignoring.\n")
    cfg = load_config(args.config)
    backend = FreeradiusBackend(cfg.freeradius)

    if getattr(args, "action", None) == "migrate":
        statements = backend.migrate()
    elif args.action == "create_user":
        password = args.password
        if not password:
            password = getpass.getpass(f"Password for {args.name}: ")
        statements = backend.create_user(username=args.name, password=password)
        statements.extend(
            backend.ensure_user_has_any_group(
                args.name, groupname=cfg.freeradius.default_group_name, priority=cfg.freeradius.default_group_priority
            )
        )
    elif args.action == "create_group":
        statements = backend.create_group(groupname=args.name, description=args.description)
    elif args.action == "delete_user":
        statements = backend.delete_user(username=args.name)
    elif args.action == "delete_group":
        reassign_group = (args.reassign_orphans_to or cfg.freeradius.default_group_name or "").strip()
        if not reassign_group:
            raise ValueError("delete group: reassign group is empty")
        if reassign_group == args.name:
            raise ValueError("delete group: --reassign-orphans-to must differ from the deleted group")

        if not bool(args.sql):
            executor = PostgresExecutor(cfg.postgres)
            preview = executor.run(backend.preview_delete_group(groupname=args.name))
            row = _first_row(preview)
            if row is not None:
                members_total = int(row[0] or 0)
                would_orphan = int(row[1] or 0)
            else:
                members_total = 0
                would_orphan = 0

            if would_orphan > 0:
                sys.stderr.write(
                    f"warning: deleting group {args.name!r} affects {members_total} users; "
                    f"{would_orphan} would have no groups.\n"
                )
                if args.reassign_orphans_to is None and _is_tty():
                    answer = input(f"Reassign orphaned users to which group? [{reassign_group}]: ").strip()
                    if answer:
                        reassign_group = answer
                        if reassign_group == args.name:
                            raise ValueError("delete group: reassign group must differ from the deleted group")
                elif args.reassign_orphans_to is not None:
                    sys.stderr.write(f"info: orphaned users will be reassigned to {reassign_group!r}.\n")

        statements = backend.delete_group(groupname=args.name, reassign_orphans_to=reassign_group)
    elif args.action == "change_user":
        password = args.password
        if not password:
            password = getpass.getpass(f"New password for {args.name}: ")
        statements = backend.change_user(username=args.name, password=password)
        statements.extend(
            backend.ensure_user_has_any_group(
                args.name, groupname=cfg.freeradius.default_group_name, priority=cfg.freeradius.default_group_priority
            )
        )
    elif args.action == "change_group":
        statements = backend.change_group(groupname=args.name, rename_to=args.rename, description=args.description)
    elif args.action == "add":
        if not bool(args.sql):
            executor = PostgresExecutor(cfg.postgres)
            preflight = executor.run(backend.preflight_user_has_password(username=args.user))
            if _first_row(preflight) is None:
                raise ValueError(
                    f"User {args.user!r} does not exist (no Cleartext-Password in radcheck). "
                    f"Create it first: tuxedo create user {args.user} --password '...'"
                )
        statements = backend.add_user_to_group(username=args.user, groupname=args.group, priority=args.priority)
    elif args.action == "remove":
        statements = backend.remove_user_from_group(
            username=args.user,
            groupname=args.group,
            ensure_groupname=cfg.freeradius.default_group_name,
            ensure_priority=cfg.freeradius.default_group_priority,
        )
    elif args.action == "block":
        statements = backend.block_user(username=args.user, reason=args.reason, duration=args.duration)
    elif args.action == "unblock":
        statements = backend.unblock_user(username=args.user)
    elif args.action == "show_users":
        statements = backend.show_users()
    elif args.action == "show_groups":
        statements = backend.show_groups()
    elif args.action == "show_blocks":
        statements = backend.show_blocks(all_blocks=bool(args.all))
    elif args.action == "find_user":
        statements = backend.find_user(username=_to_ilike_pattern(args.name))
    elif args.action == "find_group":
        statements = backend.find_group(groupname=args.name)
    else:
        raise RuntimeError(f"Unhandled action: {args.action!r}")

    should_execute = not bool(args.sql)

    if not should_execute:
        if args.output == "json":
            payload = {"statements": [s.as_dict(show_secrets=bool(args.show_secrets)) for s in statements]}
            sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        else:
            sys.stdout.write(render_program(statements, show_secrets=bool(args.show_secrets)))
        return 0

    executor = PostgresExecutor(cfg.postgres)
    results = executor.run(statements)
    if args.output == "json":
        payload = {
            "results": [
                {"title": r.title, "rowcount": r.rowcount, "rows": r.rows if r.rows is not None else None}
                for r in results
            ]
        }
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        if args.action == "find_user":
            _print_find_users_text(results)
            return 0
        _print_results_text(results)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        return 130
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except OSError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except RuntimeError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
