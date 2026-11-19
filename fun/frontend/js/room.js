const platforms = Object.freeze({
  hackerrank: {
    label: "HackerRank",
    url: "https://www.hackerrank.com/",
  },
  geeksforgeeks: {
    label: "GeeksforGeeks",
    url: "https://www.geeksforgeeks.org/",
  },
  leetcode: {
    label: "LeetCode",
    url: "https://leetcode.com/",
  },
});

const platformButtons = document.querySelectorAll("[data-platform]");
const platformFrame = document.querySelector("#platform-frame");
const openPlatform = document.querySelector("#open-platform");
const selectedPlatformName = document.querySelector("#selected-platform-name");
const embedEmpty = document.querySelector("#embed-empty");
const embedLoading = document.querySelector("#embed-loading");
const embedNotice = document.querySelector("#embed-notice");
const participantCards = document.querySelector("#participant-cards");
const chatMembers = document.querySelector("#chat-members");
const chatMessages = document.querySelector("#chat-messages");
const chatForm = document.querySelector(".chat-composer");
const chatInput = document.querySelector("#chat-input");
const chatSendButton = document.querySelector("#chat-send");
const chatStatus = document.querySelector("#chat-status");
const chatError = document.querySelector("#chat-error");
const chatPhasePill = document.querySelector("#chat-phase-pill");
const participantCount = document.querySelector("#participant-count");
const roomUser = document.querySelector("#room-user");
const serverStatus = document.querySelector("#server-status");
const logoutButton = document.querySelector("#room-logout");

let frameLoadTimer;
let selectedPlatformKey = null;
let roomSocket = null;
let reconnectTimer = null;
let stableConnectionTimer = null;
let reconnectAttempts = 0;
let stopReconnect = false;
const presenceElements = new Map();
const renderedEventIds = new Set();

function showEmbedNotice(message, isError = false) {
  embedNotice.textContent = message;
  embedNotice.classList.toggle("embed-error", isError);
}

function setServerStatus(message, state = "connected") {
  serverStatus.classList.toggle("connection-error", state === "error");
  serverStatus.classList.toggle("connection-retrying", state === "retrying");
  const dot = document.createElement("span");
  dot.className = "connection-dot";
  if (state === "retrying") {
    dot.classList.add("connection-dot-pending");
  } else if (state === "error") {
    dot.classList.add("connection-dot-offline");
  }
  dot.setAttribute("aria-hidden", "true");
  serverStatus.replaceChildren(dot, document.createTextNode(message));
}

function setChatError(message = "") {
  chatError.textContent = message;
  chatError.hidden = !message;
}

function setChatEnabled(enabled) {
  chatInput.disabled = !enabled;
  chatSendButton.disabled = !enabled;
  chatPhasePill.textContent = enabled ? "Live" : "Connecting";
}

function selectPlatform(platformKey) {
  const platform = platforms[platformKey];
  if (!platform) {
    return;
  }

  selectedPlatformKey = platformKey;
  window.clearTimeout(frameLoadTimer);
  for (const button of platformButtons) {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.platform === platformKey),
    );
  }

  selectedPlatformName.textContent = platform.label;
  openPlatform.href = platform.url;
  openPlatform.hidden = false;
  embedEmpty.hidden = true;
  embedLoading.hidden = false;
  platformFrame.hidden = false;
  showEmbedNotice(
    "Loading the site in an embedded view. If it stays blank or shows a browser error, the site may disallow framing; use “Open in new tab”.",
  );
  platformFrame.src = platform.url;

  frameLoadTimer = window.setTimeout(() => {
    embedLoading.hidden = true;
    showEmbedNotice(
      "The embedded view is taking longer than expected. This site may block framing; try opening it in a new tab.",
      true,
    );
  }, 12000);
}

for (const button of platformButtons) {
  button.addEventListener("click", () => selectPlatform(button.dataset.platform));
}

platformFrame.addEventListener("load", () => {
  if (!selectedPlatformKey) {
    return;
  }
  window.clearTimeout(frameLoadTimer);
  embedLoading.hidden = true;
  showEmbedNotice(
    "The browser finished loading the frame, but cross-origin security prevents this app from verifying the page contents. If it appears blank or blocked, open it in a new tab.",
  );
});

platformFrame.addEventListener("error", () => {
  if (!selectedPlatformKey) {
    return;
  }
  window.clearTimeout(frameLoadTimer);
  embedLoading.hidden = true;
  showEmbedNotice(
    "The browser could not load this embedded page. Open the coding platform in a new tab instead.",
    true,
  );
});

function setPresence(username, online) {
  const elements = presenceElements.get(username);
  if (!elements) {
    return;
  }

  elements.indicator.classList.toggle("presence-online", online);
  elements.indicator.setAttribute(
    "aria-label",
    `${username} is ${online ? "online" : "offline"}`,
  );
  elements.status.textContent = online ? "Online" : "Offline";
  elements.status.classList.toggle("presence-online-text", online);
  elements.chatDot.classList.toggle("presence-online", online);
}

function updatePresence(users) {
  for (const user of users) {
    if (typeof user.username === "string") {
      setPresence(user.username, user.online === true);
    }
  }
}

function renderParticipants(users) {
  participantCards.replaceChildren();
  chatMembers.replaceChildren();
  presenceElements.clear();
  participantCount.textContent = `${users.length} members`;

  for (const username of users) {
    const card = document.createElement("article");
    card.className = "participant-card";
    card.dataset.username = username;

    const heading = document.createElement("div");
    heading.className = "participant-card-head";

    const presence = document.createElement("span");
    presence.className = "presence-indicator";
    presence.setAttribute("aria-label", `${username} is offline`);

    const name = document.createElement("p");
    name.className = "participant-name";
    name.textContent = username;
    name.title = username;
    heading.append(presence, name);

    const presenceStatus = document.createElement("span");
    presenceStatus.className = "participant-status";
    presenceStatus.textContent = "Offline";

    const screen = document.createElement("div");
    screen.className = "screen-stage";

    const video = document.createElement("video");
    video.className = "screen-video";
    video.autoplay = true;
    video.playsInline = true;
    video.muted = true;
    video.hidden = true;
    video.dataset.screenVideo = username;

    const placeholder = document.createElement("div");
    placeholder.className = "screen-placeholder";
    placeholder.dataset.screenPlaceholder = username;
    placeholder.textContent = "Not sharing a coding tab";
    screen.append(video, placeholder);

    const fullscreen = document.createElement("button");
    fullscreen.className = "screen-fullscreen-button";
    fullscreen.type = "button";
    fullscreen.textContent = "Fullscreen";
    fullscreen.disabled = true;
    fullscreen.dataset.screenFullscreen = username;

    const sharing = document.createElement("span");
    sharing.className = "sharing-caption";
    sharing.dataset.screenStatus = username;
    sharing.textContent = "Not sharing";
    card.append(heading, presenceStatus, screen, fullscreen, sharing);
    participantCards.append(card);

    const chatMember = document.createElement("span");
    chatMember.className = "chat-member";
    const avatar = document.createElement("span");
    avatar.className = "chat-member-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = username.slice(0, 1);
    const statusDot = document.createElement("span");
    statusDot.className = "member-status-dot";
    statusDot.setAttribute("aria-hidden", "true");
    const chatName = document.createElement("span");
    chatName.textContent = username;
    chatMember.append(avatar, statusDot, chatName);
    chatMembers.append(chatMember);

    presenceElements.set(username, {
      indicator: presence,
      status: presenceStatus,
      chatDot: statusDot,
    });
  }
}

function renderRoomEvent(event) {
  if (typeof event.id !== "string" || renderedEventIds.has(event.id)) {
    return;
  }

  let entry;
  if (event.type === "chat_message") {
    entry = document.createElement("li");
    entry.className = "chat-entry";

    const heading = document.createElement("div");
    heading.className = "chat-entry-heading";

    const username = document.createElement("span");
    username.className = "chat-entry-username";
    username.textContent =
      typeof event.username === "string" ? event.username : "Unknown member";

    const time = document.createElement("time");
    time.className = "chat-entry-time";
    time.dateTime = typeof event.timestamp === "string" ? event.timestamp : "";
    const parsedTime = new Date(event.timestamp);
    time.textContent = Number.isNaN(parsedTime.getTime())
      ? ""
      : parsedTime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    heading.append(username, time);

    const text = document.createElement("p");
    text.className = "chat-entry-text";
    text.textContent = typeof event.message === "string" ? event.message : "";
    entry.append(heading, text);
  } else if (
    event.type === "member_joined" ||
    event.type === "member_left"
  ) {
    const username =
      typeof event.username === "string" ? event.username : "A member";
    setPresence(username, event.type === "member_joined");
    entry = document.createElement("li");
    entry.className = "chat-system-message";
    entry.textContent =
      event.type === "member_joined"
        ? `${username} joined the room`
        : `${username} left the room`;
  } else {
    return;
  }

  const emptyState = chatMessages.querySelector(".chat-empty");
  if (emptyState) {
    emptyState.remove();
  }
  entry.dataset.eventId = event.id;
  renderedEventIds.add(event.id);
  chatMessages.append(entry);

  while (chatMessages.children.length > 100) {
    const oldestEntry = chatMessages.firstElementChild;
    if (oldestEntry.dataset.eventId) {
      renderedEventIds.delete(oldestEntry.dataset.eventId);
    }
    oldestEntry.remove();
  }

  chatMessages.classList.add("has-messages");
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addEmptyChatState() {
  const empty = document.createElement("li");
  empty.id = "chat-empty";
  empty.className = "chat-empty";
  const icon = document.createElement("span");
  icon.className = "chat-empty-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "↗";
  const title = document.createElement("p");
  title.textContent = "Conversation starts here";
  const description = document.createElement("span");
  description.textContent = "No recent messages in this server session.";
  empty.append(icon, title, description);
  chatMessages.append(empty);
}

function restoreChatHistory(history) {
  chatMessages.replaceChildren();
  chatMessages.classList.remove("has-messages");
  renderedEventIds.clear();
  for (const event of history) {
    renderRoomEvent(event);
  }
  if (chatMessages.children.length === 0) {
    addEmptyChatState();
  }
}

function handleRoomEvent(event) {
  if (!event || typeof event !== "object") {
    return;
  }

  if (event.type === "room_state") {
    if (event.room_id !== "CODING-ROOM-001") {
      setChatError("The server returned an unexpected room.");
      return;
    }
    if (Array.isArray(event.users)) {
      updatePresence(event.users);
    }
    if (Array.isArray(event.history)) {
      restoreChatHistory(event.history);
    }
    chatStatus.textContent =
      "Connected. Recent messages are temporary and stored in server memory.";
    return;
  }

  if (
    event.type === "chat_message" ||
    event.type === "member_joined" ||
    event.type === "member_left"
  ) {
    setChatError();
    renderRoomEvent(event);
    return;
  }

  if (event.type === "error") {
    setChatError(
      typeof event.message === "string"
        ? event.message
        : "The server rejected that message.",
    );
  }
}

function scheduleReconnect() {
  if (stopReconnect || reconnectTimer !== null) {
    return;
  }

  const baseDelay = Math.min(500 * 2 ** reconnectAttempts, 15000);
  const delay = Math.round(baseDelay * (0.8 + Math.random() * 0.4));
  reconnectAttempts += 1;
  setServerStatus("Reconnecting…", "retrying");
  chatStatus.textContent = `Connection lost. Retrying in ${Math.max(
    1,
    Math.round(delay / 1000),
  )}s…`;
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    connectRoomSocket();
  }, delay);
}

function connectRoomSocket() {
  if (stopReconnect || !roomUser.textContent) {
    return;
  }
  if (
    roomSocket &&
    (roomSocket.readyState === WebSocket.CONNECTING ||
      roomSocket.readyState === WebSocket.OPEN)
  ) {
    return;
  }

  const socketUrl = new URL("/ws/room", window.location.href);
  socketUrl.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  setServerStatus(
    reconnectAttempts === 0 ? "Connecting to room" : "Reconnecting…",
    "retrying",
  );
  setChatEnabled(false);
  setChatStatus("Connecting to room chat…");

  const socket = new WebSocket(socketUrl);
  roomSocket = socket;

  socket.addEventListener("open", () => {
    if (roomSocket !== socket) {
      return;
    }
    setServerStatus("Connected");
    setChatEnabled(true);
    setChatStatus("Connected. Messages are temporary and held in server memory.");
    setChatError();
    window.clearTimeout(stableConnectionTimer);
    stableConnectionTimer = window.setTimeout(() => {
      if (roomSocket === socket && socket.readyState === WebSocket.OPEN) {
        reconnectAttempts = 0;
      }
    }, 10000);
  });

  socket.addEventListener("message", (messageEvent) => {
    try {
      handleRoomEvent(JSON.parse(messageEvent.data));
    } catch {
      setChatError("Received an unreadable message from the server.");
    }
  });

  socket.addEventListener("error", () => {
    setChatStatus("Connection interrupted. Trying to reconnect…");
  });

  socket.addEventListener("close", (closeEvent) => {
    window.clearTimeout(stableConnectionTimer);
    if (roomSocket === socket) {
      roomSocket = null;
    }
    setChatEnabled(false);

    if (stopReconnect) {
      return;
    }
    if ([4401, 4403].includes(closeEvent.code)) {
      stopReconnect = true;
      setServerStatus("Session expired", "error");
      chatStatus.textContent = "Please sign in again to rejoin the room.";
      window.location.assign("/");
      return;
    }
    if (closeEvent.code === 4429) {
      stopReconnect = true;
      setServerStatus("Room is full", "error");
      chatStatus.textContent = "The maximum number of room members is online.";
      return;
    }
    scheduleReconnect();
  });
}

function setChatStatus(message) {
  chatStatus.textContent = message;
}

function sendChatMessage() {
  if (!roomSocket || roomSocket.readyState !== WebSocket.OPEN) {
    setChatError("Not connected. Your message was not sent.");
    return;
  }

  const message = chatInput.value;
  if (!message.trim()) {
    setChatError("Enter a message before sending.");
    return;
  }
  if (message.length > 2000) {
    setChatError("Messages must be 2,000 characters or fewer.");
    return;
  }

  try {
    roomSocket.send(JSON.stringify({ type: "chat_message", message }));
    chatInput.value = "";
    setChatError();
  } catch {
    setChatError("Could not send the message. Please try again.");
  }
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendChatMessage();
});

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

async function loadRoom() {
  const response = await fetch("/api/session");
  if (response.status === 401) {
    window.location.replace("/");
    return;
  }
  if (!response.ok) {
    throw new Error("Could not validate the current session.");
  }

  const session = await response.json();
  roomUser.textContent = session.username;
  renderParticipants(session.users);
  connectRoomSocket();
}

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  stopReconnect = true;
  window.clearTimeout(reconnectTimer);
  window.clearTimeout(stableConnectionTimer);
  reconnectTimer = null;
  if (roomSocket) {
    const socket = roomSocket;
    roomSocket = null;
    socket.close(1000, "User logged out.");
  }
  try {
    const response = await fetch("/api/auth/logout", { method: "POST" });
    if (!response.ok) {
      throw new Error("Sign-out failed.");
    }
    window.location.assign("/");
  } catch {
    stopReconnect = false;
    logoutButton.disabled = false;
    window.alert("Could not sign out. Please try again.");
    connectRoomSocket();
  }
});

loadRoom().catch(() => {
  setServerStatus("Connection unavailable", "error");
  participantCards.textContent = "Could not load room members. Please refresh.";
  setChatEnabled(false);
  setChatStatus("Room connection is unavailable.");
});
