/* ================================================================
   POLYSTATION — Dashboard Application
   ================================================================ */

"use strict";

// ------------------------------------------------------------------ //
// State                                                               //
// ------------------------------------------------------------------ //
const State = {
  markets:         [],     // MarketInfo[]
  marketsOffset:   0,      // pagination offset
  marketsHasMore:  true,   // more pages available
  marketsLoading:  false,  // currently loading
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
  // Performance tab
  perfSummary:     null,
  perfPnlHistory:  [],
  perfTrades:      [],
  perfKernels:     [],
  perfPnlChart:    null,   // Chart.js instance
  perfRefreshTimer: null,
  // Risk tab
  riskSummary:     null,
  riskPositions:   [],
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
async function apiFetch(path, options) {
  const resp = await fetch(path, options);
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
  if (msg.type === "subscribed_market" || msg.type === "unsubscribed_market") return;
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
  } else if (msg.type === "book_update") {
    // Live order book update pushed from the server
    const tokenId = msg.token_id;
    const mkt = State.selectedMarket;
    if (!mkt) return;
    const tokenIds = mkt.token_ids || [];
    const activeToken = tokenIds[State.selectedTokenIdx] || tokenIds[0];
    if (tokenId === activeToken && msg.data) {
      State.orderBook = msg.data;
      renderOrderBook(msg.data);
      if (msg.data.midpoint != null || msg.data.best_bid != null) {
        renderPriceSummary(msg.data);
      }
    }
  }
}

function setConnStatus(state) {
  const dot = $("#conn-dot");
  const lbl = $("#conn-label");
  dot.className = `${state === "connected" ? "connected" : state === "error" ? "error" : ""}`;
  lbl.textContent = state === "connected" ? "LIVE" : state === "error" ? "ERROR" : "OFFLINE";
}

// ------------------------------------------------------------------ //
// Log data store (single source of truth shared by both views)         //
// ------------------------------------------------------------------ //
const LogStore = {
  entries: [],  // Array of { time, level, msg, ts }
  maxEntries: 500,
};

// ------------------------------------------------------------------ //
// Trade Log                                                            //
// ------------------------------------------------------------------ //
function addLog(level, msg) {
  const now = new Date();
  const time = now.toLocaleTimeString("en-US", { hour12: false });

  const entry = { time, level, msg, ts: now.getTime() };
  LogStore.entries.unshift(entry);
  if (LogStore.entries.length > LogStore.maxEntries) {
    LogStore.entries.length = LogStore.maxEntries;
  }

  // Render into the trading tab's trade log panel
  const container = $("#trade-log-entries");
  if (container) {
    const el = document.createElement("div");
    el.className = "log-entry";
    el.innerHTML = `
      <span class="log-time">${escHtml(time)}</span>
      <span class="log-level ${escHtml(level)}">${escHtml(level)}</span>
      <span class="log-msg">${escHtml(msg)}</span>
    `;
    container.prepend(el);
    while (container.children.length > 200) {
      container.removeChild(container.lastChild);
    }
  }

  // Mirror into the full-screen logs tab viewer
  renderLogsTab();
}

// ------------------------------------------------------------------ //
// Logs Tab                                                             //
// ------------------------------------------------------------------ //
let logsActiveFilter = "ALL";

function renderLogsTab() {
  const container = $("#logs-entries");
  if (!container) return;

  const filtered = logsActiveFilter === "ALL"
    ? LogStore.entries
    : LogStore.entries.filter(e => e.level === logsActiveFilter);

  container.innerHTML = filtered.map(e => `
    <div class="log-entry">
      <span class="log-time">${escHtml(e.time)}</span>
      <span class="log-level ${escHtml(e.level)}">${escHtml(e.level)}</span>
      <span class="log-msg">${escHtml(e.msg)}</span>
    </div>
  `).join("");

  const badge = $("#logs-count-badge");
  if (badge) badge.textContent = `${filtered.length} entr${filtered.length === 1 ? "y" : "ies"}`;
}

function bindLogsTab() {
  // Filter buttons
  $$(".log-filter-btn[data-level]").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".log-filter-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      logsActiveFilter = btn.getAttribute("data-level");
      renderLogsTab();
    });
  });

  // Clear button
  const clearBtn = $("#btn-clear-logs-tab");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      LogStore.entries = [];
      renderLogsTab();
      // Also clear the trade panel log
      const container = $("#trade-log-entries");
      if (container) container.innerHTML = "";
    });
  }

  // Export button
  const exportBtn = $("#btn-export-logs");
  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const lines = LogStore.entries.map(e => `[${e.time}] [${e.level}] ${e.msg}`).join("\n");
      const blob = new Blob([lines], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `polystation-logs-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }
}

// ------------------------------------------------------------------ //
// Markets Panel                                                        //
// ------------------------------------------------------------------ //
let _marketsSeq = 0;

async function refreshMarkets(append = false) {
  // Use a sequence number so stale responses don't overwrite fresh ones
  const seq = ++_marketsSeq;
  try {
    const tab = State.activeTab;
    const searchQuery = ($("#markets-search")?.value || "").trim();

    if (tab === "trending") {
      const data = await apiFetch("/api/markets/trending?limit=50");
      if (seq !== _marketsSeq) return; // stale
      State.markets = data;
      State.marketsHasMore = false;
    } else if (searchQuery.length >= 2) {
      // Server-side search through events API
      const resp = await apiFetch(`/api/markets/search?q=${encodeURIComponent(searchQuery)}&limit=100`);
      if (seq !== _marketsSeq) return; // stale
      State.markets = resp.data || [];
      State.marketsHasMore = false;
      State.marketsOffset = 0;
    } else {
      const offset = append ? State.marketsOffset : 0;
      const resp = await apiFetch(`/api/markets/?offset=${offset}&limit=100`);
      if (seq !== _marketsSeq) return; // stale
      const newData = resp.data || [];
      if (append) {
        State.markets = State.markets.concat(newData);
      } else {
        State.markets = newData;
      }
      State.marketsOffset = (append ? offset : 0) + newData.length;
      State.marketsHasMore = resp.has_more || false;
    }
    renderMarkets();
    const cnt = $("#markets-count");
    if (cnt) cnt.textContent = `${State.markets.length}${State.marketsHasMore ? "+" : ""}`;
  } catch (e) {
    if (seq === _marketsSeq) addLog("ERROR", `Markets fetch failed: ${e.message}`);
  }
}

async function loadMoreMarkets() {
  await refreshMarkets(true);
}

function renderMarkets() {
  const tbody = $("#tbl-markets tbody");
  if (!tbody) return;

  // Markets are already filtered server-side when searching
  const markets = State.markets;

  if (markets.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="state-empty">No markets found</td></tr>`;
    return;
  }

  let html = markets.map(m => {
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

  // Add "Load More" button if there are more pages
  if (State.marketsHasMore) {
    html += `<tr id="load-more-row"><td colspan="5" style="text-align:center; padding:8px;">
      <button class="btn btn-green" onclick="loadMoreMarkets()" style="width:100%;">
        Load More Markets (${State.markets.length} loaded)
      </button>
    </td></tr>`;
  }

  tbody.innerHTML = html;

  tbody.querySelectorAll("tr[data-cid]").forEach(tr => {
    tr.addEventListener("click", () => {
      const cid = tr.getAttribute("data-cid");
      const mkt = State.markets.find(m => m.condition_id === cid);
      if (mkt) selectMarket(mkt);
    });
  });
}

function selectMarket(mkt) {
  // Unsubscribe from the previous market before switching
  const ws = State.ws;
  const prevMkt = State.selectedMarket;
  if (ws && ws.readyState === WebSocket.OPEN && prevMkt) {
    const prevTokenIds = prevMkt.token_ids || [];
    prevTokenIds.forEach(tid => {
      ws.send(JSON.stringify({ type: "unsubscribe_market", token_id: tid }));
    });
  }

  State.selectedMarket = mkt;
  State.selectedTokenIdx = 0;
  renderMarkets();
  renderSelectedMarketHeader();
  refreshOrderBook();

  // Subscribe to the new market's tokens
  if (ws && ws.readyState === WebSocket.OPEN && mkt) {
    const tokenIds = mkt.token_ids || [];
    tokenIds.forEach(tid => {
      ws.send(JSON.stringify({ type: "subscribe_market", token_id: tid }));
    });
  }
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

  // Auto-fill Quick Trade price from the midpoint when the field is empty
  if (price.midpoint != null) {
    const qtPriceEl = $("#qt-price");
    if (qtPriceEl && !qtPriceEl.value) {
      qtPriceEl.value = Number(price.midpoint).toFixed(4);
    }
  }
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
    let tokenId = tokenInput?.value.trim();

    // Auto-fill from selected market if token_id is empty
    if (!tokenId && State.selectedMarket && State.selectedMarket.token_ids?.length) {
      tokenId = State.selectedMarket.token_ids[State.selectedTokenIdx || 0];
      if (tokenInput) tokenInput.value = tokenId;
    }

    if (name === "market-maker" || name === "signal") {
      if (!tokenId) {
        addLog("WARN", "Select a market first or enter a token_id");
        return;
      }
      params.token_id = tokenId;
    }

    if (name === "voice") {
      // Voice kernel needs source_type; URL is optional
      params.source_type = "youtube";
      if (tokenId) params.url = tokenId; // reuse field for URL
    }

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
  let debounceTimer = null;
  inp.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const val = inp.value.trim();
    if (val.length >= 2) {
      // Debounce server-side search
      debounceTimer = setTimeout(() => refreshMarkets(false), 400);
    } else if (val.length === 0) {
      // Reset to default paginated view
      debounceTimer = setTimeout(() => refreshMarkets(false), 200);
    }
    // For 1 char, do nothing (wait for more input)
  });
}

// ------------------------------------------------------------------ //
// Clear log button (trading tab panel)                                 //
// ------------------------------------------------------------------ //
function bindClearLog() {
  const btn = $("#btn-clear-log");
  if (!btn) return;
  btn.addEventListener("click", () => {
    LogStore.entries = [];
    const container = $("#trade-log-entries");
    if (container) container.innerHTML = "";
    renderLogsTab();
  });
}

// ------------------------------------------------------------------ //
// Performance Tab                                                       //
// ------------------------------------------------------------------ //
async function refreshPerformance() {
  try {
    const [summary, history, trades, kernels] = await Promise.allSettled([
      apiFetch("/api/performance/summary"),
      apiFetch("/api/performance/pnl-history"),
      apiFetch("/api/performance/trades"),
      apiFetch("/api/performance/kernels"),
    ]);

    if (summary.status === "fulfilled") {
      State.perfSummary = summary.value;
      renderPerfSummary(summary.value);
    }
    if (history.status === "fulfilled") {
      State.perfPnlHistory = history.value;
      renderPnlChart(history.value);
    }
    if (trades.status === "fulfilled") {
      State.perfTrades = trades.value;
      renderTradeHistory(trades.value);
    }
    if (kernels.status === "fulfilled") {
      State.perfKernels = kernels.value;
      renderKernelPerformance(kernels.value);
    }
  } catch (e) {
    addLog("ERROR", `Performance fetch failed: ${e.message}`);
  }
}

function renderPerfSummary(s) {
  if (!s) return;

  const totalPnlEl = $("#perf-total-pnl");
  if (totalPnlEl) {
    const v = Number(s.total_pnl || 0);
    totalPnlEl.textContent = `$${fmt4(v)}`;
    totalPnlEl.className = `val ${pnlClass(v)}`;
  }

  const winRateEl = $("#perf-win-rate");
  if (winRateEl) {
    const wr = s.win_rate != null ? (Number(s.win_rate) * 100).toFixed(1) + "%" : "—";
    winRateEl.textContent = wr;
    const numWr = Number(s.win_rate || 0);
    winRateEl.className = `val ${numWr >= 0.5 ? "pos" : numWr > 0 ? "neu" : "neg"}`;
  }

  const totalTradesEl = $("#perf-total-trades");
  if (totalTradesEl) totalTradesEl.textContent = s.total_trades != null ? String(s.total_trades) : "—";

  const totalVolEl = $("#perf-total-volume");
  if (totalVolEl) totalVolEl.textContent = s.total_volume != null ? `$${fmtK(s.total_volume)}` : "—";

  const kernelCountEl = $("#perf-kernel-count");
  if (kernelCountEl) kernelCountEl.textContent = s.kernel_count != null ? String(s.kernel_count) : "—";
}

function renderPnlChart(data) {
  const canvas = $("#perf-pnl-chart");
  if (!canvas) return;
  if (!data || data.length === 0) return;

  // Destroy existing chart instance to avoid canvas reuse errors
  if (State.perfPnlChart) {
    State.perfPnlChart.destroy();
    State.perfPnlChart = null;
  }

  const labels = data.map(d => {
    try {
      const dt = new Date(d.ts);
      return dt.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" });
    } catch { return d.ts || ""; }
  });

  const realizedData   = data.map(d => d.realized   != null ? Number(d.realized)   : null);
  const unrealizedData = data.map(d => d.unrealized  != null ? Number(d.unrealized) : null);
  const totalData      = data.map(d => d.total       != null ? Number(d.total)      : null);

  const gridColor  = "rgba(30, 30, 53, 0.8)";
  const labelColor = "#6666aa";

  State.perfPnlChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Realized",
          data: realizedData,
          borderColor: "#00ff88",
          backgroundColor: "rgba(0, 255, 136, 0.05)",
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 3,
          tension: 0.3,
          fill: false,
          spanGaps: true,
        },
        {
          label: "Unrealized",
          data: unrealizedData,
          borderColor: "#ffcc00",
          backgroundColor: "rgba(255, 204, 0, 0.05)",
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 3,
          tension: 0.3,
          fill: false,
          spanGaps: true,
        },
        {
          label: "Total",
          data: totalData,
          borderColor: "#00ccff",
          backgroundColor: "rgba(0, 204, 255, 0.08)",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.3,
          fill: false,
          spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: {
            color: labelColor,
            font: { family: "'JetBrains Mono', monospace", size: 10 },
            boxWidth: 12,
            padding: 16,
          },
        },
        tooltip: {
          backgroundColor: "#13131f",
          borderColor: "#2a2a4a",
          borderWidth: 1,
          titleColor: "#8888aa",
          bodyColor: "#e8e8f0",
          titleFont: { family: "'JetBrains Mono', monospace", size: 10 },
          bodyFont:  { family: "'JetBrains Mono', monospace", size: 11 },
          callbacks: {
            label: (ctx) => ` ${ctx.dataset.label}: $${fmt4(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: labelColor,
            font: { family: "'JetBrains Mono', monospace", size: 9 },
            maxTicksLimit: 12,
            maxRotation: 0,
          },
          grid: { color: gridColor },
          border: { color: "#1e1e35" },
        },
        y: {
          ticks: {
            color: labelColor,
            font: { family: "'JetBrains Mono', monospace", size: 9 },
            callback: (v) => `$${fmt2(v)}`,
          },
          grid: { color: gridColor },
          border: { color: "#1e1e35" },
        },
      },
    },
  });
}

function renderTradeHistory(trades) {
  const tbody = document.querySelector("#tbl-perf-trades tbody");
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="state-empty">No trades recorded</div></td></tr>`;
    return;
  }

  tbody.innerHTML = trades.slice(0, 200).map(t => {
    const pnlCls = pnlClass(t.pnl);
    const slipCls = t.slippage != null && Number(t.slippage) < 0 ? "text-red" : "text-secondary";
    return `
      <tr>
        <td class="text-secondary">${escHtml(fmtTs(t.timestamp))}</td>
        <td class="truncate text-secondary" title="${escHtml(t.kernel_name)}">${escHtml(t.kernel_name || "—")}</td>
        <td>${sideBadge(t.side)}</td>
        <td class="num">${fmt4(t.price)}</td>
        <td class="num">${fmtK(t.size)}</td>
        <td class="num ${pnlCls}">${t.pnl != null ? `$${fmt4(t.pnl)}` : "—"}</td>
        <td class="num ${slipCls}">${t.slippage != null ? fmt4(t.slippage) : "—"}</td>
      </tr>
    `;
  }).join("");
}

function renderKernelPerformance(kernels) {
  const container = $("#perf-kernel-cards");
  if (!container) return;

  if (!kernels || kernels.length === 0) {
    container.innerHTML = `<div class="state-empty">No kernel data</div>`;
    return;
  }

  container.innerHTML = kernels.map(k => {
    const pnlVal  = Number(k.total_pnl || 0);
    const cardCls = pnlVal > 0 ? "profitable" : pnlVal < 0 ? "losing" : "neutral";
    const pnlCls  = pnlClass(pnlVal);
    const wr      = k.win_rate != null ? (Number(k.win_rate) * 100).toFixed(1) + "%" : "—";
    return `
      <div class="kernel-perf-card ${cardCls}">
        <div class="kernel-perf-name">
          <span>${escHtml(k.name)}</span>
          <span class="kernel-perf-pnl ${pnlCls}">$${fmt4(pnlVal)}</span>
        </div>
        <div class="kernel-perf-grid">
          <span class="kernel-perf-item"><span class="k">trades </span>${k.trade_count != null ? k.trade_count : "—"}</span>
          <span class="kernel-perf-item"><span class="k">win rate </span>${wr}</span>
          <span class="kernel-perf-item"><span class="k">wins </span>${k.win_count != null ? k.win_count : "—"}</span>
          <span class="kernel-perf-item"><span class="k">losses </span>${k.loss_count != null ? k.loss_count : "—"}</span>
          <span class="kernel-perf-item"><span class="k">volume </span>$${fmtK(k.total_volume)}</span>
          <span class="kernel-perf-item"><span class="k">avg slip </span>${k.avg_slippage != null ? fmt4(k.avg_slippage) : "—"}</span>
        </div>
        <hr class="kernel-perf-divider" />
        <div class="kernel-perf-extremes">
          <span class="kernel-perf-extreme text-green"><span class="k">best  </span>${k.best_trade != null ? `$${fmt4(k.best_trade)}` : "—"}</span>
          <span class="kernel-perf-extreme text-red"><span class="k">worst </span>${k.worst_trade != null ? `$${fmt4(k.worst_trade)}` : "—"}</span>
        </div>
      </div>
    `;
  }).join("");
}

// ------------------------------------------------------------------ //
// Risk Tab                                                             //
// ------------------------------------------------------------------ //
async function refreshRisk() {
  try {
    const [summary, positions] = await Promise.allSettled([
      apiFetch("/api/risk/summary"),
      apiFetch("/api/risk/positions"),
    ]);

    if (summary.status === "fulfilled") {
      State.riskSummary = summary.value;
      renderRiskSummary(summary.value);
    }
    if (positions.status === "fulfilled") {
      State.riskPositions = positions.value;
      renderRiskPositions(positions.value);
    }
  } catch (e) {
    addLog("ERROR", `Risk fetch failed: ${e.message}`);
  }
}

function renderRiskSummary(s) {
  if (!s) return;

  const grossEl = $("#risk-gross-exposure");
  if (grossEl) grossEl.textContent = s.gross_exposure != null ? `$${fmtK(s.gross_exposure)}` : "—";

  const posCountEl = $("#risk-position-count");
  if (posCountEl) posCountEl.textContent = s.position_count != null ? String(s.position_count) : "—";

  const unrEl = $("#risk-unrealized-pnl");
  if (unrEl) {
    const v = Number(s.unrealized_pnl || 0);
    unrEl.textContent = `$${fmt4(v)}`;
    unrEl.className = `val ${pnlClass(v)}`;
  }

  const largestEl = $("#risk-largest-position");
  if (largestEl) {
    if (s.largest_position && s.largest_position.token_id) {
      const lp = s.largest_position;
      largestEl.textContent = `${lp.token_id.substring(0, 12)}… $${fmtK(Math.abs(lp.unrealized_pnl || lp.cost_basis || 0))}`;
    } else {
      largestEl.textContent = "—";
    }
  }

  // P&L breakdown cells
  const realEl = $("#risk-realized-pnl");
  if (realEl) {
    const v = Number(s.realized_pnl || 0);
    realEl.textContent = `$${fmt4(v)}`;
    realEl.className = `val ${pnlClass(v)}`;
  }

  const unrEl2 = $("#risk-unrealized-pnl-2");
  if (unrEl2) {
    const v = Number(s.unrealized_pnl || 0);
    unrEl2.textContent = `$${fmt4(v)}`;
    unrEl2.className = `val ${pnlClass(v)}`;
  }

  const totalEl = $("#risk-total-pnl");
  if (totalEl) {
    const v = Number(s.total_pnl || 0);
    totalEl.textContent = `$${fmt4(v)}`;
    totalEl.className = `val ${pnlClass(v)}`;
  }

  const tradeCountEl = $("#risk-trade-count");
  if (tradeCountEl) tradeCountEl.textContent = s.trade_count != null ? String(s.trade_count) : "—";
}

function renderRiskPositions(positions) {
  const tbody = document.querySelector("#tbl-risk-positions tbody");
  if (!tbody) return;

  if (!positions || positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10"><div class="state-empty">No open positions</div></td></tr>`;
    return;
  }

  // Find max weight for bar scaling
  const maxWeight = Math.max(...positions.map(p => Math.abs(Number(p.weight || 0))), 0.0001);

  tbody.innerHTML = positions.map(p => {
    const pnlCls   = pnlClass(p.unrealized_pnl);
    const weight   = p.weight != null ? Number(p.weight) : 0;
    const weightPct = (weight * 100).toFixed(1);
    const barWidth  = Math.min(100, (Math.abs(weight) / maxWeight) * 100).toFixed(1);
    const barColor  = weight >= 0 ? "var(--cyan)" : "var(--yellow)";
    const tokenShort = p.token_id ? p.token_id.substring(0, 12) + "…" : "—";
    const marketShort = p.market_id ? p.market_id.substring(0, 10) + "…" : "—";
    return `
      <tr>
        <td class="mono truncate" title="${escHtml(p.token_id)}">${escHtml(tokenShort)}</td>
        <td class="truncate text-secondary" title="${escHtml(p.market_id)}">${escHtml(marketShort)}</td>
        <td>${sideBadge(p.side)}</td>
        <td class="num">${fmtK(p.size)}</td>
        <td class="num">${fmt4(p.avg_entry_price)}</td>
        <td class="num">${p.current_price != null ? fmt4(p.current_price) : "—"}</td>
        <td class="num text-secondary">$${fmt4(p.cost_basis)}</td>
        <td class="num text-secondary">$${fmt4(p.market_value)}</td>
        <td class="num ${pnlCls}">${p.unrealized_pnl != null ? `$${fmt4(p.unrealized_pnl)}` : "—"}</td>
        <td class="num">
          <div class="weight-cell">
            <span>${weightPct}%</span>
            <div class="weight-bar-wrap">
              <div class="weight-bar" style="width:${barWidth}%; background:${barColor};"></div>
            </div>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

// ------------------------------------------------------------------ //
// Navigation tabs                                                       //
// ------------------------------------------------------------------ //
function bindNavTabs() {
  document.querySelectorAll(".nav-tab[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => {
      // Deactivate all tabs
      document.querySelectorAll(".nav-tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");

      // Hide all tab content (class-driven, no inline styles)
      document.querySelectorAll(".tab-content").forEach(t => {
        t.classList.remove("active");
        t.removeAttribute("style"); // clear any leftover inline display
      });

      // Show the selected tab
      const tab = document.getElementById(`tab-${btn.dataset.tab}`);
      if (tab) {
        tab.classList.add("active");
        if (btn.dataset.tab === "logs")        renderLogsTab();
        if (btn.dataset.tab === "settings")    loadSettingsFromStorage();
        if (btn.dataset.tab === "performance") {
          refreshPerformance();
          startPerfPolling();
        }
        if (btn.dataset.tab === "risk")        refreshRisk();
        if (btn.dataset.tab === "backtest") {
          // Auto-fill token_id from the currently selected market
          if (State.selectedMarket && State.selectedMarket.token_ids?.length) {
            const btInput = document.getElementById("bt-token-id");
            if (btInput && !btInput.value) {
              btInput.value = State.selectedMarket.token_ids[State.selectedTokenIdx || 0];
            }
          }
        }
      }

      // Stop performance polling when leaving the performance tab
      if (btn.dataset.tab !== "performance") stopPerfPolling();
    });
  });
}

function startPerfPolling() {
  stopPerfPolling();
  State.perfRefreshTimer = setInterval(() => {
    // Only refresh if the performance tab is still active
    const perfTab = document.getElementById("tab-performance");
    if (perfTab && perfTab.classList.contains("active")) {
      refreshPerformance();
    } else {
      stopPerfPolling();
    }
  }, 5000);
}

function stopPerfPolling() {
  if (State.perfRefreshTimer) {
    clearInterval(State.perfRefreshTimer);
    State.perfRefreshTimer = null;
  }
}

// ------------------------------------------------------------------ //
// Settings tab                                                          //
// ------------------------------------------------------------------ //
const SETTINGS_KEY = "polystation_settings";

function loadSettingsFromStorage() {
  const raw = localStorage.getItem(SETTINGS_KEY);
  if (!raw) return;
  try {
    const saved = JSON.parse(raw);
    if (saved.host)            { const el = $("#s-host");            if (el) el.value = saved.host; }
    if (saved.pbk)             { const el = $("#s-pbk");             if (el) el.value = saved.pbk; }
    if (saved.clobApiKey)      { const el = $("#s-clob-api-key");    if (el) el.value = saved.clobApiKey; }
    if (saved.maxDailyVol != null) { const el = $("#s-max-daily-vol"); if (el) el.value = saved.maxDailyVol; }
    if (saved.preventDupes != null) {
      const el = $("#s-prevent-dupes");
      if (el) el.checked = saved.preventDupes;
    }
    if (saved.dryRun != null) {
      const el = $("#s-dry-run");
      if (el) el.checked = saved.dryRun;
    }
    if (saved.refreshInterval != null) {
      const el = $("#s-refresh-interval");
      if (el) el.value = saved.refreshInterval;
    }
    if (saved.marketPageSize != null) {
      const el = $("#s-market-page-size");
      if (el) el.value = saved.marketPageSize;
    }
  } catch { /* ignore corrupt storage */ }
}

function showStatus(el, message, isError) {
  if (!el) return;
  el.textContent = message;
  el.className = `settings-status ${isError ? "error" : "visible"}`;
  if (!isError) {
    setTimeout(() => { el.className = "settings-status"; }, 2500);
  }
}

function bindSettingsTab() {
  // Save Credentials — send to server to initialize trading client
  const saveCredsBtn = $("#btn-save-credentials");
  if (saveCredsBtn) {
    saveCredsBtn.addEventListener("click", async () => {
      const statusEl = $("#credentials-save-status");
      const payload = {
        host:            ($("#s-host")?.value || "https://clob.polymarket.com").trim(),
        pk:              ($("#s-pk")?.value || "").trim(),
        pbk:             ($("#s-pbk")?.value || "").trim(),
        clob_api_key:    ($("#s-clob-api-key")?.value || "").trim(),
        clob_secret:     ($("#s-clob-secret")?.value || "").trim(),
        clob_pass_phrase:($("#s-clob-passphrase")?.value || "").trim(),
      };

      // Save non-secret fields to localStorage
      const raw = localStorage.getItem(SETTINGS_KEY);
      const existing = raw ? JSON.parse(raw) : {};
      existing.host = payload.host;
      existing.pbk = payload.pbk;
      existing.clobApiKey = payload.clob_api_key;
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(existing));

      // Send to server to initialize the live trading client
      if (payload.pk || payload.clob_api_key) {
        try {
          const resp = await apiFetch("/api/config/credentials", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
          });
          if (resp.status === "ok") {
            showStatus(statusEl, "Credentials saved — live trading enabled", false);
            addLog("INFO", "Trading credentials configured — dry run OFF");
          } else {
            showStatus(statusEl, `Error: ${resp.error}`, true);
          }
        } catch (e) {
          showStatus(statusEl, `Server error: ${e.message}`, true);
        }
      } else {
        showStatus(statusEl, "Saved locally (no keys provided for live trading)", false);
      }
    });
  }

  // Save Trading settings
  const saveTradingBtn = $("#btn-save-trading");
  if (saveTradingBtn) {
    saveTradingBtn.addEventListener("click", async () => {
      const statusEl = $("#trading-save-status");
      const dryRunEl = $("#s-dry-run");
      const maxVolEl = $("#s-max-daily-vol");
      const prevDupesEl = $("#s-prevent-dupes");

      const dryRun = dryRunEl ? dryRunEl.checked : true;

      // Call backend to update dry-run mode
      try {
        await apiPost(`/api/config/dry-run?enabled=${dryRun}`, {});
        const badge = $("#dry-run-badge");
        if (badge) badge.style.display = dryRun ? "" : "none";
        addLog("INFO", `Dry run mode set to: ${dryRun}`);
      } catch (e) {
        showStatus(statusEl, `API error: ${e.message}`, true);
        return;
      }

      const raw = localStorage.getItem(SETTINGS_KEY);
      const existing = raw ? JSON.parse(raw) : {};
      const updated = {
        ...existing,
        dryRun,
        maxDailyVol:  maxVolEl ? (Number(maxVolEl.value) || 0) : 0,
        preventDupes: prevDupesEl ? prevDupesEl.checked : false,
      };
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(updated));
      showStatus(statusEl, "Settings saved", false);
    });
  }

  // Save Dashboard settings
  const saveDashBtn = $("#btn-save-dashboard");
  if (saveDashBtn) {
    saveDashBtn.addEventListener("click", () => {
      const statusEl = $("#dashboard-save-status");
      const intervalEl = $("#s-refresh-interval");
      const pageSizeEl = $("#s-market-page-size");

      const refreshInterval = intervalEl ? (parseInt(intervalEl.value, 10) || 5) : 5;
      const marketPageSize  = pageSizeEl ? (parseInt(pageSizeEl.value, 10) || 100) : 100;

      const raw = localStorage.getItem(SETTINGS_KEY);
      const existing = raw ? JSON.parse(raw) : {};
      const updated = { ...existing, refreshInterval, marketPageSize };
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(updated));

      // Apply refresh interval immediately
      startPolling(refreshInterval);

      showStatus(statusEl, "Settings saved", false);
    });
  }

  // Sync dry-run state from server on tab load
  syncDryRunFromServer();
}

async function syncDryRunFromServer() {
  try {
    const data = await apiFetch("/api/config/dry-run");
    const el = $("#s-dry-run");
    if (el) el.checked = data.dry_run;
    const badge = $("#dry-run-badge");
    if (badge) badge.style.display = data.dry_run ? "" : "none";
  } catch { /* server may not have this endpoint yet; ignore */ }
}

// ------------------------------------------------------------------ //
// Periodic refresh                                                      //
// ------------------------------------------------------------------ //
function startPolling(intervalSec) {
  const ms = ((intervalSec && intervalSec > 0) ? intervalSec : 5) * 1000;
  if (State.refreshTimer) clearInterval(State.refreshTimer);
  State.refreshTimer = setInterval(async () => {
    // Skip market refresh if user has a search active (don't overwrite results)
    const searchActive = ($("#markets-search")?.value || "").trim().length >= 2;
    const fetches = [
      refreshStrategies(),
      refreshOrders(),
      refreshPortfolio(),
      refreshHealth(),
    ];
    if (!searchActive) fetches.push(refreshMarkets());
    await Promise.allSettled(fetches);
    if (State.selectedMarket) refreshOrderBook();
  }, ms);
}

// ------------------------------------------------------------------ //
// Quick Trade                                                           //
// ------------------------------------------------------------------ //
function bindQuickTrade() {
  const buyBtn = document.getElementById("qt-buy");
  const sellBtn = document.getElementById("qt-sell");
  if (!buyBtn || !sellBtn) return;

  async function quickTrade(side) {
    const tokenId = State.selectedMarket?.token_ids?.[State.selectedTokenIdx || 0];
    if (!tokenId) { addLog("WARN", "Select a market first"); return; }
    const price = parseFloat(document.getElementById("qt-price")?.value);
    const size = parseFloat(document.getElementById("qt-size")?.value || "50");
    if (!price || price <= 0) { addLog("WARN", "Enter a valid price"); return; }

    try {
      const result = await apiFetch("/api/orders/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token_id: tokenId, side, price, size }),
      });
      addLog("TRADE", `${side} ${size} @ ${price.toFixed(4)} → ${result.order?.status || "?"}`);
      refreshOrders();
      refreshPortfolio();
    } catch (e) {
      addLog("ERROR", `Trade failed: ${e.message}`);
    }
  }

  buyBtn.addEventListener("click", () => quickTrade("BUY"));
  sellBtn.addEventListener("click", () => quickTrade("SELL"));
}

// ------------------------------------------------------------------ //
// Backtest Tab                                                          //
// ------------------------------------------------------------------ //
function bindBacktestTab() {
  const btn = document.getElementById("btn-run-backtest");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    const tokenId = document.getElementById("bt-token-id")?.value.trim();
    const pricesRaw = document.getElementById("bt-prices")?.value.trim();
    const balance = parseFloat(document.getElementById("bt-balance")?.value || "10000");
    const kernel = document.getElementById("bt-kernel")?.value || "signal";
    const statusEl = document.getElementById("bt-status");

    if (!tokenId || !pricesRaw) {
      if (statusEl) { statusEl.textContent = "Token ID and prices required"; statusEl.classList.add("visible", "error"); }
      return;
    }

    const prices = pricesRaw.split(",").map(s => parseFloat(s.trim())).filter(n => !isNaN(n));
    if (prices.length < 5) {
      if (statusEl) { statusEl.textContent = "Need at least 5 prices"; statusEl.classList.add("visible", "error"); }
      return;
    }

    const strategy = kernel === "signal-mr" ? "mean_reversion" : "momentum";

    btn.disabled = true;
    btn.textContent = "Running...";
    if (statusEl) { statusEl.textContent = ""; statusEl.classList.remove("visible", "error"); }

    try {
      const result = await apiFetch("/api/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kernel_type: "signal",
          strategy,
          token_id: tokenId,
          prices,
          start_balance: balance,
        }),
      });

      document.getElementById("bt-results").style.display = "block";

      // Render stats
      const pnlEl = document.getElementById("bt-pnl");
      if (pnlEl) {
        pnlEl.textContent = `$${result.total_pnl.toFixed(2)}`;
        pnlEl.className = `val ${result.total_pnl > 0 ? "pos" : result.total_pnl < 0 ? "neg" : "neu"}`;
      }
      const wrEl = document.getElementById("bt-winrate");
      if (wrEl) wrEl.textContent = `${(result.win_rate * 100).toFixed(1)}%`;
      const trEl = document.getElementById("bt-trades");
      if (trEl) trEl.textContent = result.total_trades;
      const ddEl = document.getElementById("bt-drawdown");
      if (ddEl) ddEl.textContent = `$${result.max_drawdown.toFixed(2)}`;
      const shEl = document.getElementById("bt-sharpe");
      if (shEl) shEl.textContent = result.sharpe_ratio.toFixed(2);

      // Render P&L chart
      if (result.pnl_curve && result.pnl_curve.length > 0 && typeof Chart !== "undefined") {
        const canvas = document.getElementById("bt-pnl-chart");
        if (canvas) {
          const ctx = canvas.getContext("2d");
          if (window._btChart) window._btChart.destroy();
          window._btChart = new Chart(ctx, {
            type: "line",
            data: {
              labels: result.pnl_curve.map((_, i) => i),
              datasets: [{
                label: "P&L",
                data: result.pnl_curve,
                borderColor: result.total_pnl >= 0 ? "#00ff88" : "#ff4444",
                backgroundColor: result.total_pnl >= 0 ? "rgba(0,255,136,0.1)" : "rgba(255,68,68,0.1)",
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 2,
              }],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                x: { display: false },
                y: {
                  grid: { color: "rgba(30,30,53,0.5)" },
                  ticks: { color: "#8888aa", font: { family: "'JetBrains Mono'" } },
                },
              },
            },
          });
        }
      }

      addLog("INFO", `Backtest complete: ${result.summary}`);
    } catch (e) {
      if (statusEl) { statusEl.textContent = `Error: ${e.message}`; statusEl.classList.add("visible", "error"); }
    } finally {
      btn.disabled = false;
      btn.textContent = "Run Backtest";
    }
  });
}

// ------------------------------------------------------------------ //
// Initial load                                                          //
// ------------------------------------------------------------------ //
async function init() {
  addLog("INFO", "Polystation dashboard initializing…");

  // Wire up UI events
  bindNavTabs();
  bindMarketTabs();
  bindSearchInput();
  bindStartForm();
  bindClearLog();
  bindLogsTab();
  bindSettingsTab();
  bindQuickTrade();
  bindBacktestTab();

  // Load persisted settings
  loadSettingsFromStorage();

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

  // Polling fallback — use saved interval if available
  const raw = localStorage.getItem(SETTINGS_KEY);
  const savedInterval = raw ? (JSON.parse(raw).refreshInterval || 5) : 5;
  startPolling(savedInterval);
}

/* ================================================================
   PRICE HISTORY CHART — Modal overlay for market price graphs
   ================================================================ */

let _priceChart = null;
let _chartTokenId = null;

function showPriceChart() {
  const tokenId = State.selectedMarket?.token_ids?.[State.selectedTokenIdx || 0];
  if (!tokenId) { addLog("WARN", "Select a market first to view price history"); return; }
  _chartTokenId = tokenId;

  const modal = document.getElementById("chart-modal");
  if (modal) modal.style.display = "flex";

  const title = document.getElementById("chart-modal-title");
  if (title) title.textContent = (State.selectedMarket?.question || "Price History").substring(0, 80);

  loadPriceHistory("max");
}

function closeChartModal() {
  const modal = document.getElementById("chart-modal");
  if (modal) modal.style.display = "none";
  if (_priceChart) { _priceChart.destroy(); _priceChart = null; }
}

// Close on Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeChartModal();
});

// Close on clicking backdrop
document.getElementById("chart-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "chart-modal") closeChartModal();
});

async function loadPriceHistory(interval) {
  if (!_chartTokenId) return;

  const fidelity = { "1d": 5, "1w": 30, "1m": 60, "max": 120 }[interval] || 120;

  try {
    const resp = await apiFetch(`/api/markets/history/${_chartTokenId}?interval=${interval}&fidelity=${fidelity}`);
    const history = resp.history || [];

    const pointsEl = document.getElementById("chart-points");
    if (pointsEl) pointsEl.textContent = `${history.length} data points`;

    if (history.length > 0) {
      const rangeEl = document.getElementById("chart-range");
      const firstDate = new Date(history[0].t * 1000).toLocaleDateString();
      const lastDate = new Date(history[history.length - 1].t * 1000).toLocaleDateString();
      if (rangeEl) rangeEl.textContent = `${firstDate} — ${lastDate}`;
    }

    renderPriceHistoryChart(history, interval);
  } catch (e) {
    addLog("ERROR", `Price history failed: ${e.message}`);
  }
}

function renderPriceHistoryChart(history, interval) {
  if (!history.length || typeof Chart === "undefined") return;

  const canvas = document.getElementById("price-history-chart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  if (_priceChart) _priceChart.destroy();

  const labels = history.map(h => {
    const d = new Date(h.t * 1000);
    return interval === "1d"
      ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString([], { month: "short", day: "numeric" });
  });
  const prices = history.map(h => h.p);
  const firstPrice = prices[0];
  const lastPrice = prices[prices.length - 1];
  const isUp = lastPrice >= firstPrice;

  _priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Price",
        data: prices,
        borderColor: isUp ? "#00ff88" : "#ff4444",
        backgroundColor: isUp ? "rgba(0,255,136,0.08)" : "rgba(255,68,68,0.08)",
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        pointHitRadius: 8,
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "rgba(15,15,26,0.95)",
          titleColor: "#8888aa",
          bodyColor: "#e8e8f0",
          borderColor: "#2a2a4a",
          borderWidth: 1,
          titleFont: { family: "'JetBrains Mono'" },
          bodyFont: { family: "'JetBrains Mono'" },
          callbacks: {
            label: (ctx) => `$${ctx.parsed.y.toFixed(4)}`,
          }
        }
      },
      scales: {
        x: {
          grid: { color: "rgba(30,30,53,0.5)" },
          ticks: { color: "#6666aa", font: { family: "'JetBrains Mono'", size: 10 }, maxTicksLimit: 12 },
        },
        y: {
          grid: { color: "rgba(30,30,53,0.5)" },
          ticks: {
            color: "#8888aa",
            font: { family: "'JetBrains Mono'", size: 10 },
            callback: (v) => `$${v.toFixed(2)}`,
          },
        }
      }
    }
  });
}


/* ================================================================
   PANEL RESIZE — Drag handles between grid areas
   ================================================================ */

(function initResizeHandles() {

  const main = document.getElementById("main");
  if (!main) return;

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
    const tradingTab = document.getElementById("tab-trading");
    if (tradingTab) tradingTab.style.gridTemplateRows = `1fr 5px ${logHeight}px`;
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
