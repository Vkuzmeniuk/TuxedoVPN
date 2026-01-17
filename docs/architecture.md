# Architecture

This repository deploys a small VPN platform with a clear split into:

- **Data plane**: VPN clients ↔ VPN gateways ↔ Internet
- **Control plane**: management services (authentication, DNS, monitoring, automation)

The main goal is to keep **inter-server traffic inside a dedicated WireGuard tunnel** and make most services **accessible only via firewall allowlists**.

## Components

### VPN nodes (inventory group `vpn`)

- **OpenConnect VPN** (`ocserv`)
  - User VPN endpoint (default: TCP/443)
  - Authentication via FreeRADIUS (over `wg-mgmt`) or optionally via local `ocpasswd`
- **Security policy enforcement** (optional, but enabled by default in this repo)
  - Suricata in inline **NFQUEUE** mode (ruleset focuses on detecting unauthorized P2P/torrent traffic)
  - A local agent that:
    - reads Suricata `eve.json`
    - disconnects sessions via `occtl`
    - optionally sends events to an mgmt webhook for centralized blocking
- **Observability**
  - `node_exporter` (9100)
  - `ocserv` exporter (9813)

### Management server (inventory group `mgmt`)

- **FreeRADIUS** + **PostgreSQL**
  - Central authentication and accounting DB
  - Optional policies: simultaneous-use limits, enforcement blocklist, "admin-only" per NAS clients
- **WireGuard hub** (`wg-mgmt`)
  - A single tunnel for mgmt↔vpn connectivity and routing VPN client subnets
- **Pi-hole**
  - DNS for VPN clients and (optionally) VPN nodes
  - Can be restricted by source CIDR allowlists
- **Monitoring**
  - Prometheus + Grafana (server mode)
  - Scrapes exporters on mgmt/vpn; can prefer WireGuard IPs
- **Reverse proxy (optional)**
  - TLS termination + virtual hosts for mgmt services (Grafana/Prometheus/Pi-hole)
  - Accessible only after connecting to the mgmt VPN (binds to the mgmt VPN gateway IP)
- **Automation**
  - DPI webhook receiver (VPN nodes → mgmt): writes temporary blocks into the RADIUS DB
  - RADIUS→Pi-hole sync service: maps RADIUS groups to Pi-hole client groups

## Trust boundaries

- **Public surface**: the VPN gateway listener (`tcp/443`) and anything you explicitly allow via `ufw_extra_rules`.
- **Control-plane services** (RADIUS, DNS, metrics scraping) are expected to be reachable **only**:
  - locally (`127.0.0.1`) where possible, or
  - via the WireGuard interface (`wg-mgmt`).

## TLS certificates

TLS for `ocserv` (and the optional mgmt reverse proxy) is configured per-host via:

```yaml
tuxedovpn_tls_mode: "selfsigned" # selfsigned | certbot
```

- `selfsigned` (default): roles generate local certificates on hosts.
- `certbot`: roles use `/etc/letsencrypt/live/<domain>/fullchain.pem` + `privkey.pem` (can be auto-issued when `tuxedovpn_tls_mode: certbot` is enabled and files are missing).

## Traffic flows

### Authentication and accounting

1. A VPN client connects to `ocserv` on a VPN node.
2. `ocserv` sends RADIUS auth/accounting to mgmt (FreeRADIUS) over `wg-mgmt`.
3. FreeRADIUS reads/writes state in PostgreSQL.

### DNS

- VPN clients use the DNS servers pushed by `ocserv` (typically Pi-hole on mgmt).
- VPN nodes can also use Pi-hole for their own DNS queries if needed.

### Monitoring

- Prometheus on mgmt scrapes:
  - `node_exporter` on mgmt/vpn
  - `ocserv` exporter on vpn
  - FreeRADIUS Prometheus endpoint on mgmt
- The monitoring role can prefer WireGuard IPs when available (`prometheus_prefer_mgmt_wireguard: true`).

### DPI / enforcement (optional)

- On VPN nodes:
  - mangle rules send forwarded traffic into NFQUEUE
  - Suricata writes EVE events
  - the DPI agent disconnects sessions and can send webhook events
- On mgmt:
  - the webhook receiver inserts temporary rows into `vpn_user_blocklist`
  - a FreeRADIUS policy checks this table during authentication

## Addressing model

Typically two independent address spaces are used:

- **WireGuard tunnel**: default `10.202.0.0/24`
  - mgmt: `10.202.0.1`
  - vpn peers: auto-assigned in inventory order (`10.202.0.2`, `10.202.0.3`, ...)
- **VPN client subnets**: one per VPN host, for example:
  - `vpn-srv-01`: `10.66.1.0/24`
  - `vpn-srv-02`: `10.66.2.0/24`
  - `mgmt-srv-01` (private VPN): `10.66.100.0/24`

On mgmt, routes to each client subnet are added via `wg-mgmt` so that mgmt services can talk to VPN clients if needed (for example, allowlisted dashboards).

## Ports (defaults)

The exact allowlist is defined by `ufw_extra_rules` (and role-specific toggles), but typical defaults are:

- **VPN gateways**: `tcp/443` (ocserv)
- **WireGuard**: `udp/51820` (listener on mgmt)
- **RADIUS**: `udp/1812` (auth), `udp/1813` (acct) – over `wg-mgmt`
- **DNS**: `udp/53` (+ `tcp/53` if enabled) – typically from VPN client CIDR(s) and/or `wg-mgmt`
- **Metrics**:
  - `tcp/9100` node_exporter
  - `tcp/9812` FreeRADIUS Prometheus
  - `tcp/9813` ocserv exporter
  - `tcp/9815` DPI agent metrics (vpn)
  - `tcp/9816` DPI webhook (mgmt)
  - `tcp/9817` RADIUS→Pi-hole sync metrics (mgmt)
- **Dashboards** (usually available only to mgmt VPN clients): `tcp/3000` Grafana, `tcp/9090` Prometheus
