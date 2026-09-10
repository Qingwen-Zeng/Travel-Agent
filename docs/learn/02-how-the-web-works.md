# 02 — How the web works

Before you can understand a web *application*, you need the plumbing underneath it:
what a request is, what a server does, how a browser and a server talk, and what
"streaming" means. This chapter builds that from nothing, using this project's own
endpoints as the examples.

---

## 1. Client and server

Two programs, two roles:

- The **client** starts conversations. It sends a **request** ("give me X") and
  waits for a **response**.
- The **server** waits for requests and answers them. It never speaks first.

For this project:

- The **client** is the visitor's web browser (Chrome, Safari, Firefox…).
- The **server** is a Python program — `app/main.py` run by a program called
  Uvicorn — listening on a computer for incoming requests.

A single visitor loading the page and chatting produces *many* request/response
round trips: one for the HTML page, one for the CSS file, one for `app.js`, one
for each Google Maps library, one (long-lived) for each chat message, one for
each map photo. Each is independent.

## 2. What actually travels: HTTP

**HTTP** ("HyperText Transfer Protocol") is the agreed format for those requests
and responses. It is plain text (conceptually — HTTPS encrypts it in transit).

### A request has four parts

1. **A method** — the *verb*, saying what kind of action this is:
   - `GET` — "give me this resource." Should not change anything on the server.
     Safe to repeat. Used for the page, the static files, and — because of a
     browser limitation you will meet in chapter `05` — the streaming chat
     endpoint.
   - `POST` — "here is some data; do something with it." Used for `/api/chat`
     (the non-streaming version), where the visitor's message and history are
     sent in the request body.
   - `PUT`, `PATCH`, `DELETE` — update / partial-update / delete. **This app uses
     none of them**, because of Rule 2 (nothing is ever written at runtime).
2. **A path** (and optional query string) — *which* resource:
   `/`, `/static/app.js`, `/api/city/Taipei`,
   `/api/chat/stream?message=hi&history=%5B%5D`.
   Everything after the `?` is the **query string**: `key=value` pairs joined by
   `&`, with special characters percent-encoded (`%5B%5D` is `[]`).
3. **Headers** — metadata as `Name: value` lines. Examples the browser sends:
   `Host: travelai.the200.blog`, `Accept: text/html`,
   `User-Agent: Mozilla/5.0 ...`, `Cookie: ...` (this app sets no cookies).
4. **A body** — optional payload. Empty for `GET`. For this app's `POST
   /api/chat` it is a JSON object: `{"message": "...", "history": [...]}`.

### A response has three parts

1. **A status code** — a three-digit number saying how it went:
   - `2xx` success. `200 OK` is the normal one.
   - `3xx` redirect ("look over there instead").
   - `4xx` the client did something wrong. `404 Not Found` — the app returns this
     from `/api/city/{name}` when the name is not a known city. `429 Too Many
     Requests` is the *conventional* rate-limit code, though this app deliberately
     does **not** use it (chapter `03` explains why it returns a friendly `200`
     instead).
   - `5xx` the server broke.
2. **Headers** — e.g. `Content-Type: text/html; charset=utf-8` (this response is
   an HTML page), or `Content-Type: application/json`, or
   `Content-Type: text/event-stream` (this is a stream — section 6).
3. **A body** — the actual content: the HTML, the JSON, the CSS text, the image
   bytes.

### Try it yourself

With the app running locally (chapter `13`), `curl` is a command-line HTTP client.
`-v` shows the headers:

```
curl -v http://127.0.0.1:8000/
```

You will see the request line (`GET / HTTP/1.1`), the request headers, then
`< HTTP/1.1 200 OK`, the response headers including `content-type: text/html`, and
the HTML body.

## 3. URLs, hosts, ports, and `localhost`

A full URL:

```
https://travelai.the200.blog/api/chat/stream?message=hi
└─┬─┘   └────────┬────────┘└──────┬───────┘└────┬────┘
scheme        host             path        query string
```

- **scheme** — `http` or `https`. `https` = encrypted + the server proves its
  identity with a certificate (section 5).
- **host** — a name (or an IP address). The client needs to turn the name into an
  IP (section 4) before it can connect.
- **port** — implied by the scheme when omitted: `http` → 80, `https` → 443. You
  can state it explicitly: `http://127.0.0.1:8000/`. A **port** is just a
  numbered slot on a machine so multiple servers can coexist; this app's server
  listens on 8000 in development and (behind Caddy) 8000 in production too, with
  Caddy itself on 443.
- **localhost** / `127.0.0.1` — always means "this same computer." When you run
  the app locally and open `http://127.0.0.1:8000/`, the browser and the server
  are the same machine.

## 4. DNS — names to numbers

Computers route by numeric **IP address** (`2.28.113.54`), not names. **DNS**
(the Domain Name System) is the internet's phone book. When the browser needs
`travelai.the200.blog`, it asks a DNS resolver, which returns the IP, and the
browser connects to that.

Someone deploying this app has to create a **DNS record** — specifically an
**A record** — that maps `travelai.the200.blog` → the server's IP. That is one of
the steps in `DEPLOY.md` (chapter `12`). Until that record exists and propagates,
the name does not resolve and nobody can reach the site by name.

## 5. HTTPS, TLS, and certificates

Plain HTTP is readable by anything between the client and server (your café's
Wi-Fi, your ISP). **HTTPS** wraps HTTP in **TLS**, which provides two things:

1. **Encryption** — nobody in the middle can read or tamper with the traffic.
2. **Identity** — the server presents a **certificate**, cryptographically signed
   by a trusted **Certificate Authority** (CA), proving it really is
   `travelai.the200.blog` and not an impostor.

Getting a certificate used to be a chore. This project uses **Caddy** (chapter
`12`), which on first run automatically contacts a free CA (Let's Encrypt), proves
it controls the domain, obtains the certificate, serves the site over HTTPS, and
renews the certificate before it expires — with zero configuration beyond naming
the domain. That is why the `Caddyfile` is three lines.

## 6. Streaming — "a response that never ends"

Normally a response is sent all at once: the server computes the whole body, sets
`Content-Length`, sends it, done. But the model writes its reply over several
seconds, and you want the visitor to see words appear as they are generated.

The solution here is **Server-Sent Events (SSE)**. It is still one HTTP response,
but:

- The response header is `Content-Type: text/event-stream`.
- The server does **not** send a `Content-Length`. It keeps the connection open
  and writes the body in chunks over time.
- The body is a sequence of **events**, each formatted as one or more `data:`
  lines followed by a blank line:

  ```
  data: {"type": "delta", "text": "Taipei"}

  data: {"type": "delta", "text": " has"}

  data: {"type": "map", "map": {"city": "Taipei", "markers": [ ... ]}}

  data: {"type": "done"}

  ```

- The browser has a built-in client for this: `new EventSource(url)`. It fires an
  `onmessage` callback once per event, giving you `event.data` (the text after
  `data:`), which this app always `JSON.parse`s.

You can watch the raw stream with `curl` (it will hang, printing events as they
arrive, until you press Ctrl-C):

```
curl -N "http://127.0.0.1:8000/api/chat/stream?message=hi&history=%5B%5D"
```

Two important limitations of `EventSource` that shaped this app's design:

- It can only make **`GET`** requests. That is why the streaming endpoint is
  `GET /api/chat/stream` and the message + entire history are crammed into the
  query string, rather than sent in a request body.
- It automatically reconnects if the connection drops. This app's JS explicitly
  calls `.close()` after the `done` event to stop that.

There are newer, more flexible mechanisms (`fetch` with a `ReadableStream`,
WebSockets). SSE was chosen because it is simple, one-directional (server → client
is all that is needed here), and needs no extra library on either side.

## 7. What "an API" and "REST" mean here

An **API endpoint** returns *data* (usually JSON) for a program to consume, as
opposed to an HTML *page* for a person to look at. This app has three real API
endpoints:

| Endpoint | Returns |
|----------|---------|
| `GET /api/city/{name}` | JSON: the map payload for one city (used by the homepage's city browser). `404` if the name is unknown. |
| `POST /api/chat` | JSON: `{"text": "...", "map": {...}}` — the whole reply at once, no streaming. |
| `GET /api/chat/stream` | An SSE stream of `delta` / `map` / `done` events. |

**REST** is a loose set of conventions for designing such APIs: use the HTTP
methods for their meanings (`GET` reads, `POST` creates), put the resource
identity in the path (`/api/city/Taipei`, not `/api/getCity?name=Taipei`), and
return meaningful status codes. This app follows those conventions loosely; it is
small enough that it doesn't need a formal API design.

## 8. The browser as a runtime

The browser is not just a document viewer. It is an execution environment that
gives `app.js`:

- The **DOM** — the live page as a tree of objects it can read and change
  (chapter `01`, Part 2).
- **Networking** — `fetch`, `EventSource`, the ability to load `<script>` and
  `<img>` by URL.
- **Storage** — cookies, `localStorage`, `sessionStorage` (this app deliberately
  uses *none* of them — see chapter `05`; conversations live only in a plain JS
  variable and vanish on refresh).
- **APIs** — `crypto.randomUUID()`, timers, the History API, and hundreds more.

Everything `app.js` does is a call into one of these browser-provided
capabilities.

---

## Exercises & checkpoints

You need the app running locally for 1–3 (chapter `13`); 4–5 are reading.

1. Run `curl -v http://127.0.0.1:8000/` and identify, in the output: the request
   method and path, the response status code, and the `content-type` header of
   the response.
2. Run `curl -v http://127.0.0.1:8000/api/city/Taipei` and then
   `curl -v http://127.0.0.1:8000/api/city/Atlantis`. What status code does each
   return, and what does the body look like?
3. Run `curl -N "http://127.0.0.1:8000/api/chat/stream?message=hello&history=%5B%5D"`.
   Describe the sequence of `data:` lines you see. Which `type` values appear, and
   in what order? (`%5B%5D` is the URL-encoding of `[]`.)
4. The app never uses `PUT` or `DELETE`. Which of the two architectural rules from
   chapter `00` explains that?
5. `EventSource` can only issue `GET` requests. Explain, in one sentence, why that
   forces the chat history to be sent in the URL query string rather than a
   request body.

Continue to `03-backend-fastapi.md`.
