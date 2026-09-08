(function () {
  let librariesPromise = null;
  const mapsByContainer = new Map();

  function loadLibraries() {
    if (!librariesPromise) {
      librariesPromise = Promise.all([
        google.maps.importLibrary("core"),
        google.maps.importLibrary("maps"),
        google.maps.importLibrary("marker"),
      ]).then(([coreLib, mapsLib, markerLib]) => ({
        Map: mapsLib.Map,
        InfoWindow: mapsLib.InfoWindow,
        AdvancedMarkerElement: markerLib.AdvancedMarkerElement,
        LatLngBounds: coreLib.LatLngBounds,
      }));
    }
    return librariesPromise;
  }

  function getOrCreateMapEntry(container, libs) {
    let entry = mapsByContainer.get(container);
    if (!entry) {
      const map = new libs.Map(container, {
        mapId: window.APP_CONFIG.mapId,
        gestureHandling: "cooperative",
        center: { lat: 0, lng: 0 },
        zoom: 2,
      });
      entry = { map, infoWindow: new libs.InfoWindow(), markers: [] };
      mapsByContainer.set(container, entry);
    }
    return entry;
  }

  function clearMarkers(entry) {
    for (const marker of entry.markers) {
      marker.map = null;
    }
    entry.markers = [];
  }

  function buildInfoWindowContent(spot) {
    const wrapper = document.createElement("div");

    const title = document.createElement("strong");
    title.textContent = spot.title;
    wrapper.appendChild(title);

    if (spot.city) {
      const city = document.createElement("p");
      city.className = "info-window-city";
      city.textContent = spot.city;
      wrapper.appendChild(city);
    }

    if (spot.note) {
      const note = document.createElement("p");
      note.textContent = spot.note;
      wrapper.appendChild(note);
    }

    if (spot.maps_url) {
      const link = document.createElement("a");
      link.href = spot.maps_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open in Google Maps";
      wrapper.appendChild(link);
    }

    return wrapper;
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
  async function renderMapPayload(container, payload) {
    const libs = await loadLibraries();
    const entry = getOrCreateMapEntry(container, libs);
    clearMarkers(entry);

    for (const spot of payload.markers) {
      const position = { lat: spot.lat, lng: spot.lng };
      const marker = new libs.AdvancedMarkerElement({
        map: entry.map,
        position,
        title: spot.title,
      });
      marker.addEventListener("gmp-click", () => {
        entry.infoWindow.setContent(buildInfoWindowContent(spot));
        entry.infoWindow.open({ map: entry.map, anchor: marker });
      });
      entry.markers.push(marker);
    }

    frameMap(entry, libs, payload.markers);
  }

  const chatState = { history: [] };

  function hideEmptyState() {
    const emptyState = document.getElementById("empty-state");
    if (emptyState) {
      emptyState.remove();
    }
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

  // Streams a reply via SSE. Resolves once the "done" event closes the stream
  // (after any map has finished rendering); rejects on a connection error.
  function streamChatMessage(message, pendingBubble) {
    return new Promise((resolve, reject) => {
      const params = new URLSearchParams({ message, history: JSON.stringify(chatState.history) });
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
          ensureAssistantBubble();

          chatState.history.push({ role: "user", content: message });
          chatState.history.push({ role: "assistant", content: assistantText });

          if (mapPayload && mapPayload.markers.length > 0) {
            const log = document.getElementById("chat-log");
            const mapContainer = document.createElement("div");
            mapContainer.className = "chat-map";
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

  async function sendChatMessage(message) {
    const form = document.getElementById("chat-form");
    const input = document.getElementById("chat-input");
    const submitButton = form.querySelector("button");

    hideEmptyState();
    appendChatBubble("user", message);
    const pending = appendChatBubble("assistant", "Thinking…", "chat-bubble-pending");
    submitButton.disabled = true;
    input.disabled = true;

    try {
      await streamChatMessage(message, pending);
    } catch (error) {
      pending.remove();
      appendChatBubble("assistant", "Sorry, something went wrong. Please try again.");
      console.error(error);
    } finally {
      submitButton.disabled = false;
      input.disabled = false;
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

    document.querySelectorAll(".suggestion-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        sendChatMessage(chip.dataset.question).catch((error) => console.error(error));
      });
    });
  });
})();
