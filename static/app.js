const $conversation = document.querySelector("#conversation");
const $messages = document.querySelector("#messages");
const $empty = document.querySelector("#empty");
const $form = document.querySelector("#composer");
const $input = document.querySelector("#input");
const $send = document.querySelector("#send");
const $clear = document.querySelector("#clear");

const history = [];
let currentAbort = null;

function autoResize() {
  $input.style.height = "auto";
  $input.style.height = Math.min($input.scrollHeight, 200) + "px";
}

function scrollDown() {
  $conversation.scrollTop = $conversation.scrollHeight;
}

function hideEmpty() {
  $empty.classList.add("hidden");
}

function showEmpty() {
  $empty.classList.remove("hidden");
}

function addBubble(role, initialText = "") {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  if (initialText) div.textContent = initialText;
  $messages.appendChild(div);
  scrollDown();
  return div;
}

function renderAssistant(bubble, text) {
  bubble.innerHTML = DOMPurify.sanitize(marked.parse(text));
  scrollDown();
}

function setTyping(bubble) {
  bubble.innerHTML =
    '<span class="typing"><span></span><span></span><span></span></span>';
}

function parseEvent(raw) {
  let event = "message";
  const dataLines = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

function splitEventDelim(buf) {
  let end = buf.indexOf("\n\n");
  let delimLen = 2;
  const crlf = buf.indexOf("\r\n\r\n");
  if (crlf !== -1 && (end === -1 || crlf < end)) {
    end = crlf;
    delimLen = 4;
  }
  return { end, delimLen };
}

async function streamChat(messages, signal, { onDelta, onEnd, onError }) {
  let res;
  try {
    res = await fetch("/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages }),
      signal,
    });
  } catch (e) {
    if (e.name !== "AbortError") onError("Connection failed.");
    return;
  }

  if (!res.ok) {
    let detail = `Server returned ${res.status}.`;
    try {
      const j = await res.json();
      if (j.detail) detail = j.detail;
    } catch {
      // non-JSON error body — keep generic detail
    }
    onError(detail);
    return;
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      while (true) {
        const { end, delimLen } = splitEventDelim(buffer);
        if (end === -1) break;
        const raw = buffer.slice(0, end).replace(/\r\n/g, "\n");
        buffer = buffer.slice(end + delimLen);
        const parsed = parseEvent(raw);
        if (!parsed) continue;
        if (parsed.event === "delta") {
          try {
            onDelta(JSON.parse(parsed.data).text);
          } catch {
            // malformed delta event — skip
          }
        } else if (parsed.event === "end") {
          onEnd();
        } else if (parsed.event === "error") {
          try {
            onError(JSON.parse(parsed.data).message);
          } catch {
            onError("Stream error.");
          }
        }
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") onError("Stream interrupted.");
  }
}

async function sendMessage(text) {
  if (!text || currentAbort) return;

  hideEmpty();
  history.push({ role: "user", content: text });
  addBubble("user", text);

  $input.value = "";
  autoResize();

  const bubble = addBubble("assistant");
  setTyping(bubble);
  let accum = "";
  let firstDelta = true;

  currentAbort = new AbortController();
  $send.disabled = true;

  await streamChat(history, currentAbort.signal, {
    onDelta: (chunk) => {
      if (firstDelta) {
        bubble.innerHTML = "";
        firstDelta = false;
      }
      accum += chunk;
      renderAssistant(bubble, accum);
    },
    onEnd: () => {
      if (!accum) {
        bubble.textContent = "(no response)";
      }
      history.push({ role: "assistant", content: accum });
      currentAbort = null;
      $send.disabled = false;
      $input.focus();
    },
    onError: (msg) => {
      bubble.className = "bubble error";
      bubble.textContent = msg;
      currentAbort = null;
      $send.disabled = false;
    },
  });
}

$form.addEventListener("submit", (e) => {
  e.preventDefault();
  sendMessage($input.value.trim());
});

$input.addEventListener("input", autoResize);
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendMessage($input.value.trim());
  }
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    sendMessage(chip.dataset.prompt);
  });
});

$clear.addEventListener("click", () => {
  if (currentAbort) currentAbort.abort();
  history.length = 0;
  $messages.innerHTML = "";
  showEmpty();
  $input.focus();
});

window.addEventListener("pagehide", () => currentAbort?.abort());

autoResize();
$input.focus();
