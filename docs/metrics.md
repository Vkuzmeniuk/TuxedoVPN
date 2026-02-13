# Metrics overview

In this repository Prometheus + Grafana are deployed on the `mgmt` host and scrape a set of local and remote exporters.

The scrape configuration is rendered from `roles/monitoring/templates/prometheus.yml.j2`.

## Prometheus jobs (defaults)

- `prometheus`: Prometheus itself (`localhost:9090`)
- `node_<group>`: `node_exporter` for each inventory group from `prometheus_target_groups`
- `ocserv_exporter_vpn`: ocserv exporter on VPN nodes (default interval `10s`, `prometheus_ocserv_exporter_scrape_interval`)
- `dpi_agent_vpn`: DPI agent exporter on VPN nodes (default interval `5s`, `prometheus_dpi_agent_scrape_interval`)
- `freeradius_prometheus`: FreeRADIUS `rlm_prometheus` on mgmt (default interval `15s`, `prometheus_freeradius_prometheus_scrape_interval`)
- `freeradius_accounting` (optional): FreeRADIUS accounting exporter (default interval `30s`, `prometheus_freeradius_accounting_scrape_interval`)
- `radius_pihole_sync` (optional): metrics from the RADIUS → Pi-hole sync service

Note: for remote targets Prometheus prefers WireGuard IPs when `prometheus_prefer_mgmt_wireguard: true`.

Load note: avoid plotting the same KPI from multiple sources in one dashboard by default.
Recommended split:
- OCServ exporter: near-real-time operational view (sessions/connect-disconnect/current throughput)
- FreeRADIUS accounting exporter: accounting/history view (range usage, per-user totals, last-seen context)

## Exporters and endpoints

### Grafana / PromQL conventions

- `*_total` are counters: use `rate()` / `increase()`.
- `*_seconds` are seconds; `*_timestamp_seconds` is a UNIX timestamp in seconds.
- Grafana `Date & time` units expect milliseconds since epoch; multiply `*_timestamp_seconds` by `1000` for datetime panels.
- `*_bytes` / `*_octets_*` are bytes; multiply by `8` only if you need bits/sec for throughput panels.

### node_exporter (system metrics)

- Where it runs: `mgmt` + `vpn` (role: `monitoring` in node mode)
- Endpoint: `http://<host>:9100/metrics`
- Prometheus jobs: `node_mgmt`, `node_vpn` (depends on `prometheus_target_groups`)

Recommended dashboard variables:

- `job`: `label_values(up{job=~"node_.*"}, job)`
- `instance`: `label_values(up{job="$job"}, instance)`
- `nodename` (optional): `label_values(node_uname_info{job="$job"}, nodename)`

Key metrics: standard `node_*` (CPU, memory, disk, network, filesystem, etc.).

PromQL examples (common panels):

- CPU usage (Time series, unit: percent): `100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle",job=~"node_.*"}[$__rate_interval])))`
- Memory used (Time series, unit: bytes): `node_memory_MemTotal_bytes{job=~"node_.*"} - node_memory_MemAvailable_bytes{job=~"node_.*"}`
- Network RX/TX (Time series, unit: bits/sec):
  - `8 * sum by (instance) (rate(node_network_receive_bytes_total{job=~"node_.*",device!~"lo|wg.*"}[$__rate_interval]))`
  - `8 * sum by (instance) (rate(node_network_transmit_bytes_total{job=~"node_.*",device!~"lo|wg.*"}[$__rate_interval]))`

### TLS certificate expiry (node_exporter textfile collector)

- Where it runs: `mgmt` + `vpn` (monitoring role, node mode)
- Metrics:
  - `tuxedovpn_tls_cert_expiry_timestamp_seconds{cert,path}` (gauge, UNIX seconds)
  - `tuxedovpn_tls_cert_probe_success{cert,path}` (gauge, 1 if the cert file was read)
- Configure monitored certs via `tuxedovpn_cert_monitor_paths` (see `group_vars/mgmt/vars.yml` / `group_vars/vpn.yml`).

PromQL example (alert condition):

- Expiring soon (days): `(tuxedovpn_tls_cert_expiry_timestamp_seconds - time()) / 86400`

### ocserv exporter (VPN session metrics)

- Where it runs: `vpn` (role: `common-vpn`)
- Service: `ocserv-prometheus-exporter.service`
- Endpoint: `http://<vpn-host>:9813/metrics`
- Prometheus job: `ocserv_exporter_<group>` (default: `ocserv_exporter_vpn`)

Recommended dashboard variables:

- `ocserv_job`: `label_values(up{job=~"ocserv_exporter_.*"}, job)`
- `nodename`: `label_values(ocserv_scrape_timestamp{job="$ocserv_job"}, nodename)`
- `user` (active sessions only): `label_values(ocserv_sessions_bytes_received{job="$ocserv_job",nodename=~"$nodename"}, user)`

Note: the ocserv exporter adds a constant label `nodename` via `common_vpn_exporter_static_labels` (default: the system hostname / `ansible_nodename`).
This matches the `node_exporter` metric `node_uname_info{nodename=...}` and helps keep Grafana variables consistent across jobs.
Also note: series like `ocserv_sessions_bytes_received{...}` exist only when sessions are active, so `label_values(..., user)` will be empty when nobody is connected.

Metrics (custom):

- `ocserv_sessions_total` (gauge, unit: sessions) – active sessions
- `ocserv_sessions_bytes_received{nodename,user,remote,vpn_ip,group}` (gauge, unit: bytes) – per-session RX bytes snapshot
- `ocserv_sessions_bytes_sent{nodename,user,remote,vpn_ip,group}` (gauge, unit: bytes) – per-session TX bytes snapshot
- `ocserv_session_connected_seconds{nodename,user,remote,vpn_ip,group}` (gauge, unit: seconds) – session connected duration
- `ocserv_sessions_bytes_received_active_sum` / `ocserv_sessions_bytes_sent_active_sum` (gauge, unit: bytes) – snapshot sum across active sessions (can go down when sessions end)
- `ocserv_sessions_bytes_received_total` / `ocserv_sessions_bytes_sent_total` (counter, unit: bytes) – cumulative bytes across all sessions observed by exporter (useful for `rate()` throughput panels)
- `ocserv_sessions_connects_total` / `ocserv_sessions_disconnects_total` (counter, unit: sessions) – total connect/disconnect events observed by the exporter
- `ocserv_session_connects_total{user,group}` / `ocserv_session_disconnects_total{user,group}` (counter, unit: sessions) – per-user connect/disconnect events observed by the exporter
- `ocserv_exporter_session_keys_total` (gauge, unit: sessions) – number of unique session keys in the latest scrape
- `ocserv_exporter_session_key_collisions` (gauge, unit: sessions) – how many session key collisions happened in the latest scrape (should be `0`; otherwise connect/disconnect inference may be inaccurate)
- `ocserv_scrape_timestamp` (gauge, unit: UNIX seconds) – exporter scrape timestamp

Notes:

- `ocserv_sessions_bytes_*` are exported as gauges (current byte counters from ocserv). While a session is alive they behave like counters, but may reset on reconnect.
- Connect/disconnect counters are derived from a diff between consecutive scrapes. The first successful scrape after exporter start only initializes state (it does not count current sessions as "connects"). Exporter restarts reset counters; use `increase()` / `rate()` which handle counter resets.

PromQL examples (Grafana panels):

- Active sessions (Time series/Stat, unit: none): `ocserv_sessions_total{job="$ocserv_job"}`
- Total download/upload throughput (Time series, unit: bits/sec):
  - `8 * rate(ocserv_sessions_bytes_received_total{job="$ocserv_job"}[$__rate_interval])`
  - `8 * rate(ocserv_sessions_bytes_sent_total{job="$ocserv_job"}[$__rate_interval])`
- Top users by current throughput (Bar gauge, unit: bits/sec, query: Instant):
  - `topk(10, 8 * rate(ocserv_sessions_bytes_received{job="$ocserv_job"}[$__rate_interval]))`
  - `topk(10, 8 * rate(ocserv_sessions_bytes_sent{job="$ocserv_job"}[$__rate_interval]))`
- Disconnect volume (Stat, unit: none, query: Instant): `round(sum(increase(ocserv_sessions_disconnects_total{job="$ocserv_job"}[$__range])))`
- Top users by disconnects (Bar gauge, unit: none, query: Instant): `topk(10, round(sum by (user) (increase(ocserv_session_disconnects_total{job="$ocserv_job"}[$__range]))))`
- User flapping (events/min, Time series): `60 * sum by (user) (rate(ocserv_session_disconnects_total{job="$ocserv_job"}[$__rate_interval]))`

Cardinality note: the exporter emits per-session series (labels: `user`, `remote`, `vpn_ip`, `group`).

### DPI agent (enforcement + metrics)

- Where it runs: `vpn` (role: `dpi`)
- Service: `tuxedovpn-dpi-agent.service`
- Endpoint: `http://<vpn-host>:9815/metrics`
- Prometheus job: `dpi_agent_vpn`

Recommended dashboard variables:

- `nodename`: `label_values(tuxedovpn_dpi_uptime_seconds{job="dpi_agent_vpn"}, nodename)`
- `user` (optional): `label_values(tuxedovpn_dpi_events_total{job="dpi_agent_vpn",nodename="$nodename"}, user)`
- `reason` (optional): `label_values(tuxedovpn_dpi_events_total{job="dpi_agent_vpn",nodename="$nodename"}, reason)`

Metrics (custom):

- `tuxedovpn_dpi_uptime_seconds{nodename}` (gauge, unit: seconds)
- `tuxedovpn_dpi_events_total{nodename,user,reason,stage,result}` (counter, unit: events)
- `tuxedovpn_dpi_last_event_timestamp_seconds{nodename,user,reason}` (gauge, unit: UNIX seconds)

Notes:

- `tuxedovpn_dpi_events_total` is exported in two forms:
  - node-level series: `{nodename,stage,result}` (exists from process start; use for alerts/indicators)
  - per-user series: `{nodename,user,reason,stage,result}`
- `tuxedovpn_dpi_last_event_timestamp_seconds` always includes a node-level anchor series
  `{nodename,user="",reason=""}` with value `0`, plus per-user series.
- DPI signature regex is rendered into the agent config directly (not via systemd escaping), which avoids
  backslash-escaping surprises for patterns like `\b...\b`.

How to interpret `tuxedovpn_dpi_events_total`:

- This is a cumulative counter since agent start (use `increase()` / `rate()` in PromQL).
- `stage`:
  - `detect`: a Suricata EVE record matched a configured policy (ruleset/SID/regex). Coalesced: at most once per `(user, reason)` within the `DETECT_DEDUP_SECONDS` window.
  - `disconnect`: an attempt to disconnect ocserv via `occtl disconnect user <user>`.
  - `webhook`: an HTTP POST to the management webhook (throttled by `ACTION_COOLDOWN_SECONDS` per `(user-or-ip, reason)`).
- `result` (per stage):
  - `detect`: `match`
  - `disconnect`: `success`, `fail`, `error`
  - `webhook`: `success`, `fail`
- `reason`:
  - `sid:<N>` for `alert`/`drop` events with an SID.
  - `signature` / `alert` for `alert`/`drop` events without a parseable SID (fallbacks).
  - `eve:<event_type>` for non-alert EVE events (for example `eve:bittorrent_dht`).

PromQL examples:

- Actual disconnect actions: `sum by (nodename,user,reason) (increase(tuxedovpn_dpi_events_total{stage="disconnect",result="success"}[5m]))`
- Detection volume: `sum by (nodename,user,reason) (increase(tuxedovpn_dpi_events_total{stage="detect"}[5m]))`
- Node-level activity (good for "recent activity" indicators): `max by (nodename,stage,result) (increase(tuxedovpn_dpi_events_total[$__rate_interval]))`
- Event rate (Time series, unit: events/sec): `sum by (nodename,stage,result) (rate(tuxedovpn_dpi_events_total[$__rate_interval]))`
- Last event time (Table/Stat, unit: datetime): `max by (nodename,user,reason) (tuxedovpn_dpi_last_event_timestamp_seconds) * 1000`
- Unblock event (alert-friendly): `max by (nodename) (increase(tuxedovpn_dpi_events_total{stage="unblock",result="expired"}[5m])) > 0`

Alert annotation note (keep `user`/`reason`):

- The anchor series `{user="",reason=""}` is only for metric presence. If you do not filter it out,
  `topk(1, ...)` may choose the anchor and you will lose `user`/`reason`.
- For Grafana alert query `E` (latest event with labels), use:
  - `topk by (nodename) (
      1,
      tuxedovpn_dpi_last_event_timestamp_seconds{job="dpi_agent_vpn",user!="",reason!=""}
    )`
- If you need deterministic "latest per node" matching, use:
  - `(
      tuxedovpn_dpi_last_event_timestamp_seconds{job="dpi_agent_vpn",user!="",reason!=""}
    )
    == on (nodename) group_left
    max by (nodename) (
      tuxedovpn_dpi_last_event_timestamp_seconds{job="dpi_agent_vpn",user!="",reason!=""}
    )`

Logs (structured):

- DPI agent writes JSON events to journald with prefix `DPI_EVENT ` (one JSON object per line).
- Example: `journalctl -u tuxedovpn-dpi-agent -n 200 --no-pager | rg "DPI_EVENT"`

### FreeRADIUS `rlm_prometheus`

- Where it runs: `mgmt` (role: `freeradius`)
- Endpoint: `http://127.0.0.1:9812/metrics` (local)
- Prometheus job: `freeradius_prometheus`

This is the upstream Prometheus module for FreeRADIUS: it exports request counters and internal server metrics.

Troubleshooting:

- If the `freeradius_prometheus` target is `DOWN` with `connection refused`, it usually means FreeRADIUS HTTP listener is not enabled.
  On some distros `rlm_prometheus.so` is not packaged. In that case this repo falls back to a local exporter based on Status-Server
  (it is still scraped as `http://127.0.0.1:9812/metrics`).
  The fallback exporter exposes gauges `tuxedovpn_freeradius_status_*` plus `tuxedovpn_freeradius_status_exporter_scrape_success`.

### FreeRADIUS accounting exporter (radacct → Prometheus)

- Where it runs: `mgmt` (role: `freeradius`, optional)
- Service: `freeradius-accounting-exporter.service`
- Endpoint: `http://127.0.0.1:9814/metrics` (default)
- Prometheus job: `freeradius_accounting`

Recommended dashboard variables:

- `job`: `label_values(tuxedovpn_radacct_total_octets_total, job)`
- `user`: `label_values(tuxedovpn_radacct_user_total_octets_total{job="$job"}, user)`
- `remote` (optional): `label_values(tuxedovpn_radacct_user_last_seen_timestamp_seconds{job="$job"}, remote)`
- `device_id` (optional): `label_values(tuxedovpn_radacct_user_last_seen_timestamp_seconds{job="$job"}, device_id)`

Metrics (custom):

- `tuxedovpn_freeradius_accounting_exporter_scrape_success` (gauge, unit: none)
- `tuxedovpn_freeradius_accounting_exporter_scrape_duration_seconds` (gauge, unit: seconds)
- `tuxedovpn_radacct_active_sessions` (gauge, unit: sessions)
- `tuxedovpn_radacct_user_last_seen_timestamp_seconds{user,vpn_ip,remote,device_id}` (gauge, unit: UNIX seconds) – per-user last seen with best-effort context labels from `radacct` (including offline users)
- `tuxedovpn_radacct_*_octets_total` (counter, unit: bytes) – totals across all users
- `tuxedovpn_radacct_user_*_octets_total{user}` (counter, unit: bytes) – per-user totals (optionally top-N)
- `tuxedovpn_radacct_user_active_*{user}` (gauge, unit: sessions/bytes) – per-user active session snapshot
- `tuxedovpn_radacct_*_octets_by_nas_total{nas}` (counter, unit: bytes) – per-NAS totals (enabled via `freeradius_accounting_exporter_split_by_nas: true`)
- `tuxedovpn_radacct_active_*_by_nas{nas}` (gauge, unit: sessions/bytes) – per-NAS active session snapshot (enabled via `freeradius_accounting_exporter_split_by_nas: true`)
- `tuxedovpn_radacct_nas_nodename_info{nas,nodename}` (gauge, unit: none) – static NAS→nodename mapping used by the accounting exporter (when configured)

Notes:

- All `*_octets_*` metrics are bytes (octets). Multiply by `8` only if you need bits/sec.
- `*_active_*` metrics are snapshots from the latest accounting update for active sessions (not counters). There may be a delay until an interim update or a stop packet.
- For throughput comparisons vs near-real-time sources (OCServ, NIC counters), use a larger window on radacct counters:
  - recommended: 15–30 minutes (at least `3×` the `Acct-Interim-Interval`)
- If you need to align `nasipaddress` with `nodename` in Grafana, configure a NAS mapping so the exporter adds `nodename` label to per-NAS metrics.
- Per-user totals can be limited via `freeradius_accounting_exporter_top_n`. When enabled, the `user` variable will see only top-N users.
- If `radacct` rows are pruned (cleanup of long-running active sessions) or accounting updates are sparse, per-user totals may decrease. Prefer `delta(...[$__range])` (clamped to 0) for "selected range" panels and enable interim updates for more accurate time slicing.
- Labels of `tuxedovpn_radacct_user_last_seen_timestamp_seconds` depend on what the NAS sends to FreeRADIUS:
  - `vpn_ip`: `Framed-IP-Address` (usually the assigned VPN client IP)
  - `remote`: `Calling-Station-Id` (often the client's public IP, but depends on NAS)
  - `device_id`: `Connect-Info` (only if NAS/client sends it; may be empty)

PromQL examples (Grafana panels):

- Exporter health (Stat, unit: none): `max(tuxedovpn_freeradius_accounting_exporter_scrape_success{job="$job"})`
- Active sessions (Time series/Stat, unit: none): `tuxedovpn_radacct_active_sessions{job="$job"}`
- Users last seen (Table, query: Instant, value unit: datetime): `tuxedovpn_radacct_user_last_seen_timestamp_seconds{job="$job"} * 1000`
- Total throughput (Time series, unit: bits/sec): `8 * rate(tuxedovpn_radacct_total_octets_total{job="$job"}[$__rate_interval])`
- Total download/upload (Time series, unit: bits/sec):
  - `8 * rate(tuxedovpn_radacct_input_octets_total{job="$job"}[$__rate_interval])`
  - `8 * rate(tuxedovpn_radacct_output_octets_total{job="$job"}[$__rate_interval])`
- Total download/upload by NAS (Time series, unit: bits/sec, recommended window: `15m`–`30m`):
  - `8 * rate(tuxedovpn_radacct_input_octets_by_nas_total{job="$job"}[30m])`
  - `8 * rate(tuxedovpn_radacct_output_octets_by_nas_total{job="$job"}[30m])`
- Top users by current throughput (Bar gauge, unit: bits/sec, query: Instant): `topk(10, 8 * rate(tuxedovpn_radacct_user_total_octets_total{job="$job"}[$__rate_interval]))`
- Per-user throughput (Time series, unit: bits/sec, filtered): `8 * rate(tuxedovpn_radacct_user_total_octets_total{job="$job",user="$user"}[$__rate_interval])`
- Usage for selected range (Table, unit: GiB, query: Instant):
  - Download: `sum by (user) (clamp_min(delta(tuxedovpn_radacct_user_input_octets_total{job="$job"}[$__range]), 0)) / 1024 / 1024 / 1024`
  - Upload: `sum by (user) (clamp_min(delta(tuxedovpn_radacct_user_output_octets_total{job="$job"}[$__range]), 0)) / 1024 / 1024 / 1024`
  - Total: `sum by (user) (clamp_min(delta(tuxedovpn_radacct_user_total_octets_total{job="$job"}[$__range]), 0)) / 1024 / 1024 / 1024`
- Active users right now (Table, unit: none, query: Instant, format: Table): `sort_desc(tuxedovpn_radacct_user_active_sessions{job="$job"})`

### RADIUS → Pi-hole sync metrics

- Where it runs: `mgmt` (role: `radius-pihole-sync`, optional)
- Service: `tuxedovpn-radius-pihole-sync.service`
- Endpoint: `http://127.0.0.1:9817/metrics` (default)
- Prometheus job: `radius_pihole_sync`

Metrics (custom):

- `tuxedovpn_radius_pihole_sync_up` (gauge, unit: none) – 1 if the last run succeeded, otherwise 0
- `tuxedovpn_radius_pihole_sync_uptime_seconds` (gauge, unit: seconds)
- `tuxedovpn_radius_pihole_sync_last_attempt_timestamp_seconds` (gauge, unit: UNIX seconds)
- `tuxedovpn_radius_pihole_sync_last_success_timestamp_seconds` (gauge, unit: UNIX seconds)
- `tuxedovpn_radius_pihole_sync_last_duration_seconds` (gauge, unit: seconds)
- `tuxedovpn_radius_pihole_sync_errors_total` (counter, unit: errors)
- `tuxedovpn_radius_pihole_sync_reload_total` (counter, unit: reloads)
- `tuxedovpn_radius_pihole_sync_active_clients` (gauge, unit: clients)

PromQL examples (Grafana panels):

- Service health (Stat, unit: none): `max(tuxedovpn_radius_pihole_sync_up{job="radius_pihole_sync"})`
- Errors (Time series, unit: errors/min): `sum(increase(tuxedovpn_radius_pihole_sync_errors_total{job="radius_pihole_sync"}[5m]))`
- Last duration (Time series, unit: seconds): `max(tuxedovpn_radius_pihole_sync_last_duration_seconds{job="radius_pihole_sync"})`
- Last success time (Stat, unit: datetime): `max(tuxedovpn_radius_pihole_sync_last_success_timestamp_seconds{job="radius_pihole_sync"}) * 1000`

## Security notes

- Access to remote exporters is expected to be restricted via UFW and (preferably) routed over `wg-mgmt`.
  See `group_vars/vpn.yml` and `group_vars/mgmt/vars.yml`.
