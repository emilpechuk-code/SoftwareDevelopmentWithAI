const gameId = location.pathname.split("/")[2];
const sessionId = new URLSearchParams(location.search).get("session");
const app = document.getElementById("app");
const POLL_MS = 1000;
const LOBBY_MS = 2000;

async function api(path, { method = "GET", body, token } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-Player-Token"] = token;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message ?? JSON.stringify(data.detail ?? res.statusText));
  return data;
}

const storageKey = (id) => `gamer:${id}`;
const loadEntry = (id) => JSON.parse(localStorage.getItem(storageKey(id)) ?? "null");
const saveEntry = (id, entry) => localStorage.setItem(storageKey(id), JSON.stringify(entry));
const tabKey = (id) => `gamer:tab:${id}`;

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

function showError(message) {
  document.getElementById("error").textContent = message ?? "";
}

function statusMessage(env) {
  const name = (label) => env.seats.find((s) => s.label === label)?.name ?? label;
  if (env.result) return env.result.draw ? "Game over: draw" : `Game over: ${name(env.result.winner)} wins`;
  if (env.status === "waiting") return "Waiting for an opponent to join…";
  return `${name(env.turn)} to move`;
}

function statusLines(env, seats) {
  const mine = new Set(seats.map((s) => s.seat));
  const players = env.seats.map((s) => el("span", {
    className: `seat ${s.label}${env.turn === s.label ? " to-move" : ""}`,
    textContent: `${s.name} (${s.label})${mine.has(s.label) ? " – you" : ""}`,
  }));
  const lines = [el("p", {}, ...players), el("p", { textContent: statusMessage(env) })];
  if (env.mode === "online" && env.status === "waiting") {
    lines.push(el("p", { className: "share" }, "Share this link: ", el("input", { readOnly: true, value: location.href })));
  }
  return lines;
}

async function startSession(seats) {
  sessionStorage.setItem(tabKey(sessionId), JSON.stringify(seats.map((s) => s.seat)));
  const view = await import(`/games/${gameId}/static/view.js`);
  const status = el("div", { className: "status" });
  const board = el("div");
  app.replaceChildren(status, board);
  const tokenFor = (label) => seats.find((s) => s.seat === label)?.token;
  let latest = null;

  function accept(env) {
    if (latest && env.version < latest.version) return;
    latest = env;
    status.replaceChildren(...statusLines(latest, seats));
    view.render(board, latest, {
      canMove: latest.status === "playing" && Boolean(tokenFor(latest.turn)),
      onMove: async (move) => {
        try {
          accept(await api(`/api/sessions/${sessionId}/moves`, { method: "POST", body: { move }, token: tokenFor(latest.turn) }));
          showError("");
        } catch (e) {
          showError(e.message);
        }
      },
    });
  }

  async function poll() {
    try {
      const since = latest ? `?since=${latest.version}` : "";
      const res = await api(`/api/sessions/${sessionId}/state${since}`, { token: seats[0].token });
      if (res.type === "state") accept(res);
    } catch (e) {
      showError(e.message);
    }
    setTimeout(poll, POLL_MS);
  }
  poll();
}

function renderLobby() {
  const name = el("input", { placeholder: "Your name (optional)", maxLength: 40 });
  const mode = el("select", {},
    el("option", { value: "online", textContent: "Online (share a link)" }),
    el("option", { value: "hotseat", textContent: "Hot-seat (this tab plays both)" }));
  const create = el("button", { textContent: "Create game" });
  create.addEventListener("click", async () => {
    try {
      const res = await api(`/api/games/${gameId}/sessions`, { method: "POST", body: { mode: mode.value, name: name.value } });
      saveEntry(res.session_id, { mode: mode.value, seats: res.seats });
      sessionStorage.setItem(tabKey(res.session_id), JSON.stringify(res.seats.map((s) => s.seat)));
      location.search = `?session=${res.session_id}`;
    } catch (e) {
      showError(e.message);
    }
  });
  const waiting = el("ul", {}, el("li", { textContent: "Loading…" }));
  app.replaceChildren(
    el("section", {}, el("h2", { textContent: "New game" }), name, mode, create),
    el("section", {}, el("h2", { textContent: "Open games" }), waiting),
  );
  async function refresh() {
    try {
      const { sessions } = await api(`/api/games/${gameId}/sessions`);
      waiting.replaceChildren(...(sessions.length
        ? sessions.map((s) => el("li", {}, el("a", { href: `?session=${s.session_id}`, textContent: `${s.host}'s game` })))
        : [el("li", { textContent: "No open games yet." })]));
    } catch (e) {
      showError(e.message);
    }
    setTimeout(refresh, LOBBY_MS);
  }
  refresh();
}

async function openSession() {
  const entry = loadEntry(sessionId);
  const stored = entry?.seats ?? [];
  const tabSeats = JSON.parse(sessionStorage.getItem(tabKey(sessionId)) ?? "[]");
  const mine = stored.filter((s) => tabSeats.includes(s.seat));
  if (mine.length) return startSession(mine);
  if (entry?.mode === "hotseat") return startSession(stored);
  const { sessions } = await api(`/api/games/${gameId}/sessions`);
  const open = sessions.some((s) => s.session_id === sessionId);
  if (!open && stored.length === 1) return startSession(stored);
  if (!open && stored.length === 0) return showError("This game is full or no longer exists.");
  const choices = stored.map((s) => {
    const resume = el("button", { textContent: `Resume as ${s.seat}` });
    resume.addEventListener("click", () => startSession([s]));
    return resume;
  });
  if (open) choices.push(joinForm(stored));
  app.replaceChildren(el("section", {}, el("h2", { textContent: "Join game" }), ...choices));
}

function joinForm(stored) {
  const name = el("input", { placeholder: "Your name (optional)", maxLength: 40 });
  const join = el("button", { textContent: "Join as new player" });
  join.addEventListener("click", async () => {
    try {
      const seat = await api(`/api/sessions/${sessionId}/join`, { method: "POST", body: { name: name.value } });
      saveEntry(sessionId, { mode: "online", seats: [...stored, seat] });
      startSession([seat]);
    } catch (e) {
      showError(e.message);
    }
  });
  return el("div", {}, name, join);
}

document.getElementById("title").textContent = gameId;
if (!sessionId) {
  renderLobby();
} else {
  openSession().catch((e) => showError(e.message));
}
