# Deploying The 200 Travel Chat

This guide walks you through publishing the chatbot to a small Linux VPS at
`https://chat.the200.blog` and linking it from the WordPress.com page at
`https://the200.blog/travel-ai/`.

Total time: **~60 minutes** (plus 5-30 minutes of DNS propagation).
Recurring cost: **~$4-5/month** (VPS only — Anthropic API is billed
separately, per token).

The repo already ships with `Dockerfile`, `docker-compose.yml`, and
`Caddyfile` — this guide just describes how to run them on a host.

---

## Architecture

```
the200.blog/travel-ai/       (WordPress.com page, has a button)
        │
        └── link →  https://chat.the200.blog
                            │
                            ▼
                ┌─────────────────────────┐
                │   VPS (Ubuntu 24.04)    │
                │                         │
                │   Caddy (host) :443 ────┐
                │     │                   │
                │     │ reverse proxy     │
                │     ▼                   │
                │   docker compose        │
                │     └─ app :8000        │
                │          └─ .env        │
                └─────────────────────────┘
```

- **Caddy** runs on the host and handles TLS automatically via Let's Encrypt.
- **The app** runs in Docker, bound only to `127.0.0.1:8000`. Caddy is the
  only thing the public can reach.

---

## Pre-flight (do these on your laptop first)

### 1. WordPress.com plan check

You need to be able to add custom **DNS records** for `the200.blog`. To
verify:

- WP.com → **My Sites** → the200.blog → **Settings** → **Domains** →
  click on `the200.blog` → **DNS Records**.
- If you can see a panel where you can add an `A` record, you're set.
- If you can only see the existing records but not add one, your plan is
  too limited. You have two options:
  1. Upgrade to **Personal** plan ($4/mo) or higher.
  2. Move DNS management to **Cloudflare** (free). See the
     [Fallback section](#fallback-wordpresscom-cant-edit-dns) below.

### 2. Generate an Anthropic API key

- <https://console.anthropic.com/settings/keys> → **Create key**.
- Copy it somewhere temporary. You'll paste it into the server later.
- Set a usage cap at
  <https://console.anthropic.com/settings/usage> so you don't get a surprise
  bill if the URL leaks.

### 3. Push the repo to GitHub

The VPS will `git clone` from GitHub. A **private** repo is fine and
recommended (the `.gitignore` already excludes `.env`, but private is
defense-in-depth).

```bash
# from your laptop, inside the repo
git init
git add .
git commit -m "initial commit"
gh repo create the200-chat --private --source=. --push
# or do it manually via github.com if you don't have gh CLI
```

Double-check `.env` is NOT in the commit:

```bash
git ls-files | grep env
# should only show .env.example
```

### 4. SSH key

```bash
ls ~/.ssh/id_ed25519.pub
# if missing:
ssh-keygen -t ed25519 -C "the200-deploy"
```

Keep that `.pub` file open — you'll paste it into the VPS console.

---

## Step 1 — Provision the VPS

**Recommended provider**: [Hetzner Cloud](https://www.hetzner.com/cloud)
(€4/mo, EU regions, best price/perf). Alternatives: DigitalOcean ($4-6/mo),
Vultr, Linode.

Settings:

| Field | Value |
|---|---|
| Image | **Ubuntu 24.04 LTS** (or 22.04) |
| Type | x86_64, 1 vCPU / 2 GB RAM |
| Region | closest to your readers |
| SSH key | paste your `id_ed25519.pub` here |

After provisioning, copy the **public IPv4 address**. Save it somewhere —
this guide will call it `$VPS_IP`.

---

## Step 2 — Point `chat.the200.blog` at the VPS

In WP.com → **My Sites** → the200.blog → **Settings** → **Domains** → click
`the200.blog` → **DNS Records** → **Add a record**:

| Field | Value |
|---|---|
| Type | `A` |
| Name | `chat` |
| Value | `$VPS_IP` (the IPv4 from Step 1) |
| TTL | default (3600 s is fine) |

Save.

**Verify propagation** before continuing — wait 5-30 minutes, then:

```bash
nslookup chat.the200.blog
# expected output should contain: Address: <VPS_IP>
```

Or use <https://dnschecker.org/#A/chat.the200.blog>.

> ⚠️ **Step 7 (TLS) will fail if DNS hasn't propagated.** Caddy needs to
> answer a Let's Encrypt challenge on `chat.the200.blog`, which only works
> once the world resolves that name to your VPS.

---

## Step 3 — Initial server hardening

SSH in as `root`:

```bash
ssh root@$VPS_IP
```

Then on the VPS:

```bash
# Update packages
apt update && apt upgrade -y

# Create a non-root user with sudo
adduser deploy                # set a strong password when prompted
usermod -aG sudo deploy

# Copy your SSH key over so you can log in as deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy/

# Disable root SSH and password auth
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

# Firewall
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

**Test** the new login from a second terminal **before** closing your root
session:

```bash
ssh deploy@$VPS_IP
```

If that works, you can `exit` the root session. From now on, log in as
`deploy`.

---

## Step 4 — Install Docker

As `deploy` on the VPS:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deploy

# log out and back in so the docker group takes effect
exit
ssh deploy@$VPS_IP

# smoke test
docker run --rm hello-world
```

---

## Step 5 — Install Caddy on the host

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

systemctl status caddy        # should show "active (running)"
```

Caddy installs a default site that serves a placeholder page. We'll replace
it in Step 7.

---

## Step 6 — Deploy the app

As `deploy` on the VPS:

```bash
cd ~
git clone https://github.com/<YOUR_GH_USER>/the200-chat.git
cd the200-chat
```

Create `.env` with your real API key:

```bash
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...PASTE-YOUR-REAL-KEY-HERE...
MODEL=claude-haiku-4-5-20251001
MAX_OUTPUT_TOKENS=2048
MAX_INPUT_TOKENS=8000
RATE_LIMIT_PER_IP=20
RATE_LIMIT_WINDOW_SECONDS=300
MAX_CONCURRENT_STREAMS=10
EOF

chmod 600 .env
```

Build and start:

```bash
docker compose up -d --build

# wait ~30s, then verify
curl http://localhost:8000/         # should return HTML
docker compose logs --tail 30
```

You should see `Uvicorn running on http://0.0.0.0:8000` in the logs and a
successful 200 on the curl.

---

## Step 7 — Wire up Caddy (this gives you HTTPS)

Copy the repo's `Caddyfile` into Caddy's config dir and reload:

```bash
sudo cp /home/deploy/the200-chat/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy

# watch Caddy obtain the cert
sudo journalctl -u caddy -f
```

You should see lines like:

```
certificate obtained successfully  identifier=chat.the200.blog
```

Press `Ctrl+C` to stop watching logs.

**Verify HTTPS:**

```bash
curl -I https://chat.the200.blog
# Expect: HTTP/2 200, no cert errors
```

If you get a cert error, DNS probably hasn't propagated yet. Wait 10 minutes
and `sudo systemctl reload caddy` again.

---

## Step 8 — Connect the blog

Edit the WordPress page at `https://the200.blog/travel-ai/` in the WP block
editor:

1. Remove any placeholder / "coming soon" content.
2. Add a short paragraph in your voice (one or two sentences) explaining
   what the chatbot is.
3. Add a **Button** block:
   - **Text**: `Talk to my AI travel guide →`
   - **Link**: `https://chat.the200.blog`
   - **Open in**: same tab (better for mobile flow)
4. Publish / Update the page.

---

## Step 9 — End-to-end smoke test

From a browser:

- [ ] Open `https://chat.the200.blog` directly — page loads, the URL bar
      shows a valid 🔒 padlock.
- [ ] Click a suggested-prompt chip — response streams token-by-token (not
      all at once).
- [ ] Open `https://the200.blog/travel-ai/` — click your CTA button — lands
      on `chat.the200.blog`.

From the VPS:

- [ ] `sudo reboot`, wait 30 seconds, retry the chat URL — should still
      work (Docker `restart: unless-stopped` + Caddy systemd unit handle
      this automatically).

You're live. 🎉

---

## Operations playbook

All commands run on the VPS as `deploy`, inside `~/the200-chat`.

| Task | Command |
|---|---|
| Deploy a new version | `git pull && docker compose up -d --build` |
| View app logs | `docker compose logs -f` |
| Tail Caddy logs | `sudo journalctl -u caddy -f` |
| Rotate the API key | edit `.env`, then `docker compose up -d` (no rebuild needed) |
| Stop the app | `docker compose down` |
| Restart everything | `docker compose down && docker compose up -d` |
| Check disk / memory | `df -h && free -m` |
| Free disk from old images | `docker system prune -af` |

### Routine maintenance

- **Monthly**: `sudo apt update && sudo apt upgrade -y`, then
  `sudo reboot` if a kernel update lands.
- **Quarterly**: rotate the Anthropic API key.
- **Annually**: confirm `the200.blog` is on auto-renew at WP.com.

---

## Fallback: WordPress.com can't edit DNS

If WP.com → Domains shows no way to add a custom A record, move DNS to
Cloudflare (free). This does **not** transfer your domain registration; only
the DNS layer.

1. Sign up at <https://cloudflare.com>.
2. Cloudflare → **Add a site** → enter `the200.blog` → choose the Free plan.
3. Cloudflare scans your existing DNS records. **Save them somewhere
   visible** — you'll need them in step 5.
4. Cloudflare gives you 2 nameservers, e.g.
   `dana.ns.cloudflare.com`, `kirk.ns.cloudflare.com`.
5. WP.com → Domains → the200.blog → **Name Servers** → change to
   Cloudflare's two. (Propagation: usually under 1 hour, up to 24 hours.)
6. In Cloudflare → DNS:
   - Re-create the existing records that point `the200.blog` at WordPress
     servers (these were the ones you saved in step 3).
   - Add a new `A` record:
     - **Name**: `chat`
     - **IPv4**: `$VPS_IP`
     - **Proxy status**: **DNS only** (gray cloud, not orange)

> ⚠️ Cloudflare's orange-cloud proxy will break Caddy's TLS issuance.
> Keep `chat` set to **DNS only**.

Once Cloudflare is serving DNS, return to **Step 7** above.

---

## Troubleshooting

### `curl https://chat.the200.blog` returns "unable to verify the first certificate"
Caddy hasn't issued a cert yet. Check `sudo journalctl -u caddy -n 50`. If
it mentions a DNS challenge failure, your A record probably isn't live yet
worldwide. Wait, then `sudo systemctl reload caddy`.

### `docker compose logs` shows `pydantic_core._pydantic_core.ValidationError: anthropic_api_key`
Your `.env` is missing the key or has it under the wrong name. The variable
must be exactly `ANTHROPIC_API_KEY=...` with no quotes.

### The browser shows "The travel guide is having trouble right now"
The app reached Anthropic but Anthropic returned an error. Most common
causes:
- Key is invalid / revoked → rotate in Anthropic console, update `.env`,
  `docker compose up -d`.
- You hit a usage limit → check
  <https://console.anthropic.com/settings/usage>.

### Browser shows "Server busy" or "Too many messages"
Working as designed — these are the per-IP rate limit (20 msgs / 5 min)
and the global concurrent-stream cap (10). To raise them, edit `.env`
(`RATE_LIMIT_PER_IP`, `MAX_CONCURRENT_STREAMS`) and `docker compose up -d`.

### Page loads but no response when you send a message
Open browser devtools → Network → click the `/chat` request. If it shows
`(failed)` immediately, Caddy might not be reverse-proxying. Check
`sudo journalctl -u caddy -n 50` for errors. The `Caddyfile` must contain
`reverse_proxy localhost:8000` for the `chat.the200.blog` site.

---

## Security checklist

- [ ] `.env` is mode 600 and not committed to git
- [ ] Root SSH is disabled (`PermitRootLogin no`)
- [ ] Password SSH is disabled (`PasswordAuthentication no`)
- [ ] `ufw status` shows only ports 22, 80, 443 open
- [ ] Anthropic API key has a monthly usage cap set
- [ ] The compromised key from any earlier exposure is **revoked** in the
      Anthropic console (not just replaced)
