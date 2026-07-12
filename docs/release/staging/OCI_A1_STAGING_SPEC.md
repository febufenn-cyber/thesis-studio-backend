# OCI A1.Flex ARM64 Staging Host Specification

Date: 2026-07-12 · Branch: `agent/multiarch-arm-staging` · Target release: main
`b2c9c624cd6b6faffe4f9585ac7f4580631abd82`

**The amd64-only constraint is resolved.** `phase5-release.yml` builds one
manifest covering `linux/amd64` and `linux/arm64` (`docker buildx build
--platform linux/amd64,linux/arm64`) and the verify job asserts both platform
digests are present before push. OCI `VM.Standard.A1.Flex` (Ampere, aarch64)
is therefore a first-class staging target. This spec is the ARM64 companion to
`docs/release/staging/STAGING_PROVISIONING.md` (which still applies for
secrets, DB, R2, DNS, deploy and evidence); where the two differ on host
shape, **this document wins for the A1 host**.

Fixed decisions encoded here (owner, 2026-07-12): `AI_GLOBAL_ENABLED=false`,
`BILLING_PROVIDER=manual`, no PostgreSQL on the app VM, tunnel-only ingress,
no production changes, no credentials in chat/commits/logs (placeholders
only). Region: `ap-hyderabad-1`. Image repo:
`ghcr.io/febufenn-cyber/thesis-studio-backend`. Hostname:
`thesis-staging.robofox.online`.

---

## 1. OCI CLI launch template — VM.Standard.A1.Flex, 3 OCPU / 18 GB

### 1.1 Sizing rationale (why 3/18 inside the 2–4 OCPU / 16–24 GB range)

The Always Free ceiling is **4 OCPU / 24 GB total across ALL A1 instances in
the tenancy**. What actually runs on this host (from
`deploy/compose.phase5.yml` plus host services):

| Consumer | Steady RAM | Burst RAM | Notes |
|---|---:|---:|---|
| `clamav` (clamd) | ~2.5–3.0 GB | ~3.5 GB | Signatures resident in RAM (1.5–3.5 GB observed); reloads briefly spike |
| `worker-pdf` (LibreOffice) | ~0.3 GB | **3.0 GB hard cap** | cgroup limit `memory: 3g`; its 2 GB `/tmp` tmpfs counts against this same cap |
| `web-a` + `web-b` (uvicorn) | ~0.8 GB | ~1.0 GB | |
| `worker-general`, `worker-ai`, `maintenance` | ~0.9 GB | ~1.2 GB | 3 queue processes besides worker-pdf |
| App-service tmpfs `/tmp` (512 MB × 5) | 0 | ~1.0 GB | tmpfs is RAM-backed; counts only when written |
| nginx + cloudflared + sshd + journald | ~0.3 GB | ~0.4 GB | Host-level |
| OS + dockerd + containerd | ~1.2 GB | ~1.5 GB | |
| **Total** | **~6–7 GB** | **~13–14 GB** | |

- **18 GB, not 16 GB:** worst-case concurrency (ClamAV signature reload +
  LibreOffice conversion at its 3 GB cap + tmpfs writes) reaches ~13–14 GB;
  16 GB leaves under 2 GB for page cache and kernel, which invites host-level
  OOM (see §9). 18 GB keeps ~4 GB of genuine headroom.
- **18 GB, not 24 GB:** 24 GB consumes the entire free-tier RAM allotment,
  leaving zero for any other A1 use and no room to launch a replacement
  instance during a host swap (§12).
- **3 OCPU, not 2:** on A1, 1 OCPU = 1 physical Ampere core. Budget: one core
  for web + nginx + cloudflared, one for LibreOffice conversions (soffice is
  effectively single-threaded per conversion but saturates a core), one for
  clamd scans + the other workers. 2 OCPU serializes a scan spike against a
  conversion spike and blows p95. 4 OCPU consumes the whole free allotment
  for marginal benefit.
- Net free-tier headroom left by 3/18: **1 OCPU / 6 GB** for a scratch or
  replacement A1 instance.

**Boot volume 100 GB** (free tier allows 200 GB total block+boot storage;
minimum boot volume for A1 is 47 GB):

| Consumer | Estimate |
|---|---:|
| Ubuntu 22.04 + packages (docker, nginx, cloudflared, postgresql-client-16, awscli) | ~8 GB |
| App image ~2 GB per release × 3–5 retained versions in overlay2 | 6–10 GB |
| `clamav/clamav:1.4.5` image | ~1.4 GB |
| `clamav-db` named volume (signatures on disk) | 1–2 GB |
| `runtime-var` named volume (LibreOffice profile + conversion temp per compose) | spikes of several GB |
| Container json-file logs (20 MB × 5 files × 7 services, capped) | ~0.7 GB |
| journald (capped §13) | 0.5 GB |
| apt archives, headroom, debug captures | remainder |

Using 100 of the 200 free GB deliberately leaves room for a **second 100 GB
boot volume to exist concurrently** during host replacement (§12).

### 1.2 Auth note (required for every `oci` call)

This tenancy uses **session-token auth only**:

```bash
export OCI_CLI_AUTH=security_token       # required on EVERY oci invocation
export OCI_CLI_PROFILE=DEFAULT           # region ap-hyderabad-1 lives in this profile
oci session validate --profile DEFAULT || oci session refresh --profile DEFAULT
# First-time bootstrap (opens browser): oci session authenticate --region ap-hyderabad-1
```

### 1.3 Find the Ubuntu 22.04 aarch64 image OCID

Filtering by `--shape VM.Standard.A1.Flex` returns only aarch64-compatible
platform images (display names look like `Canonical-Ubuntu-22.04-aarch64-<date>`):

```bash
OCI_CLI_AUTH=security_token oci compute image list \
  --compartment-id CHANGE_ME_COMPARTMENT_OCID \
  --operating-system "Canonical Ubuntu" \
  --operating-system-version "22.04" \
  --shape VM.Standard.A1.Flex \
  --sort-by TIMECREATED --sort-order DESC \
  --query 'data[0].{name:"display-name",ocid:id}' --output table
```

Availability domain (ap-hyderabad-1 has a single AD):

```bash
OCI_CLI_AUTH=security_token oci iam availability-domain list \
  --compartment-id CHANGE_ME_TENANCY_OCID \
  --query 'data[].name' --output table
# Expect one entry like "Xxxx:AP-HYDERABAD-1-AD-1"
```

### 1.4 Launch command

```bash
OCI_CLI_AUTH=security_token oci compute instance launch \
  --availability-domain "CHANGE_ME_AD_NAME" \
  --compartment-id CHANGE_ME_COMPARTMENT_OCID \
  --shape VM.Standard.A1.Flex \
  --shape-config '{"ocpus": 3, "memoryInGBs": 18}' \
  --image-id CHANGE_ME_UBUNTU_2204_AARCH64_IMAGE_OCID \
  --display-name thesis-staging-arm \
  --subnet-id CHANGE_ME_STAGING_SUBNET_OCID \
  --nsg-ids '["CHANGE_ME_STAGING_NSG_OCID"]' \
  --assign-public-ip true \
  --boot-volume-size-in-gbs 100 \
  --ssh-authorized-keys-file ~/.ssh/thesis_staging_arm.pub
```

The SSH key must be a **staging-only keypair** (`ssh-keygen -t ed25519 -f
~/.ssh/thesis_staging_arm`), never a key reused from the shared production VM
(68.233.116.11).

### 1.5 Free-tier honesty

- **Capacity:** Always Free A1 capacity in `ap-hyderabad-1` is frequently
  exhausted ("Out of host capacity" on launch). There is one AD, so there is
  no AD-shopping. Realistic options: retry the launch on a loop (hours to
  days), or **upgrade the tenancy to Pay As You Go** — A1 usage within
  4 OCPU/24 GB remains billed at $0, and PAYG tenancies get priority
  capacity. Budget for this decision up front rather than being surprised.
- **Ceilings:** 4 OCPU / 24 GB across all A1 instances; 200 GB total
  boot+block storage; 2 volume backups; 10 TB/month egress (not a constraint
  here). This host's 3/18/100 fits with room for §12.
- **Idle reclamation:** Oracle reclaims *idle* Always Free A1 instances
  (sustained <20% CPU/network/memory over 7 days). A staging host that sits
  unused between test rounds can be reclaimed. PAYG tenancies are exempt.
  Mitigation if staying Always Free: keep the stack running (clamd's freshclam
  and health checks generate some baseline), or accept re-provisioning via §12.

---

## 2. Console launch checklist (alternative to §1.4)

1. Sign in at https://cloud.oracle.com → verify the region picker (top right)
   shows **India South (Hyderabad)** / `ap-hyderabad-1`.
2. Open the navigation menu (☰) → **Compute** → **Instances**.
3. In the left **Compartment** selector, pick the staging compartment
   (`CHANGE_ME_COMPARTMENT_NAME`).
4. Click **Create instance**.
5. **Name:** `thesis-staging-arm`.
6. **Placement:** accept `AD-1` (the only AD in Hyderabad).
7. **Image and shape** → **Change shape** → Instance type: *Virtual machine*
   → Shape series: **Ampere** → **VM.Standard.A1.Flex** → sliders: **OCPUs 3,
   Memory 18 GB** → Select shape.
8. **Change image** → Platform images → **Canonical Ubuntu** → **22.04** —
   with the Ampere shape already selected the console offers the aarch64
   build automatically. Select image.
9. **Primary VNIC / Networking:** select the staging VCN and the dedicated
   staging subnet (§3); tick **Assign a public IPv4 address**; expand
   advanced/**Use network security groups to control traffic** and attach
   `thesis-staging-nsg` (§4).
10. **Add SSH keys:** *Paste public keys* → paste the contents of
    `~/.ssh/thesis_staging_arm.pub` (staging-only key).
11. **Boot volume:** tick **Specify a custom boot volume size** → **100 GB**.
    Leave in-transit encryption on.
12. Click **Create**. Wait for state **RUNNING**; record the public IP — this
    becomes the `STAGING_HOST` GitHub environment secret
    (set per STAGING_PROVISIONING.md §7, value via stdin, never in chat).

---

## 3. VCN / subnet layout

- Use a **dedicated staging subnet** (e.g. a new regional public subnet
  `10.0.8.0/28` in the existing VCN, or a fresh VCN entirely) so staging
  rules can never loosen anything the production/shared VM relies on. The
  shared VM (68.233.116.11) must not be in this subnet.
- Attach a **dedicated NSG** (`thesis-staging-nsg`) to the instance VNIC and
  put all rules there (§4). Strip the subnet's *default security list* of its
  stock world-open TCP 22 rule (or attach an empty custom security list) so
  the NSG is the single source of truth.
- **Ingress is EMPTY** by default. All HTTP reaches the host via the
  Cloudflare Tunnel's *outbound* connections (§6). Optionally allow SSH
  ingress TCP 22 from `CHANGE_ME_OWNER_IP/32` only, and delete that rule once
  tunnel-based access is proven (§5).
- Public IP + empty-ingress NSG is the simple posture. A stricter variant
  (private subnet + NAT gateway, no public IP) also works — OCI NAT gateways
  carry no hourly charge — but complicates first-boot SSH; not required for
  staging.
- DNS (VCN resolver) and the metadata/NTP service live on link-local
  `169.254.169.254` and are not subject to NSG evaluation.

---

## 4. NSG rules table

| # | Direction | Protocol | Port | Source / Destination | Purpose |
|---|---|---|---|---|---|
| 1 | Ingress | — | — | — | **None.** (Optional, temporary: TCP 22 from `CHANGE_ME_OWNER_IP/32` — remove after §5.) |
| 2 | Egress | TCP | 443 | 0.0.0.0/0 | R2, GHCR, Resend, ClamAV signatures, Docker Hub, apt-over-https, Cloudflare APIs (full host list in §7) |
| 3 | Egress | TCP | 5432 | `CHANGE_ME_DB_HOST_IP/32` (or provider CIDR) | Isolated PostgreSQL, TLS (`?ssl=require`) |
| 4 | Egress | UDP | 7844 | 0.0.0.0/0 | cloudflared QUIC to Cloudflare edge (`region{1,2}.v2.argotunnel.com`) |
| 5 | Egress | TCP | 7844 | 0.0.0.0/0 | cloudflared http2 fallback |
| 6 | Egress | TCP | 80 | 0.0.0.0/0 | Ubuntu arm64 mirrors (`ports.ubuntu.com` serves apt over http) |
| 7 | Egress | UDP | 123 | 0.0.0.0/0 | NTP (optional; OCI serves time on link-local 169.254.169.254 which bypasses NSG) |
| 8 | Egress | UDP+TCP | 53 | 0.0.0.0/0 | DNS (optional; the VCN resolver on 169.254.169.254 bypasses NSG) |

Rows 2–6 are the minimum working set. If rule sprawl is not worth it for
staging, an egress allow-all with the **empty ingress** intact is an
acceptable interim posture — the security property this host depends on is
"no inbound path except the tunnel", not egress micro-segmentation.

---

## 5. SSH restrictions

Ubuntu OCI images already ship key-only auth via cloud-init; make it explicit
and pin it:

```bash
sudo tee /etc/ssh/sshd_config.d/99-thesis-staging.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 3
AllowUsers ubuntu
EOF
sudo systemctl reload ssh
```

- Access only with the staging-only key (`~/.ssh/thesis_staging_arm`). The
  same private key is what goes into the `STAGING_SSH_KEY` GitHub environment
  secret (stdin, per STAGING_PROVISIONING.md §7).
- **Optional hardening once tunnel-based operation is proven** (deploys
  green, smoke passing, no console debugging expected): remove the TCP 22
  ingress rule from the NSG entirely. Break-glass access remains available
  via the OCI **Console Connection** (Instance → Resources → Console
  connection) or Cloud Shell, neither of which needs an open port 22.
  Re-adding the /32 rule takes one NSG edit when needed.
- **fail2ban: optional and mostly moot.** With ingress empty (or /32-scoped)
  there is nothing for fail2ban to ban. Install it only if you choose to keep
  22 open to a range: `sudo apt-get install -y fail2ban` (defaults are fine
  for sshd).

---

## 6. Tunnel-only ingress design

The ingress path is exactly the one the repo already encodes; nothing new is
invented here:

```text
Internet → Cloudflare edge (thesis-staging.robofox.online, proxied)
        → Cloudflare Tunnel (cloudflared on the host, OUTBOUND connections only)
        → http://127.0.0.1:8100  (nginx, deploy/nginx-staging.conf)
        → upstream thesis_staging_web: 127.0.0.1:8101 (web-a) / 8102 (web-b)
           max_fails=2 fail_timeout=10s, proxy_next_upstream error timeout 502 503
        → compose services (deploy/compose.phase5.yml, bound to 127.0.0.1 only)
```

Setup on the host:

```bash
# cloudflared from Cloudflare's apt repo (arm64 builds published)
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared

cloudflared tunnel login                       # one-time browser auth (owner)
cloudflared tunnel create thesis-staging       # note the tunnel UUID it prints
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/CHANGE_ME_STAGING_TUNNEL_ID.json /etc/cloudflared/
# Install the repo template, replacing CHANGE_ME_STAGING_TUNNEL_ID (both lines):
sudo cp deploy/cloudflared-staging.example.yml /etc/cloudflared/config.yml
sudo sed -i "s/CHANGE_ME_STAGING_TUNNEL_ID/<tunnel-uuid>/g" /etc/cloudflared/config.yml

cloudflared tunnel route dns thesis-staging thesis-staging.robofox.online
# creates the proxied CNAME thesis-staging.robofox.online → <tunnel-id>.cfargotunnel.com

sudo cloudflared service install               # systemd unit
sudo systemctl enable --now cloudflared
```

nginx (host package) install per the header comment in
`deploy/nginx-staging.conf`:

```bash
sudo apt-get install -y nginx
sudo cp deploy/nginx-staging.conf /etc/nginx/sites-available/thesis-staging
sudo ln -s /etc/nginx/sites-available/thesis-staging /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

The config template's `ingress` rules already terminate at
`http://127.0.0.1:8100` and fall through to `http_status:404`; nginx listens
only on `127.0.0.1:8100`; web-a/web-b bind `127.0.0.1:8101/8102` in compose.
Nothing in this chain listens on a routable interface — which is why the NSG
ingress can be empty. Optional: put a Cloudflare Access policy in front of
the staging hostname (Zero Trust → Access → Applications); staging is not for
the public.

---

## 7. Outbound requirements table

| Destination | Port | Who initiates | Purpose |
|---|---|---|---|
| `CHANGE_ME_DB_HOST`:5432 | TCP 5432 | app containers | Isolated PostgreSQL 16, TLS enforced (`?ssl=require` in `DATABASE_URL`) |
| `CHANGE_ME_R2_ACCOUNT_ID.r2.cloudflarestorage.com` | TCP 443 | app containers | R2 bucket `thesis-staging` (S3 API via boto3) |
| `ghcr.io` + `pkg-containers.githubusercontent.com` | TCP 443 | dockerd | Pull `ghcr.io/febufenn-cyber/thesis-studio-backend` (manifest at ghcr.io, blobs redirect to pkg-containers) |
| `api.resend.com` | TCP 443 | app containers | Magic-link email (staging key, staging-safe recipient policy) |
| `database.clamav.net` | TCP 443 | **freshclam inside the clamav container** | Signature updates (CDN-fronted; no host-side freshclam needed) |
| `ports.ubuntu.com` (arm64 mirror — **not** archive.ubuntu.com) + `security.ubuntu.com` per sources | TCP 80/443 | apt / unattended-upgrades | OS security updates; arm64 Ubuntu sources point at ubuntu-ports |
| `registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com` | TCP 443 | dockerd | Pull the pinned `clamav/clamav:1.4.5@sha256:86c2a5…` image from Docker Hub |
| `download.docker.com` | TCP 443 | apt | Docker Engine apt repo (§10) |
| `pkg.cloudflare.com` | TCP 443 | apt | cloudflared apt repo (§6) |
| `region1.v2.argotunnel.com`, `region2.v2.argotunnel.com` | UDP 7844 (QUIC), TCP 7844 (http2 fallback) | cloudflared | The tunnel itself — this outbound connection IS the site's ingress |
| `api.cloudflare.com`, `update.argotunnel.com` | TCP 443 | cloudflared | Tunnel control-plane and update checks |
| `169.254.169.254` (link-local) | 80 / NTP / DNS | cloud-init, chrony/timesyncd, resolver | OCI metadata, time, VCN DNS — bypasses NSG |

Everything above is **outbound**. There is no inbound row: that is the design.

---

## 8. Disk and temp behavior (what compose actually mounts)

Read from `deploy/compose.phase5.yml`:

- Every app service is `read_only: true` with two writable surfaces:
  a **tmpfs at `/tmp`** and the shared named volume **`runtime-var` at
  `/app/var`**.
- Default app tmpfs: `/tmp size=512m,mode=1777` (RAM-backed). `worker-pdf`
  **replaces** this via YAML-merge override with `/tmp size=2g,mode=1777` —
  sized for LibreOffice conversion scratch. tmpfs pages are RAM, not disk,
  and for worker-pdf they **count against its 3 GB cgroup memory limit**: a
  ~2 GB temp file plus soffice RSS can legitimately trip the limit. That is
  intended (§9).
- LibreOffice profile directories and conversion temp that must persist
  across a container's lifetime live under `/app/var` on the `runtime-var`
  volume (disk, on the 100 GB boot volume). This can spike by several GB
  during conversions; it is rebuildable — safe to prune when the stack is
  down (`docker volume rm`), it will be recreated.
- `clamav-db` volume holds 1–2 GB of signatures on disk (rebuildable;
  freshclam refetches in ~minutes on a fresh volume).
- Log growth is capped: compose sets `json-file, max-size 20m, max-file 5`
  on every service → ≤100 MB per service, ≤~0.7 GB across the 7 services.
  journald is capped separately (§13). Watch overall usage with
  `df -h /` and `docker system df`; prune superseded release images with
  `docker image prune -a --filter "until=720h"` after a verified deploy.

---

## 9. Swap, OOM ordering, and why worker-pdf is the sacrificial process

4 GB swapfile (buffer against burst overlap, not a substitute for the 18 GB
sizing):

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-thesis-staging.conf
sudo sysctl --system
```

`vm.swappiness=10` keeps clamd's hot signature pages resident and lets only
genuinely cold pages spill.

**OOM ordering, as configured.** `worker-pdf` is the only service with a hard
memory cap (`deploy.resources.limits.memory: 3g` — enforced by docker compose
v2 without any `--compatibility` flag). So the failure order under memory
pressure is:

1. A runaway LibreOffice conversion hits worker-pdf's **own 3 GB cgroup
   limit** (tmpfs writes included) and is OOM-killed *inside that cgroup* —
   the host never enters global OOM.
2. Only if the host itself ran out of memory would the kernel's global OOM
   killer act, and it prefers the largest resident set — on this host that is
   **clamd (~3 GB)**, whose death 503s all uploads and takes ~2+ minutes to
   recover (compose healthcheck `start_period: 120s` plus signature load).

The cap exists precisely to force failure into path 1: a killed PDF
conversion is the cheapest possible casualty. Recovery is automatic on both
layers — the job-queue lease expires (`JOB_LEASE_SECONDS=120` in
`.env.staging.example`) and another attempt picks the job up, and the
container itself restarts because **`restart: unless-stopped` is set in the
`x-app` anchor of `deploy/compose.phase5.yml` and inherited by every app
service including worker-pdf** (clamav declares the same policy explicitly;
no service overrides it). Verified against the compose file at this commit —
do not paraphrase this as `always`; `unless-stopped` will *not* resurrect a
container an operator explicitly stopped, which is the behavior we want
during maintenance.

---

## 10. Docker install for arm64 Ubuntu 22.04 + daemon.json

Official Docker apt repo (`dpkg --print-architecture` resolves to `arm64`, so
the standard commands are already architecture-correct). This supersedes the
`docker.io` shortcut in STAGING_PROVISIONING.md host-prep for this host:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu   # re-login to take effect
```

`/etc/docker/daemon.json` — log rotation for anything compose doesn't cover,
and `live-restore` so containers survive dockerd restarts/upgrades
(unattended-upgrades interplay, §11):

```bash
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" },
  "live-restore": true
}
EOF
sudo systemctl restart docker
```

Then `docker login ghcr.io` with a **read-only** packages token (username =
GitHub username, token via stdin — never in shell history: use
`docker login ghcr.io -u CHANGE_ME_GH_USER --password-stdin`).

---

## 11. Unattended-upgrades + reboot policy

```bash
sudo apt-get install -y unattended-upgrades
sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
sudo tee /etc/apt/apt.conf.d/52unattended-upgrades-local >/dev/null <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "21:30";  // UTC = 03:00 IST, off-hours
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
sudo systemctl enable --now unattended-upgrades
sudo unattended-upgrade --dry-run --debug | tail -5   # sanity check
```

Reboot policy: **automatic reboots are acceptable on staging** (they would
not be on production without a maintenance window). The stack self-heals on
boot because: dockerd is `enabled` and every compose service is
`restart: unless-stopped` (§9); `cloudflared` and `nginx` are enabled systemd
units (§6). After any kernel-driven reboot, confirm with
`curl -fsS https://thesis-staging.robofox.online/readyz` or rerun
`scripts/phase5_smoke.py`. Note `live-restore: true` (§10) additionally keeps
containers running across *docker package* upgrades that restart the daemon
without a reboot.

---

## 12. Host replacement procedure (the host is stateless)

Per the "Host replacement exercise" section of
`docs/runbooks/backup-restore.md`: build a fresh host from the immutable
image, inject secrets, connect to isolated PostgreSQL/R2, start web + queue
workers, run the release-aware smoke, verify lease reclaim — with no
undocumented founder-only step. Concretely for this host, the only state that
lives on the VM is: the real `.env` (recreated from `.env.staging.example` +
the owner's secret store), the cloudflared tunnel credential JSON, and two
rebuildable docker volumes (`clamav-db`, `runtime-var`). Nothing needs backup
from the host itself; PostgreSQL and R2 live elsewhere by design.

1. Launch a replacement VM per §1.4 (the 1 OCPU / 6 GB / 100 GB free-tier
   headroom reserved in §1.1 makes old + new coexist briefly; if RAM
   headroom is insufficient, stop — not terminate — the old instance first).
2. Run bootstrap: §10 (docker), §5 (sshd), §9 (swap), §11
   (unattended-upgrades), §13 (journald), §6 (nginx + cloudflared packages).
3. Recreate `${STAGING_DEPLOY_PATH}` with `deploy/compose.phase5.yml`, and
   the real `.env` at `${STAGING_ENV_PATH}` (chmod 600) from the secret
   store — values typed/pasted locally, never through chat or logs.
4. Rejoin the tunnel — either move the existing identity or mint a new one:
   - **Reuse:** copy `/etc/cloudflared/<tunnel-id>.json` + `config.yml` from
     the secret store to the new host; `systemctl enable --now cloudflared`.
     DNS is untouched.
   - **Recreate:** `cloudflared tunnel create thesis-staging-2`, install
     config with the new UUID, then
     `cloudflared tunnel route dns --overwrite-dns thesis-staging-2 thesis-staging.robofox.online`.
5. `docker login ghcr.io` (read-only token), then
   `docker compose -f compose.phase5.yml --env-file ${STAGING_ENV_PATH} up -d`
   — `ROBOFOX_IMAGE`/`CLAMAV_IMAGE` pins in `.env` guarantee the identical
   release. Wait for clamav healthy (signature fetch on the fresh volume,
   ~minutes).
6. Verify: §14 architecture checks, then
   `python scripts/phase5_smoke.py --base-url https://thesis-staging.robofox.online --expected-release b2c9c624cd6b6faffe4f9585ac7f4580631abd82`,
   and confirm an expired job lease is reclaimed (runbook step 6).
7. Update the `STAGING_HOST` GitHub environment secret to the new IP (stdin,
   per STAGING_PROVISIONING.md §7); terminate the old instance **and its boot
   volume** (untick "preserve boot volume") to return free-tier capacity.

---

## 13. Log retention: journald + docker

journald cap (the runbook's data-minimisation rules already forbid logging
secrets/bodies; this bounds volume):

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/retention.conf >/dev/null <<'EOF'
[Journal]
SystemMaxUse=500M
EOF
sudo systemctl restart systemd-journald
journalctl --disk-usage   # confirm
```

Docker log rotation is enforced twice, deliberately: per-service in
`deploy/compose.phase5.yml` (`json-file`, `max-size: 20m`, `max-file: "5"` on
all 7 services) and daemon-wide in `/etc/docker/daemon.json` (§10) for any
container started outside compose. cloudflared and nginx log to journald /
`/var/log/nginx` (rotated by the stock logrotate config).

---

## 14. Architecture validation (run before first deploy, record in evidence)

```bash
# 1. Host is genuinely arm64
uname -m                                        # expect: aarch64
docker info --format '{{.Architecture}}'        # expect: aarch64

# 2. The release manifest offers arm64 (pre-pull check)
docker buildx imagetools inspect \
  ghcr.io/febufenn-cyber/thesis-studio-backend:b2c9c624cd6b6faffe4f9585ac7f4580631abd82 \
  | grep -A1 'linux/arm64'                      # expect a linux/arm64 platform entry

# 3. Docker resolves the manifest list to the arm64 image and it executes
docker run --rm \
  ghcr.io/febufenn-cyber/thesis-studio-backend:b2c9c624cd6b6faffe4f9585ac7f4580631abd82 \
  uname -m                                      # expect: aarch64

# 4. Full runtime evidence via the runtime smoke script — records
#    image_platform (Os/Architecture from docker inspect) and container_uname_m
#    in its JSON output, plus fail-closed boot, LibreOffice/TNR, ClamAV client,
#    /readyz release identity, worker startup, DOCX render and PDF conversion.
python scripts/container_runtime_smoke.py \
  --image ghcr.io/febufenn-cyber/thesis-studio-backend:b2c9c624cd6b6faffe4f9585ac7f4580631abd82 \
  --database-url postgresql+asyncpg://CHANGE_ME_SMOKE_DB_URL \
  --expected-sha b2c9c624cd6b6faffe4f9585ac7f4580631abd82 \
  --network host \
  --out docs/release/evidence/RUNTIME_SMOKE_ARM64_STAGING.json
```

Acceptance: all three `uname`/`Architecture` probes report `aarch64`, the
manifest inspection lists `linux/arm64`, and the smoke evidence JSON shows
`architecture_reported: arm64` / `container_uname_m: aarch64` with every
check passing. File the JSON with the staging acceptance evidence alongside
the image digest recorded by the release workflow (STAGING_PROVISIONING.md
pre-deploy gate table).

---

## Out of scope (unchanged from STAGING_PROVISIONING.md)

Production secrets, DNS, database, storage: untouched. The shared Oracle VM
(68.233.116.11) is not used for staging. AI stays disabled
(`AI_GLOBAL_ENABLED=false` — the Claude CLI/OAuth session is not a staging
dependency). Billing stays manual (`BILLING_PROVIDER=manual`). No credentials
appear in this document, in commits, or in chat — placeholders only.
