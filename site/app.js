const STATE_CN = { green: "绿灯", yellow: "黄灯", red: "红灯" };
const PERIODS = ["1D", "1W", "1M", "3M"];
const HEAT_SCALE = { "1D": 3, "1W": 6, "1M": 12, "3M": 25 };
const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const charts = [];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v, d = 2) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const signed = (v, d = 2) => (v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + fmt(v, d));

function heat(v, period) {
  if (v === null || v === undefined) return "";
  const a = Math.min(Math.abs(v) / (HEAT_SCALE[period] || 10), 1) * 0.55 + 0.05;
  const rgb = v >= 0 ? (dark ? "60,203,143" : "18,128,92") : (dark ? "255,122,89" : "196,50,10");
  return `background: rgba(${rgb},${a.toFixed(2)})`;
}

function sparkSvg(points, tone) {
  if (!points || points.length < 2) return "";
  const vals = points.map((p) => p[1]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const w = 180, h = 34, span = max - min || 1;
  const d = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`).join(" ");
  const color = tone === "good" ? css("--good") : tone === "bad" ? css("--bad") : css("--muted");
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline fill="none" stroke="${color}" stroke-width="1.5" points="${d}"/></svg>`;
}

function chart(id, option) {
  const c = echarts.init($(id), dark ? "dark" : null, { renderer: "canvas" });
  c.setOption({ backgroundColor: "transparent", textStyle: { fontFamily: "inherit" }, ...option });
  charts.push(c);
  return c;
}
window.addEventListener("resize", () => charts.forEach((c) => c.resize()));

// ---------- 阶段 ----------
function renderRegime(r) {
  const a = r.action;
  $("stage").innerHTML = `<span class="stage">${esc(a.stage)}</span><span class="pos">参考仓位 ${esc(a.position)}</span><div class="act">${esc(a.action)}</div>`;

  const sw = (el, title, st, checks, extra = "") => {
    el.className = `switch ${st}`;
    el.innerHTML = `<h3><span>${title}</span><span class="pill ${st}">${STATE_CN[st]}</span></h3>
      <ul class="checks">${checks.map((c) => `<li class="${c.triggered ? "on" : ""}"><span>${esc(c.name)}</span><span class="d">${esc(c.detail)}</span></li>`).join("")}</ul>${extra}`;
  };
  const n = r.narrative;
  const primary = n.themes[0];
  const others = n.themes.slice(1).map((t) => `${esc(t.theme)}：${STATE_CN[t.state]}（第 ${t.rank ?? "—"} 名）`).join("；");
  sw($("sw-narrative"), `叙事开关 · ${esc(n.primary ?? "未配置")}`, n.state, primary ? primary.checks : [],
    others ? `<div class="subthemes">其他持有主线：${others}</div>` : "");
  sw($("sw-liquidity"), "流动性开关", r.liquidity.state, r.liquidity.soft);
  $("hard").innerHTML = "<span class='hint'>硬性风控开关：</span>" + r.liquidity.hard
    .map((h) => `<span class="h ${h.triggered ? "on" : ""}" title="${esc(h.detail)}">${h.triggered ? "● " : "○ "}${esc(h.name)}</span>`).join("");
}

// ---------- 宏观 ----------
function renderMacro(groups) {
  $("macro-groups").innerHTML = groups.map((g) => `<div class="group"><h3>${esc(g.title)}</h3><div class="cards">${g.cards.filter((c) => c.value !== null && c.value !== undefined).map(cardHtml).join("")}</div></div>`).join("");
}

function cardHtml(c) {
  const d = Math.abs(c.value) >= 1000 ? 0 : Math.abs(c.value) >= 10 ? 2 : 3;
  const suffix = c.mode === "pct" ? "%" : "";
  const cls = (v) => (v === null || v === 0 || !c.risk ? "" : (v > 0) === (c.risk === "up_is_risk_on") ? "good" : "bad");
  const pct = c.pct_3y === null ? "" : `<div class="p" title="3年分位 ${Math.round(c.pct_3y * 100)}%"><i style="left:${(c.pct_3y * 100).toFixed(0)}%"></i></div><div class="pl">3年分位 ${Math.round(c.pct_3y * 100)}%</div>`;
  return `<div class="card ${c.tone === "neutral" ? "" : c.tone}" title="数据日期 ${esc(c.date)}">
    <div class="n">${esc(c.name)}</div>
    <div class="v">${fmt(c.value, d)}<span class="u">${esc(c.unit)}</span></div>
    <div class="c"><span class="${cls(c.chg_1w)}">1周 ${signed(c.chg_1w, d)}${suffix}</span><span class="${cls(c.chg_1m)}">1月 ${signed(c.chg_1m, d)}${suffix}</span></div>
    ${sparkSvg(c.spark, c.tone)}${pct}</div>`;
}

function renderMacroCharts(ch) {
  if (ch.net_liq.length) {
    const start = ch.net_liq[0][0];
    chart("ch-netliq", {
      tooltip: { trigger: "axis" },
      legend: { data: ["净流动性（十亿美元）", "标普500"], top: 0 },
      grid: { left: 60, right: 60, top: 36, bottom: 28 },
      xAxis: { type: "time" },
      yAxis: [{ type: "value", scale: true, name: "" }, { type: "value", scale: true, splitLine: { show: false } }],
      series: [
        { name: "净流动性（十亿美元）", type: "line", showSymbol: false, data: ch.net_liq, lineStyle: { width: 2 } },
        { name: "标普500", type: "line", showSymbol: false, yAxisIndex: 1, data: ch.spx.filter((p) => p[0] >= start), lineStyle: { width: 1.5 } },
      ],
    });
  }
  const yc = ch.yield_curve;
  chart("ch-curve", {
    tooltip: { trigger: "axis", valueFormatter: (v) => (v === null ? "—" : v.toFixed(2) + "%") },
    legend: { data: ["当前", "1个月前", "1年前"], top: 0 },
    grid: { left: 48, right: 20, top: 36, bottom: 28 },
    xAxis: { type: "category", data: yc.labels },
    yAxis: { type: "value", scale: true, axisLabel: { formatter: "{value}%" } },
    series: [
      { name: "当前", type: "line", data: yc.now, lineStyle: { width: 3 } },
      { name: "1个月前", type: "line", data: yc.m1, lineStyle: { type: "dashed" } },
      { name: "1年前", type: "line", data: yc.y1, lineStyle: { type: "dotted" } },
    ],
  });
  if (ch.breadth50.length) {
    chart("ch-breadth", {
      tooltip: { trigger: "axis", valueFormatter: (v) => v.toFixed(1) + "%" },
      legend: { data: ["站上 50 日线", "站上 200 日线"], top: 0 },
      grid: { left: 48, right: 20, top: 36, bottom: 28 },
      xAxis: { type: "time" },
      yAxis: { type: "value", min: 0, max: 100, axisLabel: { formatter: "{value}%" } },
      series: [
        { name: "站上 50 日线", type: "line", showSymbol: false, data: ch.breadth50,
          markLine: { silent: true, symbol: "none", data: [{ yAxis: 30 }, { yAxis: 70 }], lineStyle: { type: "dashed", opacity: 0.5 } } },
        { name: "站上 200 日线", type: "line", showSymbol: false, data: ch.breadth200 },
      ],
    });
  } else {
    $("ch-breadth").innerHTML = "<p class='hint'>暂无市场宽度数据</p>";
  }
}

// ---------- 轮动 ----------
function heatCells(obj) {
  return PERIODS.map((p) => `<td style="${heat(obj[p], p)}">${signed(obj[p])}</td>`).join("");
}

function renderRotation(rot, holding) {
  const head = PERIODS.map((p) => `<th>${p}</th>`).join("");
  $("tbl-themes").innerHTML = `<thead><tr><th>主题</th><th>排名</th><th>5日前</th>${head}<th>象限</th><th>拥挤度</th><th>成交额占比</th><th>占比20日变化</th></tr></thead><tbody>` +
    rot.themes.map((t) => {
      const move = t.rank_5d_ago && t.rank ? t.rank_5d_ago - t.rank : 0;
      const mark = holding.includes(t.name) ? " ★" : "";
      return `<tr><td title="${esc(t.members.join(", "))}">${esc(t.name)}${mark}</td><td>${t.rank ?? "—"}</td>
        <td class="${move > 0 ? "good" : move < 0 ? "bad" : ""}">${t.rank_5d_ago ?? "—"}</td>${heatCells(t.excess)}
        <td>${t.quadrant ? `<span class="q q-${t.quadrant}">${t.quadrant}</span>` : "—"}</td>
        <td class="${t.crowding.score >= 0.85 ? "bad" : ""}">${fmt(t.crowding.score)}</td>
        <td>${t.share_pct === null ? "—" : fmt(t.share_pct) + "%"}</td>
        <td class="${t.share_chg_pp > 0 ? "good" : t.share_chg_pp < 0 ? "bad" : ""}">${signed(t.share_chg_pp, 3)}</td></tr>`;
    }).join("") + "</tbody>";

  $("tbl-sectors").innerHTML = `<thead><tr><th>板块</th>${head}</tr></thead><tbody>` +
    [...rot.sectors].sort((a, b) => (b.excess["1M"] ?? -99) - (a.excess["1M"] ?? -99))
      .map((s) => `<tr><td>${esc(s.name)} <span class="hint">${s.ticker}</span></td>${heatCells(s.excess)}</tr>`).join("") + "</tbody>";

  $("tbl-styles").innerHTML = `<thead><tr><th>比值</th>${head}</tr></thead><tbody>` +
    rot.styles.map((s) => `<tr><td>${esc(s.name)}</td>${heatCells(s.returns)}</tr>`).join("") + "</tbody>";

  // 只给持有主线和排名前 5 的主题画轨迹，其余只画最新位置，避免图太乱
  const series = rot.themes.filter((t) => t.rrg.length).map((t) => {
    const focus = holding.includes(t.name) || (t.rank && t.rank <= 5);
    const pts = focus ? t.rrg : t.rrg.slice(-1);
    return {
      name: t.name, type: "line", smooth: true, symbolSize: (v, p) => (p.dataIndex === pts.length - 1 ? (focus ? 10 : 7) : 4),
      data: pts.map((p) => [p.x, p.y, p.date]),
      label: { show: true, formatter: (p) => (p.dataIndex === pts.length - 1 ? t.name : ""), position: "right", fontSize: 11, opacity: focus ? 1 : 0.6 },
      lineStyle: { width: holding.includes(t.name) ? 3 : 1.5 },
      itemStyle: { opacity: focus ? 1 : 0.5 },
    };
  });
  const all = rot.themes.flatMap((t) => (holding.includes(t.name) || (t.rank && t.rank <= 5) ? t.rrg : t.rrg.slice(-1)));
  const ext = (k) => Math.max(...all.map((p) => Math.abs(p[k] - 100)), 2) * 1.15;
  const ex = ext("x"), ey = ext("y");
  const zone = (name, x0, x1, y0, y1, color) => [{ name, xAxis: x0, yAxis: y0, itemStyle: { color } }, { xAxis: x1, yAxis: y1 }];
  series.push({
    type: "line", data: [], silent: true,
    markArea: { silent: true, label: { color: css("--muted"), fontSize: 12 }, data: [
      zone("领先", 100, 100 + ex, 100, 100 + ey, "rgba(18,128,92,0.06)"),
      zone("转弱", 100, 100 + ex, 100 - ey, 100, "rgba(181,71,8,0.06)"),
      zone("落后", 100 - ex, 100, 100 - ey, 100, "rgba(196,50,10,0.06)"),
      zone("改善", 100 - ex, 100, 100, 100 + ey, "rgba(47,111,222,0.06)"),
    ] },
  });
  chart("ch-rrg", {
    tooltip: { trigger: "item", formatter: (p) => p.value ? `${esc(p.seriesName)}<br>${p.value[2]}<br>RS-Ratio ${p.value[0]}　RS-Mom ${p.value[1]}` : "" },
    grid: { left: 48, right: 90, top: 16, bottom: 36 },
    xAxis: { type: "value", min: +(100 - ex).toFixed(1), max: +(100 + ex).toFixed(1), name: "相对强度 →", nameLocation: "end" },
    yAxis: { type: "value", min: +(100 - ey).toFixed(1), max: +(100 + ey).toFixed(1), name: "相对动量 ↑" },
    series,
  });
}

// ---------- 标的 ----------
function renderWatch(rows) {
  $("tbl-watch").innerHTML = `<thead><tr><th>代码</th><th>分组</th><th>最新价</th>${PERIODS.map((p) => `<th>${p}</th>`).join("")}<th>距50日线</th><th>距200日线</th><th>距52周高点</th><th>下次财报</th></tr></thead><tbody>` +
    rows.map((r) => `<tr data-t="${esc(r.ticker)}"><td><b>${esc(r.ticker)}</b></td><td class="l">${esc(r.group)}</td><td>${fmt(r.last)}</td>
      ${PERIODS.map((p) => `<td style="${heat(r.returns[p], p)}">${signed(r.returns[p])}</td>`).join("")}
      <td class="${r.vs50 >= 0 ? "good" : "bad"}">${signed(r.vs50, 1)}%</td><td class="${r.vs200 >= 0 ? "good" : "bad"}">${signed(r.vs200, 1)}%</td>
      <td>${signed(r.off_high, 1)}%</td><td>${esc(r.earnings ?? "—")}</td></tr>`).join("") + "</tbody>";
  $("tbl-watch").querySelectorAll("tbody tr").forEach((tr) => tr.addEventListener("click", () => showKline(tr.dataset.t)));
}

let kchart = null;
async function showKline(t) {
  const file = t.replace("^", "_").replace("=", "_");
  const res = await fetch(`data/prices/${encodeURIComponent(file)}.json`, { cache: "no-store" });
  if (!res.ok) return;
  const rows = await res.json();
  $("kline-panel").hidden = false;
  $("kline-title").textContent = `${t} 日K（近两年）`;
  if (kchart) kchart.remove();
  const el = $("kline");
  kchart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: css("--muted") },
    grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
    rightPriceScale: { borderColor: css("--line") },
    timeScale: { borderColor: css("--line") },
  });
  const candles = kchart.addCandlestickSeries({ upColor: css("--good"), downColor: css("--bad"), wickUpColor: css("--good"), wickDownColor: css("--bad"), borderVisible: false });
  candles.setData(rows.filter((r) => r[4] !== null).map((r) => ({ time: r[0], open: r[1] ?? r[4], high: r[2] ?? r[4], low: r[3] ?? r[4], close: r[4] })));
  const ma = (n) => rows.map((r, i) => (i < n - 1 ? null : { time: r[0], value: rows.slice(i - n + 1, i + 1).reduce((s, x) => s + x[4], 0) / n })).filter(Boolean);
  kchart.addLineSeries({ color: css("--accent"), lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(ma(50));
  kchart.addLineSeries({ color: css("--warn"), lineWidth: 1, priceLineVisible: false, lastValueVisible: false }).setData(ma(200));
  const vol = kchart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "" });
  vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  vol.setData(rows.filter((r) => r[5] !== null).map((r) => ({ time: r[0], value: r[5], color: r[4] >= (r[1] ?? r[4]) ? "rgba(18,128,92,0.35)" : "rgba(196,50,10,0.35)" })));
  kchart.timeScale().fitContent();
  $("kline-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderOptions(rows) {
  if (!rows.length) { $("tbl-options").innerHTML = "<tr><td class='hint'>暂无期权数据</td></tr>"; return; }
  $("tbl-options").innerHTML = `<thead><tr><th>代码</th><th>到期日</th><th>现价</th><th>平值隐含波动率</th><th>Put/Call 成交量</th><th>Put/Call 持仓</th><th>最大痛点</th></tr></thead><tbody>` +
    rows.map((o) => `<tr><td><b>${esc(o.ticker)}</b></td><td>${esc(o.expiry)}</td><td>${fmt(o.spot)}</td><td>${fmt(o.atm_iv, 1)}%</td>
      <td>${fmt(o.pc_volume)}</td><td>${fmt(o.pc_oi)}</td><td>${fmt(o.max_pain)}</td></tr>`).join("") + "</tbody>";
}

function renderCalendar(events) {
  $("events").innerHTML = events.length
    ? events.map((e) => `<li class="${e.importance}"><span class="dt">${esc(e.date)}</span><span class="tag">${esc(e.type)}</span><span class="nm">${esc(e.name)}</span></li>`).join("")
    : "<li class='hint'>未来 14 天没有已录入的重要事件</li>";
}

function renderLog(rows) {
  $("tbl-log").innerHTML = `<thead><tr><th>时间</th><th>时段</th><th>阶段</th><th>叙事</th><th>流动性</th><th>变化</th></tr></thead><tbody>` +
    (rows.length ? rows.map((r) => `<tr><td>${esc(r.time)}</td><td>${esc(r.slot)}</td><td>${esc(r.stage)}</td>
      <td><span class="pill ${r.narrative}">${STATE_CN[r.narrative] ?? r.narrative}</span></td>
      <td><span class="pill ${r.liquidity}">${STATE_CN[r.liquidity] ?? r.liquidity}</span></td><td class="l">${esc(r.changes)}</td></tr>`).join("")
      : "<tr><td class='hint'>暂无记录</td></tr>") + "</tbody>";
}

async function main() {
  const res = await fetch("data/dashboard.json", { cache: "no-store" });
  if (!res.ok) { $("meta").textContent = "还没有数据：等第一次定时任务运行，或在 Actions 里手动运行一次。"; return; }
  const d = await res.json();
  const slot = { premarket: "开盘前更新", postclose: "收盘后更新", manual: "手动更新" }[d.slot] ?? d.slot;
  $("meta").textContent = `行情日期 ${d.market_date} · ${slot} · 生成于 ${d.generated_at}`;
  const holding = d.regime.narrative.themes.map((t) => t.theme);
  renderRegime(d.regime);
  renderMacro(d.macro);
  renderMacroCharts(d.charts);
  renderRotation(d.rotation, holding);
  renderWatch(d.watchlist);
  renderOptions(d.options);
  renderCalendar(d.calendar);
  renderLog(d.signal_log ?? []);
  const src = d.sources;
  const srcLine = src
    ? `<div>数据源：美股/ETF ${src.massive ? "Massive 官方 API" : "yfinance（未配置 MASSIVE_API_KEY）"}；宏观 ${src.fred_api ? "FRED API" : "FRED 公开 CSV（未配置 FRED_API_KEY）"}` +
      (src.yfinance?.length ? `；用 yfinance 兜底的：${esc(src.yfinance.join("、"))}` : "") + `</div>`
    : "";
  $("warnings").innerHTML = srcLine + (d.warnings ?? []).map((w) => `<div>⚠ ${esc(w)}</div>`).join("");
  requestAnimationFrame(() => charts.forEach((c) => c.resize()));
}
main();
