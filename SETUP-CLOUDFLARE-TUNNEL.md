# Cloudflare Tunnel + Access for `thesis.robofox.online`

This wires the backend (running on the Oracle VM, bound to `127.0.0.1:8000`) to the public URL `https://thesis.robofox.online`, with **Cloudflare Access SSO** as the first auth wall in front of the magic-link flow.

End state:
- No firewall ports opened on the VM. Cloudflare Tunnel is the only ingress.
- Anyone hitting the URL is challenged by Cloudflare Access first; only your email passes.
- After Access, they reach the magic-link login page; they still need a magic-link to actually use the app.

---

## Prerequisites

- Tunnel side: ubuntu user with passwordless sudo on the VM (same as deploy script).
- DNS side: `robofox.online` is already managed in Cloudflare.
- The backend is running on the VM and `curl http://127.0.0.1:8000/healthz` returns `200` from the VM itself.

Open items the deploy already addressed: pm2 process running, app bound to `127.0.0.1:8000`, Postgres + claude CLI installed.

---

## 1. Install `cloudflared` on the VM

The Oracle VM at `68.233.116.11` is x86_64 (`uname -m` → `x86_64`):

```bash
ssh ubuntu@68.233.116.11
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
rm cloudflared.deb
cloudflared --version
```

> **Sidebar — ARM64 VMs (e.g. Oracle Ampere A1 free tier):** swap `linux-amd64` for `linux-arm64` in the URL above. Confirm arch with `uname -m` before downloading.

---

## 2. Authenticate `cloudflared` to your Cloudflare account

```bash
cloudflared tunnel login
```

It prints a URL. Copy it, open it in your Mac browser, sign in to Cloudflare, **select `robofox.online`** when prompted to authorize. The CLI will then write `~/.cloudflared/cert.pem` on the VM. This certificate authorizes this machine to manage tunnels for `robofox.online`.

---

## 3. Create the tunnel

```bash
cloudflared tunnel create thesis-studio
```

Output looks like:

```
Tunnel credentials written to /home/ubuntu/.cloudflared/<TUNNEL_UUID>.json.
Created tunnel thesis-studio with id <TUNNEL_UUID>
```

Copy the UUID. You'll need it in the next step.

---

## 4. Configure the tunnel

Create `/etc/cloudflared/config.yml`. Replace `<TUNNEL_UUID>` with the value from step 3:

```bash
sudo mkdir -p /etc/cloudflared
sudo tee /etc/cloudflared/config.yml >/dev/null <<'EOF'
tunnel: <TUNNEL_UUID>
credentials-file: /home/ubuntu/.cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: thesis.robofox.online
    service: http://localhost:8000

  # Catch-all 404 — tunnels MUST end with a default rule.
  - service: http_status:404
EOF
```

Edit the file to substitute `<TUNNEL_UUID>` in both the `tunnel:` and `credentials-file:` lines (use `sudo nano` or `sudo sed -i`).

---

## 5. Route DNS

This creates the `thesis.robofox.online` CNAME automatically (does NOT touch any other subdomain):

```bash
cloudflared tunnel route dns thesis-studio thesis.robofox.online
```

Verify in the Cloudflare dashboard → robofox.online → DNS → Records that a new CNAME for `thesis` was added pointing at `<TUNNEL_UUID>.cfargotunnel.com`. Other records (api, leads, root) are untouched.

---

## 6. Run as a systemd service

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
sudo systemctl status cloudflared --no-pager
```

The status output should show `active (running)`. If it errors, check `sudo journalctl -u cloudflared -n 50`.

Test from the VM:

```bash
curl -fsS https://thesis.robofox.online/healthz
```

Should return `{"status":"ok"}` (or whatever the healthz body is). If it returns an HTML Cloudflare error page, the tunnel isn't routing — check `cloudflared tunnel info thesis-studio`.

---

## 7. Cloudflare Access SSO (the auth wall before the auth wall)

This adds an additional gate so even reaching the magic-link login page requires your auth.

### 7a. Enable Cloudflare Access for your account

If you haven't used Zero Trust before:

1. Go to https://one.dash.cloudflare.com/
2. Pick a team name (subdomain) — e.g. `robofox` → URL becomes `robofox.cloudflareaccess.com`. **This is shown to anyone hitting your protected app**, so pick something you're OK with.
3. Choose the free plan ("Free up to 50 users").

### 7b. Configure an identity provider

Settings → Authentication → Login methods → Add new.

Easiest option: **One-time PIN** (no Google/GitHub setup required; CF emails you a 6-digit code).

If you'd rather use Google: pick Google, follow CF's wizard, paste a Google OAuth client ID/secret (one-time setup in Google Cloud Console). One-time PIN is faster for first deploy; you can add Google later.

### 7c. Create the Access application

Access → Applications → Add an application → Self-hosted.

- **Application name:** `Thesis Studio`
- **Session duration:** 24 hours (default is fine)
- **Application domain:** `thesis.robofox.online`
- **Identity providers:** check whichever you set up (One-time PIN or Google)

Click **Next** → **Configure policies**.

### 7d. Policy

- **Policy name:** `Only me`
- **Action:** Allow
- **Session duration:** 24 hours
- **Include rule:** Emails → `febin@<your real email domain>` (use the email you'll actually receive PINs at)

(Optionally add another email if you want to grant access to another inbox you control.)

Save the policy. Save the application.

### 7e. Verify

Open `https://thesis.robofox.online` in a private window or on a phone that's not authenticated. You should see the Cloudflare Access login screen showing your team name. Enter your email; if you're using One-time PIN, you'll get a 6-digit code by email. Enter it. You'll then be redirected to the actual app, where you'll hit the magic-link flow as a separate (second) auth step.

If you see the app immediately without the Access challenge, the policy didn't apply — re-check that the Application domain matches `thesis.robofox.online` exactly (no trailing slash, no path).

---

## End-to-end test from a phone

1. On a phone that isn't already authenticated to your Cloudflare Access session, open `https://thesis.robofox.online`.
2. Cloudflare Access challenge → enter your email → enter the 6-digit PIN from email.
3. Land on the magic-link login page → enter `febin@mcc.edu.in` (or any email you control) → submit.
4. Check your email for the magic link → tap it on the phone.
5. The app should load with you signed in, assigned to MCC.
6. Send a chat message; see the streamed response.

If all of that works, the app is shipped.

---

## What this setup does NOT touch

- Other DNS records on `robofox.online` (api, leads, root). Tunnel only adds the `thesis` CNAME.
- VM firewall — port 8000 stays bound to `127.0.0.1`. The tunnel reaches it via localhost.
- Other PM2 services on the VM.

---

## Operational notes

- **Restart the tunnel after config changes:** `sudo systemctl restart cloudflared`
- **See tunnel traffic:** `sudo journalctl -u cloudflared -f`
- **Rotate Access policies:** Zero Trust dashboard → Access → Applications → edit policy. Changes apply within ~1 min.
- **If the VM IP changes:** the tunnel re-establishes on its own; nothing to update.
- **If you ever want to drop the Access wall** (don't): Zero Trust → Access → Applications → delete. Tunnel keeps working, just without the SSO gate.
