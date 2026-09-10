# Learn web development and LLMOps — through this project

This folder is a self-contained course. It teaches you how a real, deployed web
application that talks to a large language model is built, from the ground up,
using **this repository as the worked example**. Every concept is explained from
scratch and then shown in the actual code that runs this site.

## Who this is for

You. Specifically: someone who already understands machine learning and large
language models (what a model is, what a token is, what "prompting" means) but has
**never built a website, a web server, or a deployed application**, and has never
used Git, Docker, SQL, JavaScript, HTML, or CSS in anger.

You do **not** need to know any of the following before starting — every one of
them is taught here:

- Python beyond "I have seen a `for` loop"
- What a "server" actually is
- HTML, CSS, JavaScript
- SQL or databases
- HTTP, JSON, APIs
- Git or GitHub
- Docker or "deployment"
- The Anthropic API or tool calling

## What you need in front of you

- A computer (macOS or Linux is assumed; Windows works with WSL).
- A terminal application. On macOS that is **Terminal.app**.
- This repository, cloned to your machine (chapter `11` teaches you how; chapter
  `13` walks you through running it).
- About 20–40 hours if you do every exercise. You can also read it straight
  through in a weekend and come back to the exercises later.

## The chapters, in order

| # | File | What it covers |
|---|------|----------------|
| — | `README.md` | This page. |
| 00 | `00-orientation.md` | What the app does, the two rules it is built on, a glossary, and a map of every file. **Read this first.** |
| 01 | `languages.md` | A thorough from-zero primer on Python, JavaScript, HTML, CSS, SQL, the shell, and the config-file formats — every example taken from this repo. |
| 02 | `02-how-the-web-works.md` | Clients, servers, HTTP, URLs, JSON, DNS, HTTPS, and "a response that never ends" (streaming). |
| 03 | `03-backend-fastapi.md` | The Python web server: FastAPI, Uvicorn, Pydantic, dependency injection, templating, and the streaming endpoint. A full tour of `app/main.py`. |
| 04 | `04-data-layer.md` | Relational databases, SQL, SQLite, the schema, and why the app can only *read* its data. Tours `app/db.py`, `app/queries.py`, `app/maps.py`, `app/geo.py`. |
| 05 | `05-frontend.md` | How a browser turns HTML+CSS+JS into a live page, the deliberate "no build step" choice, and a full tour of `app/static/app.js` and `style.css`. |
| 06 | `06-llmops-foundations.md` | What LLMOps is. The Anthropic Messages API, system prompts, tokens, cost, and the stateless-server design. |
| 07 | `07-llmops-tools-and-agents.md` | Tool calling, JSON-schema tools, the agent loop, and the three-layer defense that stops the model from ever inventing map coordinates. |
| 08 | `08-llmops-rag.md` | Retrieval-augmented generation: embeddings, vector search, FAISS, and the `get_city_context` tool. |
| 09 | `09-offline-data-pipeline.md` | The five scripts that build the database offline, the Google Places API, and the dependency-injection pattern that keeps tests offline. |
| 10 | `10-testing.md` | The testing philosophy: offline, deterministic, fake clients. `pytest`, fixtures, and the ~179-test suite. |
| 11 | `11-git-and-github.md` | Version control from scratch: commits, branches, `.gitignore`, GitHub, and how deployment depends on `git pull`. |
| 12 | `12-packaging-and-deployment.md` | Docker (images, containers, layers), Caddy, reverse proxies, automatic HTTPS, and the full server walkthrough. |
| 13 | `13-run-and-modify-it-yourself.md` | Hands-on: run the app locally, make three real changes, break a test and fix it. |
| 14 | `14-summary-and-roadmap.md` | How every piece connects, what the project deliberately leaves out, and a staged plan for continuing to learn. |

## If you only read three chapters

Read `00-orientation.md`, then `03-backend-fastapi.md`, then
`07-llmops-tools-and-agents.md`. Those three give you the spine of the whole
system: how a request comes in, how the model is called, and how the model's
tool calls become a map on the page.

## How to use the exercises

Chapters 02 through 13 each end with an **"Exercises & checkpoints"** section: two
to four concrete tasks with the outcome you should see. Do them with the app
running locally (chapter `13` gets you there). They are cumulative — later
exercises assume you did the earlier ones — but each is small.

## A one-paragraph description of the app

It is a personal travel website. One person ("Joey") exported their saved places
from Google Maps, geocoded them into a small database, and built a chat page where
visitors ask an AI version of Joey about cities, restaurants, and nightlife. When
the AI decides a map would help, the reply comes back as text **plus** an
interactive Google Map with Joey's saved spots pinned on it. There is no login,
nothing to sign up for, and visitors never change any data. It runs as a single
small server on a rented Linux machine, behind a piece of software that gives it
HTTPS automatically.

Start with `00-orientation.md`.
