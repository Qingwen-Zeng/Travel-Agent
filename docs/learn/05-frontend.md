# 05 — The frontend: one HTML file, one JS file, one CSS file

Everything that runs in the visitor's browser is three files:
`app/templates/index.html` (rendered once by the server),
`app/static/app.js` (~700 lines), and `app/static/style.css` (~750 lines). There
is no framework, no build step, and no package manager. This chapter explains why
that is a deliberate choice, then tours all three files.

---

## 1. How a browser turns three files into a live page

1. The browser requests `GET /`. The server renders `index.html` and sends it.
2. The browser parses the HTML into the **DOM** — a tree of element objects.
3. As it parses, it sees `<link rel="stylesheet" href="/static/style.css?v=...">`
   and requests the CSS. It applies those rules to the DOM to decide how
   everything looks, and paints the page.
4. At the end of `<body>` it sees `<script src="/static/app.js?v=...">`, requests
   it, and runs it. By now the DOM exists, so the script can find and modify
   elements.
5. `app.js` also triggers loading the **Google Maps JavaScript API** (section 8),
   but only lazily — the first time a map actually needs to be drawn.
6. From here on, the page is "alive": every keystroke, click, and incoming stream
   event is handled by `app.js` mutating the DOM. No further full-page loads
   happen.

That step-6 model — load once, then update the page in place with JavaScript — is
what "single-page application" means. This app is a very small one.

## 2. The deliberate "no build step" decision

Most modern frontends run a **build step**: you write in JSX/TypeScript/Sass, and
a bundler (Webpack, Vite, esbuild) compiles, bundles, minifies, and
content-hashes it into files the browser can use. That requires Node.js, a
`package.json`, a `node_modules` folder with hundreds of transitive packages, and
a second toolchain in your deployment.

This project has **none of that**:

- No `package.json`, no `node_modules`, no `npm`.
- No bundler or transpiler.
- No framework (React, Vue, Svelte, …).
- No CSS tooling (Sass, Tailwind, PostCSS).
- Not even ES modules — `app.js` is a single classic `<script>`, wrapped in an
  IIFE (chapter `01` §2.11) for name isolation.

Why this is the right call *for this app*:

- **It is tiny.** One page, ~700 lines of JS, ~750 of CSS. A build pipeline would
  be more configuration than application.
- **Deployment stays trivial.** The `Dockerfile` installs Python dependencies and
  copies files. There is no `npm ci && npm run build` stage, no `dist/` to keep
  in sync, no second language runtime in the image.
- **Nothing to maintain or break.** No lockfile churn, no framework major-version
  migrations, no supply-chain risk from hundreds of build-time packages.
- **Cache-busting is already solved** server-side with file modification times
  (section 9) — the one job content-hashing would otherwise do.
- **Every browser feature used is natively supported** in current browsers:
  `EventSource`, `fetch`/`Promise`/`async`, `crypto.randomUUID()`, `WeakMap`,
  `TreeWalker`, CSS custom properties, flexbox. Nothing needs a polyfill, so
  nothing needs transpiling.
- **It is readable.** You can open three files and understand the entire client,
  top to bottom, with no indirection through a virtual DOM or a build graph.

The price paid: DOM elements are built by hand (`document.createElement`, or one
big `innerHTML` string in `buildMapContainerElement`), Markdown is rendered by a
hand-written 40-line function, and state is managed by hand. For an app this size
that is a net simplification. For a large app with many screens it would not be —
that is when a framework earns its complexity.

## 3. `index.html` — the page skeleton

The `<body>` (Jinja2 template syntax explained in chapter `01` Part 3 and chapter
`03`):

```html
<body>
  <div class="app-layout">
    <nav class="sidebar" aria-label="Conversations">
      <button type="button" id="new-chat-button" class="new-chat-button">+ New chat</button>
      <ul id="conversation-list" class="conversation-list"></ul>
    </nav>
    <div class="chat-page chat-page-empty">
      <div class="chat-header">
        <button type="button" id="sidebar-toggle" class="sidebar-toggle" aria-label="Toggle conversations" aria-expanded="false">☰</button>
      </div>
      <div id="chat-log" class="chat-log" aria-live="polite">
        <div id="empty-state" class="empty-state">
          <p class="empty-state-greeting">So happy that you stumbled onto my AI & engine! ...</p>
          <div class="chat-form-slot"></div>
          {% if suggestion_chips %}
          <div class="suggestion-section">
            <p class="suggestion-label">Try asking</p>
            <div class="suggestion-chips">
              {% for label in suggestion_chips %}
              <button type="button" class="suggestion-chip" data-question="{{ label }}">
                <span class="suggestion-chip-dot" aria-hidden="true"></span>
                <span class="suggestion-chip-text">{{ label }}</span>
              </button>
              {% endfor %}
            </div>
            <p class="suggestion-footer-hint">Don't see your destination? Just type it above ...</p>
          </div>
          {% endif %}
        </div>
      </div>
      <form id="chat-form" class="chat-form">
        <input id="chat-input" type="text" placeholder="Ask about any city, restaurant, or trip idea…" autocomplete="off" required>
        <button type="submit" class="chat-form-submit" aria-label="Send">→</button>
      </form>
    </div>
  </div>
  <script src="/static/app.js?v={{ asset_version }}"></script>
</body>
```

Key structural facts:

- **`.app-layout`** is a flex row: a fixed-width `.sidebar` (the conversation
  list) and a flexible `.chat-page` (the chat column).
- **`#chat-log`** is where every chat bubble and every map gets appended by JS.
  `aria-live="polite"` makes screen readers announce new content.
- **`#empty-state`** (the greeting + starter chips) is rendered *by the server*,
  so the very first paint already shows it. `app.js` clones it once into a
  template so later "New chat" clicks can rebuild it with no server round trip.
- **The `<form id="chat-form">` is created once and never cloned.** On the start
  screen `app.js` physically *moves* that same form node into `.chat-form-slot`
  (up near the greeting); once a conversation exists it moves it back to the
  bottom of `.chat-page`. Because `appendChild` re-parents rather than copies, the
  form keeps its event listeners through the move.
- The `<script>` is a plain classic script at the end of `<body>`.

The `<head>` also contains the Google Maps loader — section 8.

## 4. `app.js` — overall shape

The whole file is:

```js
(function () {
  // ...everything...
})();
```

An IIFE (chapter `01` §2.11): every name inside is private, nothing leaks to
`window`. The module-level state:

```js
let librariesPromise = null;               // the Google Maps libraries, loaded once
const mapsByContainer = new WeakMap();     // map-canvas element  →  { map, markers[] }
const state = { conversations: [], activeId: null };   // the entire app state
let emptyStateTemplate = null;             // a clone of #empty-state
```

`mapsByContainer` is a **`WeakMap`**, not a `Map`, on purpose (comment at the top
of the file): switching conversations throws away and rebuilds map-canvas DOM
nodes. With a `WeakMap` keyed on the (now-detached) node, the browser can
garbage-collect the old Google `Map` object once nothing references that node. A
regular `Map` would keep every map ever rendered alive forever.

The code does nothing until the DOM is ready:

```js
document.addEventListener("DOMContentLoaded", () => {
  // wire up the form, the sidebar toggle, the delegated click listener,
  // create the first conversation, render the sidebar
});
```

## 5. Sending a message

Two ways to start a send: submitting the form, or clicking a suggestion chip.
Both call `sendChatMessage`:

```js
async function sendChatMessage(message) {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const submitButton = form.querySelector("button");
  const convo = activeConversation();

  hideEmptyState();
  appendChatBubble("user", message);
  const pending = appendChatBubble("assistant", "Thinking…", "chat-bubble-pending");
  submitButton.disabled = true;
  input.disabled = true;
  setSidebarDisabled(true);

  try {
    await streamChatMessage(message, pending, convo);
  } catch (error) {
    pending.remove();
    appendChatBubble("assistant", "Sorry, something went wrong. Please try again.");
    console.error(error);
  } finally {
    submitButton.disabled = false;
    input.disabled = false;
    setSidebarDisabled(false);
    input.focus();
  }
}
```

- `const convo = activeConversation()` is captured **before any `await`**. That
  reference is passed all the way into the stream handler, so if the visitor
  switches conversations mid-reply, the answer still lands in the *right*
  conversation's data.
- It shows an immediate optimistic user bubble and a greyed-out italic "Thinking…"
  placeholder.
- It disables the input, the send button, **and the whole sidebar** during the
  stream, then re-enables everything and refocuses the input in `finally` — so a
  failure never leaves the UI stuck.

## 6. Consuming the SSE stream

`streamChatMessage` wraps the event-driven `EventSource` API in a `Promise` so the
caller can `await` it:

```js
function streamChatMessage(message, pendingBubble, convo) {
  return new Promise((resolve, reject) => {
    const params = new URLSearchParams({ message, history: JSON.stringify(convo.history) });
    const eventSource = new EventSource(`/api/chat/stream?${params.toString()}`);

    let assistantBubble = null;
    let assistantText = "";
    let mapPayload = null;

    function ensureAssistantBubble() {
      if (!assistantBubble) {
        pendingBubble.remove();
        assistantBubble = appendChatBubble("assistant", "");
      }
      return assistantBubble;
    }

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "delta") {
        const bubble = ensureAssistantBubble();
        assistantText += data.text;
        bubble.innerHTML = renderMarkdown(assistantText);
        document.getElementById("chat-log").scrollTop = /* ... */;
      } else if (data.type === "map") {
        mapPayload = data.map;
      } else if (data.type === "done") {
        eventSource.close();
        const bubble = ensureAssistantBubble();

        convo.history.push({ role: "user", content: message });
        convo.history.push({ role: "assistant", content: assistantText });
        convo.transcript.push({ type: "user", text: message });
        convo.transcript.push({ type: "assistant", text: assistantText });
        if (!convo.title) {
          convo.title = message.length > 40 ? `${message.slice(0, 40)}…` : message;
          renderSidebar();
        }

        if (mapPayload && mapPayload.markers.length > 0) {
          linkifySpotMentions(bubble, mapPayload.markers);
          convo.transcript.push({ type: "map", payload: mapPayload });
          const mapContainer = buildMapContainerElement();
          document.getElementById("chat-log").appendChild(mapContainer);
          renderMapPayload(mapContainer, mapPayload).then(resolve).catch(reject);
        } else {
          resolve();
        }
      }
    };

    eventSource.onerror = () => { eventSource.close(); reject(new Error("Stream connection failed")); };
  });
}
```

Walk it:

- `new EventSource(url)` opens the streaming connection. Because `EventSource` can
  only `GET` (chapter `02` §6), the message and the **entire prior history**
  (`JSON.stringify(convo.history)`) are packed into the query string via
  `URLSearchParams`.
- `onmessage` fires once per SSE event. Every event is `JSON.parse`d.
- `"delta"` — a text fragment. It is appended to `assistantText`, and the *whole*
  accumulated string is re-rendered through `renderMarkdown` each time. (Simpler
  than incremental parsing; fine for short replies.) The first delta swaps the
  "Thinking…" placeholder for the real bubble.
- `"map"` — the payload is **stashed**, not drawn. It will be drawn on `done`,
  after the prose is complete, so the map appears below the finished text.
- `"done"` — close the connection (this also stops `EventSource`'s automatic
  reconnection). Then:
  - Commit the exchange to **both** `convo.history` (the `{role, content}` form
    the model needs next turn) and `convo.transcript` (the `{type, ...}` form used
    to redraw the conversation later).
  - Derive the conversation title from the first user message, truncated to 40
    characters, and re-render the sidebar.
  - If there is a map with markers: linkify spot names in the bubble (section
    7.3), record a `map` entry in the transcript, build the map container, and
    call `renderMapPayload`. Only when *that* resolves does the outer Promise
    resolve — so `sendChatMessage`'s `await` completes after the map is on screen.

## 7. Rendering

### 7.1 Markdown — a deliberately tiny, safe subset

The model replies in light Markdown. `app.js` renders it by hand, with no
library, supporting **only**: `-`/`*` bullet lists, blank-line-separated
paragraphs, `` `code` ``, `**bold**`, `*italic*`. No headings, links, images,
tables, or code fences.

The security model is the important part:

```js
function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
             .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function renderInlineMarkdown(text) {
  let html = escapeHtml(text);                         // 1. neutralise ALL HTML first
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>"); // 2. then re-introduce only
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>"); //    a fixed allowlist
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>"); //    of safe tags
  return html;
}
```

**Escape first, then wrap.** Any `<`, `>`, `&`, quote in the model's text becomes
a harmless HTML entity. Then the three regexes add back *only* `<code>`,
`<strong>`, `<em>` around already-escaped content. So even if a reply contained
`<script>alert(1)</script>`, it would render as literal visible text, never
execute. This is how you safely put model (or user) output into `innerHTML`.

Compare `appendChatBubble`:

```js
if (role === "assistant") {
  bubble.innerHTML = renderMarkdown(text);   // parsed — but only via the safe subset above
} else {
  bubble.textContent = text;                  // user text: never parsed at all
}
```

### 7.2 The map: `renderMapPayload` and the card state machine

`buildMapContainerElement()` builds the DOM for a map block (one `innerHTML`
string): a `.chat-map-canvas` (where Google draws the map) plus a floating
`.chat-map-list` card containing a header, a scrollable list, and a hidden
`.chat-map-detail-view` (photo, title, meta, a *Directions* link, phone, website,
notes, and a prev/next pager).

`renderMapPayload(container, payload)` then:

```js
async function renderMapPayload(container, payload) {
  const spots = payload.markers;
  // ... grab the sub-elements ...
  const libs = await loadLibraries();                 // Google Maps, loaded once
  const entry = getOrCreateMapEntry(canvasEl, libs);  // reuse or create the Map object
  clearMarkers(entry);
  renderSpotList(listItemsEl, spots);                 // build the list rows

  function showDetail(i) {
    detailEl.dataset.index = String(i);
    renderDetail(detailEl, spots[i], i, count);
    cardEl.classList.add("chat-map-list-showing-detail");
    badges.forEach((b, j) => b.classList.toggle("map-marker-badge-active", j === i));
    listItems.forEach((el, j) => el.classList.toggle("map-list-item-active", j === i));
    entry.map.panTo({ lat: spots[i].lat, lng: spots[i].lng });
    if (entry.map.getZoom() < 17) entry.map.setZoom(17);
  }
  function showList() { cardEl.classList.remove("chat-map-list-showing-detail"); }

  // wire close / prev / next buttons ...

  spots.forEach((spot, i) => {
    const badge = buildMarkerBadge(spot, i + 1);
    const marker = new libs.AdvancedMarkerElement({ map: entry.map, position: {lat: spot.lat, lng: spot.lng}, title: spot.title, content: badge });
    badge.addEventListener("click", () => showDetail(i));
    listItems[i].addEventListener("click", () => showDetail(i));
    badges.push(badge);
    entry.markers.push(marker);
  });

  frameMap(entry, libs, spots);           // fit the viewport to all the pins
  container.selectSpot = showDetail;       // expose for inline text links (7.3)
}
```

The floating card is a small **state machine** driven purely by CSS classes that
JS toggles:

| State | Class on `.chat-map-list` | Effect |
|-------|--------------------------|--------|
| list (default) | *(none)* | the scrollable list of spots is visible |
| collapsed | `.chat-map-list-collapsed` | card shrinks to just its header, so you can see the map |
| detail | `.chat-map-list-showing-detail` | header + list hidden, the single-spot detail view shown |
| selected pin | `.map-marker-badge-active` / `.map-list-item-active` | the current spot is highlighted in *both* the pin badge and the list row |

`detailEl.dataset.index` is the single source of truth for "which spot is open" —
the prev/next handlers read it fresh on each click rather than closing over a
stale variable.

`frameMap`: 0 markers → do nothing; 1 marker → centre and zoom to 15; many →
build a `LatLngBounds`, extend it with every point, and `fitBounds` with 40px
padding.

### 7.3 Clickable spot names in the reply text

When an assistant reply mentions a saved spot by name, the *first* mention becomes
a button that jumps the map below to that spot's detail view.

```js
function linkifyFirstSpotMention(root, title, spotIndex) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    const parent = node.parentElement;
    const skip = parent && parent.closest(".spot-name-link, code");
    const idx = skip ? -1 : node.nodeValue.toLowerCase().indexOf(title.toLowerCase());
    if (idx !== -1) {
      // split this text node into  before | <button>match</button> | after
      const text = node.nodeValue;
      const button = document.createElement("button");
      button.className = "spot-name-link";
      button.dataset.spotIndex = String(spotIndex);
      button.textContent = text.slice(idx, idx + title.length);
      const afterNode = document.createTextNode(text.slice(idx + title.length));
      node.nodeValue = text.slice(0, idx);
      parent.insertBefore(button, node.nextSibling);
      parent.insertBefore(afterNode, button.nextSibling);
      return;
    }
    node = walker.nextNode();
  }
}

function linkifySpotMentions(bubbleEl, spots) {
  spots.map((spot, i) => ({ title: spot.title, i }))
       .sort((a, b) => b.title.length - a.title.length)   // longest first
       .forEach(({ title, i }) => linkifyFirstSpotMention(bubbleEl, title, i));
}
```

- A **`TreeWalker`** steps through only the *text nodes* of the rendered bubble,
  so it can edit raw text without disturbing the `<strong>`/`<em>`/`<code>`
  structure Markdown produced.
- It splits the matched text node into three: the text before, a new
  `<button class="spot-name-link" data-spot-index="i">`, and the text after.
- It **skips** text already inside a `.spot-name-link` or `<code>`, so nothing
  gets double-linked.
- **Longest titles first**, so "Wine Bar" is linked before the bare word "Bar",
  and the already-linked "Wine Bar" is then skipped when "Bar" is processed.

The click is handled by **one delegated listener** on `#chat-log` (so it survives
conversation switches that replace all of `#chat-log`'s children):

```js
chatLog.addEventListener("click", (event) => {
  const link = event.target.closest(".spot-name-link");
  if (!link) return;
  const bubble = link.closest(".chat-bubble-assistant");
  let sibling = bubble.nextElementSibling;
  while (sibling && !sibling.classList.contains("chat-map") && !sibling.classList.contains("chat-bubble")) {
    sibling = sibling.nextElementSibling;
  }
  if (sibling && sibling.classList.contains("chat-map") && sibling.selectSpot) {
    sibling.scrollIntoView({ behavior: "smooth", block: "nearest" });
    sibling.selectSpot(Number(link.dataset.spotIndex));
  }
});
```

It walks forward from the clicked link's assistant bubble to the next `.chat-map`
sibling, scrolls it into view, and calls `sibling.selectSpot(index)` — which is
the `showDetail` closure that `renderMapPayload` stashed on the container. That is
the whole reason `showDetail` is exposed as `container.selectSpot`: to give inline
text links a handle into a specific map's internal state.

## 8. Loading the Google Maps JavaScript API

Three scripts in `<head>`, in order:

**1.** Publish config for `app.js` to read later:

```html
<script>
  window.APP_CONFIG = { mapId: {{ google_maps_map_id | tojson }} };
</script>
```

**2.** Google's official inline "dynamic library import" loader (a minified
snippet you paste from Google's docs). Deobfuscated, it:

- defines `google.maps.importLibrary(name)` — a function you call later to load
  one named piece of the Maps API on demand;
- on the first call, builds a `<script>` pointing at
  `https://maps.googleapis.com/maps/api/js?key=...&v=weekly&callback=...` and adds
  it to `<head>`; later calls reuse the same in-flight Promise, so the API script
  loads exactly once;
- takes its parameters from the object passed to it:

  ```html
  <script>
    (g=>{ /* minified loader */ })({
      key: {{ google_maps_browser_key | tojson }},
      v: "weekly",
    });
  </script>
  ```

  No `libraries=` is hard-coded in the URL — that is the point of the dynamic
  loader; libraries are requested from JS when needed.

**3.** `app.js` itself, at the end of `<body>`.

Then in `app.js`:

```js
function loadLibraries() {
  if (!librariesPromise) {
    librariesPromise = Promise.all([
      google.maps.importLibrary("core"),    // → LatLngBounds
      google.maps.importLibrary("maps"),    // → Map
      google.maps.importLibrary("marker"),  // → AdvancedMarkerElement
    ]).then(([core, maps, marker]) => ({ Map: maps.Map, AdvancedMarkerElement: marker.AdvancedMarkerElement, LatLngBounds: core.LatLngBounds }));
  }
  return librariesPromise;
}
```

`librariesPromise` is a module-level singleton, so however many maps a session
renders, the libraries resolve once.

### API key vs Map ID

- **`GOOGLE_MAPS_BROWSER_KEY`** — a *browser key*. It is sent to every visitor in
  the HTML; it is **public by design**, readable in "View Source." It is not
  protected by secrecy but by *restrictions* set in the Google Cloud Console:
  locked to your domain (HTTP referrers), locked to the Maps JavaScript API only
  (it cannot call the billable Places API), and given a daily quota. It is a
  *different* key from `GOOGLE_PLACES_API_KEY`, which is server-only and never
  reaches the browser (chapters `09`, `12`).
- **`GOOGLE_MAPS_MAP_ID`** — not a key. An identifier for a *map style
  configuration* you create in the Console. It is **required for Advanced
  Markers**; without it, `AdvancedMarkerElement` silently fails to render. It is
  passed into every `new libs.Map(canvasEl, { mapId: window.APP_CONFIG.mapId, ... })`.

### Advanced Markers

`AdvancedMarkerElement` is Google's modern marker. The feature this app relies on:
its `content` property accepts **any DOM element**, so a marker can *be* a styled
HTML `<button>` instead of a teardrop pin image. `buildMarkerBadge` creates a
little rounded rating badge `<button class="map-marker-badge">` and hands it in as
`content`. That is why `.map-marker-badge` is a normal CSS class with `:hover` and
an `-active` state — the "pin" is a DOM node the app owns and styles.

Removing a marker is `marker.map = null` (see `clearMarkers`), the Advanced Marker
idiom.

## 9. `?v=` cache-busting

```html
<link rel="stylesheet" href="/static/style.css?v={{ asset_version }}">
<script src="/static/app.js?v={{ asset_version }}"></script>
```

`asset_version` is computed server-side (chapter `03` §6) from the two files'
last-modified times, e.g. `"1757462640-1757462700"`. Same files → same string →
browser reuses its cache. Edit either file (and redeploy — Docker resets mtimes) →
new string → new URL → browser refetches. No hashing, no manifest, no tooling.

## 10. The multi-conversation state model

```js
const state = { conversations: [], activeId: null };
```

That plain object is the entire store. No Redux, no signals, no framework. Each
conversation:

```js
{
  id: crypto.randomUUID(),
  title: null,          // null until the first message; then message.slice(0, 40) + "…"
  history: [],           // [{role, content}]  — the LLM-facing memory, sent on the next request
  transcript: [],        // [{type: "user"|"assistant"|"map", ...}] — the UI-facing record, for redrawing
}
```

Why two lists?

- `history` is exactly the shape the model needs as context — `{role, content}`
  pairs. It is `JSON.stringify`d into the `history` query param on every stream
  request. The **server keeps none of this**; the browser is the sole memory.
- `transcript` is richer: it also records which reply had a map and *which* map,
  so a reopened conversation can be redrawn pixel-for-pixel — bubbles *and* maps —
  by replaying it through the same `appendChatBubble` / `renderMapPayload` used
  live.

`switchConversation(id)` wipes `#chat-log` (`log.innerHTML = ""`) and either shows
a fresh empty state or calls `renderTranscript(convo.transcript)`.
`createConversation()` `unshift`s a new empty conversation (newest on top) and
switches to it. `renderSidebar()` rebuilds the `<ul>` from `state.conversations`,
marking the active one with `.conversation-item-active` and `aria-current="true"`.

**Persistence: none, on purpose.** No `localStorage`, no `sessionStorage`, no
cookie. A refresh or tab close discards every conversation. This keeps the server
completely stateless and sidesteps any storage/privacy questions. (A page refresh
does *not* clear `sessionStorage` — only closing the tab does — so
`sessionStorage` would actually be the *wrong* tool for "gone on refresh"; a plain
in-memory variable is the correct match.)

## 11. `style.css` — organisation

One file, ~750 lines, no preprocessor, no framework. Top to bottom:

### Design tokens on `:root`

```css
:root {
  --color-bg: #f6f3ec;
  --color-surface: #efebe1;
  --color-border: #e0dbcc;
  --color-text: #2c2a25;
  --color-accent: #3f4f4a;
  --color-accent-text: #f6f3ec;
  /* a separate, neutral palette used ONLY inside the floating map card: */
  --map-card-bg: #ffffff;
  --map-card-text: #202124;
  --map-card-hover: #f1f3f4;
}
```

Two token families on purpose: `--color-*` is the warm "paper" theme for the site
chrome (sidebar, bubbles, input); `--map-card-*` is a neutral Google-grey palette
used only in the map card, so it visually reads as "a Google Maps UI."

### Reset and base

```css
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, "Helvetica Neue", system-ui, "Segoe UI", sans-serif;
  color: var(--color-text);
  background: var(--color-bg);
}
```

Minimal reset. A **system font stack** — no web font is downloaded.

### Layout

`.app-layout` (flex row) → `.sidebar` (fixed 260px, `flex-shrink: 0`) +
`.chat-page` (`flex: 1; min-width: 0; max-width: 720px; margin: 0 auto`).
`.chat-page` is itself a flex column: `.chat-header` (mobile only), the scrollable
`#chat-log` (`flex: 1; overflow-y: auto`), and the pinned `.chat-form`. The
`.chat-page-empty` modifier centres the content and floats the input up near the
greeting on the start screen.

### Component blocks

In file order: the sidebar buttons, the conversation list, the chat header and
sidebar toggle, the chat log (with a custom thin scrollbar), the empty state and
suggestion chips, the chat bubbles (`.chat-bubble-user` has the lopsided
`border-radius: 16px 16px 4px 16px`; `.chat-bubble-assistant` has typographic
rules for its `<p>`/`<ul>`/`<strong>`/`<code>`), `.spot-name-link` (styled to look
like an inline text link even though it is a `<button>`), the whole `.chat-map*`
family (canvas, floating card, collapsed state, list rows, marker badges, the
detail view), and finally `.chat-form` (a rounded pill with a circular send
button).

### Responsive: one media query

```css
@media (max-width: 700px) {
  .chat-header { display: flex; }             /* show the ☰ button */
  .sidebar {
    position: fixed; inset: 0 25% 0 0;
    transform: translateX(-100%);             /* off-canvas drawer */
    transition: transform 0.2s ease;
  }
  .app-layout.sidebar-open .sidebar { transform: translateX(0); }
  .app-layout.sidebar-open::after {           /* dimmed backdrop, NO extra HTML element */
    content: ""; position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35);
  }
  .chat-map-list { /* corner card becomes a bottom sheet */ }
}
```

One breakpoint. The sidebar becomes a drawer; `.sidebar-open` (added by JS on the
☰ tap) slides it in. The backdrop is a `::after` pseudo-element — a click that
lands on `.app-layout` itself (only possible in the backdrop gap) closes the
sidebar.

---

## Exercises & checkpoints

App running locally (chapter `13`). Use the browser's DevTools (F12 / right-click
→ Inspect).

1. **Add a suggestion chip.** In `app/main.py`, add a pair to `FAVORITE_EXAMPLES`
   for a city that exists in your database. Reload `/` and confirm a new chip
   appears. Click it — does it send that exact text as a message?
2. **Watch the stream.** Open DevTools → Network. Send a chat message. Find the
   `stream?message=...` request, open it, and look at the "EventStream" / response
   tab. Identify the `delta`, `map` (if any), and `done` events.
3. **Change a colour token.** In `style.css`, change `--color-accent` to a
   different hex. Hard-reload (Cmd/Ctrl-Shift-R). What all changed? Note the
   `?v=` on the stylesheet URL before and after `touch app/static/style.css`.
4. **Add a field to the detail card.** The map payload includes `maps_url`.
   In `buildMapContainerElement` add a `<div class="chat-map-detail-mapsurl">`
   and in `renderDetail` set its `textContent` to `spot.maps_url`. Send a message
   that produces a map, open a spot's detail, and confirm you see the URL.
5. **Break linkify, then understand it.** Temporarily change
   `linkifySpotMentions`'s sort to `.sort((a, b) => a.title.length - b.title.length)`
   (shortest first). Find two saved spots where one name contains the other, ask
   about them, and observe the double-linking bug. Revert.
6. **Prove there is no persistence.** Have a conversation, then refresh the page.
   What happens to the sidebar and the conversation? Which lines of `app.js`
   (or absence of lines) explain it?

Continue to `06-llmops-foundations.md`.
