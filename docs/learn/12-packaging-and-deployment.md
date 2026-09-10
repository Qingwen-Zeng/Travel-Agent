# 12 — Packaging and deployment

You have an app that runs on your laptop. This chapter is about the last mile:
packaging it with **Docker** so it runs identically anywhere, putting it on a
rented Linux server, and giving it HTTPS with **Caddy**. The files are
`Dockerfile`, `.dockerignore`, `Caddyfile`, and the walkthrough in `DEPLOY.md`.

---

## 1. The problem: "it works on my machine"

Your laptop has a specific Python version, specific installed libraries, specific
system packages, specific file paths. A server has different ones. "Copy the
files over and run it" fails in a dozen small ways. **Docker** solves this by
packaging the app *together with its entire environment* into one portable unit.

## 2. Images and containers

- A **Docker image** is a frozen, layered filesystem snapshot: a base operating
  system, plus Python, plus your dependencies, plus your code — everything needed
  to run, baked in. It is built once from a `Dockerfile` and does not change.
- A **container** is a running instance of an image: an isolated process (or
  process tree) with its own view of the filesystem, started from the image.

You can run many containers from one image. Stopping and deleting a container and
starting a fresh one from the same image is the normal way to "restart" — the new
container is byte-identical to how the old one started.

## 3. The `Dockerfile`, line by line

```dockerfile
FROM python:3.13-slim
```
Start from an official pre-built image: Debian Linux with Python 3.13, `slim`
variant (no compilers, docs, or extras — smaller). This is a **single-stage**
build (one `FROM`).

```dockerfile
WORKDIR /app
```
Set the working directory inside the image to `/app` (created if absent). All
later `COPY` destinations and the final `CMD` are relative to here. So
`app/main.py` lands at `/app/app/main.py`, and `travel.db` at `/app/travel.db` —
which matches `DATABASE_PATH=travel.db` (a relative path resolved from the process
working directory).

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```
Copy **only** `requirements.txt` first, then install. This is the **layer-caching
trick**: Docker builds the image as a stack of layers, one per instruction, and
reuses a cached layer if its inputs are unchanged. As long as `requirements.txt`
has not changed, a rebuild reuses the (slow) `pip install` layer even when your
application code changed. `--no-cache-dir` tells pip not to keep its download
cache inside the image, shaving size.

```dockerfile
COPY app/ ./app/
```
Copy the application package. This layer changes on almost every code edit — which
is exactly why it comes *after* the dependency install, so an edit does not
invalidate the pip layer.

```dockerfile
COPY travel.db ./travel.db
COPY stories.faiss ./stories.faiss
```
Copy the **prebuilt** database and FAISS index into the image. See section 4.

```dockerfile
EXPOSE 8000
```
Documentation only: "this image's process listens on TCP 8000." It does **not**
publish the port — you still need `-p 8000:8000` on `docker run`.

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
The default command when a container starts. `app.main:app` = "the `app` object in
module `app.main`." `--host 0.0.0.0` is essential — binding to `127.0.0.1` inside
a container makes it unreachable from outside the container. No `--reload` (that
is a dev-only convenience). The JSON-array ("exec") form means uvicorn is PID 1
and receives shutdown signals directly.

## 4. Why the database is baked into the image

This is the central deployment decision, and it follows straight from chapter
`00`'s **Rule 2** (data never changes at runtime):

- Because the data is immutable for the life of a deployment, there is no reason
  to mount it as an external volume. Bake it in.
- Consequences: **no volume to manage, no database server to run, no migration
  step on deploy, no backup strategy** (the data is rebuilt from source any
  time). The image is entirely self-contained.
- The build inputs (`travel.db`, `stories.faiss`) are produced *first*, on your
  laptop, by the scripts in chapter `09`. `docker build` just `COPY`s them. If
  either file is missing, the `COPY` fails and the build errors out — a useful
  forcing function.
- **Deploy = build a new image. Roll back = run the previous image.** Code version
  and data version are locked together in one artifact.

The trade-off: the image is large (`sentence-transformers` pulls in PyTorch,
~hundreds of MB) and every content update is a full rebuild+redeploy. For a
one-owner site with rarely-changing curated data, that is a deliberately good
deal.

## 5. `.dockerignore` — keeping things out of the image

Before building, Docker sends the whole directory (the "build context") to the
Docker engine. `.dockerignore` trims that set. Nothing listed here can be
`COPY`ed, even accidentally.

```
.venv/          # the host's virtualenv — huge, wrong OS, irrelevant (image builds its own)
__pycache__/    # stale bytecode caches
.pytest_cache/
.git/           # the entire history — often the biggest folder, never needed at runtime
.claude/
.env            # SECRETS. Never bake real keys into an image layer (layers are extractable).
.env.example    # just a template
data/
Saved/          # the raw CSV export — a build INPUT, private, not needed by the server
stories.json    # the raw diary — private; the server only needs the derived stories.faiss
tests/          # not run in production
*.md            # all docs, including this course
```

The two motivations again: keep **secrets** out (`.env`), and keep **large or
private inputs** out (`Saved/`, `stories.json`, `.git/`). The `Dockerfile` only
`COPY`s named paths anyway, so `.dockerignore` here is mostly belt-and-braces —
but it also keeps the build context small and fast.

## 6. Environment variables at run time, not build time

Notice the `Dockerfile` never mentions `LLM_API_KEY` or any secret. Config is
injected when the container *starts*:

```
docker run -d --name travel-agent -p 8000:8000 --env-file .env travel-agent
```

- `-d` — detached (background).
- `--name travel-agent` — a name to refer to it by.
- `-p 8000:8000` — publish container port 8000 to host port 8000.
- `--env-file .env` — read `KEY=value` lines from `.env` and set them as
  environment variables inside the container. `app/config.py` reads them at
  startup.
- `travel-agent` — the image name (from `docker build -t travel-agent .`).

This is the "12-factor" principle: **config lives in the environment, not in the
code or the image.** The same image runs in dev and prod; only the injected
environment differs. And a leaked image contains no keys.

## 7. Reverse proxy and automatic HTTPS: Caddy

The container listens on plain HTTP, port 8000, bound to `localhost` on the
server — not reachable from the internet. In front of it sits **Caddy**.

### What a reverse proxy is

A server that receives the public traffic and forwards it to your application,
then relays the responses back. "Reverse" because it fronts the *server* side (a
normal/forward proxy fronts clients).

```
Browser  ──HTTPS :443──▶  Caddy (on the server)  ──HTTP :8000──▶  the container (localhost:8000)
```

Caddy takes three jobs off the app: terminating TLS (decrypting HTTPS so the app
speaks plain HTTP internally), owning the privileged public ports (80/443), and
being the single hardened front door so the app process is never directly
exposed.

### The `Caddyfile`

```
your-domain.com {
    reverse_proxy localhost:8000
}
```

That is the entire config. "For requests to `your-domain.com`, forward to the
local app on 8000." Caddy also sets sensible proxy headers (`X-Forwarded-For`,
`X-Forwarded-Proto`, `Host`) automatically.

### How automatic HTTPS works

When Caddy starts with a block keyed by a real domain name, it:

1. Contacts a public **ACME** certificate authority (Let's Encrypt by default).
2. Proves you control the domain via an ACME challenge — typically HTTP-01: the CA
   fetches a token from `http://your-domain.com/.well-known/acme-challenge/...`
   which Caddy serves. This requires the domain's DNS to already point at this
   server and ports 80 + 443 to be open.
3. Receives a real, browser-trusted certificate and stores it.
4. Serves the site on 443 with that cert, and auto-redirects HTTP → HTTPS.
5. **Renews automatically** in the background before expiry. No cron job, no
   certbot, no manual step.

(If the domain were `localhost` or an IP, Caddy makes a local self-signed cert
instead — which is why the config must be edited to a real domain.)

## 8. The full server walkthrough (`DEPLOY.md`, summarised)

The target: turn the laptop-only app into `https://travelai.the200.blog/` on a
Hetzner Cloud VPS. `DEPLOY.md` is written for someone with zero deployment
experience; here are its steps.

1. **Set spend limits first.** Before the URL is public: an Anthropic monthly
   hard limit, and a Google Cloud **quota** on the Maps JS API (a billing budget
   only emails — a quota actually caps). The app's own `RATE_LIMIT_PER_HOUR` /
   `DAILY_MESSAGE_CAP` are a second layer, not a substitute.
2. **Create the server.** A Hetzner project; add a server: nearest location,
   Ubuntu LTS, cheapest shared-vCPU plan, an SSH key, and a **firewall allowing
   only inbound 22 / 80 / 443**. (The firewall matters: `docker run -p 8000:8000`
   binds the app straight to the public internet on 8000, bypassing Caddy — the
   firewall must block 8000.) Note the server's IP.
3. **Point DNS at it.** In the DNS provider, edit the `travelai` **A record** to
   the new server's IP. Propagation takes minutes to hours.
4. **Connect:** `ssh root@YOUR_SERVER_IP`.
5. **Install Docker:** `curl -fsSL https://get.docker.com | sh`.
6. **Get code and data onto the server.** Code via Git:
   `git clone https://github.com/Qingwen-Zeng/Travel-Agent.git travel-agent`.
   Data — git-ignored — copied from the laptop separately:
   `scp travel.db stories.faiss root@IP:/root/travel-agent/` and
   `rsync -avz app/static/spot_photos/ root@IP:/root/travel-agent/app/static/spot_photos/`.
   `Saved/`, `stories.json`, and `.env` never go to the server.
7. **Create `.env` on the server** with production values (ideally a fresh
   Anthropic key dedicated to prod). Also: in Google Cloud, change the browser
   key's allowed HTTP referrers to `travelai.the200.blog` (not `localhost`).
8. **Build and run:**
   `docker build -t travel-agent .` then
   `docker run -d --name travel-agent -p 8000:8000 --env-file .env --restart unless-stopped travel-agent`.
   Verify inside the box: `curl http://localhost:8000/` prints HTML.
9. **Install Caddy**, set `/etc/caddy/Caddyfile` to the three-line block with the
   real domain, `systemctl restart caddy`. Caddy fetches the certificate on
   first start (needs step 3's DNS to have propagated).
10. **Verify:** open `https://travelai.the200.blog/` — chat page, padlock icon.

**Redeploying** thereafter: `git push` from the laptop (re-`scp`/`rsync` the data
files only if they changed), then on the server `git pull && docker build ... &&
docker stop travel-agent && docker rm travel-agent && docker run ...`.

## 9. The two Google keys — a security boundary in the deployment

This came up in chapters `05` and `09`; here is the whole picture in one place.

| | `GOOGLE_MAPS_BROWSER_KEY` | `GOOGLE_PLACES_API_KEY` |
|---|---|---|
| Runs where | in every visitor's browser | only on the owner's laptop, in the offline scripts |
| Loaded by the web app? | yes — embedded in every page | **no** — not even a field on `Settings` |
| Public? | yes, unavoidably | no — never transmitted |
| Restriction | HTTP referrers = the production domain; API = Maps JavaScript only | API = Places only |
| Used for | loading the map + Advanced Markers | geocoding + rating/photo enrichment |

The browser key is *going* to be public, so it is locked to your domain and to a
non-billable-heavy API, plus a quota. The Places key — which does the work that
costs money per call — never leaves the laptop, so a scraped page cannot run up
charges with it. And because of Rule 1, no Google API is called on the server
request path at all: the coordinates are already in the database.

## 10. Spend limits, layered (the full stack)

1. **Anthropic monthly hard limit** — calls fail when hit. Set in the console.
2. **Google Cloud quota** on Maps JS API requests/day — actually caps usage.
   (A billing *budget* only emails.)
3. **App per-IP limit** (`RATE_LIMIT_PER_HOUR`, default 10) — mild abuse control.
4. **App site-wide daily cap** (`DAILY_MESSAGE_CAP`, default 300) — the app's own
   ceiling, meaningful because it holds across all IPs.
5. **`MAX_TOOL_CALLS_PER_TURN = 4`** in `app/chat.py` — bounds the model calls per
   message.

Layers 1–2 are the real safety net; 3–5 are defence in depth and UX (a friendly
"come back later" instead of a surprise bill).

---

## Exercises & checkpoints

Docker installed (`docker --version` works). If you cannot install Docker, do
1–2 by reading and skip 3–4.

1. **Read the layers.** For each line of the `Dockerfile`, say whether editing
   `app/main.py` would invalidate that layer's cache on the next `docker build`.
   Why is `COPY requirements.txt` before `COPY app/`?
2. **Find the secrets.** Grep the `Dockerfile` and `.dockerignore` for `.env`.
   Where does the running container actually get `LLM_API_KEY` from, if not the
   image?
3. **Build and run it locally.** With `travel.db` and `stories.faiss` present:
   `docker build -t travel-agent .`, then
   `docker run -d --name ta -p 8001:8000 --env-file .env travel-agent`, then
   `curl http://localhost:8001/`. Do you get the HTML page? Clean up with
   `docker stop ta && docker rm ta`.
4. **Write a Caddyfile.** For a hypothetical domain `trips.example.com` proxying
   to a container on port 8000, write the three-line Caddyfile. What must be true
   about DNS and firewall ports before Caddy could get a certificate for it?
5. **List the leak points.** Name every place an API key *could* end up exposed
   in this system (the HTML, the JS, the image, the git history, the logs) and,
   for each, what stops it. (Answers span `.gitignore`, `.dockerignore`,
   `config.py`'s exclusion of the Places key, and the browser-key restrictions.)

Continue to `13-run-and-modify-it-yourself.md`.
