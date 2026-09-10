(function () {
  let librariesPromise = null;
  // WeakMap, not Map: switching conversations discards and rebuilds canvas elements,
  // so old entries must be garbage-collectable once nothing else references that node.
  const mapsByContainer = new WeakMap();

  function loadLibraries() {
    if (!librariesPromise) {
      librariesPromise = Promise.all([
        google.maps.importLibrary("core"),
        google.maps.importLibrary("maps"),
        google.maps.importLibrary("marker"),
      ]).then(([coreLib, mapsLib, markerLib]) => ({
        Map: mapsLib.Map,
        AdvancedMarkerElement: markerLib.AdvancedMarkerElement,
        LatLngBounds: coreLib.LatLngBounds,
      }));
    }
    return librariesPromise;
  }

  function getOrCreateMapEntry(canvasEl, libs) {
    let entry = mapsByContainer.get(canvasEl);
    if (!entry) {
      const map = new libs.Map(canvasEl, {
        mapId: window.APP_CONFIG.mapId,
        gestureHandling: "cooperative",
        center: { lat: 0, lng: 0 },
        zoom: 2,
      });
      entry = { map, markers: [] };
      mapsByContainer.set(canvasEl, entry);
    }
    return entry;
  }

  function clearMarkers(entry) {
    for (const marker of entry.markers) {
      marker.map = null;
    }
    entry.markers = [];
  }

  // A small white rating badge on the map — real rating when we have one (enriched via
  // scripts/enrich_places.py), otherwise the spot's position in the list as a fallback.
  function buildMarkerBadge(spot, number) {
    const badge = document.createElement("button");
    badge.type = "button";
    badge.className = "map-marker-badge";
    badge.textContent = spot.rating != null ? spot.rating.toFixed(1) : String(number);
    badge.setAttribute("aria-label", `${spot.title}: view details`);
    return badge;
  }

  function buildListItem(spot, number) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "map-list-item";

    if (spot.photo_url) {
      const thumb = document.createElement("img");
      thumb.className = "map-list-item-thumb";
      thumb.src = spot.photo_url;
      thumb.alt = "";
      item.appendChild(thumb);
    } else {
      const badge = document.createElement("span");
      badge.className = "map-list-item-badge";
      badge.textContent = spot.rating != null ? spot.rating.toFixed(1) : String(number);
      item.appendChild(badge);
    }

    const body = document.createElement("span");
    body.className = "map-list-item-body";

    const title = document.createElement("span");
    title.className = "map-list-item-title";
    title.textContent = spot.title;
    body.appendChild(title);

    const meta = document.createElement("span");
    meta.className = "map-list-item-meta";
    const category = spot.city ? `${spot.category} · ${spot.city}` : spot.category;
    meta.textContent = spot.rating != null ? `${spot.rating.toFixed(1)} ★ · ${category}` : category;
    body.appendChild(meta);

    if (spot.note) {
      const note = document.createElement("span");
      note.className = "map-list-item-note";
      note.textContent = spot.note;
      body.appendChild(note);
    }

    item.appendChild(body);
    return item;
  }

  function renderSpotList(listEl, spots) {
    listEl.innerHTML = "";
    spots.forEach((spot, i) => {
      listEl.appendChild(buildListItem(spot, i + 1));
    });
  }

  function directionsUrl(spot) {
    return `https://www.google.com/maps/dir/?api=1&destination=${spot.lat},${spot.lng}`;
  }

  // Fills in the detail view for one spot — photo, rating/reviews/category, a
  // Directions link (the only actionable jump-away action), phone/website/notes as
  // plain read-only text, and a pager to move through the rest of the list.
  function renderDetail(detailEl, spot, index, total) {
    const photoWrap = detailEl.querySelector(".chat-map-detail-photo");
    photoWrap.innerHTML = "";
    if (spot.photo_url) {
      const img = document.createElement("img");
      img.src = spot.photo_url;
      img.alt = spot.title;
      photoWrap.appendChild(img);
      photoWrap.hidden = false;
    } else {
      photoWrap.hidden = true;
    }

    detailEl.querySelector(".chat-map-detail-title").textContent = spot.title;

    const metaParts = [];
    if (spot.rating != null) {
      metaParts.push(`${spot.rating.toFixed(1)} ★`);
    }
    metaParts.push(spot.city ? `${spot.category} · ${spot.city}` : spot.category);
    detailEl.querySelector(".chat-map-detail-meta").textContent = metaParts.join(" · ");

    detailEl.querySelector(".chat-map-detail-directions").href = directionsUrl(spot);

    const phoneEl = detailEl.querySelector(".chat-map-detail-phone");
    phoneEl.textContent = spot.phone || "";
    phoneEl.hidden = !spot.phone;

    const websiteEl = detailEl.querySelector(".chat-map-detail-website");
    websiteEl.textContent = spot.website || "";
    websiteEl.hidden = !spot.website;

    const notesLabel = detailEl.querySelector(".chat-map-detail-notes-label");
    const notesEl = detailEl.querySelector(".chat-map-detail-notes");
    notesEl.textContent = spot.note || "";
    notesLabel.hidden = !spot.note;
    notesEl.hidden = !spot.note;

    detailEl.querySelector(".chat-map-detail-pager-label").textContent = `${index + 1} of ${total}`;
    detailEl.querySelector(".chat-map-detail-prev").disabled = index === 0;
    detailEl.querySelector(".chat-map-detail-next").disabled = index === total - 1;
  }

  function frameMap(entry, libs, markers) {
    if (markers.length === 0) {
      return;
    }
    if (markers.length === 1) {
      entry.map.setCenter({ lat: markers[0].lat, lng: markers[0].lng });
      entry.map.setZoom(15);
      return;
    }
    const bounds = new libs.LatLngBounds();
    for (const spot of markers) {
      bounds.extend({ lat: spot.lat, lng: spot.lng });
    }
    entry.map.fitBounds(bounds, 40);
  }

  // Shared by every chat reply that includes a map — one renderer, many containers.
  // `container` holds a map canvas and a floating card overlaid on it, which switches
  // between a scrollable list view and a single-spot detail view. Selecting a spot (by
  // marker or list row) opens its detail view in place; Directions is the only action
  // that leaves the page.
  async function renderMapPayload(container, payload) {
    const canvasEl = container.querySelector(".chat-map-canvas");
    const cardEl = container.querySelector(".chat-map-list");
    const listItemsEl = container.querySelector(".chat-map-list-items");
    const listHeader = container.querySelector(".chat-map-list-header");
    const listTitle = container.querySelector(".chat-map-list-title");
    const detailEl = container.querySelector(".chat-map-detail-view");

    const spots = payload.markers;
    const count = spots.length;
    listTitle.textContent = `${count} saved spot${count === 1 ? "" : "s"}`;
    listHeader.addEventListener("click", () => {
      cardEl.classList.toggle("chat-map-list-collapsed");
    });

    const libs = await loadLibraries();
    const entry = getOrCreateMapEntry(canvasEl, libs);
    clearMarkers(entry);
    renderSpotList(listItemsEl, spots);

    const listItems = Array.from(listItemsEl.children);
    const badges = [];

    // `detailEl.dataset.index` tracks the current selection so prev/next always reads
    // the latest value instead of closing over a stale one.
    function showDetail(i) {
      detailEl.dataset.index = String(i);
      renderDetail(detailEl, spots[i], i, count);
      cardEl.classList.add("chat-map-list-showing-detail");
      cardEl.classList.remove("chat-map-list-collapsed");
      badges.forEach((b, j) => b.classList.toggle("map-marker-badge-active", j === i));
      listItems.forEach((el, j) => el.classList.toggle("map-list-item-active", j === i));
      const spot = spots[i];
      entry.map.panTo({ lat: spot.lat, lng: spot.lng });
      if (entry.map.getZoom() < 17) {
        entry.map.setZoom(17);
      }
    }

    function showList() {
      cardEl.classList.remove("chat-map-list-showing-detail");
    }

    detailEl.querySelector(".chat-map-detail-close").addEventListener("click", showList);
    detailEl.querySelector(".chat-map-detail-prev").addEventListener("click", () => {
      const current = Number(detailEl.dataset.index);
      if (current > 0) showDetail(current - 1);
    });
    detailEl.querySelector(".chat-map-detail-next").addEventListener("click", () => {
      const current = Number(detailEl.dataset.index);
      if (current < count - 1) showDetail(current + 1);
    });

    spots.forEach((spot, i) => {
      const position = { lat: spot.lat, lng: spot.lng };
      const badge = buildMarkerBadge(spot, i + 1);
      const marker = new libs.AdvancedMarkerElement({
        map: entry.map,
        position,
        title: spot.title,
        content: badge,
      });
      badge.addEventListener("click", () => showDetail(i));
      listItems[i].addEventListener("click", () => showDetail(i));

      badges.push(badge);
      entry.markers.push(marker);
    });

    frameMap(entry, libs, spots);

    // Exposed so a spot name clicked inline in the chat text (see
    // linkifySpotMentions) can jump straight to this spot's detail view.
    container.selectSpot = showDetail;
  }

  function buildMapContainerElement() {
    const mapContainer = document.createElement("div");
    mapContainer.className = "chat-map";
    mapContainer.innerHTML =
      '<div class="chat-map-canvas"></div>' +
      '<div class="chat-map-list">' +
      '<button type="button" class="chat-map-list-header">' +
      '<span class="chat-map-list-title"></span>' +
      '<span class="chat-map-list-toggle-icon" aria-hidden="true">▾</span>' +
      "</button>" +
      '<div class="chat-map-list-items"></div>' +
      '<div class="chat-map-detail-view">' +
      '<button type="button" class="chat-map-detail-close" aria-label="Back to list">✕</button>' +
      '<div class="chat-map-detail-photo"></div>' +
      '<div class="chat-map-detail-body">' +
      '<div class="chat-map-detail-title"></div>' +
      '<div class="chat-map-detail-meta"></div>' +
      '<a class="chat-map-detail-directions" target="_blank" rel="noopener noreferrer">Directions</a>' +
      '<div class="chat-map-detail-phone"></div>' +
      '<div class="chat-map-detail-website"></div>' +
      '<div class="chat-map-detail-notes-label">My notes</div>' +
      '<div class="chat-map-detail-notes"></div>' +
      "</div>" +
      '<div class="chat-map-detail-pager">' +
      '<button type="button" class="chat-map-detail-prev" aria-label="Previous spot">←</button>' +
      '<span class="chat-map-detail-pager-label"></span>' +
      '<button type="button" class="chat-map-detail-next" aria-label="Next spot">→</button>' +
      "</div>" +
      "</div>" +
      "</div>";
    return mapContainer;
  }

  // Finds the first plain-text occurrence of a spot's title inside `root` (an assistant
  // chat bubble) and replaces it with a clickable button, leaving the rest of the text
  // untouched. Skips text already inside a previous spot link (or a <code> span) so
  // overlapping titles (e.g. "Bar" inside "Wine Bar") can't be double-linked.
  function linkifyFirstSpotMention(root, title, spotIndex) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const parent = node.parentElement;
      const skip = parent && parent.closest(".spot-name-link, code");
      const idx = skip ? -1 : node.nodeValue.toLowerCase().indexOf(title.toLowerCase());
      if (idx !== -1) {
        const text = node.nodeValue;
        const before = text.slice(0, idx);
        const match = text.slice(idx, idx + title.length);
        const after = text.slice(idx + title.length);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "spot-name-link";
        button.dataset.spotIndex = String(spotIndex);
        button.textContent = match;

        const afterNode = document.createTextNode(after);
        node.nodeValue = before;
        parent.insertBefore(button, node.nextSibling);
        parent.insertBefore(afterNode, button.nextSibling);
        return;
      }
      node = walker.nextNode();
    }
  }

  // Makes the first mention of each spot's name inside an assistant reply clickable,
  // so clicking it opens that spot's detail view on the map below — the same result as
  // clicking it in the map's own list. Longest titles first, so a shorter spot's name
  // that happens to be a substring of a longer one (already linked) is left alone.
  function linkifySpotMentions(bubbleEl, spots) {
    spots
      .map((spot, i) => ({ title: spot.title, i }))
      .sort((a, b) => b.title.length - a.title.length)
      .forEach(({ title, i }) => linkifyFirstSpotMention(bubbleEl, title, i));
  }

  // --- Multi-conversation state (in-memory only — nothing here ever touches a Web
  // Storage API, a cookie, or the server, so a refresh or tab close wipes it all). ---

  const state = { conversations: [], activeId: null };
  let emptyStateTemplate = null;

  function activeConversation() {
    return state.conversations.find((c) => c.id === state.activeId);
  }

  function conversationTitle(convo) {
    return convo.title || "New chat";
  }

  function bindSuggestionChips(root) {
    root.querySelectorAll(".suggestion-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        sendChatMessage(chip.dataset.question).catch((error) => console.error(error));
      });
    });
  }

  // The real #chat-form is a single, permanent element (its listeners are bound once,
  // in DOMContentLoaded) — on the start screen it's moved up between the greeting and
  // the suggestions to match the reference layout, then moved back to the bottom of
  // .chat-page as soon as there's an actual conversation. appendChild re-parents an
  // existing node rather than cloning it, so this never loses its event listeners.
  function showEmptyState() {
    document.querySelector(".chat-page").classList.add("chat-page-empty");
    if (!emptyStateTemplate) {
      return;
    }
    const clone = emptyStateTemplate.cloneNode(true);
    document.getElementById("chat-log").appendChild(clone);
    bindSuggestionChips(clone);
    const formSlot = clone.querySelector(".chat-form-slot");
    if (formSlot) {
      formSlot.appendChild(document.getElementById("chat-form"));
    }
  }

  function hideEmptyState() {
    const chatPage = document.querySelector(".chat-page");
    chatPage.classList.remove("chat-page-empty");
    chatPage.appendChild(document.getElementById("chat-form"));
    const emptyState = document.getElementById("empty-state");
    if (emptyState) {
      emptyState.remove();
    }
  }

  // Replays a conversation's saved transcript through the same render functions used
  // live, so reopening a past conversation shows the exact same bubbles and maps.
  async function renderTranscript(transcript) {
    const log = document.getElementById("chat-log");
    let lastAssistantBubble = null;
    for (const entry of transcript) {
      if (entry.type === "user") {
        appendChatBubble("user", entry.text);
        lastAssistantBubble = null;
      } else if (entry.type === "assistant") {
        lastAssistantBubble = appendChatBubble("assistant", entry.text);
      } else if (entry.type === "map") {
        if (lastAssistantBubble) {
          linkifySpotMentions(lastAssistantBubble, entry.payload.markers);
        }
        const mapContainer = buildMapContainerElement();
        log.appendChild(mapContainer);
        await renderMapPayload(mapContainer, entry.payload);
      }
    }
    log.scrollTop = log.scrollHeight;
  }

  function renderSidebar() {
    const list = document.getElementById("conversation-list");
    list.innerHTML = "";
    state.conversations.forEach((convo) => {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "conversation-item";
      if (convo.id === state.activeId) {
        button.classList.add("conversation-item-active");
        button.setAttribute("aria-current", "true");
      }
      button.textContent = conversationTitle(convo);
      button.addEventListener("click", () => switchConversation(convo.id));
      li.appendChild(button);
      list.appendChild(li);
    });
  }

  function closeMobileSidebar() {
    document.querySelector(".app-layout").classList.remove("sidebar-open");
    const toggle = document.getElementById("sidebar-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", "false");
    }
  }

  function switchConversation(id) {
    if (id === state.activeId) {
      closeMobileSidebar();
      return;
    }
    state.activeId = id;
    const log = document.getElementById("chat-log");
    // When the current conversation is empty, showEmptyState() has parked the single
    // #chat-form element inside #chat-log. Move it back out before wiping the log, or
    // log.innerHTML = "" destroys it and the switch (and every later send) breaks.
    document.querySelector(".chat-page").appendChild(document.getElementById("chat-form"));
    log.innerHTML = "";
    const convo = activeConversation();
    if (convo.transcript.length === 0) {
      showEmptyState();
    } else {
      hideEmptyState();
      renderTranscript(convo.transcript).catch((error) => console.error(error));
    }
    renderSidebar();
    closeMobileSidebar();
  }

  function createConversation() {
    const convo = {
      id: crypto.randomUUID(),
      title: null,
      history: [],
      transcript: [],
    };
    state.conversations.unshift(convo);
    switchConversation(convo.id);
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Escapes first, then only ever wraps already-escaped text in a fixed set of
  // safe tags — the model's prose can never inject raw HTML this way.
  function renderInlineMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
    return html;
  }

  function renderMarkdown(text) {
    const htmlParts = [];
    let listItems = [];
    let paragraphLines = [];

    function flushList() {
      if (listItems.length > 0) {
        const items = listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("");
        htmlParts.push(`<ul>${items}</ul>`);
        listItems = [];
      }
    }

    function flushParagraph() {
      if (paragraphLines.length > 0) {
        htmlParts.push(`<p>${paragraphLines.map(renderInlineMarkdown).join("<br>")}</p>`);
        paragraphLines = [];
      }
    }

    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      const listMatch = trimmed.match(/^[-*]\s+(.*)$/);
      if (listMatch) {
        flushParagraph();
        listItems.push(listMatch[1]);
      } else if (trimmed === "") {
        flushList();
        flushParagraph();
      } else {
        flushList();
        paragraphLines.push(line);
      }
    }
    flushList();
    flushParagraph();

    return htmlParts.join("");
  }

  function appendChatBubble(role, text, extraClass) {
    const log = document.getElementById("chat-log");
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble chat-bubble-${role}`;
    if (extraClass) {
      bubble.classList.add(extraClass);
    }
    if (role === "assistant") {
      bubble.innerHTML = renderMarkdown(text);
    } else {
      bubble.textContent = text;
    }
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  // Streams a reply via SSE into the given conversation. Resolves once the "done"
  // event closes the stream (after any map has finished rendering); rejects on a
  // connection error. `convo` is captured by the caller at send-time, so a reply still
  // lands in the right conversation's data even if the user switches away mid-stream.
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
          const log = document.getElementById("chat-log");
          log.scrollTop = log.scrollHeight;
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
            const log = document.getElementById("chat-log");
            const mapContainer = buildMapContainerElement();
            log.appendChild(mapContainer);
            log.scrollTop = log.scrollHeight;
            renderMapPayload(mapContainer, mapPayload).then(resolve).catch(reject);
          } else {
            resolve();
          }
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        reject(new Error("Stream connection failed"));
      };
    });
  }

  function setSidebarDisabled(disabled) {
    document.querySelectorAll(".conversation-item, #new-chat-button").forEach((el) => {
      el.disabled = disabled;
    });
  }

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

  document.addEventListener("DOMContentLoaded", () => {
    const chatForm = document.getElementById("chat-form");
    if (chatForm) {
      chatForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const input = document.getElementById("chat-input");
        const message = input.value.trim();
        if (!message) {
          return;
        }
        input.value = "";
        sendChatMessage(message).catch((error) => console.error(error));
      });
    }

    // The server renders the first empty state (greeting + suggestion chips) directly
    // into the page; clone it once so later "New chat" clicks can reuse the exact same
    // content without a round-trip, since it never changes within a session.
    const existingEmptyState = document.getElementById("empty-state");
    if (existingEmptyState) {
      emptyStateTemplate = existingEmptyState.cloneNode(true);
      bindSuggestionChips(existingEmptyState);
      const formSlot = existingEmptyState.querySelector(".chat-form-slot");
      if (formSlot) {
        formSlot.appendChild(document.getElementById("chat-form"));
      }
    }

    // Delegated so it keeps working across conversation switches (which replace
    // #chat-log's children) without re-binding per bubble.
    const chatLog = document.getElementById("chat-log");
    if (chatLog) {
      chatLog.addEventListener("click", (event) => {
        const link = event.target.closest(".spot-name-link");
        if (!link) return;
        const bubble = link.closest(".chat-bubble-assistant");
        if (!bubble) return;
        let sibling = bubble.nextElementSibling;
        while (sibling && !sibling.classList.contains("chat-map") && !sibling.classList.contains("chat-bubble")) {
          sibling = sibling.nextElementSibling;
        }
        if (sibling && sibling.classList.contains("chat-map") && sibling.selectSpot) {
          sibling.scrollIntoView({ behavior: "smooth", block: "nearest" });
          sibling.selectSpot(Number(link.dataset.spotIndex));
        }
      });
    }

    const firstConversation = { id: crypto.randomUUID(), title: null, history: [], transcript: [] };
    state.conversations.push(firstConversation);
    state.activeId = firstConversation.id;
    renderSidebar();

    const newChatButton = document.getElementById("new-chat-button");
    if (newChatButton) {
      newChatButton.addEventListener("click", () => createConversation());
    }

    const sidebarToggle = document.getElementById("sidebar-toggle");
    const appLayout = document.querySelector(".app-layout");
    if (sidebarToggle) {
      sidebarToggle.addEventListener("click", () => {
        const isOpen = appLayout.classList.toggle("sidebar-open");
        sidebarToggle.setAttribute("aria-expanded", String(isOpen));
      });
    }
    if (appLayout) {
      // On mobile the open sidebar is covered by a dimmed backdrop (::after);
      // a click there lands on .app-layout itself since the sidebar and chat
      // page don't extend under it, so this closes the sidebar without any
      // extra backdrop element.
      appLayout.addEventListener("click", (event) => {
        if (event.target === appLayout) closeMobileSidebar();
      });
    }
  });
})();
