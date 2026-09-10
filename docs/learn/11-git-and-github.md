# 11 — Git and GitHub, from scratch

Every file in this project is tracked by **Git**, the history is hosted on
**GitHub**, and — importantly — the deployment process *depends* on Git: updating
the live site is `git pull` on the server. This chapter teaches Git from nothing,
using this repository's own history and `.gitignore` as the examples.

---

## 1. The problem Git solves

Without version control you have `main.py`, `main_v2.py`, `main_final.py`,
`main_final_ACTUAL.py`, no record of *why* any change was made, and no safe way
for two people to edit the same file. Git replaces all of that with a single,
navigable history of **snapshots**.

## 2. The mental model: snapshots, not diffs

A Git repository is a folder with a hidden `.git/` subfolder holding the entire
history. The history is a chain of **commits**. Each commit is:

- a complete snapshot of every tracked file at that moment,
- a pointer to its parent commit (the one before it),
- an author, a timestamp, and a message.

(Internally Git deduplicates identical file contents so the storage is efficient,
but the *model* to hold in your head is "each commit is a full snapshot.")

Run `git log --oneline` in this repo and you see the chain:

```
94578b0 chanegs
bed5dcc Build Travel Agent: FastAPI chat app with saved-spots map, ...
f468578 change
6d101fd update
...
```

Each 7-character code (`94578b0`) is the start of the commit's **hash** — a unique
id. `HEAD` is a name for "the commit you are currently on" (normally the newest on
your branch).

## 3. The three areas

A file in a Git repo is in one of these:

1. **Working directory** — the actual files on disk, as you edit them.
2. **Staging area** (the "index") — a holding pen for the changes that will go
   into your *next* commit.
3. **The repository** — the committed history.

The everyday flow: edit files (working dir) → `git add` the ones you want
(staging) → `git commit` (repository).

## 4. The commands you actually need

### Inspecting

```
git status          # what's changed, what's staged, what's untracked
git diff            # line-by-line changes you have NOT staged yet
git diff --staged   # line-by-line changes you HAVE staged
git log             # the commit history (press q to quit)
git log --oneline   # one line per commit
git show <hash>     # what a specific commit changed
git blame app/main.py   # who last changed each line, and in which commit
```

### Making a commit

```
git add app/main.py app/chat.py     # stage specific files (preferred)
git add -A                          # stage EVERYTHING changed (use carefully)
git status                          # ALWAYS check what you staged
git commit -m "Add health-check endpoint"
```

`git status` after a broad `git add` is a habit worth building: it is your last
chance to notice you accidentally staged `.env` or a huge binary.

### Branches

A **branch** is a movable name pointing at a commit. `main` is the default. You
make a branch to work on something without disturbing `main`:

```
git switch -c fix-map-zoom     # create branch 'fix-map-zoom' and move onto it
# ... edit, add, commit ...
git switch main                # go back to main
git merge fix-map-zoom         # bring the branch's commits into main
```

This project's history is mostly linear (commits straight on `main`), which is
fine for a solo project. On a team, each change goes on its own branch and is
merged via a Pull Request (section 7).

### Undoing (carefully)

```
git restore app/main.py         # discard UNSTAGED changes to a file (cannot be undone!)
git restore --staged app/main.py  # unstage a file, keep the edits
git revert <hash>               # make a NEW commit that undoes an old one (safe, keeps history)
```

Avoid `git reset --hard` and `git checkout .` unless you are certain — they throw
away uncommitted work permanently. Before any destructive command, run
`git status` and `git stash` (which shelves your changes for later) if there is
anything you might want.

## 5. `.gitignore` — what Git must never track

A file listing path patterns Git ignores (chapter `01` §7.5). This repo's, with
the reasoning:

```gitignore
# --- Secrets ---
.env                        # real API keys. NEVER in version history.

# --- Python ---
__pycache__/                # compiled bytecode — regenerated, machine-specific
*.py[cod]

# --- Virtual environments ---
.venv/                      # hundreds of MB of installed libraries; rebuilt from requirements.txt

# --- Tooling caches ---
.pytest_cache/

# --- Editor / OS ---
.DS_Store                   # macOS folder metadata — noise

# --- Private docs (not shared) ---
DEPLOY.md                   # contains server IPs / deployment specifics
CLAUDE.md
CONTEXT.md

# --- Project data (built offline, never committed) ---
Saved/                      # the raw Google Maps CSV export — private, and an INPUT, not needed to run
*.db                        # travel.db — regenerable from Saved/ (chapter 09). Also large & binary.
*.db-shm
*.db-wal
stories.json                # the private diary source
stories.faiss               # the built index — regenerable from stories.json
app/static/spot_photos/     # downloaded photos — regenerable, and hundreds of files
```

Two categories:

- **Secrets** (`.env`) — must never enter history, because history is forever and
  is pushed to GitHub. A key committed once and "deleted" in a later commit is
  still in the history and must be treated as leaked.
- **Regenerable / machine-specific artifacts** (`.venv/`, `__pycache__/`,
  `*.db`, `stories.faiss`, `spot_photos/`) — no value in tracking; they bloat the
  repo and cause spurious conflicts. Given chapter `00`'s **Rule 2**, `travel.db`
  is *always* rebuildable from `Saved/` + the scripts, so not tracking it loses
  nothing. The repo tracks the *recipe*, not the *output*.

If you ever see `git status` list `travel.db` or `.env` as "untracked" and about
to be added — stop. Something is wrong with `.gitignore`.

## 6. What *is* tracked

`git ls-files` shows it: all of `app/`, all of `scripts/`, all of `tests/`,
`requirements.txt`, `.env.example` (the template, safe — it has blank values),
`Dockerfile`, `.dockerignore`, `Caddyfile`, `.gitignore`, `README.md`,
`BUILD_INSTRUCTIONS.md`, and now `docs/learn/`. That is: **every file needed to
rebuild the app from scratch, and nothing else.**

## 7. GitHub

GitHub is a website that hosts Git repositories and adds collaboration features. A
GitHub repo is a **remote** — a copy of your history living on their servers. This
project's remote is:

```
origin  https://github.com/Qingwen-Zeng/Travel-Agent.git
```

`origin` is just the conventional name for "the main remote." Commands:

```
git clone https://github.com/Qingwen-Zeng/Travel-Agent.git   # download the repo + full history
git push                                                      # send your local commits to origin
git pull                                                      # fetch origin's new commits and merge them in
git fetch                                                     # fetch without merging
```

On a team, changes flow through a **Pull Request (PR)**: you push a branch, open a
PR on GitHub proposing to merge it into `main`, others review the diff and
comment, CI runs the tests, and when approved it is merged. For this solo project
the flow is simpler (commit to `main`, push), but the mechanism is the same.

## 8. How deployment depends on Git

The server does **not** receive code via file copy. Per `DEPLOY.md` (chapter
`12`), the code gets onto the server by cloning this GitHub repo:

```
# on the server, once:
git clone https://github.com/Qingwen-Zeng/Travel-Agent.git travel-agent
```

And every subsequent deploy is:

```
# on your laptop:
git push

# on the server:
cd travel-agent
git pull
docker build -t travel-agent .
docker stop travel-agent && docker rm travel-agent
docker run -d --name travel-agent -p 8000:8000 --env-file .env travel-agent
```

`git pull` is the mechanism that moves new code from GitHub to the server. This is
why the data files are handled *separately* (copied with `scp`/`rsync`) — they are
git-ignored, so `git pull` would never bring them, by design.

## 9. Commit hygiene

This repo's older history has messages like `change`, `update`, `chanegs` — not a
model to follow. A good commit message:

- has a short summary line (≤ ~72 chars) in the imperative mood ("Add rate-limit
  headers", not "Added" or "Adds"),
- explains *why* in the body if the reason is not obvious from the diff,
- is one logical change (don't mix a bug fix and a refactor in one commit).

`bed5dcc Build Travel Agent: FastAPI chat app with saved-spots map, country/proximity
search, and personal-diary RAG` is a decent summary line — it says what the commit
delivers.

---

## Exercises & checkpoints

In the cloned repo.

1. **Read the history.** Run `git log --oneline`. How many commits? Run
   `git show bed5dcc --stat` — how many files did that commit add?
2. **See what is ignored.** Run `git status`. Do `travel.db`, `.env`, or
   `.venv/` appear as untracked? They should not. Now run
   `git check-ignore -v travel.db` — which line of `.gitignore` matches it?
3. **Make a branch and a commit.** `git switch -c my-notes`, add a new file
   `docs/learn/NOTES.md` with a sentence in it, `git add docs/learn/NOTES.md`,
   `git commit -m "Add personal notes file"`. Run `git log --oneline` — see your
   commit on top. Then `git switch main` and `git log --oneline` — your commit is
   not there. Switch back with `git switch my-notes`.
4. **Undo safely.** On your `my-notes` branch, edit `docs/learn/NOTES.md`, then
   run `git restore docs/learn/NOTES.md`. What happened to your edit? Now try
   `git revert HEAD` — what does *that* do differently?
5. **Reason about secrets.** Suppose someone commits `.env` with a real key, then
   the next day commits a `.gitignore` that ignores it and deletes the file. Is
   the key safe now? Why or why not? What must they actually do?

Continue to `12-packaging-and-deployment.md`.
