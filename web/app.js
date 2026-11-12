"use strict";
// TokenBar — painel. Todo texto vindo da API entra via textContent (nunca innerHTML).

const POLL_MS = 60_000;
const $ = (sel, root = document) => root.querySelector(sel);

const state = { data: null, lastOk: 0, loading: false, celebrate: 0 };

/* ---------- janelinha da bandeja ---------- */
const MINI = new URLSearchParams(location.search).get("mini") === "1";
const PIN_KEY = "tokenbar.pinned";
if (MINI) document.documentElement.classList.add("mini");
function pinned() { try { return localStorage.getItem(PIN_KEY) === "1"; } catch { return false; } }
function setPinned(v) {
  try { localStorage.setItem(PIN_KEY, v ? "1" : "0"); } catch { /* ok */ }
  $("#pin").setAttribute("aria-pressed", String(v));
}
if (MINI) {
  setPinned(pinned());
  $("#pin").addEventListener("click", () => setPinned(!pinned()));
  // Como um menu do Windows: clicou fora, fecha (a menos que esteja fixada).
  let blurTimer = 0;
  window.addEventListener("blur", () => {
    if (pinned()) return;
    blurTimer = setTimeout(() => window.close(), 250);
  });
  window.addEventListener("focus", () => clearTimeout(blurTimer));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") window.close(); });
}

/* ---------- tema ---------- */
const THEME_KEY = "tokenbar.theme";
function storedTheme() { try { return localStorage.getItem(THEME_KEY); } catch { return null; } }
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}
function isDark() {
  const t = document.documentElement.dataset.theme;
  if (t) return t === "dark";
  return matchMedia("(prefers-color-scheme: dark)").matches;
}
applyTheme(storedTheme());
$("#theme").addEventListener("click", () => {
  const next = isDark() ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem(THEME_KEY, next); } catch { /* sem armazenamento: tudo bem */ }
  render();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);

/* ---------- mascote ---------- */
const MOOD_LABEL = {
  pronto: "Tudo em ordem", atencao: "Atenção", erro: "Limite atingido",
  processando: "Processando", vazio: "Sem dados", repouso: "Em repouso", sucesso: "Atualizado",
};
function mascotSrc(mood) { return `/assets/mascote/${mood}${isDark() ? "-branco" : ""}.svg`; }
function setMascot(img, mood) {
  const src = mascotSrc(mood);
  if (img.getAttribute("src") !== src) img.setAttribute("src", src);
  img.alt = `Mascote GGDS: ${MOOD_LABEL[mood] || mood}`;
}

/* ---------- formatação ---------- */
const nfCompact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
const fmtTokens = (n) => (n ? nfCompact.format(n) : "0");
const fmtTime = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const fmtWeekday = new Intl.DateTimeFormat("pt-BR", { weekday: "short" });
const fmtDayTime = new Intl.DateTimeFormat("pt-BR", { weekday: "short", hour: "2-digit", minute: "2-digit" });

function fmtDuration(ms) {
  if (ms <= 0) return "agora";
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60), mm = m % 60;
  if (h < 24) return mm ? `${h}h ${String(mm).padStart(2, "0")}min` : `${h}h`;
  const d = Math.floor(h / 24), hh = h % 24;
  return hh ? `${d}d ${hh}h` : `${d}d`;
}
function fmtResetAt(date) {
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay ? fmtTime.format(date) : fmtDayTime.format(date).replace(".", "");
}
function ago(ts) {
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 10) return "agora mesmo";
  if (s < 60) return `há ${s} s`;
  return `há ${Math.round(s / 60)} min`;
}

/* ---------- regras ---------- */
function level(pct) {
  if (pct == null) return "none";
  if (pct >= 100) return "full";
  if (pct >= 80) return "warn";
  return "ok";
}
function pace(w) {
  // Quanto da janela já passou → onde você "deveria" estar num ritmo uniforme.
  if (!w.resets_at || !w.window_seconds || w.window_seconds < 86400) return null;
  const left = new Date(w.resets_at).getTime() - Date.now();
  const elapsed = 1 - left / (w.window_seconds * 1000);
  // Nas primeiras ~12 h da semana o ritmo ainda não diz nada.
  if (elapsed < 0.07 || elapsed > 1) return null;
  return Math.round(elapsed * 100);
}
function providerMood(p) {
  if (!p) return "processando";
  if (p.status === "missing") return "vazio";
  if (p.status === "expired") return "atencao";
  if (p.status === "error" && !p.windows.length) return "erro";
  const max = Math.max(-1, ...p.windows.map((w) => w.used_percent ?? -1));
  if (max < 0) return "vazio";
  if (max >= 100) return "erro";
  if (max >= 80 || p.status === "stale") return "atencao";
  return "pronto";
}

/* ---------- herói ---------- */
function renderHero(providers) {
  const img = $("#hero-mascot");
  const eyebrow = $("#hero-eyebrow"), title = $("#hero-title"), detail = $("#hero-detail");
  const hero = $(".hero");
  if (!providers) {
    setMascot(img, "processando");
    return;
  }
  // Situação mais crítica entre todas as janelas.
  const all = providers.flatMap((p) => p.windows.map((w) => ({ p, w })));
  const full = all.filter(({ w }) => (w.used_percent ?? 0) >= 100);
  const warn = all.filter(({ w }) => (w.used_percent ?? 0) >= 80 && (w.used_percent ?? 0) < 100);
  const broken = providers.filter((p) => ["missing", "expired", "error"].includes(p.status) && !p.windows.length);

  let mood = "pronto", eb, t, d;
  if (full.length) {
    mood = "erro";
    const first = full.sort((a, b) => new Date(a.w.resets_at) - new Date(b.w.resets_at))[0];
    eb = "Limite atingido";
    t = `${first.p.name} esgotou: ${first.w.label.toLowerCase()}.`;
    d = first.w.resets_at
      ? `Libera às ${fmtResetAt(new Date(first.w.resets_at))} (em ${fmtDuration(new Date(first.w.resets_at) - Date.now())}).`
      : "Aguardando a janela reiniciar.";
    const others = providers.filter((p) => p !== first.p && p.windows.every((w) => (w.used_percent ?? 0) < 100));
    if (others.length) d += ` ${others.map((p) => p.name).join(" e ")} segue disponível.`;
  } else if (warn.length) {
    mood = "atencao";
    const top = warn.sort((a, b) => b.w.used_percent - a.w.used_percent)[0];
    eb = "Atenção";
    t = `${top.p.name} em ${Math.round(top.w.used_percent)}% · ${top.w.label.toLowerCase()}.`;
    d = top.w.resets_at ? `Reinicia em ${fmtDuration(new Date(top.w.resets_at) - Date.now())}. Vale dosar o uso.` : "";
  } else if (broken.length) {
    mood = broken.some((p) => p.status === "error") ? "erro" : "atencao";
    eb = "Precisa de você";
    t = `${broken.map((p) => p.name).join(" e ")} sem leitura.`;
    d = broken[0].message || "";
  } else {
    eb = "Tudo em ordem";
    const s = providers.map((p) => {
      const w = p.windows.find((x) => x.id === "session");
      return w ? `${p.name} ${Math.round(w.used_percent)}%` : null;
    }).filter(Boolean);
    t = "Folga nos dois limites.";
    d = s.length ? `Sessão atual: ${s.join(" · ")}.` : "";
  }
  if (state.celebrate > Date.now() && mood === "pronto") { mood = "sucesso"; }
  setMascot(img, mood);
  eyebrow.textContent = eb;
  title.textContent = t;
  detail.textContent = d;
  hero.style.setProperty("--hero-accent",
    mood === "erro" ? "var(--bad)" : mood === "atencao" ? "var(--warn)" : "var(--accent)");
}

/* ---------- cartões ---------- */
function chip(text, cls) {
  const s = document.createElement("span");
  s.className = `chip ${cls || ""}`;
  s.textContent = text;
  return s;
}

function renderWindow(w, isPrimary) {
  const el = $("#tpl-window").content.firstElementChild.cloneNode(true);
  const pct = w.used_percent;
  el.dataset.level = level(pct);
  if (isPrimary) el.classList.add("primary");
  $(".win-label", el).textContent = w.label;

  const pctEl = $(".win-pct", el);
  if (pct == null) pctEl.textContent = "—";
  else {
    pctEl.textContent = String(Math.round(pct));
    const small = document.createElement("small");
    small.textContent = "%";
    pctEl.append(small);
  }
  const bar = $(".bar", el);
  bar.setAttribute("aria-valuenow", String(Math.round(pct ?? 0)));
  bar.setAttribute("aria-label", `${w.label}: ${Math.round(pct ?? 0)}% usado`);
  const fill = $(".bar-fill", el);
  requestAnimationFrame(() => fill.style.setProperty("width", `${pct ?? 0}%`));

  const reset = $(".win-reset", el);
  if (w.resets_at) {
    const at = new Date(w.resets_at);
    reset.textContent = MINI
      ? `↻ ${fmtDuration(at - Date.now())} · ${fmtResetAt(at)}`
      : `reinicia em ${fmtDuration(at - Date.now())} · ${fmtResetAt(at)}`;
  } else {
    reset.textContent = pct === 0 ? "janela livre" : "";
  }

  const p = pace(w);
  if (p != null && pct != null) {
    const mark = $(".bar-pace", el);
    mark.classList.add("on");
    mark.style.setProperty("left", `${p}%`);
    const diff = Math.round(pct - p);
    const paceEl = $(".win-pace", el);
    if (Math.abs(diff) <= 3) paceEl.textContent = "no ritmo";
    else if (diff > 0) { paceEl.textContent = MINI ? `+${diff} acima do ritmo` : `${diff} pts acima do ritmo`; paceEl.classList.add("ahead"); }
    else { paceEl.textContent = MINI ? `${-diff} de folga` : `${-diff} pts de folga`; paceEl.classList.add("behind"); }
  }
  return el;
}

function renderProviders(providers) {
  const root = $("#providers");
  root.replaceChildren();
  const list = providers || [{ id: "claude", name: "Claude" }, { id: "codex", name: "Codex" }];
  for (const p of list) {
    const card = $("#tpl-provider").content.firstElementChild.cloneNode(true);
    card.dataset.provider = p.id;
    $(".card-name", card).textContent = p.name;
    setMascot($(".card-mascot", card), providers ? providerMood(p) : "processando");
    const chips = $(".chips", card);
    if (!providers) { chips.append(chip("lendo…")); root.append(card); continue; }
    if (p.plan) chips.append(chip(p.plan));
    if (p.source === "api") chips.append(chip("ao vivo", "live"));
    else if (p.source === "logs") chips.append(chip(`logs · ${p.as_of ? ago(new Date(p.as_of).getTime()) : "?"}`, "logs"));
    if (p.status === "expired") chips.append(chip("login expirado", "bad"));
    if (p.status === "missing") chips.append(chip("sem login", "bad"));
    // "Limite atingido." já aparece na barra vermelha; não repete.
    $(".card-msg", card).textContent = p.message === "Limite atingido." ? "" : (p.message || "");
    const wins = $(".windows", card);
    p.windows.forEach((w, i) => wins.append(renderWindow(w, i < 2)));
    root.append(card);
  }
}

/* ---------- uso por dia ---------- */
function stat(k, v) {
  const d = document.createElement("div");
  d.className = "stat";
  const a = document.createElement("span"); a.className = "stat-k"; a.textContent = k;
  const b = document.createElement("span"); b.className = "stat-v mono"; b.textContent = v;
  d.append(a, b);
  return d;
}

function renderUsage(usage) {
  const root = $("#usage");
  root.replaceChildren();
  if (!usage || !usage.days || !usage.days.length) return;
  const specs = [
    { id: "claude", name: "Claude Code",
      main: (u) => u.input + u.output + u.cache_write, cache: (u) => u.cache_read,
      legendMain: "entrada + saída", legendCache: "leitura de cache" },
    { id: "codex", name: "Codex",
      main: (u) => Math.max(0, u.input - u.cached) + u.output, cache: (u) => u.cached,
      legendMain: "entrada + saída", legendCache: "entrada em cache" },
  ];
  for (const s of specs) {
    const days = usage.days.map((d) => ({ date: d.date, u: d[s.id] }));
    const today = days[days.length - 1].u;
    const week = days.reduce((acc, d) => acc + s.main(d.u), 0);
    // A leitura de cache costuma ser 100x maior que o uso novo; as barras mostram só o uso novo.
    const max = Math.max(1, ...days.map((d) => s.main(d.u)));

    const card = document.createElement("article");
    card.className = "card uc";
    const head = document.createElement("div"); head.className = "uc-head";
    const h = document.createElement("h3"); h.textContent = s.name;
    const leg = document.createElement("div"); leg.className = "legend";
    const l1 = document.createElement("span"); const i1 = document.createElement("i"); l1.append(i1, `tokens novos (${s.legendMain})`);
    leg.append(l1);
    head.append(h, leg);

    const stats = document.createElement("div"); stats.className = "uc-stats";
    stats.append(stat("hoje", fmtTokens(s.main(today))), stat(s.legendCache, fmtTokens(s.cache(today))), stat("7 dias", fmtTokens(week)));

    const bars = document.createElement("div"); bars.className = "bars";
    days.forEach((d, idx) => {
      const main = s.main(d.u), cache = s.cache(d.u);
      const col = document.createElement("div");
      col.className = "day" + (idx === days.length - 1 ? " today" : "");
      const val = document.createElement("span"); val.className = "day-val mono"; val.textContent = main ? fmtTokens(main) : "·";
      const wrap = document.createElement("div"); wrap.className = "day-col";
      const bar = document.createElement("div"); bar.className = "day-bar";
      bar.style.setProperty("height", `${Math.max(1.5, (main / max) * 100)}%`);
      bar.title = `${d.date}: ${fmtTokens(main)} tokens novos · ${fmtTokens(cache)} ${s.legendCache} · saída ${fmtTokens(d.u.output)}`;
      if (main) {
        const segM = document.createElement("div"); segM.className = "seg-main"; segM.style.setProperty("height", "100%");
        bar.append(segM);
      }
      wrap.append(bar);
      const lbl = document.createElement("span"); lbl.className = "day-lbl";
      lbl.textContent = idx === days.length - 1 ? "hoje" : fmtWeekday.format(new Date(`${d.date}T12:00:00`)).replace(".", "");
      col.append(val, wrap, lbl);
      bars.append(col);
    });
    card.append(head, stats, bars);
    root.append(card);
  }
}

/* ---------- ciclo ---------- */
function render() {
  const d = state.data;
  renderHero(d ? d.providers : null);
  renderProviders(d ? d.providers : null);
  renderUsage(d ? d.usage : null);
  if (d) $("#version").textContent = `TokenBar v${d.version}`;
}

function tickUpdated() {
  const txt = state.lastOk ? `atualizado ${ago(state.lastOk)}` : (state.loading ? "carregando…" : "sem dados");
  $("#updated").textContent = txt;
  $("#mini-updated").textContent = txt;
}

async function load(force = false) {
  if (state.loading) return;
  state.loading = true;
  const btn = $("#refresh");
  btn.setAttribute("aria-busy", "true");
  tickUpdated();
  try {
    const res = await fetch(`/api/status${force ? "?refresh=1" : ""}`, {
      headers: { "X-TokenBar": "1" }, cache: "no-store", credentials: "omit",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.data = await res.json();
    state.lastOk = Date.now();
    if (force) state.celebrate = Date.now() + 2500;
    render();
    updateTitle();
  } catch (err) {
    $("#updated").textContent = "servidor local parado?";
    if (!state.data) {
      setMascot($("#hero-mascot"), "erro");
      $("#hero-eyebrow").textContent = "Algo deu errado";
      $("#hero-title").textContent = "Não consegui falar com o servidor local.";
      $("#hero-detail").textContent = "Inicie o TokenBar com scripts\\tokenbar.cmd e recarregue a página.";
    }
  } finally {
    state.loading = false;
    btn.removeAttribute("aria-busy");
    tickUpdated();
  }
}

function updateTitle() {
  // Título da aba resume as sessões: útil com a janela minimizada.
  const ps = state.data?.providers || [];
  const parts = ps.map((p) => {
    const w = p.windows.find((x) => x.id === "session");
    return w && w.used_percent != null ? `${p.name} ${Math.round(w.used_percent)}%` : null;
  }).filter(Boolean);
  document.title = parts.length ? `${parts.join(" · ")} — TokenBar` : "TokenBar · GGDS";
}

$("#refresh").addEventListener("click", () => load(true));
document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "r" || e.key === "R") load(true);
  if (e.key === "t" || e.key === "T") $("#theme").click();
  if (MINI && (e.key === "f" || e.key === "F")) $("#pin").click();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && Date.now() - state.lastOk > POLL_MS / 2) load();
});

render();
load();
setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
setInterval(() => { tickUpdated(); if (state.data) renderHero(state.data.providers); }, 15_000);
