<div align="center">
  <p>
    <img src="docs/Logo.png" alt="TuxedoVPN logo" width="60%">
  </p>
  <h1>TuxedoVPN (Ansible)</h1>
  <p>Infrastructure as Code to deploy a small VPN platform with OpenConnect access, WireGuard mgmt mesh, and built-in observability.</p>
  <p><a href="#quick-start">Quick start</a> | <a href="#requirements">Requirements</a> | <a href="#documentation">Docs</a></p>
</div>

---

## Highlights

- **VPN gateways**: OpenConnect (`ocserv`) for user access and admin/ops access
- **Central authentication/accounting**: FreeRADIUS + PostgreSQL
- **Inter-server network**: WireGuard tunnel mgmt-vpn (`wg-mgmt`)
- **DNS**: Pi-hole on the management server, used by VPN clients and VPN nodes
- **Observability**: Prometheus + Grafana + exporters
- **Centralized logging**: Loki + Promtail (optional)
- **Optional security policy enforcement**: Suricata (NFQUEUE) + automatic temporary user blocks in RADIUS

## Topology (high level)

- `mgmt` hosts:
  - FreeRADIUS + PostgreSQL (authentication/accounting DB)
  - Prometheus + Grafana (monitoring)
  - Loki (log storage) + Promtail (log shipping)
  - Pi-hole (DNS for VPN clients/nodes)
  - DPI webhook service (writes temporary blocks into the RADIUS DB)
  - Admin VPN endpoint (ops/admin access)
- `vpn` hosts:
  - User VPN endpoint(s) (ocserv)
  - Suricata (NFQUEUE) + DPI agent (disconnect + sending events to mgmt)
  - Promtail (log shipping)

Inter-server traffic (RADIUS, DNS, Prometheus scraping) is routed through **WireGuard `wg-mgmt`** by default.

## Repository layout

- `site.yml` – main playbook (full deployment)
- `init_deploy.yaml` – bootstrap: create user `support` + sudo + SSH key
- `inventory/hosts.ini.example` – inventory template (copy to `inventory/hosts.ini`, which is ignored by git)
- `group_vars/` + `host_vars/` – configuration and per-host parameters (subnets/domains)
- `roles/` – implementation
- `docs/` – additional documentation

## Requirements

- Ansible on your workstation (controller)
- Linux hosts (primary target: Ubuntu 22.04/24.04; Vagrant uses a 22.04 box)
- SSH access (root for `init_deploy.yaml`, then user `support` with sudo)

## Quick start

### 1) Inventory

Copy the inventory template and edit it:

```bash
cp inventory/hosts.ini.example inventory/hosts.ini
```

Then define the groups:

- `[mgmt]` – management server(s)
- `[vpn]` – VPN gateway(s)

For each VPN host, set a dedicated client subnet in `host_vars/<host>.yml`:

```yaml
vpn_network_address: "10.66.1.0"
vpn_network_prefix_length: 24
vpn_domain: "vpn.example.com"
```

### 2) Secrets (Ansible Vault)

Create encrypted vault files (not committed to git):

- `group_vars/all/vault.yml` (template: `group_vars/all/__vault_template.yml`)
- `group_vars/mgmt/vault.yml` (template: `group_vars/mgmt/__vault_template.yml`)

Commands:

```bash
ansible-vault create group_vars/all/vault.yml
ansible-vault create group_vars/mgmt/vault.yml
```

Small safety notes:

- Keep the Vault password out of the repo (password manager / prompt is fine).
- CI runs a secret scan (`.github/workflows/gitleaks.yml`) to catch accidental leaks.
- `site.yml` refuses to run with placeholder secrets (`change_me_*`).

### 3) SSH key for Ansible

```bash
ssh-keygen -t ed25519 -C "ansible" -f ~/.ssh/ansible_ed25519
```

### 4) Initial access bootstrap (creates user `support`)

```bash
ansible-playbook -i inventory/hosts.ini init_deploy.yaml -u root -k -J
```

Notes:
- `-k` prompts for the current SSH password for `root`.
- `-J` prompts for the Ansible Vault password.

### 5) Deploy everything

```bash
ansible-playbook site.yml -J
```

Common targeted runs:

```bash
# Only mgmt roles (skip mgmt-wireguard if `--limit` does not include vpn hosts)
ansible-playbook site.yml -l mgmt -J --skip-tags mgmt-wireguard

# Only FreeRADIUS on mgmt
ansible-playbook site.yml -l mgmt -t freeradius -J
```

## What `site.yml` does

`site.yml` applies roles in this order:

1. **All hosts**: `common` + node_exporter (`monitoring` in node mode)
2. **mgmt+vpn**: `mgmt-wireguard` (creates `wg-mgmt` and routes)
3. **mgmt**: Prometheus+Grafana, Loki (optional), FreeRADIUS+PostgreSQL, DPI webhook, private VPN, Pi-hole, RADIUS-Pi-hole sync
   - (optional) nginx reverse proxy for Grafana/Prometheus/Pi-hole
4. **vpn**: public VPN, Suricata + DPI agent
5. **All hosts**: Promtail (optional) ships logs to Loki

## Documentation

- `docs/README.md` – documentation index
- `docs/wireguard-mgmt.md` – mgmt-vpn WireGuard tunnel design
- `docs/certificates.md` – Certbot/Let’s Encrypt notes
- `docs/metrics.md` – metrics/Prometheus jobs overview
- `docs/logging.md` – centralized logging with Loki + Promtail
- `roles/mgmt-reverse-proxy/README.md` – HTTPS reverse proxy for mgmt services
- `docs/role-map.md` – role execution map (handy for debugging)
- `docs/security-hardening.md` – security hardening notes (firewall model, optional extras)

## Optional: local Vagrant lab

`Vagrantfile` boots VMs with multiple interfaces and a pre-created `support` user.

```bash
vagrant up
vagrant up mgmt-srv-01 vpn-srv-01
```

If you really need a password login for `support` in the lab, set it via env var:

```bash
export TUXEDOVPN_VAGRANT_SUPPORT_PASSWORD='...'
```

Optional helper playbooks:

- Disable the default Vagrant NAT interface: `ansible-playbook remove-NAT-Vagrant.yml -J`
- Upgrade Ubuntu on VPN nodes: `ansible-playbook upgrade.yml -J -l vpn`
