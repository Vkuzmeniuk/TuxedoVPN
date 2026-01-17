# mgmt-reverse-proxy (role)

Installs an nginx reverse proxy on the management server to publish internal web services
(Grafana/Prometheus/Pi-hole) over TLS.

Hostnames can be configured in two ways:

- per-service domains: `grafana_domain`, `prometheus_domain`, `pihole_domain` (recommended; set per host)
- default scheme: `grafana.<mgmt_reverse_proxy_base_domain>` etc

The role is designed to avoid conflicts with `ocserv`:

- `ocserv` must listen on the public IP (`vpn_listen_host` must not be `0.0.0.0`)
- nginx listens on the mgmt VPN gateway IP (for example `vpn_dns_client_ip`: `10.66.100.1`)
- Note: ocserv creates per-user tun devices, so this IP may not exist until a client connects; the role enables `net.ipv4.ip_nonlocal_bind=1` to allow nginx to bind anyway.

TLS mode is selected via `mgmt_reverse_proxy_tls_mode` (or per-host via `tuxedovpn_tls_mode`):

- `selfsigned` (default): generates a local SAN certificate
- `certbot`: uses `/etc/letsencrypt/live/<cert_name>/fullchain.pem` + `privkey.pem`
