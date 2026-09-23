/* پنل ربات طلا — جاوااسکریپت ساده، بدون build و بدون فریم‌ورک. */
"use strict";

const LC = window.LightweightCharts;
const $ = (sel) => document.querySelector(sel);

// ───────────────────────── کمک‌کننده‌ها ─────────────────────────

/** ساخت المان DOM. متن‌ها همیشه با textContent (امن در برابر XSS). */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const nf = (d = 2) => new Intl.NumberFormat("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
function num(x, d = 2) { return x == null || Number.isNaN(x) ? "—" : nf(d).format(x); }
function money(x) { return x == null ? "—" : (Math.abs(x) >= 100000 ? num(x, 0) : num(x, 2)); }
function signed(x, d = 2, suffix = "") {
  if (x == null) return "—";
  return (x > 0 ? "+" : x < 0 ? "−" : "") + nf(d).format(Math.abs(x)) + suffix;
}
function pct(x, d = 2) { return signed(x, d, "%"); }
function tone(x) { return x > 0 ? "up" : x < 0 ? "down" : ""; }

const TZ = "Asia/Tehran";
const fmtDateTime = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { timeZone: TZ, year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
const fmtDay = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { timeZone: TZ, month: "short", day: "numeric" });
const fmtMonth = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { timeZone: TZ, month: "short", year: "numeric" });
const fmtYear = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { timeZone: TZ, year: "numeric" });
const fmtTime = new Intl.DateTimeFormat("fa-IR-u-nu-latn", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
const toDate = (t) => (typeof t === "number" ? new Date(t * 1000) : new Date(t));
function when(t) { return t ? fmtDateTime.format(toDate(t)) : "—"; }
function clock(t) { return t ? fmtTime.format(toDate(t)) : "—"; }

const REASONS = { signal: "سیگنال استراتژی", stop_loss: "حد ضرر", take_profit: "حد سود", max_drawdown: "قطع اضطراری", manual: "دستی", end_of_data: "پایان داده" };

/** پیام خطای شبکه را کوتاه و قابل فهم می‌کند. */
function shortError(msg) {
  if (!msg) return "";
  if (/Max retries|ConnectionPool|NameResolution|timed out|Tunnel|ProxyError|403|451/i.test(msg)) {
    return "از این سرور در دسترس نیست (مسدود یا بدون اینترنت).";
  }
  return msg.length > 120 ? msg.slice(0, 120) + "…" : msg;
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " error" : "");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), isError ? 7000 : 3500);
}

function confirmBox(text) {
  return new Promise((resolve) => {
    const modal = $("#confirm");
    $("#confirm-text").textContent = text;
    modal.hidden = false;
    const done = (v) => { modal.hidden = true; yes.onclick = no.onclick = null; resolve(v); };
    const yes = $("#confirm-yes"), no = $("#confirm-no");
    yes.onclick = () => done(true);
    no.onclick = () => done(false);
    no.focus();
  });
}

class ApiError extends Error {}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && path !== "/api/login") {
    showLogin();
    throw new ApiError("ابتدا وارد شو.");
  }
  let data = null;
  try { data = await res.json(); } catch { /* پاسخ خالی */ }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = "ورودی نامعتبر: " + msg.map((d) => d.msg).join("، ");
    throw new ApiError(msg || `خطای سرور (${res.status})`);
  }
  return data;
}

// ───────────────────────── تم و رنگ ─────────────────────────

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function colors() {
  return {
    surface: cssVar("--surface"), text: cssVar("--text-2"), muted: cssVar("--muted"),
    grid: cssVar("--grid"), axis: cssVar("--axis"),
    s: [cssVar("--s1"), cssVar("--s2"), cssVar("--s3")],
    up: cssVar("--candle-up"), down: cssVar("--candle-down"),
    good: cssVar("--good"), bad: cssVar("--bad"), accent: cssVar("--accent"),
  };
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch { /* حالت خصوصی */ }
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* مهم نیست */ }
    Charts.retheme();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => Charts.retheme());
}

// ───────────────────────── نمودارها ─────────────────────────

const LINE_STYLES = [LC.LineStyle.Solid, LC.LineStyle.Dashed, LC.LineStyle.Dotted];
const LINE_STYLE_CLASS = ["", "dashed", "dotted"];

const Charts = {
  all: new Set(),

  base(el) {
    const c = colors();
    const chart = LC.createChart(el, {
      autoSize: true,
      layout: {
        background: { type: "solid", color: c.surface },
        textColor: c.text,
        fontFamily: "Vazirmatn, system-ui, sans-serif",
        fontSize: 12,
      },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.axis },
      timeScale: {
        borderColor: c.axis, timeVisible: true, secondsVisible: false,
        tickMarkFormatter: (t, type) => {
          const d = toDate(t);
          if (type === 0) return fmtYear.format(d);
          if (type === 1) return fmtMonth.format(d);
          if (type === 2) return fmtDay.format(d);
          return fmtTime.format(d);
        },
      },
      localization: { locale: "en-US", timeFormatter: (t) => when(t), priceFormatter: (p) => money(p) },
      crosshair: { mode: LC.CrosshairMode.Normal },
    });
    this.all.add(chart);
    return chart;
  },

  retheme() {
    const c = colors();
    for (const chart of this.all) {
      chart.applyOptions({
        layout: { background: { type: "solid", color: c.surface }, textColor: c.text },
        grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
        rightPriceScale: { borderColor: c.axis },
        timeScale: { borderColor: c.axis },
      });
    }
    for (const fn of this.rethemers) fn();
  },
  rethemers: [],
};

/** نمودار قیمت: کندل + خطوط اندیکاتور + نشانگر معامله + خطوط حد ضرر/سود. */
class PriceChart {
  constructor(el, legendEl, hoverEl) {
    this.chart = Charts.base(el);
    this.legendEl = legendEl;
    this.hoverEl = hoverEl;
    this.lines = new Map();
    this.priceLines = [];
    const c = colors();
    this.candles = this.chart.addSeries(LC.CandlestickSeries, {
      upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down, borderVisible: false,
      priceLineVisible: true,
    });
    this.markers = LC.createSeriesMarkers(this.candles, []);
    this.fitted = false;
    Charts.rethemers.push(() => this.retheme());
    if (hoverEl) {
      this.chart.subscribeCrosshairMove((p) => this.hover(p));
    }
  }

  retheme() {
    const c = colors();
    this.candles.applyOptions({ upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down });
    [...this.lines.values()].forEach((s, i) => s.applyOptions({ color: c.s[i % 3] }));
    this.renderLegend();
    if (this._markers) this.setMarkers(this._markers);
  }

  setData(candles, lines = {}, markers = [], precision = 2) {
    const c = colors();
    const fmt = { type: "price", precision, minMove: 1 / 10 ** precision };
    this.candles.applyOptions({ priceFormat: fmt });
    this.candles.setData(candles);
    this.candleTimes = candles.map((x) => x.time);

    const names = Object.keys(lines);
    for (const [name, s] of this.lines) {
      if (!names.includes(name)) { this.chart.removeSeries(s); this.lines.delete(name); }
    }
    names.forEach((name, i) => {
      let s = this.lines.get(name);
      if (!s) {
        s = this.chart.addSeries(LC.LineSeries, {
          color: c.s[i % 3], lineWidth: 2, lineStyle: LINE_STYLES[i % 3], title: name,
          priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false, priceFormat: fmt,
        });
        this.lines.set(name, s);
      }
      s.setData(lines[name]);
    });
    this.renderLegend();
    this.setMarkers(markers);
    if (!this.fitted) { this.chart.timeScale().fitContent(); this.fitted = true; }
  }

  renderLegend() {
    if (!this.legendEl) return;
    const c = colors();
    this.legendEl.replaceChildren(
      ...[...this.lines.keys()].map((name, i) =>
        h("span", { class: "legend-item" },
          h("span", { class: "legend-swatch " + LINE_STYLE_CLASS[i % 3], style: `border-color:${c.s[i % 3]}` }), name)),
    );
  }

  /** نشانگر خرید/فروش — زمان را به نزدیک‌ترین کندلِ قبلی می‌چسباند. */
  setMarkers(markers) {
    this._markers = markers;
    const c = colors();
    const times = this.candleTimes || [];
    const snap = (t) => {
      let lo = 0, hi = times.length - 1, ans = null;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (times[mid] <= t) { ans = times[mid]; lo = mid + 1; } else hi = mid - 1; }
      return ans;
    };
    const out = markers
      .map((m) => ({ ...m, time: snap(m.time) }))
      .filter((m) => m.time != null)
      .map((m) => m.side === "buy"
        ? { time: m.time, position: "belowBar", shape: "arrowUp", color: c.good, text: "خرید" }
        : { time: m.time, position: "aboveBar", shape: "arrowDown", color: c.bad, text: "فروش" })
      .sort((a, b) => a.time - b.time);
    this.markers.setMarkers(out);
  }

  setLevels(levels) {
    this.priceLines.forEach((pl) => this.candles.removePriceLine(pl));
    const c = colors();
    this.priceLines = levels.map((l) => this.candles.createPriceLine({
      price: l.price, color: l.kind === "stop" ? c.bad : l.kind === "target" ? c.good : c.accent,
      lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title: l.title,
    }));
  }

  hover(p) {
    if (!p || !p.time || !p.seriesData) { this.hoverEl.textContent = ""; return; }
    const bar = p.seriesData.get(this.candles);
    if (!bar) { this.hoverEl.textContent = ""; return; }
    const change = ((bar.close / bar.open) - 1) * 100;
    const parts = [
      when(p.time), `باز ${money(bar.open)}`, `بالا ${money(bar.high)}`, `پایین ${money(bar.low)}`, `بسته ${money(bar.close)}`,
    ];
    for (const [name, s] of this.lines) {
      const v = p.seriesData.get(s);
      if (v && v.value != null) parts.push(`${name}: ${money(v.value)}`);
    }
    this.hoverEl.replaceChildren(parts.join("  ·  ") + "  ·  ", h("span", { class: tone(change) }, pct(change)));
  }
}

/** نمودار خطی ساده (منحنی سرمایه). */
class LineChart {
  constructor(el, { area = false, legendEl = null, hoverEl = null } = {}) {
    this.chart = Charts.base(el);
    this.area = area;
    this.legendEl = legendEl;
    this.hoverEl = hoverEl;
    this.series = [];
    Charts.rethemers.push(() => this.retheme());
    if (hoverEl) this.chart.subscribeCrosshairMove((p) => this.hover(p));
  }

  retheme() {
    const c = colors();
    this.series.forEach((s, i) => {
      const color = c.s[i % 3];
      s.api.applyOptions(this.area && i === 0
        ? { lineColor: color, topColor: color + "55", bottomColor: color + "05" }
        : { color });
    });
    this.renderLegend();
  }

  setData(list) {
    const c = colors();
    this.series.forEach((s) => this.chart.removeSeries(s.api));
    this.series = list.map((item, i) => {
      const color = c.s[i % 3];
      const api = this.area && i === 0
        ? this.chart.addSeries(LC.AreaSeries, { lineColor: color, topColor: color + "55", bottomColor: color + "05", lineWidth: 2, priceLineVisible: false, title: item.name || "" })
        : this.chart.addSeries(LC.LineSeries, { color, lineWidth: 2, lineStyle: LINE_STYLES[i % 3], priceLineVisible: false, title: item.name || "" });
      api.setData(item.data);
      return { api, name: item.name };
    });
    this.renderLegend();
    this.chart.timeScale().fitContent();
  }

  renderLegend() {
    if (!this.legendEl) return;
    const c = colors();
    this.legendEl.replaceChildren(...this.series.map((s, i) =>
      h("span", { class: "legend-item" },
        h("span", { class: "legend-swatch " + LINE_STYLE_CLASS[i % 3], style: `border-color:${c.s[i % 3]}` }), s.name)));
  }

  hover(p) {
    if (!p || !p.time) { this.hoverEl.textContent = ""; return; }
    const parts = [when(p.time)];
    for (const s of this.series) {
      const v = p.seriesData.get(s.api);
      if (v && v.value != null) parts.push(`${s.name}: ${money(v.value)}`);
    }
    this.hoverEl.textContent = parts.join("  ·  ");
  }
}

const precisionFor = (price) => (price >= 100000 ? 0 : 2);

// ───────────────────────── ورود ─────────────────────────

function showLogin() {
  Poller.stopAll();
  $("#app-view").hidden = true;
  $("#login-view").hidden = false;
  setTimeout(() => $("#login-password").focus(), 50);
}

async function showApp() {
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  await Settings.load();
  route();
}

function initLogin() {
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#login-error").textContent = "";
    try {
      await api("/api/login", { method: "POST", body: { password: $("#login-password").value } });
      $("#login-password").value = "";
      await showApp();
    } catch (err) {
      $("#login-error").textContent = err.message;
    }
  });
  $("#logout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" }).catch(() => {});
    showLogin();
  });
}

// ───────────────────────── زمان‌بندی به‌روزرسانی ─────────────────────────

const Poller = {
  timers: {},
  every(name, ms, fn) {
    this.stop(name);
    const tick = async () => {
      if (!document.hidden) { try { await fn(); } catch (e) { if (!(e instanceof ApiError)) console.error(e); } }
      this.timers[name] = setTimeout(tick, ms);
    };
    tick();
  },
  stop(name) { clearTimeout(this.timers[name]); delete this.timers[name]; },
  stopAll() { Object.keys(this.timers).forEach((n) => this.stop(n)); },
};

// ───────────────────────── داشبورد ─────────────────────────

const Dashboard = {
  priceChart: null,
  equityChart: null,
  lastLogId: 0,
  status: null,

  init() {
    this.priceChart = new PriceChart($("#price-chart"), $("#price-legend"), $("#price-hover"));
    this.equityChart = new LineChart($("#equity-chart"), { area: true });

    $("#bot-toggle").addEventListener("click", () => this.toggleBot());
    $("#reset-account").addEventListener("click", () => this.resetAccount());
    $("#close-position").addEventListener("click", () => this.closePosition());
  },

  start() {
    Poller.every("status", 5000, () => this.loadStatus());
    Poller.every("market", 30000, () => this.loadMarket());
    Poller.every("trades", 20000, () => this.loadTrades());
    Poller.every("logs", 5000, () => this.loadLogs());
  },

  stop() { ["status", "market", "trades", "logs"].forEach((n) => Poller.stop(n)); },

  async loadStatus() {
    const s = await api("/api/status");
    this.status = s;
    const { bot, account: a, market: m } = s;

    $("#m-symbol").textContent = m.symbol;
    $("#m-timeframe").textContent = m.timeframe;
    $("#bot-strategy").textContent = m.strategy_title;

    const state = $("#bot-state");
    state.className = "bot-state" + (a.halted ? " halted" : bot.running ? " on" : "");
    state.querySelector(".label").textContent = a.halted ? "متوقف (قطع اضطراری)" : bot.running ? "روشن — در حال کار" : "خاموش";
    const btn = $("#bot-toggle");
    btn.textContent = bot.running ? "خاموش کن" : "روشن کن";
    btn.className = "btn " + (bot.running ? "btn-ghost" : "btn-primary");
    btn.disabled = a.halted && !bot.running;
    $("#bot-action").textContent = bot.running
      ? (bot.action ? `آخرین تصمیم (${clock(bot.time)}): ${bot.action}` : "در حال گرفتن اولین داده…")
      : "";
    $("#bot-error").textContent = bot.running && bot.error ? "خطای آخر: " + bot.error.split("\n")[0] : "";
    $("#halted-banner").hidden = !a.halted;

    $("#a-equity").textContent = money(a.equity);
    const ret = $("#a-return");
    ret.textContent = `${pct(a.return_pct)} نسبت به شروع`;
    ret.className = "tile-sub " + tone(a.return_pct);
    const realized = $("#a-realized");
    realized.textContent = signed(a.realized_pnl);
    realized.className = "tile-value " + tone(a.realized_pnl);
    $("#a-fees").textContent = money(a.total_fees);
    const dd = $("#a-dd");
    dd.textContent = pct(a.drawdown_pct);
    dd.className = "tile-value " + (a.drawdown_pct < -a.max_drawdown_stop_pct / 2 ? "down" : "");
    $("#a-ddstop").textContent = `−${num(a.max_drawdown_stop_pct, 0)}%`;
    $("#a-trades").textContent = a.num_trades;
    $("#a-winrate").textContent = a.win_rate_pct == null ? "هنوز معامله‌ای بسته نشده" : `${num(a.win_rate_pct, 0)}% برنده`;
    $("#a-initial").textContent = money(a.initial_capital);
    $("#a-cash").textContent = money(a.cash);
    $("#a-peak").textContent = money(a.peak_equity);

    this.renderPosition(a.position, bot.price);
  },

  renderPosition(p, price) {
    const box = $("#position");
    $("#close-position").hidden = !p;
    if (!p) {
      box.className = "position muted";
      box.textContent = "پوزیشن بازی نداری — ربات منتظر سیگنال خرید است.";
      this.priceChart.setLevels([]);
      return;
    }
    box.className = "position";
    const now = price || p.entry_price;
    const span = p.target_price - p.stop_price;
    const at = (x) => Math.min(100, Math.max(0, ((x - p.stop_price) / span) * 100));
    box.replaceChildren(
      h("dl", { class: "kv" },
        h("dt", {}, "حجم"), h("dd", {}, `${num(p.quantity, 4)} اونس`),
        h("dt", {}, "قیمت خرید"), h("dd", {}, money(p.entry_price)),
        h("dt", {}, "قیمت فعلی"), h("dd", {}, money(now)),
        h("dt", {}, "سود/زیان باز"), h("dd", { class: tone(p.unrealized_pnl) }, `${signed(p.unrealized_pnl)} (${pct(p.unrealized_pct)})`),
        h("dt", {}, "حد ضرر"), h("dd", { class: "down" }, money(p.stop_price)),
        h("dt", {}, "حد سود"), h("dd", { class: "up" }, money(p.target_price)),
        h("dt", {}, "زمان خرید"), h("dd", {}, when(p.entry_time)),
      ),
      h("div", { class: "progress", title: "جای قیمت فعلی بین حد ضرر (چپ) و حد سود (راست)" },
        h("div", { class: "zone-bad", style: `left:0;width:${at(p.entry_price)}%` }),
        h("div", { class: "zone-good", style: `left:${at(p.entry_price)}%;right:0` }),
        h("div", { class: "marker", style: `left:calc(${at(now)}% - 1px)` })),
      h("div", { class: "progress-labels" }, h("span", {}, "حد ضرر"), h("span", {}, "حد سود")),
      h("p", { class: "muted small" }, `اگر حد ضرر بخورد حدود ${money(p.risk_to_stop)} دلار ضرر می‌کنی.`),
    );
    this.priceChart.setLevels([
      { price: p.stop_price, kind: "stop", title: "حد ضرر" },
      { price: p.target_price, kind: "target", title: "حد سود" },
      { price: p.entry_price, kind: "entry", title: "خرید" },
    ]);
  },

  async loadMarket() {
    try {
      const m = await api("/api/market?limit=400");
      $("#m-price").textContent = money(m.price);
      const ch = $("#m-change");
      ch.replaceChildren(...(m.change_24h_pct == null ? [] : [h("span", { dir: "ltr" }, pct(m.change_24h_pct)), " در ۲۴ ساعت"]));
      ch.className = "delta " + tone(m.change_24h_pct);
      $("#m-source").textContent = m.source || "—";
      $("#sample-warning").hidden = m.source !== "sample";
      $("#m-updated").textContent = clock(m.updated);
      this.priceChart.setData(m.candles, m.lines, m.markers, precisionFor(m.price));
      this.renderChecks(m.checks);
    } catch (e) {
      if (e instanceof ApiError) {
        $("#checks").replaceChildren(h("li", {}, h("span", { class: "ic no" }, "!"), h("span", {}, "قیمت دریافت نشد: " + e.message.split("\n")[0])));
      }
      throw e;
    }
  },

  renderChecks(checks) {
    const list = $("#checks");
    if (!checks || !checks.length) { list.replaceChildren(h("li", { class: "muted" }, "داده کافی برای تحلیل نیست.")); return; }
    list.replaceChildren(...checks.map((c) => h("li", {},
      h("span", { class: "ic " + (c.ok === true ? "yes" : c.ok === false ? "no" : "info"), "aria-label": c.ok === true ? "برقرار" : c.ok === false ? "برقرار نیست" : "اطلاعات" },
        c.ok === true ? "✓" : c.ok === false ? "✕" : "i"),
      h("span", {}, c.text))));
  },

  async loadTrades() {
    const t = await api("/api/trades");
    const body = $("#trades-body");
    body.replaceChildren(...(t.trades.length ? t.trades.map((x) => h("tr", {},
      h("td", {}, when(x.entry_time)), h("td", {}, when(x.exit_time)),
      h("td", { class: "n" }, money(x.entry_price)), h("td", { class: "n" }, money(x.exit_price)),
      h("td", { class: "n" }, num(x.quantity, 4)),
      h("td", { class: "n " + tone(x.pnl) }, signed(x.pnl)),
      h("td", { class: "n " + tone(x.pnl_pct) }, pct(x.pnl_pct)),
      h("td", {}, REASONS[x.exit_reason] || x.exit_reason || "—"),
    )) : [h("tr", {}, h("td", { colspan: 8, class: "muted" }, "هنوز معامله‌ای انجام نشده."))]));

    const hasEquity = t.equity_history.length > 1;
    $("#equity-empty").hidden = hasEquity;
    $("#equity-chart").hidden = !hasEquity;
    if (hasEquity) this.equityChart.setData([{ name: "ارزش حساب", data: t.equity_history }]);
  },

  async loadLogs() {
    const { logs } = await api(`/api/logs?after=${this.lastLogId}`);
    if (!logs.length) return;
    const box = $("#logs");
    const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
    for (const l of logs) {
      this.lastLogId = Math.max(this.lastLogId, l.id);
      box.append(h("div", { class: "log-line " + l.level }, h("time", {}, clock(l.time)), h("span", { class: "msg" }, l.message)));
    }
    while (box.children.length > 300) box.firstChild.remove();
    if (stick) box.scrollTop = box.scrollHeight;
  },

  async toggleBot() {
    const running = this.status && this.status.bot.running;
    const btn = $("#bot-toggle");
    btn.disabled = true;
    try {
      await api(running ? "/api/bot/stop" : "/api/bot/start", { method: "POST" });
      toast(running ? "ربات خاموش شد." : "ربات روشن شد. اولین تصمیم تا چند ثانیه دیگر…");
    } catch (e) { toast(e.message, true); }
    btn.disabled = false;
    this.loadStatus();
  },

  async resetAccount() {
    if (!(await confirmBox("همه معاملات و موجودی حساب کاغذی پاک می‌شود و با سرمایه اولیه از نو شروع می‌کنی. مطمئنی؟"))) return;
    try {
      await api("/api/bot/reset", { method: "POST" });
      toast("حساب ریست شد.");
      this.loadStatus(); this.loadTrades(); this.loadMarket();
    } catch (e) { toast(e.message, true); }
  },

  async closePosition() {
    if (!(await confirmBox("پوزیشن باز با قیمت فعلی بازار فروخته شود؟"))) return;
    try {
      await api("/api/bot/close", { method: "POST" });
      toast("پوزیشن بسته شد.");
      this.loadStatus(); this.loadTrades(); this.loadMarket();
    } catch (e) { toast(e.message, true); }
  },
};

// ───────────────────────── فرم پارامترهای استراتژی ─────────────────────────

function renderParams(container, strategy, values) {
  container.replaceChildren(...Object.entries(strategy.params).map(([key, p]) => {
    const value = values && values[key] != null ? values[key] : strategy.defaults[key];
    return h("label", { class: "field" },
      h("span", {}, p.label),
      h("input", { type: "number", name: key, min: p.min, max: p.max, step: p.step, value, required: true }),
      h("small", { class: "muted" }, p.help));
  }));
}

function readParams(container) {
  const out = {};
  container.querySelectorAll("input[name]").forEach((i) => { out[i.name] = Number(i.value); });
  return out;
}

// ───────────────────────── بک‌تست ─────────────────────────

const METRIC_INFO = [
  ["total_return_pct", "بازده کل", (v) => pct(v), "سود یا زیان کل در این دوره، بعد از کارمزد.", (m) => (m.total_return_pct > 0 ? "good" : "bad")],
  ["buy_hold_return_pct", "خرید و نگه‌داری", (v) => pct(v), "اگر روز اول طلا می‌خریدی و دست نمی‌زدی.", () => null],
  ["max_drawdown_pct", "بیشترین افت", (v) => pct(v), "بدترین فاصله حساب از سقفش. زیر ۲۰٪ خوب است.", (m) => (m.max_drawdown_pct > -10 ? "good" : m.max_drawdown_pct > -25 ? "ok" : "bad")],
  ["sharpe", "نسبت شارپ", (v) => num(v), "سود به ازای ریسک. بالای ۱ خوب، زیر ۰ بد.", (m) => (m.sharpe >= 1 ? "good" : m.sharpe > 0 ? "ok" : "bad")],
  ["num_trades", "تعداد معامله", (v) => num(v, 0), "زیر ۳۰ معامله، نتیجه از نظر آماری ضعیف است.", (m) => (m.num_trades >= 30 ? "good" : m.num_trades >= 10 ? "ok" : "bad")],
  ["win_rate_pct", "درصد برد", (v) => num(v, 1) + "%", "چند درصد معاملات سودده بودند. به‌تنهایی مهم نیست؛ اندازه برد و باخت هم مهم است.", () => null],
  ["profit_factor", "ضریب سوددهی", (v) => (v == null ? "∞" : num(v)), "مجموع سودها ÷ مجموع ضررها. بالای ۱.۵ خوب است.", (m) => (m.profit_factor == null || m.profit_factor >= 1.5 ? "good" : m.profit_factor >= 1 ? "ok" : "bad")],
  ["exposure_pct", "زمان در بازار", (v) => num(v, 0) + "%", "چند درصد زمان پول در طلا بود. بقیه زمان پول نقد و بی‌خطر بود.", () => null],
];
const LEVEL_TEXT = { good: "خوب", ok: "متوسط", bad: "ضعیف" };
const LEVEL_ICON = { good: "✓", ok: "!", bad: "✕" };

const Backtest = {
  equityChart: null,
  priceChart: null,
  last: null,

  init() {
    this.equityChart = new LineChart($("#bt-equity-chart"), { legendEl: $("#bt-eq-legend"), hoverEl: $("#bt-eq-hover") });
    this.priceChart = new PriceChart($("#bt-price-chart"), $("#bt-price-legend"), null);
    $("#bt-strategy").addEventListener("change", () => this.renderForm());
    $("#bt-defaults").addEventListener("click", () => this.renderForm(true));
    $("#bt-form").addEventListener("submit", (e) => { e.preventDefault(); this.run(); });
    $("#bt-apply").addEventListener("click", () => this.apply());
  },

  fill() {
    const s = Settings.data;
    const sel = $("#bt-strategy");
    if (!sel.options.length) {
      sel.replaceChildren(...s.strategies.map((x) => h("option", { value: x.name }, x.title)));
      $("#bt-timeframe").replaceChildren(...s.timeframes.map((t) => h("option", { value: t }, t)));
      sel.value = s.config.strategy.name;
      $("#bt-timeframe").value = s.config.market.timeframe;
      this.renderForm();
    }
  },

  renderForm(useDefaults = false) {
    const s = Settings.data;
    const strat = s.strategies.find((x) => x.name === $("#bt-strategy").value);
    $("#bt-desc").textContent = strat.description;
    const current = !useDefaults && s.config.strategy.name === strat.name ? s.config.strategy.params : null;
    renderParams($("#bt-params"), strat, current);
  },

  async run() {
    const btn = $("#bt-run");
    btn.disabled = true;
    $("#bt-status").textContent = "در حال گرفتن داده و اجرای بک‌تست… (ممکن است چند ثانیه طول بکشد)";
    try {
      const body = {
        strategy: $("#bt-strategy").value,
        params: readParams($("#bt-params")),
        timeframe: $("#bt-timeframe").value,
        limit: Number($("#bt-limit").value),
      };
      const r = await api("/api/backtest", { method: "POST", body });
      this.last = r;
      this.render(r);
      $("#bt-status").textContent = `${r.bars} کندل از ${when(r.period[0])} تا ${when(r.period[1])} · منبع: ${r.source}`;
    } catch (e) {
      $("#bt-status").textContent = "";
      toast(e.message, true);
    }
    btn.disabled = false;
  },

  render(r) {
    $("#bt-result").hidden = false;
    const v = r.verdict;
    const box = $("#bt-verdict");
    box.className = "card verdict " + v.level;
    box.replaceChildren(
      h("div", { class: "verdict-head" }, h("span", { class: "badge " + v.level }, `${LEVEL_ICON[v.level]} نتیجه ${LEVEL_TEXT[v.level]}`), h("span", {}, v.summary)),
      h("div", { class: "findings" }, ...v.findings.map((f) => h("div", { class: "finding" },
        h("strong", {}, h("span", { class: "badge " + f.level }, LEVEL_ICON[f.level]), f.title),
        h("span", { class: "muted" }, f.text)))),
      ...(r.stopped_early ? [h("p", { class: "banner banner-bad" }, "⛔ کلید قطع اضطراری وسط بک‌تست زده شد و ربات متوقف شد.")] : []),
    );

    const m = r.metrics;
    $("#bt-tiles").replaceChildren(...METRIC_INFO.map(([key, label, fmt, help, grade]) => {
      const g = grade(m);
      return h("div", { class: "card tile" },
        h("div", { class: "tile-label" }, label, g ? h("span", { class: "badge " + g + " status-icon", title: LEVEL_TEXT[g] }, LEVEL_ICON[g]) : null),
        h("div", { class: "tile-value" }, fmt(m[key])),
        h("div", { class: "tile-help" }, help));
    }));

    this.equityChart.setData([
      { name: "ربات", data: r.equity },
      { name: "خرید و نگه‌داری", data: r.buy_hold },
    ]);

    const markers = [];
    for (const t of r.trades) {
      markers.push({ time: t.entry_time, side: "buy" });
      markers.push({ time: t.exit_time, side: "sell", reason: t.exit_reason });
    }
    this.priceChart.fitted = false;
    const lastClose = r.candles.length ? r.candles[r.candles.length - 1].close : 0;
    this.priceChart.setData(r.candles, r.lines, markers, precisionFor(lastClose));

    $("#bt-trades").replaceChildren(...(r.trades.length ? [...r.trades].reverse().map((t) => h("tr", {},
      h("td", {}, when(t.entry_time)), h("td", {}, when(t.exit_time)),
      h("td", { class: "n" }, money(t.entry_price)), h("td", { class: "n" }, money(t.exit_price)),
      h("td", { class: "n " + tone(t.pnl) }, signed(t.pnl)), h("td", { class: "n " + tone(t.pnl_pct) }, pct(t.pnl_pct)),
      h("td", {}, REASONS[t.exit_reason] || t.exit_reason), h("td", { class: "n" }, t.bars_held),
    )) : [h("tr", {}, h("td", { colspan: 8, class: "muted" }, "در این بازه هیچ معامله‌ای انجام نشد."))]));
  },

  async apply() {
    if (!this.last) return;
    if (!(await confirmBox("این استراتژی، پارامترها و تایم‌فریم برای ربات ذخیره شود؟ اگر ربات روشن است، با تنظیمات جدید دوباره روشن می‌شود."))) return;
    try {
      const r = await api("/api/settings", { method: "PUT", body: {
        strategy: { name: this.last.strategy, params: this.last.params },
        market: { timeframe: this.last.timeframe },
      } });
      toast(r.restarted ? "ذخیره شد و ربات با تنظیمات جدید دوباره روشن شد." : "ذخیره شد.");
      await Settings.load();
    } catch (e) { toast(e.message, true); }
  },
};

// ───────────────────────── تنظیمات ─────────────────────────

const Settings = {
  data: null,

  async load() {
    this.data = await api("/api/settings");
    $("#version").textContent = "";
    this.fill();
    Backtest.fill();
    this.renderGuide();
  },

  init() {
    $("#s-strategy").addEventListener("change", () => this.renderStrategy());
    $("#s-symbol").addEventListener("change", () => this.hints());
    $("#s-source").addEventListener("change", () => this.hints());
    ["#s-capital", "#s-risk", "#s-maxdd", "#s-maxpos"].forEach((id) => $(id).addEventListener("input", () => this.riskExample()));
    $("#settings-form").addEventListener("submit", (e) => { e.preventDefault(); this.save(); });
    $("#s-reset").addEventListener("click", () => this.reset());
    $("#s-doctor").addEventListener("click", () => this.doctor());
  },

  fill() {
    const d = this.data, c = d.config;
    const symbols = [...d.symbols];
    if (!symbols.find((s) => s.symbol === c.market.symbol)) symbols.push({ symbol: c.market.symbol, title: c.market.symbol, hint: "" });
    $("#s-symbol").replaceChildren(...symbols.map((s) => h("option", { value: s.symbol }, `${s.title} — ${s.symbol}`)));
    $("#s-source").replaceChildren(...d.sources.map((s) => h("option", { value: s.name }, s.name)));
    $("#s-timeframe").replaceChildren(...d.timeframes.map((t) => h("option", { value: t }, t)));
    $("#s-strategy").replaceChildren(...d.strategies.map((s) => h("option", { value: s.name }, s.title)));

    $("#s-symbol").value = c.market.symbol;
    $("#s-source").value = c.market.source;
    $("#s-timeframe").value = c.market.timeframe;
    $("#s-strategy").value = c.strategy.name;
    $("#s-capital").value = c.risk.initial_capital;
    $("#s-risk").value = +(c.risk.risk_per_trade * 100).toFixed(3);
    $("#s-maxpos").value = +(c.risk.max_position_pct * 100).toFixed(2);
    $("#s-maxdd").value = +(c.risk.max_drawdown_stop * 100).toFixed(2);
    $("#s-fee").value = +(c.costs.fee_rate * 100).toFixed(4);
    $("#s-slip").value = +(c.costs.slippage_rate * 100).toFixed(4);
    $("#s-poll").value = c.live.poll_seconds;
    this.renderStrategy(c.strategy.params);
    this.hints();
    this.riskExample();
  },

  renderStrategy(values) {
    const strat = this.data.strategies.find((x) => x.name === $("#s-strategy").value);
    $("#s-strategy-desc").textContent = strat.description;
    const same = this.data.config.strategy.name === strat.name;
    renderParams($("#s-params"), strat, values || (same ? this.data.config.strategy.params : null));
  },

  hints() {
    const sym = this.data.symbols.find((s) => s.symbol === $("#s-symbol").value);
    $("#s-symbol-hint").textContent = sym ? sym.hint : "";
    const src = this.data.sources.find((s) => s.name === $("#s-source").value);
    $("#s-source-hint").textContent = src ? src.title : "";
  },

  riskExample() {
    const cap = Number($("#s-capital").value) || 0;
    const r = (Number($("#s-risk").value) || 0) / 100;
    const dd = (Number($("#s-maxdd").value) || 0) / 100;
    const losses = r > 0 && dd > 0 && dd < 1 ? Math.ceil(Math.log(1 - dd) / Math.log(1 - r)) : null;
    $("#risk-example").textContent =
      `مثال: با سرمایه ${money(cap)} دلار و ریسک ${num(r * 100, 1)}٪، اگر حد ضرر یک معامله بخورد حدود ${money(cap * r)} دلار ضرر می‌کنی.` +
      (losses ? ` برای اینکه کلید قطع اضطراری (${num(dd * 100, 0)}٪ افت) بخورد، تقریباً ${losses} باخت پشت‌سرهم لازم است.` : "");
  },

  collect() {
    return {
      market: { symbol: $("#s-symbol").value, source: $("#s-source").value, timeframe: $("#s-timeframe").value },
      strategy: { name: $("#s-strategy").value, params: readParams($("#s-params")) },
      risk: {
        initial_capital: Number($("#s-capital").value),
        risk_per_trade: Number($("#s-risk").value) / 100,
        max_position_pct: Number($("#s-maxpos").value) / 100,
        max_drawdown_stop: Number($("#s-maxdd").value) / 100,
      },
      costs: { fee_rate: Number($("#s-fee").value) / 100, slippage_rate: Number($("#s-slip").value) / 100 },
      live: { poll_seconds: Number($("#s-poll").value) },
    };
  },

  async save() {
    const status = $("#s-status");
    status.className = "small";
    status.textContent = "در حال ذخیره…";
    try {
      const r = await api("/api/settings", { method: "PUT", body: this.collect() });
      status.className = "small up";
      status.textContent = r.restarted ? "✓ ذخیره شد و ربات با تنظیمات جدید دوباره روشن شد." : "✓ ذخیره شد.";
      await this.load();
      Dashboard.priceChart.fitted = false;
    } catch (e) {
      status.className = "small down";
      status.textContent = "✕ " + e.message;
    }
  },

  async reset() {
    if (!(await confirmBox("همه تغییرات پنل پاک شود و تنظیمات فایل config.yaml برگردد؟"))) return;
    try {
      await api("/api/settings", { method: "DELETE" });
      toast("تنظیمات به پیش‌فرض برگشت.");
      await this.load();
    } catch (e) { toast(e.message, true); }
  },

  async doctor() {
    const box = $("#doctor-result");
    box.replaceChildren(h("span", { class: "muted" }, "در حال امتحان منابع… (تا ۳۰ ثانیه)"));
    try {
      const r = await api("/api/doctor");
      box.replaceChildren(...r.results.map((x) => h("div", { class: "doctor-row" },
        h("span", { class: "badge " + (x.ok ? "good" : "bad") }, x.ok ? "✓ در دسترس" : "✕ در دسترس نیست"),
        h("strong", {}, x.source),
        h("span", { class: "muted doctor-msg" }, x.ok ? `قیمت ${money(x.price)} · ${x.ms} میلی‌ثانیه` : shortError(x.error)))));
    } catch (e) { box.replaceChildren(h("span", { class: "down" }, e.message)); }
  },

  renderGuide() {
    $("#guide-strategies").replaceChildren(...this.data.strategies.map((s) => h("div", { class: "strategy-card" },
      h("h3", {}, s.title), h("p", { class: "muted" }, s.description))));
  },
};

// ───────────────────────── مسیریابی تب‌ها ─────────────────────────

const TABS = ["dashboard", "backtest", "settings", "guide"];

function route() {
  const tab = TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "dashboard";
  for (const t of TABS) {
    $(`#tab-${t}`).hidden = t !== tab;
    document.querySelector(`.tabs a[data-tab="${t}"]`).setAttribute("aria-selected", String(t === tab));
  }
  if (tab === "dashboard") Dashboard.start(); else Dashboard.stop();
  if (tab === "settings" && Settings.data) Settings.fill();
}

// ───────────────────────── شروع ─────────────────────────

async function boot() {
  if (!LC) {
    document.body.textContent = "کتابخانه نمودار بارگذاری نشد. صفحه را دوباره بارگذاری کن.";
    return;
  }
  initTheme();
  initLogin();
  Dashboard.init();
  Backtest.init();
  Settings.init();
  window.addEventListener("hashchange", () => { if (!$("#app-view").hidden) route(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("#app-view").hidden) route(); });

  try {
    await api("/api/me");
    await showApp();
  } catch {
    showLogin();
  }
}

document.addEventListener("DOMContentLoaded", boot);
