# Logging (Loki)

This repo already deploys **Grafana** on the `mgmt` host. Loki can be added as a log backend so you can query logs in **Grafana Explore** and correlate them with Prometheus metrics.

## What to ship to Loki (recommended)

Focus on logs that are high-signal for VPN operations and incident response:

- **ocserv** (`/var/log/ocserv.log`): auth failures, disconnects, client IPs, session lifecycle
- **FreeRADIUS** (`/var/log/freeradius/*.log` + journal): rejects, SQL errors, policy decisions, accounting
- **Suricata + DPI agent** (vpn nodes): alerts and enforcement events
  - `tuxedovpn-dpi-agent.service` journal (disconnect + webhook events)
  - `tuxedovpn-suricata.service` journal and `/var/log/suricata/fast.log`
  - Avoid enabling full `eve.json` shipping by default (high-volume)
- **Pi-hole** (`/var/log/pihole/*.log`): DNS failures/blocks for VPN clients
- **Reverse proxy** (`/var/log/nginx/*.log`): access to Grafana/Prometheus/Pi-hole via the mgmt VPN
- **System logs** (`/var/log/syslog`, `/var/log/auth.log`): SSH and base OS events
- **Project services** (journal): `tuxedovpn-dpi-blocker.service`, `tuxedovpn-radius-pihole-sync.service`
- **Fail2Ban** (`/var/log/fail2ban.log`): SSH/ocserv bans and other jail activity

## Deployment model

- `mgmt`: runs **Loki** (listens on `tcp/3100`)
- `mgmt` + `vpn`: run **Promtail** agents (push to Loki over `wg-mgmt`)
- Grafana gets a Loki datasource via provisioning (when `loki_enable: true`)

Security expectations:

- Loki is not meant to be exposed publicly. UFW rules should allow `tcp/3100` only on the WireGuard interface.

## Enable via Ansible

1) Enable roles:

```yaml
# group_vars/mgmt/vars.yml (or host_vars/<mgmt-host>.yml)
loki_enable: true
```

```yaml
# group_vars/all/vars.yml (or per-group)
promtail_enable: true
```

2) Apply:

```bash
ansible-playbook site.yml -J
```

Targeted runs:

```bash
ansible-playbook site.yml -l mgmt -t loki,monitoring_server -J
ansible-playbook site.yml -t promtail -J
```

## Notes / tuning knobs

- Loki retention defaults to **7 days** (`loki_retention_period: 168h`).
- Fail2Ban logs are shipped from `/var/log/fail2ban.log` when `promtail_fail2ban_enable: true` (defaults to `common_fail2ban_enable`).
- Suricata `eve.json` is disabled by default. To enable on vpn nodes:

```yaml
promtail_suricata_eve_enable: true
```

## Quick LogQL examples

- ocserv logs for one host:
  - `{job="ocserv",host="vpn-srv-01"}`
- DPI agent events:
  - `{job="journal",unit="tuxedovpn-dpi-agent.service"}`
- FreeRADIUS rejects:
  - `{job="freeradius"} |= "Reject"`
- Fail2Ban bans:
  - `{job="fail2ban"} |= " Ban "`
