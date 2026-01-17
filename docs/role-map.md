# Role execution map

This document describes the execution flow for each role, highlighting conditional branches and rescue paths, so you can reason about partially/selectively executed deployments.

## common
1. **Base (`baseline.yml`)**
   - Set timezone, install `common_packages`, create `admin_user`, import SSH keys.
   - Start and enable `chrony` and `fail2ban`.
2. **SSH hardening (`ssh.yml`)**
   - Install a drop-in config; changes trigger the `Restart ssh` handler.
3. **Unattended upgrades (`updates.yml`)**
   - Ensure `unattended-upgrades` is installed, deploy templates and enable the service.
4. **Firewall (`ufw.yml`)**
   - Install `ufw`.
   - Allow SSH only when `manage_ssh | bool` (default `true`).
   - Normalize `ufw_extra_rules`; skip downstream tasks when the list is empty.
   - Apply non-routed or routed rules depending on `item.route`.
   - Enable UFW when `ufw_enabled | bool` (default `true`).

## common-vpn
1. **Package preparation**
   - Build the package list based on `vpn_auth_mode` and `vpn_connection_test_enable`.
   - Pre-flight `dpkg --configure -a` on APT-based systems to clear/fix locks.
   - Install packages with a rescue block that retries after re-running `dpkg --configure -a`.
2. **Filesystem and certificates**
   - Create configuration directories.
   - When `vpn_cert_use_existing` is `false`, generate a self-signed cert/key via `certtool`.
   - Compute `_ocserv_cert_fullchain` and `_ocserv_cert_key` (existing files or self-signed).
3. **Credential derivation**
   - Compute `_vpn_test_password` from multiple fallbacks (default user password, become password, RADIUS secret).
4. **RADIUS integration (`vpn_auth_mode == 'radius'`)**
   - Validate that `vpn_radius_servers` is set and contains `secret` and `host`.
   - Create `/etc/radcli`, render `radiusclient.conf` and `servers`.
5. **Config rendering**
   - Render `ocserv.conf` from `common_vpn_template_src`; changes trigger `Restart ocserv`.
6. **Optional connection test (`vpn_connection_test_enable`)**
   - Compute the server certificate pin.
   - Run `openconnect --authenticate`; skipped when proxy protocol is enabled or prerequisites are missing.
7. **Service management**
   - Enable and start `ocserv`.
8. **Prometheus exporter (`common_vpn_exporter_enable`)**
   - Deploy the exporter script and unit, ensure the service is running; template changes trigger handlers.
9. **Local users (`vpn_auth_mode == 'local'` and `vpn_manage_users`)**
   - Install `python3-pexpect`.
   - Run `ocpasswd` via an expect wrapper to upsert the default user; notify `Restart ocserv`.
10. **Network tuning**
    - Include `00_detect_uplink.yml` to determine `vpn_uplink_iface` via a fallback chain.
    - Apply sysctl tuning when `common_vpn_sysctl_enable`.
    - Manage UFW rules: install baseline, optionally add NFQUEUE mangle section, filter allowlist, NAT masquerade rules. Each block is removed when prerequisites disappear.

## public-vpn / private-vpn
- Thin wrappers around `common-vpn`: provide different defaults (`templates/ocserv.conf.j2`, camouflage secrets, NAT subnets, certificate usage).
- No additional tasks; behavior is fully defined by `common-vpn`.

## freeradius
1. **Repository and packages**
   - Optionally enable upstream PPA when `freeradius_manage_repo`.
   - Install FreeRADIUS, PostgreSQL and dependencies.
   - Ensure PostgreSQL and FreeRADIUS services are enabled.
2. **Discover configuration paths**
   - Query PostgreSQL for config and `pg_hba` paths; store facts.
3. **Access preparation**
   - Build `freeradius_vpn_host_cidrs` and NAT CIDR lists from inventory.
   - Flatten and deduplicate into `freeradius_effective_cidrs`.
4. **PostgreSQL tuning**
   - Enable listen on all addresses with SSL.
   - Manage local and remote HBA entries via `blockinfile`.
5. **DB provisioning**
   - Create user, set password, create DB, grant privileges.
   - Copy schema once (sentinel file).
   - Ensure schema privileges and default privileges.
   - Optional: gigawords detection in radacct adjusts SQL expressions.
   - Create helper tables/views: blocklist, indexes, daily usage, active sessions.
6. **Manage the default VPN user (`freeradius_manage_vpn_user`)**
   - Retrieve creds via fallbacks; assert password is available.
   - Render an SQL script, apply it, remove the temporary file.
   - Verify the radcheck record exists and matches the expected password; reseed if needed.
6.1. **Optional group assignments (`freeradius_user_group_assignments`)**
   - Upsert `radusergroup` rows (username → groupname, priority).
   - Used by Pi-hole sync and optional access-control policies.
7. **radacct cleanup (`freeradius_radacct_cleanup_enable`)**
   - Deploy the cleanup script and cron; when disabled, remove both.
8. **NAS clients**
   - Build the client list from VPN hosts + additional ones.
   - Optionally add a localhost NAS entry.
   - Validate that entries contain IP/secret.
   - Normalize and render SQL to sync the `nas` table; deduplicate existing rows.
   - Mask secrets in the failure payload before `fail`.
9. **Module configuration**
   - Render and enable the SQL module, default site and optional Prometheus module/site (when `freeradius_prometheus_enable`).
   - Render the VPN policy (blocklist/limits + optional `enforce_admin_only_nas`) and optional SQL counters for simultaneous use and daily quota.
10. **Clients.conf**
    - Render the aggregated clients config.
11. **Service control**
    - Ensure FreeRADIUS is running.
12. **Validation (`freeradius_validate_vpn_user`)**
    - Flush handlers to apply configs.
    - Optionally clear stale sessions.
    - Run `radtest` via localhost until success; assert success.

## monitoring
### Node mode (`mode: node`)
1. Install `prometheus-node-exporter`.
2. Enable and start the service.

### Server mode (`mode: server`)
1. Normalize target groups, static targets and allowed CIDRs (preparation for future firewall integration).
2. Install Prometheus, render configuration, enable the service.
3. Add the Grafana repository and key, install Grafana.
4. Set the admin password in `grafana.ini`.
5. Ensure provisioning directories exist.
6. Provision Prometheus datasource and dashboard provider.
7. Enable and start `grafana-server`.

Handlers restart Prometheus or Grafana when relevant templates change.

## pihole
1. Check that Pi-hole is not installed yet. The check is based on the presence of two files:
1.1. `/usr/local/bin/pihole` — Pi-hole CLI command
1.2. `/etc/pihole/pihole.toml` — main configuration file
2. If Pi-hole is absent, perform installation steps:
2.1. Create `/etc/pihole` and the unattended install file — `/etc/pihole/setupVars.conf`
2.2. Install Pi-hole via the curl script (https://docs.pi-hole.net/main/basic-install/)
2.3. Update lists ("gravity") and set the local admin password (stored in `pihole_admin_password` in ansible-vault)
3. Open ports 80 (http) and 8443 (https) on the firewall for GUI access, and 53 (tcp/udp) for DNS queries

## mgmt-reverse-proxy (optional)
1. When `mgmt_reverse_proxy_enable` is `false`, ensure the nginx site file is absent (nginx is not needed).
2. When enabled:
   - Install nginx.
   - Choose TLS mode:
     - `selfsigned`: generate a local SAN certificate for service subdomains.
     - `certbot`: use `/etc/letsencrypt/live/<cert_name>/fullchain.pem` + `privkey.pem` (files must exist).
   - Bind to `mgmt_reverse_proxy_bind_ip:443` (expected mgmt VPN gateway IP) to avoid conflicts with ocserv.
   - Proxy:
     - `grafana.<base>` → `127.0.0.1:3000`
     - `prometheus.<base>` → `127.0.0.1:9090`
     - `pihole.<base>` → `127.0.0.1:80` (optional redirect `/` → `/admin/`)

## Role interactions
- `common` must run first so subsequent roles can rely on a consistent baseline.
- `freeradius` shares secrets (`radius_shared_secret`, managed VPN user) consumed by `common-vpn`.
- `monitoring` in server mode relies on inventory groups to enumerate scrape targets.

Conditional skips mostly depend on boolean toggles (`*_enable`), authentication mode (`vpn_auth_mode`) or inventory values. When a step is skipped, downstream assertions/tasks either short-circuit (via `when`) or remove previously created artifacts to keep idempotency.
