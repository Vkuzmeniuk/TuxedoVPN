# tuxedo — CLI for VPN users/groups (SQL)

If you don’t want to hand-write SQL (or rerun half of Ansible just to change one user), `tuxedo` gives you a small set of day-2 commands:

- create/delete users (`radcheck`)
- change passwords
- manage group membership (`radusergroup`)
- block/unblock users (`vpn_user_blocklist`)

The backend in this repo is FreeRADIUS + PostgreSQL on the mgmt host.

## Quick examples

Apply changes (default):

```bash
tuxedo create user alice --password '...'
tuxedo add alice admins
tuxedo block alice --reason MANUAL --for 2h
```

Print SQL only (no execution):

```bash
tuxedo --sql create user alice --password '...'
tuxedo --sql add alice admins
```

Read-only:

```bash
tuxedo show users
tuxedo find user 'ali*'
tuxedo show blocks --all
```

Notes:

- If you omit `--password`, it will prompt.
- Sensitive params are redacted by default; add `--show-secrets` if you really need to print them.
- Each command runs in a single transaction.

## Install / config

- Dev usage and config examples live in `tuxedo/README.md`.
- In the Ansible deployment this is installed by `roles/tuxedo-cli/` (config ends up in `/etc/tuxedovpn/tuxedo.ini` on mgmt).
