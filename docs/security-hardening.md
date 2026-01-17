# Security hardening notes (TuxedoVPN)

This document is a collection of hardening practices and "knobs". Not everything here is enabled by default—always check `group_vars/*` and role defaults.

## Firewall model (UFW)

`roles/common/tasks/ufw.yml` sets base policies:

- deny incoming by default
- allow outgoing by default
- deny routed by default

Access to services is then allowed via `ufw_extra_rules` (see `group_vars/vpn.yml` and `group_vars/mgmt/vars.yml`).

## TLS: self-signed ↔ Certbot

TLS for `ocserv` (and the optional mgmt reverse proxy) is configured per host via a single variable:

```yaml
tuxedovpn_tls_mode: "selfsigned" # selfsigned | certbot
```

- `selfsigned` (default): roles generate local certificates/keys on hosts.
- `certbot`: roles use `/etc/letsencrypt/live/<domain>/fullchain.pem` + `privkey.pem` (issue certificates first).

Details: `docs/certificates.md`.

## mgmt web services (recommendation: expose only inside VPN)

By default Grafana/Prometheus/Pi-hole run on mgmt and can be restricted via UFW to mgmt VPN clients only.

For better UX (HTTPS + subdomains) enable the optional nginx reverse proxy role:

- `group_vars/mgmt/vars.yml`: `mgmt_reverse_proxy_enable: true`
- ensure Pi-hole serves DNS records for `grafana.<domain>`, `prometheus.<domain>`, `pihole.<domain>` pointing to the mgmt VPN gateway IP (the `pihole` role manages them automatically when `*_domain` vars are set)

## Metrics exposure

The default mode in this repo is **HTTP scraping** from mgmt (Prometheus) to exporters on mgmt/vpn.
Traffic is expected to go over `wg-mgmt`.

Basic hardening is done via allowlisting:

- VPN nodes expose exporter inbound ports only to the mgmt WireGuard IP (see `group_vars/vpn.yml`).
- mgmt dashboards are typically restricted to mgmt VPN clients (see `group_vars/mgmt/vars.yml`).
HTTPS scraping for metrics is intentionally out of scope here to keep the deployment simple.

## Control-plane isolation via WireGuard

Inter-server traffic (RADIUS, DNS, scraping) goes through `wg-mgmt`.
Design and verification: `docs/wireguard-mgmt.md`.

## fail2ban

Enabled by default in this repo (`common_fail2ban_enable: true` in `group_vars/all/vars.yml`).

If you disable it, keep an eye on brute-force exposure (at least for SSH and `ocserv`).
