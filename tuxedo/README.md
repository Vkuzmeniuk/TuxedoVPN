# tuxedo (CLI)

`tuxedo` is a small CLI wrapper around **SQL** operations used to manage VPN users/groups.

In this repo the natural first backend is **FreeRADIUS + PostgreSQL**:

- Users: `radcheck` (`Cleartext-Password`)
- Group membership: `radusergroup` (`username → groupname`)
- Blocks: `vpn_user_blocklist` (used by a FreeRADIUS policy)

## Installation (for development)

```bash
python3 -m pip install -e ./tuxedo[postgres]
```

If your system Python is marked as "externally managed" (common on Debian/Ubuntu), use a venv:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ./tuxedo[postgres]
```

## Quick examples

Apply changes (default):

```bash
tuxedo create user alice --password '...'
tuxedo add alice admins
tuxedo block alice --reason MANUAL --for 2h
```

By default sensitive parameters (for example, passwords) are redacted in output. If you need raw values, use `--show-secrets`.

New users are automatically added to the default group (config: `freeradius.default_group_name`) if they have no groups yet.

Print SQL only (no execution):

```bash
tuxedo --sql create user alice --password '...'
tuxedo --sql add alice admins
```

Read-only queries (executed by default):

```bash
tuxedo show users
tuxedo find user alice
tuxedo find user 'a*'
tuxedo find user '*lic*'
```

Print SQL for read-only queries:

```bash
tuxedo --sql show blocks
```

Deleting groups:

- If deleting a group would leave users without groups, tuxedo will reassign them to the default group (or use `delete group --reassign-orphans-to ...`).

Apply changes to PostgreSQL:

```bash
export TUXEDO_PG_DSN='dbname=radius user=radius host=127.0.0.1 port=5432'
tuxedo migrate
tuxedo create user alice --password '...'
tuxedo add alice admins
```

## Configuration

The config file is optional. Lookup order:

1. `--config /path/to/tuxedo.ini`
2. `TUXEDO_CONFIG=/path/to/tuxedo.ini`
3. `/etc/tuxedovpn/tuxedo.ini`
4. `~/.config/tuxedo/config.ini`

Environment variables:

- `TUXEDO_PG_DSN`: libpq-style DSN (preferred)

To execute SQL (default; any command without `--sql`), install the PostgreSQL driver:

- Debian/Ubuntu: `apt install python3-psycopg2`
- pip: `python3 -m pip install -e ./tuxedo[postgres]`

Example `tuxedo.ini`:

```ini
[postgres]
dsn = dbname=radius user=radius host=127.0.0.1 port=5432

[freeradius]
radcheck_table = radcheck
radusergroup_table = radusergroup
blocklist_table = vpn_user_blocklist
groups_table = vpn_groups
```
