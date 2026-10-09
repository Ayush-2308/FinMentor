const suggestions = [
  "How much did I spend on groceries in January?",
  "What does my health insurance cover?",
  "What's my total investment gain?",
  "What's excluded from my insurance policy?",
  "What was my salary credit this month?",
];

const screens = {
  welcome: document.querySelector("#screen-welcome"),
  auth: document.querySelector("#screen-auth"),
  verify: document.querySelector("#screen-verify"),
  chat: document.querySelector("#screen-chat"),
};

const sessionKey = "finmentor.session";
let mode = "signup";
let channel = "email";
let pending = null;
let documents = [];
let conversations = [];
let conversationId = null;
let pollTimer = null;
let recognition = null;
let listening = false;

const SpeechApi = window.SpeechRecognition || window.webkitSpeechRecognition;

document.querySelector("#enter").addEventListener("click", () => show("auth"));
document.querySelector("#welcome-orb").addEventListener("click", () => show("auth"));
document.querySelector("#auth-back").addEventListener("click", () => show("welcome"));
document.querySelector("#verify-back").addEventListener("click", () => show("auth"));

document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});
document.querySelectorAll("[data-channel]").forEach((button) => {
  button.addEventListener("click", () => setChannel(button.dataset.channel));
});

document.querySelector("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = document.querySelector("#password").value;
  const payload = contactPayload();
  if (!payload) return;
  payload.password = password;
  await startAuth(mode === "signup" ? "/auth/signup" : "/auth/login", payload);
});

document.querySelector("#code-instead").addEventListener("click", async () => {
  const payload = contactPayload();
  if (!payload) return;
  payload.create_user = mode === "signup";
  await startAuth("/auth/otp", payload);
});

document.querySelector("#verify-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = otpValue();
  if (token.length < 6) {
    setText("#verify-error", "Enter the 6-digit code.");
    return;
  }
  await startAuth("/auth/verify", {
    channel: pending.channel,
    email: pending.email,
    phone: pending.phone,
    token,
    verification_type: pending.verification_type,
  });
});

document.querySelector("#resend").addEventListener("click", async () => {
  if (!pending) return;
  await startAuth("/auth/otp", {
    channel: pending.channel,
    email: pending.email,
    phone: pending.phone,
    create_user: pending.verification_type === "signup",
  });
});

wireOtp();

document.querySelector("#suggestions").append(
  ...suggestions.map((question) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = question;
    button.addEventListener("click", () => ask(question, false));
    return button;
  }),
);

document.querySelector("#composer").addEventListener("submit", (event) => {
  event.preventDefault();
  const field = document.querySelector("#query");
  const text = field.value.trim();
  if (!text) return;
  field.value = "";
  field.style.height = "auto";
  ask(text, false);
});

document.querySelector("#mic").addEventListener("click", () => {
  if (listening) stopVoice();
  else startVoice();
});
document.querySelector("#chat-orb").addEventListener("click", () => startVoice());
document.querySelector("#voice-orb").addEventListener("click", stopVoice);
document.querySelector("#stop-voice").addEventListener("click", stopVoice);

document.querySelector("#open-files").addEventListener("click", () => {
  document.querySelector("#drawer").hidden = false;
  refreshDocuments().catch((error) => setUpload(error.message, true));
});
document.querySelector("#close-files").addEventListener("click", closeDrawer);
document.querySelector("#drawer-scrim").addEventListener("click", closeDrawer);
document.querySelector("#open-history").addEventListener("click", () => {
  document.querySelector("#history-drawer").hidden = false;
  refreshConversations().catch(() => {});
});
document.querySelector("#close-history").addEventListener("click", closeHistory);
document.querySelector("#history-scrim").addEventListener("click", closeHistory);
document.querySelector("#sign-out").addEventListener("click", signOut);
document.querySelector("#new-chat").addEventListener("click", () => {
  startNewChat();
  closeHistory();
});
document.querySelector("#doc-type").addEventListener("change", () => {
  document.querySelector("#custom-type-field").hidden = document.querySelector("#doc-type").value !== "__custom__";
});

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.querySelector("#file-input").files[0];
  if (!file) {
    setUpload("Choose a file first.", true);
    return;
  }
  const body = new FormData();
  body.append("file", file);
  const hint = selectedDocType();
  if (hint === false) return;
  if (hint) body.append("doc_type_hint", hint);
  const button = document.querySelector("#upload-button");
  button.disabled = true;
  setUpload("Uploading…");
  try {
    const response = await api("/upload", { method: "POST", body });
    if (!response.ok) throw new Error(await readError(response));
    document.querySelector("#file-input").value = "";
    setUpload("Indexing in the background.", false);
    await refreshDocuments();
  } catch (error) {
    setUpload(error.message, true);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#query").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 112)}px`;
});

document.querySelector("#query").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    document.querySelector("#composer").requestSubmit();
  }
});

boot();

function show(name) {
  Object.entries(screens).forEach(([key, node]) => {
    const on = key === name;
    node.classList.toggle("is-on", on);
    node.hidden = !on;
  });
}

function setMode(next) {
  mode = next;
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.classList.toggle("is-on", button.dataset.mode === next);
  });
  if (next === "login") {
    const email = document.querySelector("#email");
    const password = document.querySelector("#password");
    if (email && !email.value) email.value = "demo@finmentor.app";
    if (password && !password.value) password.value = "Demo@12345";
  }
  document.querySelector("#auth-title").textContent = next === "signup" ? "Create an account" : "Welcome back";
  document.querySelector("#auth-copy").textContent = next === "signup"
    ? "Email or phone. We send a code before the agent opens."
    : "Log in with your password, or ask for a fresh code.";
  document.querySelector("#auth-submit").textContent = next === "signup" ? "Create account" : "Log in";
  document.querySelector("#password").autocomplete = next === "signup" ? "new-password" : "current-password";
}

function setChannel(next) {
  channel = next;
  document.querySelectorAll("[data-channel]").forEach((button) => {
    button.classList.toggle("is-on", button.dataset.channel === next);
  });
  document.querySelector("#email-field").hidden = next !== "email";
  document.querySelector("#phone-field").hidden = next !== "phone";
}

function contactPayload() {
  setText("#auth-error", "");
  if (channel === "email") {
    const email = document.querySelector("#email").value.trim();
    if (!email.includes("@")) {
      setText("#auth-error", "Enter a valid email address.");
      return null;
    }
    return { channel, email };
  }
  const phone = document.querySelector("#phone").value.trim().replace(/\s/g, "");
  if (!phone.startsWith("+")) {
    setText("#auth-error", "Include the country code, like +91.");
    return null;
  }
  return { channel, phone };
}

async function startAuth(path, payload) {
  const button = document.querySelector("#auth-submit");
  button.disabled = true;
  setText("#auth-error", "");
  setText("#verify-error", "");
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not continue.");
    if (data.status === "verification_required") {
      pending = {
        channel: data.channel,
        email: payload.email || null,
        phone: payload.phone || null,
        verification_type: data.verification_type,
      };
      document.querySelector("#verify-destination").textContent = data.destination;
      clearOtp();
      show("verify");
      return;
    }
    saveSession(data);
    openChat();
  } catch (error) {
    const slot = screens.verify.classList.contains("is-on") ? "#verify-error" : "#auth-error";
    setText(slot, error.message);
  } finally {
    button.disabled = false;
  }
}

function saveSession(data) {
  localStorage.setItem(sessionKey, JSON.stringify({
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    user_id: data.user_id,
    destination: data.destination,
  }));
}

function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(sessionKey) || "null");
  } catch (_error) {
    return null;
  }
}

async function boot() {
  const session = loadSession();
  if (!session?.access_token) {
    show("welcome");
    return;
  }
  const response = await api("/documents");
  if (response.status === 401) {
    localStorage.removeItem(sessionKey);
    show("welcome");
    return;
  }
  openChat();
}

function openChat() {
  show("chat");
  loadDocTypes().catch(() => {});
  refreshDocuments().catch(() => {});
  refreshConversations().catch(() => {});
}

async function signOut() {
  const session = loadSession();
  if (session?.access_token) {
    await fetch("/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${session.access_token}` } });
  }
  localStorage.removeItem(sessionKey);
  documents = [];
  conversations = [];
  conversationId = null;
  document.querySelector("#transcript").replaceChildren();
  screens.chat.classList.remove("has-thread");
  window.speechSynthesis?.cancel();
  stopVoice();
  show("welcome");
}

async function api(path, options = {}, retry = true) {
  const session = loadSession();
  const headers = new Headers(options.headers || {});
  if (session?.access_token) headers.set("Authorization", `Bearer ${session.access_token}`);
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && retry && session?.refresh_token) {
    const refreshed = await fetch("/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: session.refresh_token }),
    });
    if (!refreshed.ok) return response;
    saveSession(await refreshed.json());
    return api(path, options, false);
  }
  return response;
}

async function ask(text, fromVoice) {
  screens.chat.classList.add("has-thread");
  append("user", text);
  const pendingBubble = append("agent", "Looking through your files…");
  try {
    const response = await api("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: text, conversation_id: conversationId }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const data = await response.json();
    if (data.conversation_id) conversationId = data.conversation_id;
    fillAnswer(pendingBubble, data);
    refreshConversations().catch(() => {});
    if (fromVoice) speak(data.answer);
  } catch (error) {
    pendingBubble.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.textContent = error.message;
    pendingBubble.append(paragraph);
  }
}

function append(role, text) {
  const bubble = document.createElement("article");
  bubble.className = `bubble ${role}`;
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  bubble.append(paragraph);
  document.querySelector("#transcript").append(bubble);
  bubble.scrollIntoView({ block: "end", behavior: "smooth" });
  return bubble;
}

function fillAnswer(bubble, data) {
  bubble.replaceChildren();
  if (data.grounded === true || data.grounded === false) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = data.grounded ? "From your files" : "Not in your files";
    bubble.append(tag);
  }
  const paragraph = document.createElement("p");
  paragraph.textContent = data.answer;
  bubble.append(paragraph);
  (data.sources || []).forEach((source) => {
    const note = document.createElement("div");
    note.className = "cite";
    const known = documents.find((doc) => doc.id === source.document_id);
    note.textContent = `${known ? known.filename : "Document"} · ${Number(source.similarity_score).toFixed(2)}\n${source.chunk_text}`;
    bubble.append(note);
  });
}

function startVoice() {
  if (!SpeechApi) {
    screens.chat.classList.add("has-thread");
    append("agent", "This browser can't use the microphone. Try Chrome, then tap the mic.");
    return;
  }
  if (listening) return;
  recognition = new SpeechApi();
  recognition.lang = "en-IN";
  recognition.interimResults = true;
  recognition.onresult = (event) => {
    let finalText = "";
    let interim = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const piece = event.results[index][0].transcript;
      if (event.results[index].isFinal) finalText += piece;
      else interim += piece;
    }
    document.querySelector("#live-speech").textContent = finalText || interim;
    if (finalText.trim()) {
      stopVoice();
      ask(finalText.trim(), true);
    }
  };
  recognition.onerror = () => stopVoice();
  recognition.onend = () => {
    listening = false;
    document.querySelector("#mic").classList.remove("is-hot");
    document.querySelector("#voice").hidden = true;
  };
  listening = true;
  document.querySelector("#mic").classList.add("is-hot");
  document.querySelector("#voice").hidden = false;
  document.querySelector("#live-speech").textContent = "";
  document.querySelector("#voice-label").textContent = "Listening";
  recognition.start();
}

function stopVoice() {
  recognition?.stop();
  listening = false;
  document.querySelector("#mic").classList.remove("is-hot");
  document.querySelector("#voice").hidden = true;
}

function speak(text) {
  if (!window.speechSynthesis || !text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text.slice(0, 500));
  utterance.lang = "en-IN";
  window.speechSynthesis.speak(utterance);
}

async function refreshDocuments() {
  const response = await api("/documents");
  if (!response.ok) throw new Error(await readError(response));
  documents = await response.json();
  renderDocuments();
  const waiting = documents.some((doc) => doc.status === "processing");
  if (waiting && !pollTimer) {
    pollTimer = setInterval(() => refreshDocuments().catch(() => {}), 2000);
  }
  if (!waiting && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function renderDocuments() {
  const list = document.querySelector("#document-list");
  list.replaceChildren();
  if (!documents.length) {
    const item = document.createElement("li");
    item.textContent = "No files yet.";
    list.append(item);
    return;
  }
  documents.forEach((doc) => {
    const item = document.createElement("li");
    const name = document.createElement("span");
    const kind = doc.doc_type_hint ? ` · ${doc.doc_type_hint.replaceAll("_", " ")}` : "";
    name.textContent = `${doc.filename}${kind}`;
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = doc.status;
    item.append(name, badge);
    list.append(item);
  });
}

function closeDrawer() {
  document.querySelector("#drawer").hidden = true;
}

function closeHistory() {
  document.querySelector("#history-drawer").hidden = true;
}

function startNewChat() {
  conversationId = null;
  document.querySelector("#transcript").replaceChildren();
  screens.chat.classList.remove("has-thread");
  window.speechSynthesis?.cancel();
  refreshConversations().catch(() => {});
}

function selectedDocType() {
  const preset = document.querySelector("#doc-type").value;
  if (!preset) return "";
  if (preset !== "__custom__") return preset;
  const custom = document.querySelector("#custom-type").value.trim();
  if (custom.length < 2) {
    setUpload("Type a custom name, at least 2 characters.", true);
    return false;
  }
  return custom;
}

async function loadDocTypes() {
  const select = document.querySelector("#doc-type");
  if (select.dataset.loaded === "1") return;
  const response = await fetch("/doc-types");
  if (!response.ok) return;
  const types = await response.json();
  const custom = select.querySelector('option[value="__custom__"]');
  types.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    select.insertBefore(option, custom);
  });
  select.dataset.loaded = "1";
}

async function refreshConversations() {
  const response = await api("/conversations");
  if (!response.ok) return;
  conversations = await response.json();
  renderConversations();
}

function renderConversations() {
  const list = document.querySelector("#chat-list");
  list.replaceChildren();
  if (!conversations.length) {
    const item = document.createElement("li");
    item.textContent = "No chats yet.";
    list.append(item);
    return;
  }
  conversations.forEach((chat) => {
    const item = document.createElement("li");
    if (chat.id === conversationId) item.classList.add("is-on");
    const meta = document.createElement("div");
    meta.className = "meta";
    const title = document.createElement("span");
    title.textContent = chat.title;
    const preview = document.createElement("small");
    preview.textContent = chat.preview || "Empty";
    meta.append(title, preview);
    meta.addEventListener("click", () => openConversation(chat.id));
    const wipe = document.createElement("button");
    wipe.type = "button";
    wipe.className = "wipe";
    wipe.setAttribute("aria-label", "Delete chat");
    wipe.textContent = "✕";
    wipe.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteConversation(chat.id);
    });
    item.append(meta, wipe);
    list.append(item);
  });
}

async function openConversation(id) {
  const response = await api(`/conversations/${id}`);
  if (!response.ok) return;
  const data = await response.json();
  conversationId = data.id;
  const feed = document.querySelector("#transcript");
  feed.replaceChildren();
  (data.messages || []).forEach((message) => {
    if (message.role === "user") {
      append("user", message.content);
    } else {
      const bubble = append("agent", message.content);
      fillAnswer(bubble, {
        answer: message.content,
        grounded: message.grounded,
        sources: message.sources || [],
      });
    }
  });
  screens.chat.classList.toggle("has-thread", Boolean((data.messages || []).length));
  closeHistory();
}

async function deleteConversation(id) {
  const response = await api(`/conversations/${id}`, { method: "DELETE" });
  if (!response.ok) return;
  if (conversationId === id) startNewChat();
  await refreshConversations();
}

function setUpload(message, isError = false) {
  const node = document.querySelector("#upload-status");
  node.textContent = message;
  node.classList.toggle("ok", !isError && Boolean(message));
}

function wireOtp() {
  const inputs = [...document.querySelectorAll("#otp input")];
  inputs.forEach((input, index) => {
    input.addEventListener("input", () => {
      const digits = input.value.replace(/\D/g, "");
      if (digits.length > 1) {
        spreadOtp(digits);
        return;
      }
      input.value = digits;
      if (digits && inputs[index + 1]) inputs[index + 1].focus();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Backspace" && !input.value && inputs[index - 1]) inputs[index - 1].focus();
    });
    input.addEventListener("paste", (event) => {
      event.preventDefault();
      spreadOtp(event.clipboardData.getData("text"));
    });
  });
}

function spreadOtp(text) {
  const digits = text.replace(/\D/g, "").slice(0, 6);
  const inputs = [...document.querySelectorAll("#otp input")];
  inputs.forEach((input, index) => {
    input.value = digits[index] || "";
  });
  inputs[Math.min(digits.length, 5)]?.focus();
}

function otpValue() {
  return [...document.querySelectorAll("#otp input")].map((input) => input.value).join("");
}

function clearOtp() {
  document.querySelectorAll("#otp input").forEach((input) => {
    input.value = "";
  });
}

function setText(selector, message) {
  document.querySelector(selector).textContent = message;
}

async function readError(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
  } catch (_error) {
    // Not JSON.
  }
  return `Request failed (${response.status}).`;
}
