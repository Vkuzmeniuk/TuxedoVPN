# tuxedo-cli (role)

Deploys the `tuxedo` CLI only to **mgmt** hosts.

What it does:

- Installs `python3` + `python3-psycopg2`
- Copies `tuxedo/src/tuxedo` into `/opt/tuxedo/tuxedo`
- Installs the wrapper `/usr/local/bin/tuxedo`
- Renders `/etc/tuxedovpn/tuxedo.ini` + `/etc/tuxedovpn/tuxedo.pgpass`
- Ensures helper tables exist (`vpn_groups`, `vpn_user_blocklist`)
- Configures `freeradius.default_group_name` (fallback group)

Run:

```bash
ansible-playbook site.yml -l mgmt -t tuxedo_cli -J
```

After deployment (on the mgmt host):

```bash
tuxedo --sql show users   # print SQL only
tuxedo show users         # execute SELECT (requires Postgres access)
```

Apply changes (mutating commands):

```bash
tuxedo create user user1 --password '...'
tuxedo add user1 admins
```

If a user would otherwise be left without groups (for example after `delete group` / `remove`), tuxedo will reassign them to `freeradius.default_group_name`.
