# Quick start

This guide assumes:

- Your inventory has at least **one mgmt host** and **one vpn host**.
- For the initial bootstrap you can SSH as `root` (or you have an equivalent bootstrap access).

## 1) Configure the inventory

Start from the example inventory and keep your real one untracked:

```bash
cp inventory/hosts.ini.example inventory/hosts.ini
```

Then edit `inventory/hosts.ini` and place hosts into groups:

- `[mgmt]` – management server(s)
- `[vpn]` – VPN gateway(s)

## 2) Define VPN subnets per host

Each VPN node needs its own client subnet. Create `host_vars/<host>.yml`:

```yaml
vpn_network_address: "10.66.1.0"
vpn_network_prefix_length: 24
vpn_domain: "vpn.example.com"
```

Why this is needed:

- `mgmt-wireguard` uses VPN client subnets to add routes on mgmt.
- FreeRADIUS and Pi-hole policies may build allowlists based on these subnets.

## 3) Create vault files (secrets)

Create encrypted vault files from templates:

- `group_vars/all/vault.yml` (template: `group_vars/all/__vault_template.yml`)
- `group_vars/mgmt/vault.yml` (template: `group_vars/mgmt/__vault_template.yml`)

Commands:

```bash
ansible-vault create group_vars/all/vault.yml
ansible-vault create group_vars/mgmt/vault.yml
```

Minimal set of secrets you will typically need:

- sudo/become password (`ansible_become_password`)
- RADIUS shared secret (`vault_radius_shared_secret`)
- FreeRADIUS DB password (`vault_freeradius_db_password`)
- VPN user passwords (for example `vault_vpn_default_user_password`)
- Pi-hole/Grafana admin passwords (mgmt vault)

If you leave placeholder values like `change_me_*`, the deploy will stop early on purpose (see `site.yml` preflight checks).

## 4) Prepare the controller SSH key

```bash
ssh-keygen -t ed25519 -C "ansible" -f ~/.ssh/ansible_ed25519
```

`group_vars/all/vars.yml` expects the key at this path by default.

## 5) Bootstrap hosts (create the admin user)

`init_deploy.yaml` creates user `support` (sudo + SSH key).

```bash
ansible-playbook -i inventory/hosts.ini init_deploy.yaml -u root -k -J
```

If you rebuild hosts often (Vagrant/lab), you may want to disable host key checking just for that run:

```bash
ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook -i inventory/hosts.ini init_deploy.yaml -u root -k -J
```

## 6) Run the full deployment

```bash
ansible-playbook site.yml -J
```

## Optional: TLS mode (self-signed vs Certbot)

By default the platform uses self-signed certificates.
Switching is done per host via a single variable in `host_vars/<host>.yml`:

```yaml
tuxedovpn_tls_mode: "selfsigned" # selfsigned | certbot
```

To use Let’s Encrypt certificates:

1. Issue certificates first (see `docs/certificates.md`).
2. Set `tuxedovpn_tls_mode: "certbot"` for the required hosts (for example `host_vars/vpn-srv-01.yml`).
3. Re-run `ansible-playbook site.yml -J`.

If you use `--limit`, keep in mind:

- `mgmt-wireguard` must run **on both `mgmt` and `vpn`** (otherwise keys won't be exchanged).
- If you run only `-l mgmt`, add `--skip-tags mgmt-wireguard`.

## 7) Verification

On mgmt:

- WireGuard: `sudo wg show wg-mgmt`
- FreeRADIUS: `systemctl status freeradius`
- Prometheus: `systemctl status prometheus`
- Grafana: `systemctl status grafana-server`
- Pi-hole: `sudo pihole status`

On vpn:

- ocserv: `systemctl status ocserv`
- Suricata unit (NFQUEUE): `systemctl status tuxedovpn-suricata`
- DPI agent: `systemctl status tuxedovpn-dpi-agent`

## Optional: reverse proxy for mgmt services (Grafana/Prometheus/Pi-hole)

To expose mgmt web services via HTTPS on the mgmt VPN IP (available only after VPN login):

1. Enable the role in `group_vars/mgmt/vars.yml`:
   - `mgmt_reverse_proxy_enable: true`
2. Pick the hostnames:
   - easiest: set `grafana_domain` / `prometheus_domain` / `pihole_domain` in `host_vars/<mgmt-host>.yml`
   - fallback: the role uses `grafana.<mgmt_reverse_proxy_base_domain>` etc
3. Create matching DNS records in your internal DNS (typically Pi-hole) pointing to the mgmt VPN gateway IP (example `10.66.100.1`).
4. Apply the role:

```bash
ansible-playbook site.yml -l mgmt -t mgmt_reverse_proxy -J
```

## Optional: Vagrant lab

For local experiments use `Vagrantfile`:

```bash
vagrant up
```

If you need a password login for `support` in the lab, set it before `vagrant up`:

```bash
export TUXEDOVPN_VAGRANT_SUPPORT_PASSWORD='...'
```

To disable the default Vagrant NAT, use `remove-NAT-Vagrant.yml`.
