# Operations (runbooks)

This file covers day-2 tasks: adding nodes/users and rotating secrets.

## Add a new VPN node (VPN gateway)

1. Add the host to your local `inventory/hosts.ini` under the `[vpn]` group.
2. Create `host_vars/<new-host>.yml` and set a **unique** VPN client subnet:
   - `vpn_network_address`
   - `vpn_network_prefix_length`
   - `vpn_domain` (used for certificates/UX)
3. Re-run WireGuard on mgmt+vpn (important):

```bash
ansible-playbook site.yml -t mgmt-wireguard -l mgmt,vpn -J
```

4. Apply roles to the new node:

```bash
ansible-playbook site.yml -l <new-host> -J
```

Notes:

- `mgmt-wireguard` auto-assigns WireGuard peer IPs in inventory order unless you override addresses per host.
- Routes to the new client subnet are added on mgmt via `wg-mgmt`.

## Add / update VPN users (RADIUS)

### Add a user with a password from Vault

1. Put the password into `group_vars/all/vault.yml` (example keys exist in `group_vars/all/__vault_template.yml`):

- `vault_vpn_default_user_password`
- `vault_vpn_user1_password`

2. Reference it from `group_vars/mgmt/vars.yml` via `freeradius_extra_users`:

```yaml
freeradius_extra_users:
  - username: "user1"
    password: "{{ vault_vpn_user1_password }}"
```

3. Apply the FreeRADIUS role on mgmt:

```bash
ansible-playbook site.yml -l mgmt -t freeradius -J
```

### Access control via RADIUS groups

FreeRADIUS uses SQL-level group membership (`radusergroup`). In this repo it is managed via:

- `freeradius_user_group_assignments` in `group_vars/mgmt/vars.yml`

Typical pattern:

- group `admins`: access to mgmt/private VPN (NAS `localhost`)
- group `default`: access only to the public VPN

"Admin-only NAS" policy is controlled via:

- `freeradius_admin_only_nas_enforce: true`
- `freeradius_admin_only_nas_shortnames: ["localhost"]`

## Secret rotation

### RADIUS shared secret

1. Update `vault_radius_shared_secret` in `group_vars/all/vault.yml`.
2. Re-deploy:

```bash
ansible-playbook site.yml -J
```

### FreeRADIUS DB password

1. Update `vault_freeradius_db_password` in `group_vars/all/vault.yml`.
2. Apply the FreeRADIUS role:

```bash
ansible-playbook site.yml -l mgmt -t freeradius -J
```

## Certificates: self-signed ↔ Certbot

TLS mode is set per host via a single variable:

- `host_vars/<host>.yml`: `tuxedovpn_tls_mode: "selfsigned" | "certbot"`

## Access to mgmt web services (current approach)

By default `mgmt_reverse_proxy_enable: false`, so services are exposed via ports (typically after connecting to the mgmt VPN):

- Grafana: `http://<mgmt-vpn-gateway-ip>:3000`
- Prometheus: `http://<mgmt-vpn-gateway-ip>:9090`
- Pi-hole: `http://<mgmt-vpn-gateway-ip>/admin` (or `http://<mgmt-vpn-gateway-ip>:80/admin`)

UFW rules in `group_vars/mgmt/vars.yml` restrict these ports to the mgmt VPN client subnet.

### Switch ocserv to Let’s Encrypt

1. Set `tuxedovpn_tls_mode: "certbot"` for the VPN host(s) (for example in `host_vars/vpn-srv-01.yml`):

```yaml
tuxedovpn_tls_mode: "certbot"
```

2. Ensure `vault_certbot_email` is set (recommended in Ansible Vault).

3. Apply roles on VPN nodes (certificate will be auto-issued if missing):

```bash
ansible-playbook site.yml -l vpn -J
```

For mgmt/private ocserv on the mgmt host:

```bash
ansible-playbook site.yml -l mgmt -t private_vpn -J
```

### Switch mgmt reverse proxy to Let’s Encrypt

1. Set `mgmt_reverse_proxy_tls_mode: "certbot"` for mgmt host(s) (for example in `host_vars/mgmt-srv-01.yml`).

2. Ensure `vault_certbot_email` is set (recommended in Ansible Vault).

3. Apply (certificate for mgmt service domains will be auto-issued if missing):

```bash
ansible-playbook site.yml -l mgmt -t mgmt_reverse_proxy -J
```

## Enable mgmt reverse proxy (HTTPS for Grafana/Prometheus/Pi-hole)

Goal: access internal web services via HTTPS **only after connecting to the mgmt VPN**.

1. Enable in `group_vars/mgmt/vars.yml`:
   - `mgmt_reverse_proxy_enable: true`
2. Pick the hostnames (per mgmt host):
   - set `grafana_domain` / `prometheus_domain` / `pihole_domain` in `host_vars/<mgmt-host>.yml`, or
   - rely on the defaults: `grafana.<mgmt_reverse_proxy_base_domain>` etc
3. Ensure Pi-hole serves matching DNS records pointing to the mgmt VPN gateway IP (example `10.66.100.1`):
   - this repo manages them automatically from the `*_domain` vars via the `pihole` role, or
   - create them manually in Pi-hole if you don't run the role.
4. Apply:

```bash
ansible-playbook site.yml -l mgmt -t mgmt_reverse_proxy -J
```

Notes:

- The role binds nginx to the mgmt VPN gateway IP to avoid a conflict with `ocserv` on `:443`.
- When enabled, the role narrows ocserv's bind address on mgmt (see `group_vars/mgmt/vars.yml`) so that `ocserv` and nginx can coexist.

## Troubleshooting

## Centralized logging (Loki)

See `docs/logging.md` for enabling Loki + Promtail and basic LogQL queries.

### WireGuard tunnel issues

Commands: `docs/wireguard-mgmt.md`. Typical checks:

- `sudo wg show wg-mgmt`
- `systemctl status wg-quick@wg-mgmt`
- `ip route | grep wg-mgmt` (on mgmt)

### RADIUS authentication errors

On mgmt:

- FreeRADIUS logs: `journalctl -u freeradius -n 200 --no-pager`
- Local test: `radtest <user> <pass> 127.0.0.1 0 <shared_secret>`

On vpn:

- Make sure `ocserv` uses the expected RADIUS server (typically the mgmt WireGuard IP).
- Verify that the firewall allows outgoing RADIUS over `wg-mgmt`.

### DPI / Suricata

On vpn:

- Suricata config test: `sudo suricata -T -c /etc/suricata/suricata.yaml`
- EVE events: `sudo tail -n 200 /var/log/suricata/eve.json`
- DPI agent logs: `journalctl -u tuxedovpn-dpi-agent -n 200 --no-pager`

On mgmt:

- DPI webhook logs: `journalctl -u tuxedovpn-dpi-blocker -n 200 --no-pager`
