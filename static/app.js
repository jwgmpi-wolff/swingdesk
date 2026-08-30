"use strict";

const state = { csrf: "", data: null, liveTrading: false, selectedTicker: "", tab: "overview" };
const byId = (id) => document.getElementById(id);
const money = (value, currency = "USD") => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "--";
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: parsed < 1 ? 4 : 2 }).format(parsed);
};
const quantity = (value, digits = 6) => Number(value || 0).toLocaleString("en-US", { maximumFractionDigits: digits });
const dateTime = (value) => value ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "--";
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (state.csrf) headers["X-CSRF-Token"] = state.csrf;
  let response;
  try {
    response = await fetch(path, { ...options, headers, signal: options.signal || AbortSignal.timeout(15000) });
  } catch (error) {
    throw new Error("Cannot reach Swingdesk. Start the Windows dashboard server and try again.");
  }
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) showLogin();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function showLogin() {
  state.csrf = "";
  byId("app-shell").hidden = true;
  byId("login-shell").hidden = false;
  byId("password").focus();
}

function showApp() {
  byId("login-shell").hidden = true;
  byId("app-shell").hidden = false;
}

function notify(message, success = false) {
  const alert = byId("alert");
  alert.textContent = message;
  alert.classList.toggle("success", success);
  alert.hidden = false;
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => { alert.hidden = true; }, 6000);
}

function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${tab}`));
  document.querySelectorAll("[data-tab]").forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  if (tab === "overview" && state.data) window.requestAnimationFrame(renderSelectedStrategy);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function pill(value) {
  const normalized = String(value || "").toLowerCase();
  return `<span class="pill ${escapeHtml(normalized)}">${escapeHtml(value || "--")}</span>`;
}

function orderRows(orders, compact = false) {
  if (!orders.length) return `<tr><td class="empty-cell" colspan="8">No equity orders found</td></tr>`;
  return orders.map((order) => compact
    ? `<tr><td><strong>${escapeHtml(order.product)}</strong></td><td>${pill(order.side)}</td><td>${pill(order.status)}</td><td>${quantity(order.filled_size)}</td><td>${money(order.average_price)}</td><td>${dateTime(order.created_at)}</td></tr>`
    : `<tr><td>${dateTime(order.created_at)}</td><td><strong>${escapeHtml(order.product)}</strong></td><td>${pill(order.side)}</td><td>${escapeHtml(order.type)}</td><td>${pill(order.status)}</td><td>${quantity(order.filled_size)}</td><td>${money(order.filled_value)}</td><td>${money(order.fees)}</td></tr>`
  ).join("");
}

function fillRows(fills) {
  if (!fills.length) return `<tr><td class="empty-cell" colspan="7">No equity fills found</td></tr>`;
  return fills.map((fill) => `<tr><td>${dateTime(fill.trade_time)}</td><td><strong>${escapeHtml(fill.product)}</strong></td><td>${pill(fill.side)}</td><td>${money(fill.price)}</td><td>${quantity(fill.size)}</td><td>${money(fill.commission)}</td><td>${escapeHtml(fill.liquidity)}</td></tr>`).join("");
}

function renderBalances(balances) {
  byId("balance-list").innerHTML = balances.length ? balances.map((balance) => `
    <div class="balance-row">
      <span class="asset-symbol">${escapeHtml(balance.currency.slice(0, 3))}</span>
      <span class="balance-name"><strong>${escapeHtml(balance.currency)}</strong><small>${escapeHtml(balance.name)}</small></span>
      <span class="balance-value"><strong>${quantity(balance.available)}</strong><small>${quantity(balance.hold)} held</small></span>
    </div>`).join("") : `<div class="empty-cell">No non-zero balances found</div>`;
}

function render(data) {
  state.data = data;
  state.liveTrading = data.live_trading;
  const available = data.strategies.map((strategy) => strategy.ticker);
  if (!available.includes(state.selectedTicker)) state.selectedTicker = available[0] || "";
  byId("strategy-select").innerHTML = data.strategies.map((strategy) => `<option value="${escapeHtml(strategy.ticker)}">${escapeHtml(strategy.ticker)}</option>`).join("");
  byId("strategy-select").value = state.selectedTicker;
  renderSelectedStrategy();
  byId("updated-at").textContent = `Updated ${dateTime(data.as_of)}`;
  renderBalances(data.balances);
  byId("recent-orders").innerHTML = orderRows(data.orders.slice(0, 5), true);
  byId("orders-table").innerHTML = orderRows(data.orders);
  byId("fills-table").innerHTML = fillRows(data.fills);
  populateSettings(data);
  if (data.warnings?.length) notify(data.warnings.join(" "));
}

function renderSelectedStrategy() {
  const strategy = state.data?.strategies.find((item) => item.ticker === state.selectedTicker);
  if (!strategy) return;
  byId("metric-ticker").textContent = strategy.ticker;
  byId("metric-position").textContent = strategy.position_active ? "Local position active" : "No local position";
  byId("metric-close").textContent = money(strategy.latest_close);
  byId("metric-entry").textContent = strategy.entry_price ? `Entry ${money(strategy.entry_price)}` : "No entry recorded";
  byId("metric-signal").textContent = strategy.signal.replaceAll("_", " ");
  byId("metric-mode").textContent = state.liveTrading ? "LIVE" : "DRY RUN";
  byId("metric-notional").textContent = `${money(strategy.trade_usd_amount)} per entry`;
  byId("chart-subtitle").textContent = `${strategy.ticker} / 90 completed sessions`;
  drawChart(strategy.chart);
}

async function refresh() {
  const button = byId("refresh-button");
  button.disabled = true;
  button.textContent = "...";
  try { render(await api("/api/overview")); }
  catch (error) { notify(error.message); }
  finally { button.disabled = false; button.innerHTML = "&#8635;"; }
}

function strategyRow(strategy = { ticker: "", trade_usd_amount: "100", stop_loss_percent: "0.10" }) {
  return `<div class="strategy-row">
    <label><span>Ticker</span><input name="ticker" value="${escapeHtml(strategy.ticker)}" required maxlength="12" autocomplete="off"></label>
    <label><span>Entry notional</span><div class="input-prefix"><b>$</b><input name="trade_usd_amount" value="${escapeHtml(strategy.trade_usd_amount)}" type="number" min="1" step="0.01" required></div></label>
    <label><span>Stop loss</span><div class="input-suffix"><input name="stop_loss_percent" value="${Number(strategy.stop_loss_percent) * 100}" type="number" min="0.1" max="99" step="0.1" required><b>%</b></div></label>
    <button class="remove-strategy" type="button" title="Remove strategy" aria-label="Remove strategy">&times;</button>
  </div>`;
}

function populateSettings(settings) {
  const form = byId("settings-form");
  byId("strategy-list").innerHTML = settings.strategies.map(strategyRow).join("");
  form.elements.live_trading.checked = settings.live_trading;
  byId("live-warning").hidden = !settings.live_trading;
}

async function loadFunding() {
  try {
    const funding = await api("/api/funding");
    const bank = funding.payment_methods.find((method) => method.type.includes("BANK"));
    byId("funding-status").textContent = bank ? `${bank.name} is available through Coinbase.` : "No linked bank is exposed to this API key. Coinbase will guide account linking and transfer authorization.";
    byId("deposit-link").href = funding.deposit_url;
    byId("withdraw-link").href = funding.withdraw_url;
  } catch (error) { byId("funding-status").textContent = error.message; }
}

function drawChart(points) {
  const canvas = byId("strategy-chart");
  if (!canvas || !points.length || canvas.offsetWidth === 0) return;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.offsetWidth;
  const height = canvas.offsetHeight;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  const pad = { top: 12, right: 58, bottom: 28, left: 10 };
  const values = points.flatMap((point) => [point.close, point.sma20, point.sma50]);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const x = (index) => pad.left + index * (width - pad.left - pad.right) / Math.max(points.length - 1, 1);
  const y = (value) => pad.top + (high - value) * (height - pad.top - pad.bottom) / span;
  context.font = "10px Cascadia Code";
  context.fillStyle = "#69746f";
  context.strokeStyle = "#e4e8e4";
  context.lineWidth = 1;
  for (let index = 0; index <= 4; index += 1) {
    const gridY = pad.top + index * (height - pad.top - pad.bottom) / 4;
    context.beginPath(); context.moveTo(pad.left, gridY); context.lineTo(width - pad.right + 5, gridY); context.stroke();
    context.fillText(money(high - index * span / 4), width - pad.right + 9, gridY + 3);
  }
  [["close", "#14211d", 2.3], ["sma20", "#167d58", 1.8], ["sma50", "#d52b2b", 1.8]].forEach(([key, color, lineWidth]) => {
    context.beginPath(); context.strokeStyle = color; context.lineWidth = lineWidth; context.lineJoin = "round";
    points.forEach((point, index) => index ? context.lineTo(x(index), y(point[key])) : context.moveTo(x(index), y(point[key])));
    context.stroke();
  });
  context.fillStyle = "#69746f";
  [0, Math.floor((points.length - 1) / 2), points.length - 1].forEach((index) => context.fillText(points[index].date.slice(5), x(index) - 15, height - 7));
}

function filterTable(inputId, source, renderer, targetId) {
  const query = byId(inputId).value.trim().toLowerCase();
  const filtered = source.filter((item) => Object.values(item).some((value) => String(value).toLowerCase().includes(query)));
  byId(targetId).innerHTML = renderer(filtered);
}

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  byId("login-error").textContent = "";
  const unlockButton = byId("unlock-button");
  unlockButton.disabled = true;
  unlockButton.textContent = "Unlocking...";
  try {
    const payload = await api("/api/login", { method: "POST", body: JSON.stringify({ password: byId("password").value }) });
    state.csrf = payload.csrf_token;
    byId("password").value = "";
    showApp();
    await Promise.all([refresh(), loadFunding()]);
  } catch (error) { byId("login-error").textContent = error.message; }
  finally { unlockButton.disabled = false; unlockButton.textContent = "Unlock"; }
});

byId("password-toggle").addEventListener("click", () => {
  const password = byId("password");
  const reveal = password.type === "password";
  password.type = reveal ? "text" : "password";
  byId("password-toggle").setAttribute("aria-pressed", String(reveal));
  byId("password-toggle").setAttribute("aria-label", reveal ? "Hide password" : "Show password");
  byId("password-toggle").title = reveal ? "Hide password" : "Show password";
  password.focus();
});

document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", (event) => { event.preventDefault(); switchTab(button.dataset.tab); }));
byId("refresh-button").addEventListener("click", refresh);
byId("logout-button").addEventListener("click", async () => { try { await api("/api/logout", { method: "POST" }); } finally { showLogin(); } });
byId("settings-form").elements.live_trading.addEventListener("change", (event) => { byId("live-warning").hidden = !event.target.checked; });
byId("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const strategies = [...byId("strategy-list").querySelectorAll(".strategy-row")].map((row) => ({
    ticker: row.querySelector('[name="ticker"]').value,
    trade_usd_amount: row.querySelector('[name="trade_usd_amount"]').value,
    stop_loss_percent: String(Number(row.querySelector('[name="stop_loss_percent"]').value) / 100),
  }));
  const payload = { strategies, live_trading: form.elements.live_trading.checked };
  try {
    const saved = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    state.liveTrading = saved.live_trading;
    notify("Settings saved. Refreshing strategy data...", true);
    await refresh();
  } catch (error) { notify(error.message); }
});
byId("add-strategy").addEventListener("click", () => {
  if (byId("strategy-list").children.length >= 20) return notify("A maximum of 20 stock strategies is supported.");
  byId("strategy-list").insertAdjacentHTML("beforeend", strategyRow());
});
byId("strategy-list").addEventListener("click", (event) => {
  const button = event.target.closest(".remove-strategy");
  if (!button) return;
  if (byId("strategy-list").children.length === 1) return notify("Keep at least one stock strategy.");
  button.closest(".strategy-row").remove();
});
byId("strategy-select").addEventListener("change", (event) => { state.selectedTicker = event.target.value; renderSelectedStrategy(); });
byId("show-passwords").addEventListener("change", (event) => {
  byId("password-form").querySelectorAll('input[type="password"], input[type="text"]').forEach((input) => { input.type = event.target.checked ? "text" : "password"; });
});
byId("password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  delete payload["show-passwords"];
  try {
    await api("/api/password", { method: "PUT", body: JSON.stringify(payload) });
    form.reset();
    showLogin();
    byId("login-error").textContent = "Password changed. Sign in with your new password.";
  } catch (error) { notify(error.message); }
});
byId("run-button").addEventListener("click", () => {
  byId("confirm-title").textContent = state.liveTrading ? "Run with live trading?" : "Run strategy now?";
  byId("confirm-copy").textContent = state.liveTrading ? "This run may submit a real order using available funds." : "The latest completed candle will be evaluated in dry-run mode.";
  byId("confirm-run").textContent = state.liveTrading ? "Confirm live run" : "Run dry check";
  byId("confirm-dialog").showModal();
});
byId("confirm-dialog").addEventListener("close", async () => {
  if (byId("confirm-dialog").returnValue !== "confirm") return;
  const button = byId("run-button");
  button.disabled = true; button.textContent = "Running...";
  try {
    const result = await api("/api/run", { method: "POST", body: JSON.stringify({ confirm_live: state.liveTrading }) });
    notify(result.log.at(-1) || "Strategy run completed", result.ok);
    await refresh();
  } catch (error) { notify(error.message); }
  finally { button.disabled = false; button.textContent = "Run strategy now"; }
});
byId("order-search").addEventListener("input", () => filterTable("order-search", state.data?.orders || [], orderRows, "orders-table"));
byId("fill-search").addEventListener("input", () => filterTable("fill-search", state.data?.fills || [], fillRows, "fills-table"));
window.addEventListener("resize", () => { if (state.data && state.tab === "overview") renderSelectedStrategy(); });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js");