(() => {
const shareButton = document.querySelector("#share-screen");
const stopShareButton = document.querySelector("#stop-screen-share");
const shareStatus = document.querySelector("#screen-share-status");
const shareError = document.querySelector("#screen-share-error");
const roomLogoutButton = document.querySelector("#room-logout");

const peerConnections = new Map();
const sharingUsers = new Set();
let currentUsername = "";
let configuredUsers = [];
let localStream = null;
let signalingSocket = null;
let reconnectTimer = null;
let reconnectAttempts = 0;
let stopSignaling = false;
let iceServers = [];

function setShareStatus(message) {
  shareStatus.textContent = message;
}

function setShareError(message = "") {
  shareError.textContent = message;
  shareError.hidden = !message;
}

function getParticipantCard(username) {
  return [...document.querySelectorAll(".participant-card")].find(
    (card) => card.dataset.username === username,
  );
}

function getScreenVideo(username) {
  return getParticipantCard(username)?.querySelector(
    `[data-screen-video="${CSS.escape(username)}"]`,
  );
}

function getFullscreenButton(username) {
  return getParticipantCard(username)?.querySelector(
    `[data-screen-fullscreen="${CSS.escape(username)}"]`,
  );
}

function updateSharingDisplay(username, isSharing) {
  const card = getParticipantCard(username);
  if (!card) {
    return;
  }
  const caption = card.querySelector(`[data-screen-status="${CSS.escape(username)}"]`);
  const placeholder = card.querySelector(
    `[data-screen-placeholder="${CSS.escape(username)}"]`,
  );
  card.classList.toggle("is-sharing", isSharing);
  if (caption) {
    caption.textContent = isSharing
      ? username === currentUsername
        ? "Sharing this browser tab"
        : "Sharing a browser tab"
      : "Not sharing";
  }
  if (placeholder && !isSharing) {
    placeholder.textContent = "Not sharing a browser tab";
    placeholder.hidden = false;
  } else if (placeholder && isSharing) {
    placeholder.textContent = "Connecting to shared browser tab…";
  }
}

function updateSharingUsers(users) {
  sharingUsers.clear();
  for (const username of users) {
    if (typeof username === "string" && configuredUsers.includes(username)) {
      sharingUsers.add(username);
    }
  }
  for (const username of configuredUsers) {
    const isSharing = sharingUsers.has(username);
    updateSharingDisplay(username, isSharing);
    if (!isSharing && username !== currentUsername) {
      clearRemoteVideo(username);
    }
  }
}

function clearRemoteVideo(username) {
  const video = getScreenVideo(username);
  if (!video || username === currentUsername) {
    return;
  }
  video.pause();
  video.srcObject = null;
  video.hidden = true;
  const fullscreen = getFullscreenButton(username);
  if (fullscreen) {
    fullscreen.disabled = true;
  }
  const placeholder = getParticipantCard(username)?.querySelector(
    `[data-screen-placeholder="${CSS.escape(username)}"]`,
  );
  if (placeholder) {
    placeholder.hidden = false;
    placeholder.textContent = sharingUsers.has(username)
      ? "Connecting to shared browser tab…"
      : "Not sharing a browser tab";
  }
}

function setRemoteVideo(username, stream) {
  const video = getScreenVideo(username);
  const placeholder = getParticipantCard(username)?.querySelector(
    `[data-screen-placeholder="${CSS.escape(username)}"]`,
  );
  if (!video || !placeholder) {
    return;
  }
  video.srcObject = stream;
  video.hidden = false;
  const fullscreen = getFullscreenButton(username);
  if (fullscreen) {
    fullscreen.disabled = false;
  }
  placeholder.hidden = true;
  video.play().catch(() => {
    setShareError(
      `The shared tab from ${username} is ready, but the browser could not start video playback.`,
    );
  });
}

function sendSocketEvent(event) {
  if (!signalingSocket || signalingSocket.readyState !== WebSocket.OPEN) {
    return false;
  }
  try {
    signalingSocket.send(JSON.stringify(event));
    return true;
  } catch {
    return false;
  }
}

function sendSignal(target, signal) {
  if (!sendSocketEvent({ type: "webrtc_signal", target, signal })) {
    setShareError("Signaling disconnected. WebRTC updates could not be sent.");
    return false;
  }
  return true;
}

function isOfferer(username) {
  return configuredUsers.indexOf(currentUsername) < configuredUsers.indexOf(username);
}

function closePeer(username) {
  const peer = peerConnections.get(username);
  if (!peer) {
    clearRemoteVideo(username);
    return;
  }
  peerConnections.delete(username);
  peer.pc.ontrack = null;
  peer.pc.onicecandidate = null;
  peer.pc.onconnectionstatechange = null;
  peer.pc.oniceconnectionstatechange = null;
  peer.pc.close();
  clearRemoteVideo(username);
}

function closeAllPeers() {
  for (const username of peerConnections.keys()) {
    closePeer(username);
  }
}

function attachLocalTrack(peer) {
  const track = localStream?.getVideoTracks()[0] || null;
  return peer.sender.replaceTrack(track);
}

function ensurePeer(username) {
  if (
    !configuredUsers.includes(username) ||
    username === currentUsername ||
    !iceServers.length
  ) {
    return null;
  }

  const existing = peerConnections.get(username);
  if (existing && existing.pc.connectionState !== "closed") {
    return existing;
  }
  if (existing) {
    peerConnections.delete(username);
  }

  const pc = new RTCPeerConnection({ iceServers });
  const transceiver = pc.addTransceiver("video", { direction: "sendrecv" });
  const peer = {
    pc,
    sender: transceiver.sender,
    remoteStream: new MediaStream(),
    pendingCandidates: [],
    makingOffer: false,
    restartCount: 0,
    restartTimer: null,
  };
  peerConnections.set(username, peer);

  pc.onicecandidate = (event) => {
    const candidate = event.candidate
      ? event.candidate.toJSON()
      : null;
    sendSignal(username, { type: "ice_candidate", candidate });
  };

  pc.ontrack = (event) => {
    if (event.streams[0]) {
      peer.remoteStream = event.streams[0];
    } else if (!peer.remoteStream.getTracks().includes(event.track)) {
      peer.remoteStream.addTrack(event.track);
    }
    const stream = peer.remoteStream;
    if (sharingUsers.has(username)) {
      setRemoteVideo(username, stream);
    }
    event.track.addEventListener("ended", () => {
      if (peerConnections.get(username) === peer) {
        clearRemoteVideo(username);
      }
    });
  };

  pc.onconnectionstatechange = () => {
    if (peerConnections.get(username) !== peer) {
      return;
    }
    if (pc.connectionState === "connected") {
      peer.restartCount = 0;
      setShareError();
      return;
    }
    if (pc.connectionState === "failed") {
      setShareStatus(
        `Connection to ${username} failed. STUN may not reach this network; configure TURN.`,
      );
      requestIceRestart(username, peer);
    } else if (pc.connectionState === "disconnected") {
      setShareStatus(`Connection to ${username} was interrupted; attempting recovery…`);
      window.clearTimeout(peer.restartTimer);
      peer.restartTimer = window.setTimeout(() => {
        if (
          peerConnections.get(username) === peer &&
          pc.connectionState === "disconnected"
        ) {
          requestIceRestart(username, peer);
        }
      }, 5000);
    }
  };

  pc.oniceconnectionstatechange = () => {
    if (pc.iceConnectionState === "failed") {
      requestIceRestart(username, peer);
    }
  };

  attachLocalTrack(peer).catch(() => {
    setShareError(`Could not prepare the screen-sharing connection to ${username}.`);
  });

  if (isOfferer(username)) {
    negotiate(username, peer).catch(() => {
      setShareError(`Could not start the WebRTC connection to ${username}.`);
    });
  }
  return peer;
}

async function negotiate(username, peer, iceRestart = false) {
  if (
    peerConnections.get(username) !== peer ||
    peer.makingOffer ||
    peer.pc.signalingState !== "stable"
  ) {
    return;
  }
  peer.makingOffer = true;
  try {
    if (iceRestart) {
      peer.pc.restartIce();
    }
    const offer = await peer.pc.createOffer(
      iceRestart ? { iceRestart: true } : undefined,
    );
    await peer.pc.setLocalDescription(offer);
    sendSignal(username, {
      type: peer.pc.localDescription.type,
      sdp: peer.pc.localDescription.sdp,
    });
  } finally {
    peer.makingOffer = false;
  }
}

function requestIceRestart(username, peer) {
  if (peerConnections.get(username) !== peer || peer.restartCount >= 3) {
    return;
  }
  peer.restartCount += 1;
  if (isOfferer(username)) {
    negotiate(username, peer, true).catch(() => {
      setShareError(`Could not restart the connection to ${username}.`);
    });
  } else if (!sendSocketEvent({ type: "peer_restart", target: username })) {
    setShareError(`Could not request an ICE restart from ${username}.`);
  }
}

async function addPendingCandidates(peer) {
  const pending = peer.pendingCandidates.splice(0);
  for (const candidate of pending) {
    await peer.pc.addIceCandidate(candidate);
  }
}

async function handleSignalEvent(event) {
  const username = event.from;
  if (
    typeof username !== "string" ||
    username === currentUsername ||
    !configuredUsers.includes(username) ||
    !event.signal ||
    typeof event.signal !== "object"
  ) {
    return;
  }

  const peer = ensurePeer(username);
  if (!peer) {
    return;
  }
  const signal = event.signal;

  if (signal.type === "ice_candidate") {
    if (signal.candidate === null) {
      return;
    }
    const candidate = new RTCIceCandidate(signal.candidate);
    if (peer.pc.remoteDescription) {
      await peer.pc.addIceCandidate(candidate);
    } else {
      peer.pendingCandidates.push(candidate);
    }
    return;
  }

  if (signal.type === "offer") {
    const collision =
      peer.makingOffer || peer.pc.signalingState !== "stable";
    if (collision && isOfferer(username)) {
      return;
    }
    if (collision) {
      await peer.pc.setLocalDescription({ type: "rollback" });
    }
    await peer.pc.setRemoteDescription({
      type: "offer",
      sdp: signal.sdp,
    });
    await addPendingCandidates(peer);
    await attachLocalTrack(peer);
    const answer = await peer.pc.createAnswer();
    await peer.pc.setLocalDescription(answer);
    sendSignal(username, {
      type: peer.pc.localDescription.type,
      sdp: peer.pc.localDescription.sdp,
    });
  } else if (signal.type === "answer") {
    if (peer.pc.signalingState !== "have-local-offer") {
      return;
    }
    await peer.pc.setRemoteDescription({
      type: "answer",
      sdp: signal.sdp,
    });
    await addPendingCandidates(peer);
  }
}

function updateParticipantOnlineState(participants) {
  const online = new Set(
    participants
      .filter((participant) => participant.online === true)
      .map((participant) => participant.username),
  );
  for (const username of online) {
    if (username !== currentUsername) {
      ensurePeer(username);
    }
  }
  for (const username of configuredUsers) {
    if (username !== currentUsername && !online.has(username)) {
      closePeer(username);
    }
  }
}

function handleSignalingEvent(event) {
  if (!event || typeof event !== "object") {
    return;
  }
  if (event.type === "signaling_state") {
    updateParticipantOnlineState(
      Array.isArray(event.participants) ? event.participants : [],
    );
    updateSharingUsers(
      Array.isArray(event.sharing_users) ? event.sharing_users : [],
    );
    setShareStatus("Connected to the room's screen-sharing signal service.");
  } else if (event.type === "peer_joined" || event.type === "peer_reconnected") {
    const username = event.username;
    if (typeof username === "string" && username !== currentUsername) {
      closePeer(username);
      ensurePeer(username);
    }
  } else if (event.type === "peer_left") {
    if (typeof event.username === "string") {
      sharingUsers.delete(event.username);
      updateSharingDisplay(event.username, false);
      closePeer(event.username);
    }
  } else if (event.type === "screen_share_started") {
    if (
      typeof event.username === "string" &&
      configuredUsers.includes(event.username)
    ) {
      sharingUsers.add(event.username);
      updateSharingDisplay(event.username, true);
      const peer = peerConnections.get(event.username);
      if (peer?.remoteStream.getVideoTracks().length) {
        setRemoteVideo(event.username, peer.remoteStream);
      }
    }
  } else if (event.type === "screen_share_stopped") {
    if (
      typeof event.username === "string" &&
      configuredUsers.includes(event.username)
    ) {
      sharingUsers.delete(event.username);
      updateSharingDisplay(event.username, false);
      clearRemoteVideo(event.username);
    }
  } else if (event.type === "webrtc_signal") {
    handleSignalEvent(event).catch(() => {
      setShareError("Could not process a WebRTC signaling message.");
    });
  } else if (event.type === "peer_restart") {
    const username = event.username;
    const peer = peerConnections.get(username);
    if (peer && isOfferer(username)) {
      requestIceRestart(username, peer);
    }
  } else if (event.type === "error") {
    setShareError(
      typeof event.message === "string"
        ? event.message
        : "The signaling service rejected an event.",
    );
  }
}

function scheduleSignalingReconnect() {
  if (stopSignaling || reconnectTimer !== null) {
    return;
  }
  const delay = Math.min(1000 * 2 ** reconnectAttempts, 15000);
  reconnectAttempts += 1;
  setShareStatus(`Signaling disconnected. Reconnecting in ${Math.ceil(delay / 1000)}s…`);
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    connectSignaling();
  }, delay);
}

function connectSignaling() {
  if (stopSignaling || !currentUsername) {
    return;
  }
  if (
    signalingSocket &&
    [WebSocket.CONNECTING, WebSocket.OPEN].includes(signalingSocket.readyState)
  ) {
    return;
  }

  const url = new URL("/ws/signaling", window.location.href);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  setShareStatus("Connecting to screen-sharing service…");
  const socket = new WebSocket(url);
  signalingSocket = socket;

  socket.addEventListener("open", () => {
    if (signalingSocket === socket) {
      setShareStatus("Connected to the room's screen-sharing signal service.");
      shareButton.disabled = false;
      setShareError();
    }
  });

  socket.addEventListener("message", (messageEvent) => {
    try {
      handleSignalingEvent(JSON.parse(messageEvent.data));
    } catch {
      setShareError("Received an unreadable signaling message.");
    }
  });

  socket.addEventListener("error", () => {
    setShareStatus("Screen-sharing signal connection interrupted.");
  });

  socket.addEventListener("close", (event) => {
    if (signalingSocket === socket) {
      signalingSocket = null;
    }
    shareButton.disabled = true;
    closeAllPeers();
    stopLocalSharing(false);
    if (stopSignaling) {
      return;
    }
    if ([4401, 4403].includes(event.code)) {
      stopSignaling = true;
      window.location.assign("/");
      return;
    }
    if (event.code === 4410) {
      stopSignaling = true;
      setShareStatus("Screen-sharing connection replaced by another room session.");
      setShareError("Only one active screen-sharing connection per account is supported.");
      return;
    }
    scheduleSignalingReconnect();
  });
}

async function startSharing() {
  setShareError();
  if (!window.isSecureContext || !navigator.mediaDevices?.getDisplayMedia) {
    setShareError(
      "Browser tab capture is unavailable here. Use HTTPS or localhost with a supported browser.",
    );
    return;
  }

  shareButton.disabled = true;
  setShareStatus("Choose a browser tab in the browser picker…");
  let stream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        displaySurface: "browser",
        frameRate: { ideal: 15, max: 20 },
        width: { ideal: 1280, max: 1280 },
        height: { ideal: 720, max: 720 },
      },
      audio: false,
      selfBrowserSurface: "exclude",
      surfaceSwitching: "exclude",
      monitorTypeSurfaces: "exclude",
    });
  } catch (error) {
    shareButton.disabled = !signalingSocket || signalingSocket.readyState !== WebSocket.OPEN;
    if (error?.name === "NotAllowedError" || error?.name === "AbortError") {
      setShareError("Tab sharing was cancelled or permission was denied.");
    } else {
      setShareError("The browser could not start tab capture. Try a supported browser over HTTPS or localhost.");
    }
    setShareStatus("Not sharing.");
    return;
  }

  const track = stream.getVideoTracks()[0];
  const displaySurface = track?.getSettings().displaySurface;
  if (!track || displaySurface !== "browser") {
    stream.getTracks().forEach((mediaTrack) => mediaTrack.stop());
    shareButton.disabled = !signalingSocket || signalingSocket.readyState !== WebSocket.OPEN;
    setShareStatus("Not sharing.");
    setShareError(
      displaySurface
        ? "The selected source is not reported as a browser tab. It was stopped; no window or monitor fallback is allowed."
        : "This browser does not report whether capture is a browser tab. Sharing was stopped because tab-only capture cannot be verified.",
    );
    return;
  }

  localStream = stream;
  const localVideo = getScreenVideo(currentUsername);
  const localPlaceholder = getParticipantCard(currentUsername)?.querySelector(
    `[data-screen-placeholder="${CSS.escape(currentUsername)}"]`,
  );
  if (localVideo) {
    localVideo.srcObject = stream;
    localVideo.hidden = false;
    const fullscreen = getFullscreenButton(currentUsername);
    if (fullscreen) {
      fullscreen.disabled = false;
    }
    localVideo.play().catch(() => {
      setShareError("Your tab is sharing, but the local preview could not start.");
    });
  }
  if (localPlaceholder) {
    localPlaceholder.hidden = true;
  }
  stream.getTracks().forEach((mediaTrack) => {
    mediaTrack.addEventListener("ended", () => stopLocalSharing(true), { once: true });
  });

  try {
    await Promise.all([...peerConnections.values()].map(attachLocalTrack));
  } catch {
    await stopLocalSharing(false);
    setShareError("Could not attach the selected tab to every participant connection.");
    shareButton.disabled = false;
    return;
  }

  stopShareButton.disabled = false;
  shareButton.disabled = true;
  setShareStatus("Your browser tab is being shared with the room.");
  if (!sendSocketEvent({ type: "screen_share_started" })) {
    await stopLocalSharing(false);
    setShareError("Signaling disconnected before the share could be announced.");
  }
}

async function stopLocalSharing(notifyServer) {
  const stream = localStream;
  localStream = null;
  setShareError();
  stopShareButton.disabled = true;
  const localVideo = currentUsername ? getScreenVideo(currentUsername) : null;
  if (localVideo) {
    localVideo.pause();
    localVideo.srcObject = null;
    localVideo.hidden = true;
  }
  const localFullscreen = currentUsername
    ? getFullscreenButton(currentUsername)
    : null;
  if (localFullscreen) {
    localFullscreen.disabled = true;
  }
  if (currentUsername) {
    updateSharingDisplay(currentUsername, false);
  }

  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
  }
  const cleanupResults = await Promise.all(
    [...peerConnections.values()].map((peer) =>
      peer.sender.replaceTrack(null).then(
        () => true,
        () => false,
      ),
    ),
  );
  if (notifyServer && stream && cleanupResults.includes(false)) {
    setShareError(
      "The tab stopped locally, but a peer connection did not confirm track cleanup.",
    );
  }
  if (notifyServer && stream) {
    if (!sendSocketEvent({ type: "screen_share_stopped" })) {
      setShareError(
        "The tab stopped locally, but the server could not be notified to update room status.",
      );
    }
  }
  if (signalingSocket?.readyState === WebSocket.OPEN) {
    shareButton.disabled = false;
  }
  if (stream) {
    setShareStatus("Screen sharing stopped.");
  }
}

async function loadWebRtc() {
  const [sessionResponse, configResponse] = await Promise.all([
    fetch("/api/session"),
    fetch("/api/webrtc-config"),
  ]);
  if (sessionResponse.status === 401 || configResponse.status === 401) {
    window.location.replace("/");
    return;
  }
  if (!sessionResponse.ok || !configResponse.ok) {
    throw new Error("Could not load authenticated WebRTC configuration.");
  }
  const session = await sessionResponse.json();
  const configuration = await configResponse.json();
  currentUsername = session.username;
  configuredUsers = Array.isArray(session.users) ? session.users : [];
  iceServers = Array.isArray(configuration.iceServers)
    ? configuration.iceServers
    : [];
  if (
    typeof currentUsername !== "string" ||
    configuredUsers.length !== 3 ||
    !configuredUsers.includes(currentUsername) ||
    iceServers.length === 0
  ) {
    throw new Error("The room returned invalid WebRTC configuration.");
  }
  connectSignaling();
}

shareButton.addEventListener("click", startSharing);
stopShareButton.addEventListener("click", () => stopLocalSharing(true));
document.querySelector("#participant-cards").addEventListener("click", (event) => {
  const button = event.target.closest("[data-screen-fullscreen]");
  if (!button || button.disabled) {
    return;
  }
  const username = button.dataset.screenFullscreen;
  const video = getScreenVideo(username);
  if (!video || video.hidden) {
    return;
  }
  if (typeof video.requestFullscreen !== "function") {
    setShareError("Fullscreen video is not supported by this browser.");
    return;
  }
  video.requestFullscreen().catch(() => {
    setShareError("Could not open the shared browser tab in fullscreen.");
  });
});

roomLogoutButton.addEventListener("click", () => {
  stopSignaling = true;
  window.clearTimeout(reconnectTimer);
  reconnectTimer = null;
  stopLocalSharing(true);
  signalingSocket?.close(1000, "User logged out.");
});

window.addEventListener("beforeunload", () => {
  stopSignaling = true;
  window.clearTimeout(reconnectTimer);
  localStream?.getTracks().forEach((track) => track.stop());
  closeAllPeers();
  signalingSocket?.close(1000, "Room closed.");
});

loadWebRtc().catch(() => {
  shareButton.disabled = true;
  setShareStatus("Screen-sharing service is unavailable.");
  setShareError("Could not load secure room signaling. Refresh the room or sign in again.");
});
})();
