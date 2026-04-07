/* ================================================================
   POLYSTATION — Dashboard Application
   ================================================================ */

"use strict";

// ------------------------------------------------------------------ //
// State                                                               //
// ------------------------------------------------------------------ //
const State = {
  markets:         [],     // MarketInfo[]
  selectedMarket:  null,   // MarketInfo
  selectedTokenIdx: 0,     // index into selectedMarket.token_ids
  orderBook:       null,   // raw /api/markets/book response
  strategies:      {},     // { name: statusDict }
  orders:          [],     // Order[]
  portfolio:       null,   // summary dict
  pnl:             null,   // pnl dict
  apiHealth:       null,   // health dict
  activeTab:       "active",  // "active" | "trending"
  ws:              null,
  wsRetry:         0,
  refreshTimer:    null,
};

// ------------------------------------------------------------------ //
// Utilities                                                           //
// ------------------------------------------------------------------ //
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function fmt2(n) { return n == null ? "—" : Number(n).toFixed(2); }
function fmt4(n) { return n == null ? "—" : Number(n).toFixed(4); }
function fmtK(n) {
  if (n == null) return "—";
  n = Number(n);
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toFixed(0);
}
function fmtPct(n) { return n == null ? "—" : (Number(n) >= 0 ? "+" : "") + Number(n).toFixed(2) + "%"; }
function fmtPrice(n) { return n == null ? "—" : Number(n).toFixed(4); }
function fmtTs(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return iso.substring(11, 19) || iso; }
}

function pnlClass(val) {
  if (val == null) return "neu";
  return Number(val) > 0 ? "pos" : Number(val) < 0 ? "neg" : "neu";
}

function statusBadge(status) {
  const cls = (status || "").toLowerCase();
  return `<span class="strategy-status-badge ${cls}">${status || "unknown"}</span>`;
}

function sideBadge(side) {
  const cls = (side || "").toLowerCase();
  return `<span class="badge badge-${cls}">${side || "—"}</span>`;
}

function orderStatusBadge(status) {
  return `<span class="badge badge-${(status || "").toLowerCase()}">${status || "—"}</span>`;
}

function escHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function flash(el, cls) {
  if (!el) return;
  el.classList.remove("flash-green", "flash-red");
  void el.offsetWidth; // force reflow
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), 700);
}

// ------------------------------------------------------------------ //
// API helpers                                                          //
// ------------------------------------------------------------------ //
async function apiFetch(path) {
  const resp = await fetch(path);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return resp.json();
}

async function apiPost(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return resp.json();
}

// ------------------------------------------------------------------ //
// WebSocket                                                            //
// ------------------------------------------------------------------ //
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws`;

  const ws = new WebSocket(url);
  State.ws = ws;

  ws.onopen = () => {
    State.wsRetry = 0;
    setConnStatus("connected");
    addLog("INFO", "WebSocket connected");
    ws.send(JSON.stringify({ type: "ping" }));
  };

  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      handleWsMessage(msg);
    } catch { /* ignore bad frames */ }
  };

  ws.onerror = () => {
    setConnStatus("error");
  };

  ws.onclose = () => {
    setConnStatus("disconnected");
    const delay = Math.min(1000 * 2 ** State.wsRetry, 30000);
    State.wsRetry++;
    addLog("WARN", `WebSocket closed — reconnecting in ${(delay / 1000).toFixed(0)}s`);
    setTimeout(connectWS, delay);
  };
}

function handleWsMessage(msg) {
  if (msg.type === "pong") return;
  if (msg.type === "connected") return;
  if (msg.type === "trade") {
    addLog("TRADE", `${msg.side} ${fmtK(msg.size)} @ ${fmtPrice(msg.price)} — ${(msg.kernel || "")}`);
    refreshOrders();
    refreshPortfolio();
  } else if (msg.type === "order_update") {
    refreshOrders();
  } else if (msg.type === "kernel_event") {
    addLog("INFO", `Kernel ${msg.name}: ${msg.event}`);
    refreshStrategies();
  } else if (msg.type === "price_update") {
    // Optionally update specific cells
  }
}

function setConnStatus(state) {
  const dot = $("#conn-dot");
  const lbl = $("#conn-label");
  dot.className = `${state === "connected" ? "connected" : state === "error" ? "error" : ""}`;
  lbl.textContent = state === "connected" ? "LIVE" : state === "error" ? "ERROR" : "OFFLINE";
}

// ------------------------------------------------------------------ //
// Trade Log                                                            //
// ------------------------------------------------------------------ //
function addLog(level, msg) {
  const container = $("#trade-log-entries");
  const now = new Date();
  const time = now.toLocaleTimeString("en-US", { hour12: false });

  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.innerHTML = `
    <span class="log-time">${escHtml(time)}</span>
    <span class="log-level ${escHtml(level)}">${escHtml(level)}</span>
    <span class="log-msg">${escHtml(msg)}</span>
  `;
  container.prepend(entry);

  // Keep max 200 entries
  while (container.children.length > 200) {
    container.removeChild(container.lastChild);
  }
}

// ------------------------------------------------------------------ //
// Markets Panel                                                        //
// ------------------------------------------------------------------ //
async function refreshMarkets() {
  try {
    const tab = State.activeTab;
    const data = tab === "trending"
      ? await apiFetch("/api/markets/trending")
      : await apiFetch("/api/markets/");
    State.markets = data;
    renderMarkets();
  } catch (e) {
    addLog("ERROR", `Markets fetch failed: ${e.message}`);
  }
}

function renderMarkets() {
  const tbody = $("#tbl-markets tbody");
  if (!tbody) return;

  const query = ($("#markets-search")?.value || "").toLowerCase().trim();
  const markets = query
    ? State.markets.filter(m => m.question.toLowerCase().includes(query))
    : State.markets;

  if (markets.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="state-empty">No markets found</td></tr>`;
    return;
  }

  tbody.innerHTML = markets.map(m => {
    const isSel = State.selectedMarket && m.condition_id === State.selectedMarket.condition_id;
    const bid = m.best_bid != null ? Number(m.best_bid).toFixed(4) : "—";
    const ask = m.best_ask != null ? Number(m.best_ask).toFixed(4) : "—";
    const vol = fmtK(m.volume);
    const ltp = m.last_trade_price != null ? Number(m.last_trade_price).toFixed(4) : "—";
    return `
      <tr class="${isSel ? "selected" : ""}" data-cid="${escHtml(m.condition_id)}">
        <td class="truncate" title="${escHtml(m.question)}">${escHtml(m.question)}</td>
        <td class="num text-green">${bid}</td>
        <td class="num text-red">${ask}</td>
        <td class="num text-secondary">${vol}</td>
        <td class="num">${ltp}</td>
      </tr>
    `;
  }).join("");

  tbody.querySelectorAll("tr[data-cid]").forEach(tr => {
    tr.addEventListener("click", () => {
      const cid = tr.getAttribute("data-cid");
      const mkt = State.markets.find(m => m.condition_id === cid);
      if (mkt) selectMarket(mkt);
    });
  });
}

function selectMarket(mkt) {
  State.selectedMarket = mkt;
  State.selectedTokenIdx = 0;
  renderMarkets();
  renderSelectedMarketHeader();
  refreshOrderBook();
}

function renderSelectedMarketHeader() {
  const el = $("#ob-market-question");
  if (!el) return;
  const mkt = State.selectedMarket;
  if (!mkt) {
    el.textContent = "Select a market";
    return;
  }
  el.textContent = mkt.question;
  el.title = mkt.question;

  // Populate outcome tabs if there are multiple token_ids
  const tabs = $("#ob-token-tabs");
  if (!tabs) return;
  const outcomes = mkt.outcomes || [];
  const tokenIds = mkt.token_ids || [];
  if (tokenIds.length <= 1) {
    tabs.innerHTML = "";
    return;
  }
  tabs.innerHTML = tokenIds.map((tid, i) => {
    const label = outcomes[i] || `Token ${i}`;
    return `<button class="markets-tab ${i === State.selectedTokenIdx ? "active" : ""}" data-idx="${i}">${escHtml(label)}</button>`;
  }).join("");
  tabs.querySelectorAll("button[data-idx]").forEach(btn => {
    btn.addEventListener("click", () => {
      State.selectedTokenIdx = parseInt(btn.getAttribute("data-idx"), 10);
      tabs.querySelectorAll("button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      refreshOrderBook();
    });
  });
}

// ------------------------------------------------------------------ //
// Order Book Panel                                                      //
// ------------------------------------------------------------------ //
async function refreshOrderBook() {
  if (!State.selectedMarket) return;
  const tokenIds = State.selectedMarket.token_ids || [];
  if (tokenIds.length === 0) return;
  const tokenId = tokenIds[State.selectedTokenIdx] || tokenIds[0];

  try {
    const book = await apiFetch(`/api/markets/book/${encodeURIComponent(tokenId)}`);
    State.orderBook = book;
    renderOrderBook(book);

    // Also fetch pricing summary
    const price = await apiFetch(`/api/markets/price/${encodeURIComponent(tokenId)}`);
    renderPriceSummary(price);
  } catch (e) {
    addLog("ERROR", `Order book fetch failed: ${e.message}`);
  }
}

function renderPriceSummary(price) {
  const midEl = $("#ob-midpoint");
  const spreadEl = $("#ob-spread");
  const bidEl = $("#ob-best-bid");
  const askEl = $("#ob-best-ask");

  if (midEl) { midEl.textContent = fmtPrice(price.midpoint); flash(midEl, "flash-green"); }
  if (spreadEl) { spreadEl.textContent = fmtPrice(price.spread); }
  if (bidEl) { bidEl.textContent = fmtPrice(price.best_bid); }
  if (askEl) { askEl.textContent = fmtPrice(price.best_ask); }
}

function renderOrderBook(book) {
  const bidsEl = $("#ob-bids");
  const asksEl = $("#ob-asks");
  if (!bidsEl || !asksEl) return;

  const bids = book.bids || [];
  const asks = book.asks || [];

  const maxSize = Math.max(
    ...bids.map(l => l.size),
    ...asks.map(l => l.size),
    1
  );

  function renderLevels(levels, container, side) {
    container.innerHTML = levels.slice(0, 18).map(lv => {
      const fillPct = ((lv.size / maxSize) * 100).toFixed(1);
      return `
        <div class="ob-row">
          <div class="ob-fill" style="width:${fillPct}%"></div>
          <span class="price">${fmtPrice(lv.price)}</span>
          <span class="size">${fmtK(lv.size)}</span>
        </div>
      `;
    }).join("") || `<div class="state-empty">Empty</div>`;
  }

  renderLevels(bids, bidsEl, "bid");
  renderLevels(asks, asksEl, "ask");
}

// ------------------------------------------------------------------ //
// Strategies Panel                                                      //
// ------------------------------------------------------------------ //
async function refreshStrategies() {
  try {
    const data = await apiFetch("/api/strategies/");
    State.strategies = data.kernels || {};
    renderStrategies();
  } catch (e) {
    addLog("ERROR", `Strategies fetch failed: ${e.message}`);
  }
}

async function loadAvailableKernels() {
  try {
    const data = await apiFetch("/api/strategies/available");
    const sel = $("#kernel-select");
    if (!sel) return;
    sel.innerHTML = data.kernels.map(k => `<option value="${escHtml(k)}">${escHtml(k)}</option>`).join("");
  } catch (e) {
    addLog("WARN", `Could not load kernel list: ${e.message}`);
  }
}

function renderStrategies() {
  const container = $("#strategies-list");
  if (!container) return;

  const kernels = Object.values(State.strategies);

  if (kernels.length === 0) {
    container.innerHTML = `<div class="state-empty">No kernels registered</div>`;
    return;
  }

  container.innerHTML = kernels.map(k => {
    const status = (k.status || "stopped");
    const extraMeta = buildKernelMeta(k);
    return `
      <div class="strategy-card ${status}" data-name="${escHtml(k.name)}">
        <div class="strategy-name">
          <span>${escHtml(k.name)}</span>
          ${statusBadge(status)}
        </div>
        <div class="strategy-meta">
          ${extraMeta}
        </div>
        <div class="strategy-actions">
          ${status === "running"
            ? `<button class="btn btn-red btn-sm" data-action="stop" data-name="${escHtml(k.name)}">STOP</button>`
            : `<button class="btn btn-green btn-sm" data-action="start-existing" data-name="${escHtml(k.name)}">START</button>`
          }
        </div>
      </div>
    `;
  }).join("");

  container.querySelectorAll("button[data-action]").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const action = btn.getAttribute("data-action");
      const name = btn.getAttribute("data-name");
      if (action === "stop") await stopKernel(name);
    });
  });
}

function buildKernelMeta(k) {
  const items = [];
  if (k.token_id) items.push(`<span class="strategy-meta-item"><span class="k">token </span>${escHtml(k.token_id.substring(0, 16))}…</span>`);
  if (k.cycle_count != null) items.push(`<span class="strategy-meta-item"><span class="k">cycles </span>${k.cycle_count}</span>`);
  if (k.signals_fired != null) items.push(`<span class="strategy-meta-item"><span class="k">signals </span>${k.signals_fired}</span>`);
  if (k.spread != null) items.push(`<span class="strategy-meta-item"><span class="k">spread </span>${fmt4(k.spread)}</span>`);
  if (k.strategy) items.push(`<span class="strategy-meta-item"><span class="k">strat </span>${escHtml(k.strategy)}</span>`);
  if (k.source_type) items.push(`<span class="strategy-meta-item"><span class="k">source </span>${escHtml(k.source_type)}</span>`);
  if (k.error) items.push(`<span class="strategy-meta-item text-red" style="grid-column:1/-1">${escHtml(k.error)}</span>`);
  return items.join("") || `<span class="strategy-meta-item text-muted">No details</span>`;
}

async function startKernel(name, params) {
  try {
    addLog("INFO", `Starting kernel: ${name}`);
    const result = await apiPost("/api/strategies/start", { name, params });
    addLog("INFO", `Kernel started: ${result.name}`);
    await refreshStrategies();
  } catch (e) {
    addLog("ERROR", `Failed to start kernel ${name}: ${e.message}`);
  }
}

async function stopKernel(name) {
  try {
    addLog("INFO", `Stopping kernel: ${name}`);
    const result = await apiPost(`/api/strategies/stop/${encodeURIComponent(name)}`, {});
    addLog("INFO", `Kernel stopped: ${result.name}`);
    await refreshStrategies();
  } catch (e) {
    addLog("ERROR", `Failed to stop kernel ${name}: ${e.message}`);
  }
}

// ------------------------------------------------------------------ //
// Portfolio Panel                                                       //
// ------------------------------------------------------------------ //
async function refreshPortfolio() {
  try {
    const [summary, pnl] = await Promise.all([
      apiFetch("/api/portfolio/"),
      apiFetch("/api/portfolio/pnl"),
    ]);
    State.portfolio = summary;
    State.pnl = pnl;
    renderPortfolio();
    renderPnlSummary();
  } catch (e) {
    addLog("ERROR", `Portfolio fetch failed: ${e.message}`);
  }
}

function renderPnlSummary() {
  const pnl = State.pnl;
  if (!pnl) return;

  const realEl = $("#pnl-realized");
  const unrEl  = $("#pnl-unrealized");
  const totEl  = $("#pnl-total");

  if (realEl) { realEl.textContent = `$${fmt4(pnl.realized)}`; realEl.className = `val ${pnlClass(pnl.realized)}`; }
  if (unrEl)  { unrEl.textContent  = `$${fmt4(pnl.unrealized)}`; unrEl.className = `val ${pnlClass(pnl.unrealized)}`; }
  if (totEl)  {
    totEl.textContent = `$${fmt4(pnl.total)}`;
    totEl.className = `val ${pnlClass(pnl.total)}`;
    flash(totEl, pnl.total >= 0 ? "flash-green" : "flash-red");
  }

  const tradeCount = $("#portfolio-trade-count");
  if (tradeCount && pnl.trade_count != null) tradeCount.textContent = pnl.trade_count;
}

function renderPortfolio() {
  const tbody = $("#tbl-portfolio tbody");
  if (!tbody) return;

  const positions = State.portfolio?.positions || {};
  const entries = Object.values(positions);

  if (entries.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="state-empty">No open positions</td></tr>`;
    return;
  }

  tbody.innerHTML = entries.map(p => {
    const pnlCls = pnlClass(p.unrealized_pnl);
    return `
      <tr>
        <td class="truncate mono" title="${escHtml(p.token_id)}">${escHtml(p.token_id.substring(0, 12))}…</td>
        <td>${sideBadge(p.side)}</td>
        <td class="num">${fmt4(p.avg_entry_price)}</td>
        <td class="num">${p.current_price != null ? fmt4(p.current_price) : "—"}</td>
        <td class="num">${fmtK(p.size)}</td>
        <td class="num ${pnlCls}">${p.unrealized_pnl != null ? fmt4(p.unrealized_pnl) : "—"}</td>
      </tr>
    `;
  }).join("");
}

// ------------------------------------------------------------------ //
// Orders Panel                                                          //
// ------------------------------------------------------------------ //
async function refreshOrders() {
  try {
    const orders = await apiFetch("/api/orders/?limit=50");
    State.orders = orders;
    renderOrders();
  } catch (e) {
    addLog("ERROR", `Orders fetch failed: ${e.message}`);
  }
}

function renderOrders() {
  const tbody = $("#tbl-orders tbody");
  if (!tbody) return;

  const orders = State.orders || [];
  if (orders.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="state-empty">No orders</td></tr>`;
    return;
  }

  tbody.innerHTML = orders.slice(0, 30).map(o => {
    return `
      <tr>
        <td class="mono truncate" title="${escHtml(o.id)}">${escHtml(o.id)}</td>
        <td>${sideBadge(o.side)}</td>
        <td class="num">${fmt4(o.price)}</td>
        <td class="num">${fmtK(o.size)}</td>
        <td>${orderStatusBadge(o.status)}</td>
        <td class="truncate text-secondary" title="${escHtml(o.kernel_name)}">${escHtml(o.kernel_name || "—")}</td>
      </tr>
    `;
  }).join("");
}

// ------------------------------------------------------------------ //
// Header: Health + Server Time                                          //
// ------------------------------------------------------------------ //
async function refreshHealth() {
  try {
    const health = await apiFetch("/api/markets/health");
    State.apiHealth = health;
    const clobEl = $("#header-clob-status");
    if (clobEl) {
      clobEl.textContent = health.clob ? "ONLINE" : "OFFLINE";
      clobEl.className = `val ${health.clob ? "text-green" : "text-red"}`;
    }
    if (health.server_time) {
      const stEl = $("#header-server-time");
      if (stEl) {
        const d = new Date(health.server_time * 1000);
        stEl.textContent = d.toUTCString().replace("GMT", "UTC");
      }
    }
  } catch { /* silently ignore */ }
}

// ------------------------------------------------------------------ //
// Start Kernel Form                                                     //
// ------------------------------------------------------------------ //
function bindStartForm() {
  const btn = $("#btn-start-kernel");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const sel = $("#kernel-select");
    const tokenInput = $("#kernel-token-id");
    const name = sel?.value;
    if (!name) return;
    const params = {};
    const tokenId = tokenInput?.value.trim();
    if (tokenId) params.token_id = tokenId;
    await startKernel(name, params);
  });
}

// ------------------------------------------------------------------ //
// Market tabs                                                           //
// ------------------------------------------------------------------ //
function bindMarketTabs() {
  $$(".markets-tab[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".markets-tab[data-tab]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      State.activeTab = btn.getAttribute("data-tab");
      refreshMarkets();
    });
  });
}

function bindSearchInput() {
  const inp = $("#markets-search");
  if (!inp) return;
  inp.addEventListener("input", () => renderMarkets());
}

// ------------------------------------------------------------------ //
// Clear log button                                                      //
// ------------------------------------------------------------------ //
function bindClearLog() {
  const btn = $("#btn-clear-log");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const container = $("#trade-log-entries");
    if (container) container.innerHTML = "";
  });
}

// ------------------------------------------------------------------ //
// Periodic refresh                                                      //
// ------------------------------------------------------------------ //
function startPolling() {
  if (State.refreshTimer) clearInterval(State.refreshTimer);
  State.refreshTimer = setInterval(async () => {
    await Promise.allSettled([
      refreshMarkets(),
      refreshStrategies(),
      refreshOrders(),
      refreshPortfolio(),
      refreshHealth(),
    ]);
    if (State.selectedMarket) refreshOrderBook();
  }, 5000);
}

// ------------------------------------------------------------------ //
// Initial load                                                          //
// ------------------------------------------------------------------ //
async function init() {
  addLog("INFO", "Polystation dashboard initializing…");

  // Wire up UI events
  bindMarketTabs();
  bindSearchInput();
  bindStartForm();
  bindClearLog();

  // First-load data fetches (in parallel)
  await Promise.allSettled([
    refreshMarkets(),
    refreshStrategies(),
    refreshOrders(),
    refreshPortfolio(),
    refreshHealth(),
    loadAvailableKernels(),
  ]);

  addLog("INFO", "Initial data loaded");

  // WebSocket for real-time pushes
  connectWS();

  // Polling fallback every 5 seconds
  startPolling();
}

/* ================================================================
   PANEL RESIZE — Drag handles between grid areas
   ================================================================ */

(function initResizeHandles() {

  const main = document.getElementById("main");
  const app  = document.getElementById("app");
  if (!main || !app) return;

  // Current sizes (pixels) — start from CSS defaults
  let colSizes = null;   // [col1, col2, col3] in px
  let rowSizes = null;   // [row1, row2] in px
  let logHeight = 180;   // trade log height in px

  function getComputedGridSizes() {
    const cols = getComputedStyle(main).gridTemplateColumns.split(/\s+/).map(parseFloat);
    const rows = getComputedStyle(main).gridTemplateRows.split(/\s+/).map(parseFloat);
    return { cols, rows };
  }

  function applyGridCols() {
    if (!colSizes) return;
    main.style.gridTemplateColumns = colSizes.map(s => s + "px").join(" ");
  }

  function applyGridRows() {
    if (!rowSizes) return;
    main.style.gridTemplateRows = rowSizes.map(s => s + "px").join(" ");
  }

  function applyLogHeight() {
    app.style.gridTemplateRows = `44px 1fr 5px ${logHeight}px`;
  }

  // Generic drag handler
  function startDrag(e, onMove, cursorClass) {
    e.preventDefault();
    const target = e.currentTarget;
    target.classList.add("active");
    document.body.classList.add(cursorClass);

    function move(ev) { onMove(ev); }
    function up() {
      target.classList.remove("active");
      document.body.classList.remove(cursorClass);
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    }

    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  }

  // --- Column gutters ---

  // Gutter between col 1 and col 2
  const gc1 = document.getElementById("gutter-col-1");
  if (gc1) {
    gc1.addEventListener("mousedown", function(e) {
      if (!colSizes) colSizes = getComputedGridSizes().cols;
      const startX = e.clientX;
      const startCol1 = colSizes[0];
      const startCol2 = colSizes[1];
      const total = startCol1 + startCol2;

      startDrag(e, function(ev) {
        const dx = ev.clientX - startX;
        const newCol1 = Math.max(200, Math.min(total - 200, startCol1 + dx));
        colSizes[0] = newCol1;
        colSizes[1] = total - newCol1;
        applyGridCols();
      }, "resizing");
    });
  }

  // Gutter between col 2 and col 3
  const gc2 = document.getElementById("gutter-col-2");
  if (gc2) {
    gc2.addEventListener("mousedown", function(e) {
      if (!colSizes) colSizes = getComputedGridSizes().cols;
      const startX = e.clientX;
      const startCol2 = colSizes[1];
      const startCol3 = colSizes[2];
      const total = startCol2 + startCol3;

      startDrag(e, function(ev) {
        const dx = ev.clientX - startX;
        const newCol2 = Math.max(200, Math.min(total - 180, startCol2 + dx));
        colSizes[1] = newCol2;
        colSizes[2] = total - newCol2;
        applyGridCols();
      }, "resizing");
    });
  }

  // --- Row gutters (within #main) ---

  // Gutter between row 1 and row 2 in middle column
  const grMid = document.getElementById("gutter-row-mid");
  if (grMid) {
    grMid.addEventListener("mousedown", function(e) {
      if (!rowSizes) rowSizes = getComputedGridSizes().rows;
      const startY = e.clientY;
      const startRow1 = rowSizes[0];
      const startRow2 = rowSizes[1];
      const total = startRow1 + startRow2;

      startDrag(e, function(ev) {
        const dy = ev.clientY - startY;
        const newRow1 = Math.max(100, Math.min(total - 100, startRow1 + dy));
        rowSizes[0] = newRow1;
        rowSizes[1] = total - newRow1;
        applyGridRows();
      }, "resizing-row");
    });
  }

  // Gutter between row 1 and row 2 in right column
  const grRight = document.getElementById("gutter-row-right");
  if (grRight) {
    grRight.addEventListener("mousedown", function(e) {
      if (!rowSizes) rowSizes = getComputedGridSizes().rows;
      const startY = e.clientY;
      const startRow1 = rowSizes[0];
      const startRow2 = rowSizes[1];
      const total = startRow1 + startRow2;

      startDrag(e, function(ev) {
        const dy = ev.clientY - startY;
        const newRow1 = Math.max(100, Math.min(total - 100, startRow1 + dy));
        rowSizes[0] = newRow1;
        rowSizes[1] = total - newRow1;
        applyGridRows();
      }, "resizing-row");
    });
  }

  // --- Bottom gutter (trade log height) ---

  const gBottom = document.getElementById("gutter-bottom");
  if (gBottom) {
    gBottom.addEventListener("mousedown", function(e) {
      const startY = e.clientY;
      const startHeight = logHeight;

      startDrag(e, function(ev) {
        const dy = ev.clientY - startY;
        logHeight = Math.max(60, Math.min(500, startHeight - dy));
        applyLogHeight();
      }, "resizing-row");
    });
  }

  // Recalculate on window resize
  window.addEventListener("resize", function() {
    colSizes = null;
    rowSizes = null;
  });

})();


// Boot when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
