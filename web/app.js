"use strict";
// TokenBar · painel. Texto vindo da API entra sempre via textContent (nunca innerHTML).

const POLL_MS = 60_000;
const SVGNS = "http://www.w3.org/2000/svg";
const $ = (sel, root = document) => root.querySelector(sel);
const html = document.documentElement;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const state = { data: null, lastOk: 0, loading: false, busyMood: null, cards: new Map() };

/* ====================== janelinha da bandeja ====================== */
const MINI = new URLSearchParams(location.search).get("mini") === "1";
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* sem armazenamento: tudo bem */ } },
};
if (MINI) html.classList.add("mini");

function pinned() { return store.get("tokenbar.pinned") === "1"; }
function setPinned(v) {
  store.set("tokenbar.pinned", v ? "1" : "0");
  $("#pin").setAttribute("aria-pressed", String(v));
}
if (MINI) {
  setPinned(pinned());
  $("#pin").addEventListener("click", () => setPinned(!pinned()));
  $("#close").addEventListener("click", () => window.close());
  // Como um menu do Windows: clicou fora, some (a menos que esteja fixada).
  // Só fecha se a janela já tiver recebido foco de verdade e o perdido por mais de 250 ms
  // (evita fechar durante a abertura, quando o Windows ainda está ajustando a janela).
  let blurTimer = 0, focusedOnce = document.hasFocus();
  window.addEventListener("focus", () => { focusedOnce = true; clearTimeout(blurTimer); });
  window.addEventListener("blur", () => {
    if (pinned() || !focusedOnce) return;
    clearTimeout(blurTimer);
    blurTimer = setTimeout(() => { if (!document.hasFocus() && !pinned()) window.close(); }, 250);
  });
}

/* ============================ tema ============================ */
function systemTheme() { return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"; }
function applyTheme(t) { html.dataset.theme = t === "light" ? "light" : "dark"; }
applyTheme(store.get("tokenbar.theme") || systemTheme());
$("#theme").addEventListener("click", () => {
  const next = html.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  store.set("tokenbar.theme", next);
  setMood(currentMood, true);
});

/* ============================ cena 3D ============================ */
const widget = $("#widget");
function prepareLayers() {
  document.querySelectorAll(".layer").forEach((el, i) => {
    el.style.setProperty("--depth", el.dataset.depth || "0");
    el.style.setProperty("--delay", `${0.06 + i * 0.07}s`);
  });
}
prepareLayers();
html.classList.add("boot");

const tilt = { x: 0, y: 0, tx: 0, ty: 0, active: false, t0: performance.now() };
window.addEventListener("pointermove", (e) => {
  const nx = e.clientX / innerWidth - 0.5, ny = e.clientY / innerHeight - 0.5;
  tilt.tx = -ny * (MINI ? 3.5 : 9);
  tilt.ty = nx * (MINI ? 4.5 : 12);
  tilt.active = true;
  for (const card of document.querySelectorAll(".card")) {
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", `${e.clientX - r.left}px`);
    card.style.setProperty("--my", `${e.clientY - r.top}px`);
  }
});
document.addEventListener("pointerleave", () => { tilt.active = false; });
window.addEventListener("blur", () => { tilt.active = false; });

function frame(now) {
  if (!tilt.active) {
    // Sem ponteiro: um balanço lento, quase imperceptível, mantém a cena viva.
    const t = (now - tilt.t0) / 1000;
    tilt.tx = Math.sin(t * 0.6) * 1.2;
    tilt.ty = Math.cos(t * 0.45) * 1.6;
  }
  tilt.x += (tilt.tx - tilt.x) * 0.08;
  tilt.y += (tilt.ty - tilt.y) * 0.08;
  widget.style.setProperty("--rx", `${tilt.x.toFixed(3)}deg`);
  widget.style.setProperty("--ry", `${tilt.y.toFixed(3)}deg`);
  requestAnimationFrame(frame);
}
if (!reduceMotion) requestAnimationFrame(frame);

/* ============================ mascote ============================ */
const MOODS = {
  pronto: { ink: null, color: "var(--ambar)" },
  buscando: { ink: null, color: "var(--ambar)" },
  processando: { ink: null, color: "var(--ambar)" },
  sucesso: { ink: "var(--good)", color: "var(--good)" },
  atencao: { ink: "var(--warn)", color: "var(--warn)" },
  erro: { ink: "var(--bad)", color: "var(--bad)" },
  vazio: { ink: null, color: "var(--ambar)" },
  repouso: { ink: null, color: "var(--ambar)" },
};
let currentMood = null;
let mascotSeq = 0;
let mascotFront = $("#mascot-a"), mascotBack = $("#mascot-b");
mascotBack.classList.add("out");

function mascotSrc(mood) { return `/assets/mascote/${mood}${html.dataset.theme === "dark" ? "-branco" : ""}.svg`; }

function setMood(mood, force = false) {
  if (mood === currentMood && !force) return;
  currentMood = mood;
  document.body.dataset.mood = mood;
  const m = MOODS[mood] || MOODS.pronto;
  html.style.setProperty("--mood-ink", m.ink || "var(--accent-ink)");
  html.style.setProperty("--mood-color", m.color);
  const src = mascotSrc(mood);
  const seq = ++mascotSeq;
  if (mascotFront.getAttribute("src") === src) { mascotBack.onload = null; return; }
  // Troca com cruzamento: o novo entra com um pequeno salto, o antigo encolhe.
  // Só a troca mais recente vale (evita "ida e volta" quando o humor muda duas vezes seguidas).
  const incoming = mascotBack;
  const show = () => {
    if (seq !== mascotSeq || incoming !== mascotBack) return;
    incoming.onload = null;
    incoming.classList.remove("out");
    mascotFront.classList.add("out");
    [mascotFront, mascotBack] = [incoming, mascotFront];
  };
  incoming.onload = show;
  incoming.setAttribute("src", src);
  if (incoming.complete && incoming.naturalWidth) show();
}

/* ============================ formatação ============================ */
const fmtTime = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const fmtDayTime = new Intl.DateTimeFormat("pt-BR", { weekday: "short", hour: "2-digit", minute: "2-digit" });
function fmtDuration(ms) {
  if (ms <= 0) return "agora";
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m}min`;
  const h = Math.floor(m / 60), mm = m % 60;
  if (h < 24) return mm ? `${h}h${String(mm).padStart(2, "0")}` : `${h}h`;
  const d = Math.floor(h / 24), hh = h % 24;
  return hh ? `${d}d ${hh}h` : `${d}d`;
}
function fmtAt(date) {
  return date.toDateString() === new Date().toDateString()
    ? fmtTime.format(date)
    : fmtDayTime.format(date).replace(".", "").replace(",", "");
}
function ago(ts) {
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 15) return "agora";
  if (s < 60) return `há ${s}s`;
  if (s < 3600) return `há ${Math.round(s / 60)}min`;
  if (s < 86400) return `há ${Math.round(s / 3600)}h`;
  return `há ${Math.round(s / 86400)}d`;
}
const level = (p) => (p == null ? "none" : p >= 100 ? "full" : p >= 80 ? "warn" : "ok");

function paceOf(w) {
  if (!w.resets_at || !w.window_seconds || w.window_seconds < 86400) return null;
  const elapsed = 1 - (new Date(w.resets_at).getTime() - Date.now()) / (w.window_seconds * 1000);
  return elapsed < 0.07 || elapsed > 1 ? null : elapsed * 100;
}

/* ============================ números animados ============================ */
function countTo(el, to) {
  const from = Number(el.dataset.value || 0);
  el.dataset.value = String(to);
  const num = el.firstChild;
  if (reduceMotion || from === to || document.hidden) { num.nodeValue = String(Math.round(to)); return; }
  const t0 = performance.now(), dur = 1250;
  // Garante o valor final mesmo se a aba parar de pintar no meio da animação.
  setTimeout(() => { if (el.dataset.value === String(to)) num.nodeValue = String(Math.round(to)); }, dur + 150);
  const step = (now) => {
    if (el.dataset.value !== String(to)) return;
    const k = Math.min(1, (now - t0) / dur);
    const e = 1 - Math.pow(1 - k, 4);
    num.nodeValue = String(Math.round(from + (to - from) * e));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ============================ anéis ============================ */
const R = 26, C = 2 * Math.PI * R;
let gradSeq = 0;

function buildRing() {
  const cell = document.createElement("div");
  cell.className = "ring-cell";
  const ring = document.createElement("div");
  ring.className = "ring";
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("viewBox", "0 0 62 62");
  const id = `g${++gradSeq}`;
  const defs = document.createElementNS(SVGNS, "defs");
  const grad = document.createElementNS(SVGNS, "linearGradient");
  grad.id = id;
  grad.setAttribute("x1", "0"); grad.setAttribute("y1", "0"); grad.setAttribute("x2", "1"); grad.setAttribute("y2", "1");
  for (const [off, v] of [["0", "var(--c2)"], ["1", "var(--c1)"]]) {
    const s = document.createElementNS(SVGNS, "stop");
    s.setAttribute("offset", off);
    s.style.setProperty("stop-color", v);
    grad.append(s);
  }
  defs.append(grad);
  const track = document.createElementNS(SVGNS, "circle");
  track.setAttribute("class", "track");
  const arc = document.createElementNS(SVGNS, "circle");
  arc.setAttribute("class", "arc");
  arc.setAttribute("stroke", `url(#${id})`);
  arc.setAttribute("stroke-dasharray", `${C} ${C}`);
  arc.setAttribute("stroke-dashoffset", String(C));
  for (const c of [track, arc]) { c.setAttribute("cx", "31"); c.setAttribute("cy", "31"); c.setAttribute("r", String(R)); }
  const pace = document.createElementNS(SVGNS, "circle");
  pace.setAttribute("class", "pace");
  pace.setAttribute("r", "2.2");
  pace.style.setProperty("opacity", "0");
  svg.append(defs, track, arc, pace);

  const core = document.createElement("div");
  core.className = "ring-core";
  const num = document.createElement("span");
  num.className = "ring-num";
  num.append(document.createTextNode("–"));
  const pct = document.createElement("small");
  pct.textContent = "%";
  num.append(pct);
  core.append(num);
  ring.append(svg, core);

  const meta = document.createElement("div");
  meta.className = "ring-meta";
  const label = document.createElement("span"); label.className = "ring-label";
  const reset = document.createElement("span"); reset.className = "ring-reset";
  const resetAt = document.createElement("span"); resetAt.className = "ring-at";
  const paceTxt = document.createElement("span"); paceTxt.className = "ring-pace";
  meta.append(label, reset, resetAt, paceTxt);
  cell.append(ring, meta);
  return { cell, ring, arc, pace, num, label, reset, resetAt, paceTxt };
}

function updateRing(r, w) {
  const pct = w ? w.used_percent : null;
  r.ring.dataset.level = level(pct);
  r.label.textContent = (w ? w.label : r.fallback).replace("Sessão · 5h", "Sessão 5h");
  if (pct == null) {
    r.num.dataset.value = "";          // cancela contagens em andamento
    r.num.firstChild.nodeValue = "–";
    r.arc.setAttribute("stroke-dashoffset", String(C));
  } else {
    countTo(r.num, Math.round(pct));
    // Começa do zero na 1ª pintura para o arco "desenhar" na entrada.
    setTimeout(() => r.arc.setAttribute("stroke-dashoffset", String(C * (1 - pct / 100))), 60);
  }
  if (w && w.resets_at) {
    const at = new Date(w.resets_at);
    r.reset.textContent = `↻ em ${fmtDuration(at - Date.now())}`;
    r.resetAt.textContent = fmtAt(at);
    r.cell.title = `${w.label}: ${Math.round(pct ?? 0)}% usado · reinicia ${at.toLocaleString("pt-BR")}`;
  } else {
    r.reset.textContent = pct === 0 ? "janela livre" : pct == null ? "sem dados" : "";
    r.resetAt.textContent = "";
    r.cell.removeAttribute("title");
  }
  const p = w ? paceOf(w) : null;
  r.paceTxt.className = "ring-pace";
  if (p != null && pct != null) {
    const a = (p / 100) * 2 * Math.PI;
    r.pace.setAttribute("cx", String(31 + R * Math.cos(a)));
    r.pace.setAttribute("cy", String(31 + R * Math.sin(a)));
    r.pace.style.setProperty("opacity", ".8");
    const diff = Math.round(pct - p);
    if (Math.abs(diff) <= 3) r.paceTxt.textContent = "no ritmo";
    else if (diff > 0) { r.paceTxt.textContent = `+${diff} acima do ritmo`; r.paceTxt.classList.add("ahead"); }
    else { r.paceTxt.textContent = `${-diff} de folga`; r.paceTxt.classList.add("behind"); }
  } else {
    r.pace.style.setProperty("opacity", "0");
    r.paceTxt.textContent = "";
  }
}

/* ============================ cartões ============================ */
function getCard(p, index) {
  let c = state.cards.get(p.id);
  if (c) return c;
  const el = $("#tpl-provider").content.firstElementChild.cloneNode(true);
  el.dataset.provider = p.id;
  el.style.setProperty("--depth", el.dataset.depth);
  el.style.setProperty("--delay", `${0.16 + index * 0.1}s`);
  const rings = [buildRing(), buildRing()];
  rings[0].fallback = "Sessão 5h";
  rings[1].fallback = "Semana";
  $(".rings", el).append(rings[0].cell, rings[1].cell);
  c = { el, rings, extras: new Map() };
  state.cards.set(p.id, c);
  $("#providers").append(el);
  return c;
}

function updateCard(p, index) {
  const c = getCard(p, index);
  c.el.classList.toggle("ghost", !p.windows);
  $(".p-name", c.el).textContent = p.name;
  $(".p-plan", c.el).textContent = p.plan || "";
  const live = $(".p-live", c.el);
  live.className = "p-live";
  if (!p.windows) live.textContent = "";
  else if (p.source === "api") { live.textContent = "ao vivo"; live.classList.add("live"); }
  else if (p.source === "logs") { live.textContent = `log ${p.as_of ? ago(new Date(p.as_of).getTime()) : ""}`; live.classList.add("logs"); }
  else if (p.status === "expired") { live.textContent = "login expirado"; live.classList.add("bad"); }
  else if (p.status === "missing") { live.textContent = "sem login"; live.classList.add("bad"); }
  else live.textContent = "";
  const msg = p.message && p.message !== "Limite atingido." ? p.message : "";
  $(".p-msg", c.el).textContent = msg;
  $(".p-msg", c.el).title = msg;

  const wins = p.windows || [];
  const session = wins.find((w) => w.id === "session") || wins[0];
  const weekly = wins.find((w) => w.id === "weekly") || wins.find((w) => w !== session);
  updateRing(c.rings[0], session || null);
  updateRing(c.rings[1], weekly || null);

  // Demais limites (ex.: "Semana · Fable") como barras finas.
  const box = $(".extras", c.el);
  const rest = wins.filter((w) => w !== session && w !== weekly);
  const seen = new Set();
  for (const w of rest) {
    seen.add(w.id);
    let row = c.extras.get(w.id);
    if (!row) {
      row = document.createElement("div");
      row.className = "xrow";
      const l = document.createElement("span"); l.className = "xrow-label";
      const bar = document.createElement("div"); bar.className = "xbar"; bar.append(document.createElement("i"));
      const v = document.createElement("span"); v.className = "xrow-pct";
      row.append(l, bar, v);
      box.append(row);
      c.extras.set(w.id, row);
    }
    row.dataset.level = level(w.used_percent);
    row.children[0].textContent = w.label;
    row.children[2].textContent = `${Math.round(w.used_percent ?? 0)}%`;
    const fill = row.children[1].firstChild;
    setTimeout(() => fill.style.setProperty("width", `${w.used_percent ?? 0}%`), 60);
  }
  for (const [id, row] of c.extras) if (!seen.has(id)) { row.remove(); c.extras.delete(id); }
}

/* ============================ manchete ============================ */
function setText(el, text) {
  if (el.textContent === text) return;
  el.textContent = text;
  el.classList.remove("swap");
  void el.offsetWidth;
  el.classList.add("swap");
}

function moodFor(providers) {
  const all = providers.flatMap((p) => p.windows.map((w) => ({ p, w })));
  const full = all.filter(({ w }) => (w.used_percent ?? 0) >= 100);
  const warn = all.filter(({ w }) => (w.used_percent ?? 0) >= 80 && (w.used_percent ?? 0) < 100);
  const broken = providers.filter((p) => !p.windows.length);
  const free = (p) => {
    const s = p.windows.find((w) => w.id === "session");
    return s ? Math.round(100 - s.used_percent) : null;
  };

  if (full.length) {
    const first = full.sort((a, b) => new Date(a.w.resets_at) - new Date(b.w.resets_at))[0];
    const others = providers.filter((p) => p !== first.p && p.windows.length && p.windows.every((w) => (w.used_percent ?? 0) < 100));
    const at = first.w.resets_at ? new Date(first.w.resets_at) : null;
    return {
      mood: "erro", eyebrow: "Limite atingido",
      headline: at ? `${first.p.name} volta às ${fmtAt(at)}` : `${first.p.name} no limite`,
      sub: others.length && free(others[0]) != null
        ? `${others[0].name} ainda tem ${free(others[0])}% livre`
        : at ? `em ${fmtDuration(at - Date.now())}` : "",
    };
  }
  if (warn.length) {
    const top = warn.sort((a, b) => b.w.used_percent - a.w.used_percent)[0];
    return {
      mood: "atencao", eyebrow: "Atenção",
      headline: `${top.p.name} em ${Math.round(top.w.used_percent)}% · ${top.w.label.toLowerCase()}`,
      sub: top.w.resets_at ? `reinicia em ${fmtDuration(new Date(top.w.resets_at) - Date.now())}` : "",
    };
  }
  if (broken.length) {
    const why = { expired: "login expirado", missing: "sem login", error: "falha na consulta" }[broken[0].status] || "sem leitura";
    return {
      mood: broken.some((p) => p.status === "missing") ? "vazio" : broken.some((p) => p.status === "error") ? "erro" : "atencao",
      eyebrow: "Precisa de você",
      headline: `${broken.map((p) => p.name).join(" e ")}: ${why}`,
      sub: "Detalhes no cartão abaixo",
    };
  }
  const maxAll = Math.max(...all.map(({ w }) => w.used_percent ?? 0));
  return {
    mood: maxAll < 5 ? "repouso" : "pronto",
    eyebrow: "Tudo em ordem",
    headline: maxAll < 5 ? "Cotas cheias, pode usar" : "Folga nos dois limites",
    sub: providers.map((p) => (free(p) != null ? `${p.name} ${free(p)}% livre` : null)).filter(Boolean).join(" · "),
  };
}

function renderHead() {
  const d = state.data;
  if (!d) return;
  const h = moodFor(d.providers);
  setMood(state.busyMood || h.mood);
  setText($("#eyebrow"), state.busyMood === "processando" ? "Atualizando" : state.busyMood === "sucesso" ? "Atualizado" : h.eyebrow);
  setText($("#headline"), h.headline);
  setText($("#sub"), h.sub);
}

/* ============================ ciclo ============================ */
function render() {
  const d = state.data;
  const list = d ? d.providers : [{ id: "claude", name: "Claude" }, { id: "codex", name: "Codex" }];
  list.forEach((p, i) => updateCard(p, i));
  prepareLayersOnce();
  renderHead();
  updateTitle();
}

let layersReady = false;
function prepareLayersOnce() {
  if (layersReady) return;
  layersReady = true;
  // Depois da 1ª pintura liberamos a entrada em cascata (setTimeout: funciona até em 2º plano).
  setTimeout(() => html.classList.remove("boot"), 40);
  // Terminada a entrada em cascata, as camadas passam a seguir o ponteiro (partindo do repouso).
  setTimeout(() => {
    tilt.x = tilt.y = 0;
    widget.style.setProperty("--rx", "0deg");
    widget.style.setProperty("--ry", "0deg");
    html.classList.add("live");
  }, 1500);
}

function tickStamp() {
  const el = $("#stamp"), txt = $("#stamp-text");
  el.classList.remove("stale", "down");
  if (!state.lastOk) { txt.textContent = state.loading ? "conectando" : "sem conexão"; if (!state.loading) el.classList.add("down"); return; }
  const age = Date.now() - state.lastOk;
  if (age > POLL_MS * 3) el.classList.add("stale");
  const anyLogs = state.data?.providers.some((p) => p.source === "logs");
  txt.textContent = `${anyLogs ? "parcial" : "ao vivo"} · ${ago(state.lastOk)}`;
}

function updateTitle() {
  const ps = state.data?.providers || [];
  const parts = ps.map((p) => {
    const w = p.windows.find((x) => x.id === "session");
    return w && w.used_percent != null ? `${p.name} ${Math.round(w.used_percent)}%` : null;
  }).filter(Boolean);
  document.title = parts.length ? `${parts.join(" · ")} — TokenBar` : "TokenBar · GGDS";
}

async function load(force = false) {
  if (state.loading) return;
  state.loading = true;
  const btn = $("#refresh");
  btn.setAttribute("aria-busy", "true");
  if (force || !state.data) { state.busyMood = state.data ? "processando" : null; if (!state.data) setMood("buscando"); renderHead(); }
  const started = performance.now();
  try {
    const res = await fetch(`/api/status${force ? "?refresh=1" : ""}`, {
      headers: { "X-TokenBar": "1" }, cache: "no-store", credentials: "omit",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    // Deixa o "processando" respirar um pouco antes de mostrar o resultado.
    if (force) await new Promise((r) => setTimeout(r, Math.max(0, 650 - (performance.now() - started))));
    state.data = data;
    state.lastOk = Date.now();
    if (force) {
      state.busyMood = "sucesso";
      setTimeout(() => { state.busyMood = null; renderHead(); }, 1700);
    } else {
      state.busyMood = null;
    }
    render();
  } catch {
    state.busyMood = null;
    if (!state.data) {
      setMood("erro");
      setText($("#eyebrow"), "Algo deu errado");
      setText($("#headline"), "Servidor local não respondeu");
      setText($("#sub"), "Abra o TokenBar pelo atalho e tente de novo.");
    }
  } finally {
    state.loading = false;
    btn.removeAttribute("aria-busy");
    tickStamp();
  }
}

$("#refresh").addEventListener("click", () => load(true));
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === "r") load(true);
  else if (k === "t") $("#theme").click();
  else if (k === "f" && MINI) $("#pin").click();
  else if (k === "escape" && MINI) window.close();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && Date.now() - state.lastOk > POLL_MS / 2) load();
});

render();
load();
setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
setInterval(() => {
  tickStamp();
  if (state.data) state.data.providers.forEach((p, i) => updateCard(p, i));
  renderHead();
}, 20_000);
