const gameId = location.pathname.split("/")[2];
const sessionId = new URLSearchParams(location.search).get("session");
const app = document.getElementById("app");
const POLL_MS = 1000;

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
  return [el("p", {}, ...players), el("p", { textContent: statusMessage(env) })];
}

async function startSession(seats) {
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
  const create = el("button", { textContent: "Create hot-seat game" });
  create.addEventListener("click", async () => {
    try {
      const res = await api(`/api/games/${gameId}/sessions`, { method: "POST", body: { mode: "hotseat", name: name.value } });
      saveEntry(res.session_id, { mode: "hotseat", seats: res.seats });
      location.search = `?session=${res.session_id}`;
    } catch (e) {
      showError(e.message);
    }
  });
  app.replaceChildren(el("section", {}, el("h2", { textContent: "New game" }), name, create));
}

document.getElementById("title").textContent = gameId;
if (!sessionId) {
  renderLobby();
} else {
  const entry = loadEntry(sessionId);
  if (entry) startSession(entry.seats);
  else showError("You do not hold a seat in this game.");
}
