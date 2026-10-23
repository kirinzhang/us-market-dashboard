"""主流程：拉数据 → 算指标 → 阶段判断 → 写页面数据 → 状态变化时发邮件。

用法：
  python -m dashboard.build            # 按美东时间判断是否在 05:30 / 17:00 窗口内，不在则跳过
  python -m dashboard.build --force    # 立刻运行（手动触发时用）
  python -m dashboard.build --force --no-email
"""

import argparse
import csv
import json
import logging
import math
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import config, fetch_fred, fetch_market, indicators as ind, notify, regime
from .schedule import current_slot

log = logging.getLogger("dashboard")


# ---------- 工具 ----------

def clean(obj):
    """把 NaN/inf 变成 null，numpy 类型变成原生类型，方便写 JSON。"""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "item"):
        obj = obj.item()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean(data), f, ensure_ascii=False, separators=(",", ":"))


def col(df: pd.DataFrame | None, ticker: str) -> pd.Series | None:
    if df is None or ticker not in df.columns:
        return None
    s = df[ticker].dropna()
    return s if not s.empty else None


def set_output(key: str, value: str):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{key}={value}\n")


# ---------- 各部分 ----------

def build_macro(fred: dict, close: pd.DataFrame, net_liq: pd.Series | None, breadth50, breadth200) -> list[dict]:
    def f(sid):
        return fred.get(sid, pd.Series(dtype=float))

    def m(t):
        s = col(close, t)
        return s if s is not None else pd.Series(dtype=float)

    groups = []
    liq = []
    if net_liq is not None:
        liq.append(ind.card(net_liq, "净流动性", "十亿美元", "diff", "up_is_risk_on", 0))
    liq += [
        ind.card(ind.to_billions(f("WALCL")), "美联储总资产", "十亿美元", "diff", "up_is_risk_on", 0),
        ind.card(ind.to_billions(f("WTREGEN")), "TGA 账户", "十亿美元", "diff", "up_is_risk_off", 0),
        ind.card(ind.to_billions(f("RRPONTSYD")), "隔夜逆回购", "十亿美元", "diff", None, 0),
        ind.card(ind.to_billions(f("WRESBAL")), "银行准备金", "十亿美元", "diff", "up_is_risk_on", 0),
    ]
    sofr, iorb = f("SOFR"), f("IORB")
    if not sofr.empty and not iorb.empty:
        spread = (sofr - iorb.reindex(sofr.index).ffill()).dropna() * 100
        liq.append(ind.card(spread, "SOFR − IORB", "基点", "diff", "up_is_risk_off", 1))
    groups.append({"title": "数量层：美联储净流动性", "cards": liq})

    groups.append({"title": "利率与曲线", "cards": [
        ind.card(f("DGS2"), "2年美债", "%", "diff", None),
        ind.card(f("DGS10"), "10年美债", "%", "diff", "up_is_risk_off"),
        ind.card(f("DGS30"), "30年美债", "%", "diff", None),
        ind.card(f("T10Y2Y"), "10Y − 2Y", "%", "diff", None),
        ind.card(f("T10Y3M"), "10Y − 3M", "%", "diff", None),
        ind.card(f("DFII10"), "10年实际利率", "%", "diff", "up_is_risk_off"),
        ind.card(f("T10YIE"), "10年盈亏平衡通胀", "%", "diff", None),
    ]})

    vix, vix3m = m("^VIX"), m("^VIX3M")
    term = (vix / vix3m.reindex(vix.index)).dropna() if not vix.empty and not vix3m.empty else pd.Series(dtype=float)
    groups.append({"title": "信用与风险偏好", "cards": [
        ind.card(f("BAMLH0A0HYM2"), "高收益债利差", "%", "diff", "up_is_risk_off"),
        ind.card(f("BAMLC0A0CM"), "投资级利差", "%", "diff", "up_is_risk_off"),
        ind.card(vix, "VIX", "", "diff", "up_is_risk_off"),
        ind.card(term, "VIX / VIX3M", "", "diff", "up_is_risk_off", 3),
        ind.card(m("^MOVE"), "MOVE 美债波动率", "", "diff", "up_is_risk_off"),
        ind.card(f("NFCI"), "金融条件 NFCI", "", "diff", "up_is_risk_off", 3),
    ]})

    copper, gold = m("HG=F"), m("GC=F")
    cg = (copper / gold.reindex(copper.index)).dropna() * 1000 if not copper.empty and not gold.empty else pd.Series(dtype=float)
    groups.append({"title": "大类资产", "cards": [
        ind.card(m("DX-Y.NYB"), "美元指数", "", "pct", "up_is_risk_off"),
        ind.card(m("JPY=X"), "美元/日元", "", "pct", None),
        ind.card(m("CL=F"), "WTI 原油", "美元", "pct", None),
        ind.card(gold, "黄金", "美元", "pct", None),
        ind.card(cg, "铜金比 ×1000", "", "pct", "up_is_risk_on", 3),
        ind.card(m("BTC-USD"), "比特币", "美元", "pct", "up_is_risk_on", 0),
    ]})

    spy, rsp = m("SPY"), m("RSP")
    eqw = (rsp / spy.reindex(rsp.index)).dropna() if not spy.empty and not rsp.empty else pd.Series(dtype=float)
    idx_cards = [
        ind.card(m("^GSPC"), "标普500", "", "pct", "up_is_risk_on", 0),
        ind.card(m("^NDX"), "纳斯达克100", "", "pct", "up_is_risk_on", 0),
        ind.card(m("^RUT"), "罗素2000", "", "pct", "up_is_risk_on", 0),
        ind.card(eqw, "等权 / 市值加权", "", "pct", "up_is_risk_on", 4),
    ]
    if breadth50 is not None:
        idx_cards.append(ind.card(breadth50, "站上 50 日线比例", "%", "diff", "up_is_risk_on", 1))
    if breadth200 is not None:
        idx_cards.append(ind.card(breadth200, "站上 200 日线比例", "%", "diff", "up_is_risk_on", 1))
    groups.append({"title": "美股指数与市场宽度", "cards": idx_cards})
    return groups


def build_yield_curve(fred: dict) -> dict:
    tenors = [("3M", "DGS3MO"), ("2Y", "DGS2"), ("10Y", "DGS10"), ("30Y", "DGS30")]

    def at(days):
        row = []
        for _, sid in tenors:
            s = fred.get(sid, pd.Series(dtype=float)).dropna()
            if days and not s.empty:
                s = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
            row.append(round(float(s.iloc[-1]), 3) if not s.empty else None)
        return row

    return {"labels": [t for t, _ in tenors], "now": at(0), "m1": at(30), "y1": at(365)}


def build_rotation(close, volume, universe, market_total, bench) -> tuple[dict, dict]:
    """返回（页面数据, 叙事判断需要的中间结果）。"""
    sectors = []
    for t, name in universe.get("sectors", {}).items():
        s = col(close, t)
        if s is None:
            continue
        sectors.append({"ticker": t, "name": name, "returns": ind.period_returns(s),
                        "excess": ind.period_returns(s, bench)})

    theme_idx = {}
    for name, members in universe.get("themes", {}).items():
        idx = ind.basket_index(close, members)
        if not idx.empty:
            theme_idx[name] = idx
    idx_df = pd.DataFrame(theme_idx)
    score = ind.strength_score(idx_df, bench)
    rank = score.rank(axis=1, ascending=False)

    themes, inter = [], {}
    for name, idx in theme_idx.items():
        members = universe["themes"][name]
        share20 = ind.dollar_volume_share(close, volume, members, market_total) if volume is not None else pd.Series(dtype=float)
        crowd = ind.crowding(idx, close, members, share20)
        tail = ind.rrg(idx, bench)
        quad = ind.rrg_quadrant(tail[-1]["x"], tail[-1]["y"]) if tail else None
        s20 = share20.dropna()
        share_chg = float((s20.iloc[-1] - s20.iloc[-21]) * 100) if len(s20) > 21 else None
        cur_rank = rank[name].dropna()
        themes.append({
            "name": name,
            "members": [m for m in members if m in close.columns],
            "returns": ind.period_returns(idx),
            "excess": ind.period_returns(idx, bench),
            "rank": int(cur_rank.iloc[-1]) if not cur_rank.empty else None,
            "rank_5d_ago": int(cur_rank.iloc[-6]) if len(cur_rank) > 6 else None,
            "score": round(float(score[name].dropna().iloc[-1]) * 100, 2) if not score[name].dropna().empty else None,
            "rrg": tail,
            "quadrant": quad,
            "crowding": crowd,
            "share_pct": round(float(s20.iloc[-1]) * 100, 2) if not s20.empty else None,
            "share_chg_pp": round(share_chg, 3) if share_chg is not None else None,
            "spark": ind.spark(idx / idx.iloc[-min(len(idx), 252)] * 100, 252, 2),
        })
        inter[name] = {"rank": rank[name], "idx": idx, "share20": share20, "crowd": crowd.get("score")}
    themes.sort(key=lambda x: (x["rank"] is None, x["rank"]))

    styles = []
    for st in universe.get("styles", []):
        a, b = col(close, st["num"]), col(close, st["den"])
        if a is None or b is None:
            continue
        ratio = (a / b.reindex(a.index)).dropna()
        styles.append({"name": st["name"], "returns": ind.period_returns(ratio),
                       "spark": ind.spark(ratio / ratio.iloc[-min(len(ratio), 252)] * 100, 252, 2)})
    return {"sectors": sectors, "themes": themes, "styles": styles}, inter


def build_watchlist(close, universe, earnings: dict) -> list[dict]:
    rows = []
    groups = [("AI 核心", universe.get("watchlist", [])), ("杠杆 ETF", universe.get("leveraged", [])),
              ("大盘", universe.get("broad_etfs", [universe["benchmark"]]))]
    seen = set()
    for group, tickers in groups:
        for t in tickers:
            s = col(close, t)
            if s is None or t in seen:
                continue
            seen.add(t)
            sma50, sma200 = s.rolling(50).mean().iloc[-1], s.rolling(200).mean().iloc[-1]
            hi52 = s.iloc[-252:].max()
            rows.append({
                "ticker": t, "group": group, "last": round(float(s.iloc[-1]), 2),
                "returns": ind.period_returns(s),
                "vs50": round((s.iloc[-1] / sma50 - 1) * 100, 1) if pd.notna(sma50) else None,
                "vs200": round((s.iloc[-1] / sma200 - 1) * 100, 1) if pd.notna(sma200) else None,
                "off_high": round((s.iloc[-1] / hi52 - 1) * 100, 1),
                "earnings": earnings.get(t),
            })
    return rows


def build_calendar(events_cfg: dict, earnings: dict, lookahead: int) -> list[dict]:
    today = date.today()
    end = today + timedelta(days=lookahead)
    out = []
    for e in events_cfg.get("events", []):
        d = e["date"] if isinstance(e["date"], date) else date.fromisoformat(str(e["date"]))
        if today <= d <= end:
            out.append({"date": d.isoformat(), "name": e["name"], "importance": e.get("importance", "medium"),
                        "type": "宏观"})
    for t, d in earnings.items():
        if d and today.isoformat() <= d <= end.isoformat():
            out.append({"date": d, "name": f"{t} 财报", "importance": "high", "type": "财报"})
    return sorted(out, key=lambda x: x["date"])


def write_price_files(prices: dict, tickers: list[str]):
    out_dir = config.SITE_DATA_DIR / "prices"
    for t in tickers:
        c = col(prices.get("Close"), t)
        if c is None:
            continue
        rows = []
        for d in c.index[-504:]:
            o, h, lo, v = (prices[k].at[d, t] if k in prices and t in prices[k] else None
                           for k in ("Open", "High", "Low", "Volume"))
            rows.append([d.strftime("%Y-%m-%d"), *(round(float(x), 4) if x is not None and pd.notna(x) else None
                                                  for x in (o, h, lo, c.at[d])),
                         int(v) if v is not None and pd.notna(v) else None])
        write_json(out_dir / f"{t.replace('^', '_').replace('=', '_')}.json", rows)


# ---------- 状态与日志 ----------

def load_state() -> dict | None:
    p = config.STATE_DIR / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save_state(cur: dict):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / "state.json").write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


def append_log(cur: dict, changes: list[str]):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = config.STATE_DIR / "signal_log.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "slot", "stage", "narrative", "liquidity", "hard", "changes"])
        w.writerow([cur["time"], cur["slot"], cur["stage"], cur["narrative"], cur["liquidity"],
                    "；".join(cur["hard"]), "；".join(changes)])


def read_log(n: int = 40) -> list[dict]:
    p = config.STATE_DIR / "signal_log.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[-n:][::-1]


# ---------- 主流程 ----------

def run(slot: str, send_email: bool) -> dict:
    cfg = config.load_all()
    universe, settings, events = cfg["universe"], cfg["settings"], cfg["events"]
    warnings: list[str] = []
    start = (date.today() - timedelta(days=365 * 4)).isoformat()

    log.info("拉取 FRED…")
    fred, w = fetch_fred.fetch_all(start)
    warnings += w

    log.info("拉取关注标的行情…")
    tickers = config.all_market_tickers(universe)
    prices = fetch_market.download_prices(tickers, period="3y")
    close, volume = prices.get("Close"), prices.get("Volume")
    if close is None or close.empty:
        raise RuntimeError("行情数据为空，终止")
    missing = sorted(set(tickers) - set(close.columns))
    if missing:
        warnings.append("以下代码没有拿到行情：" + "、".join(missing))
    bench = close[universe["benchmark"]].dropna()

    breadth50 = breadth200 = None
    market_total = (close * volume).sum(axis=1, min_count=1) if volume is not None else None
    try:
        log.info("拉取标普 500 成分股（市场宽度）…")
        spx_members = fetch_market.sp500_constituents()
        sp = fetch_market.download_prices(spx_members, period="2y")
        breadth50 = ind.breadth(sp["Close"], 50)
        breadth200 = ind.breadth(sp["Close"], 200)
        if "Volume" in sp:
            market_total = (sp["Close"] * sp["Volume"]).sum(axis=1, min_count=1)
    except Exception as err:
        warnings.append(f"市场宽度计算失败：{err}")

    net_liq = None
    try:
        net_liq = ind.net_liquidity(fred["WALCL"], fred["WTREGEN"], fred["RRPONTSYD"])
    except Exception as err:
        warnings.append(f"净流动性计算失败：{err}")

    log.info("计算轮动…")
    rotation, inter = build_rotation(close, volume, universe, market_total, bench)

    earnings = {}
    for t in universe.get("watchlist", []):
        try:
            earnings[t] = fetch_market.next_earnings(t)
        except Exception as err:
            log.info("财报日期 %s 获取失败：%s", t, err)
    options = []
    for t in universe.get("options", []):
        try:
            spot = col(close, t)
            options.append(fetch_market.option_snapshot(t, float(spot.iloc[-1]) if spot is not None else None))
        except Exception as err:
            warnings.append(f"{t} 期权快照失败：{err}")

    log.info("阶段判断…")
    liq = regime.evaluate_liquidity({
        "net_liq": net_liq, "hy_oas": fred.get("BAMLH0A0HYM2"), "dxy": col(close, "DX-Y.NYB"),
        "vix": col(close, "^VIX"), "vix3m": col(close, "^VIX3M"), "spx": col(close, "^GSPC"),
        "breadth50": breadth50, "usdjpy": col(close, "JPY=X"),
    }, settings)
    theme_evals = [regime.evaluate_theme(name, inter[name]["rank"], inter[name]["idx"], inter[name]["share20"],
                                         inter[name]["crowd"], settings)
                   for name in universe.get("holding_themes", []) if name in inter]
    narr = regime.evaluate_narrative(theme_evals)
    action = regime.decide_action(narr["state"], liq["state"])

    now = datetime.now(timezone.utc)
    dash = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "slot": slot,
        "market_date": close.index[-1].strftime("%Y-%m-%d"),
        "warnings": warnings,
        "regime": {"narrative": narr, "liquidity": liq, "action": action},
        "macro": build_macro(fred, close, net_liq, breadth50, breadth200),
        "charts": {
            "net_liq": ind.spark(net_liq, 160, 0) if net_liq is not None else [],
            "spx": ind.spark(col(close, "^GSPC") if col(close, "^GSPC") is not None else bench, 780, 1),
            "yield_curve": build_yield_curve(fred),
            "breadth50": ind.spark(breadth50, 260, 1) if breadth50 is not None else [],
            "breadth200": ind.spark(breadth200, 260, 1) if breadth200 is not None else [],
        },
        "rotation": rotation,
        "watchlist": build_watchlist(close, universe, earnings),
        "options": options,
        "calendar": build_calendar(events, earnings, settings["calendar"]["lookahead_days"]),
    }

    cur = {"time": dash["generated_at"], "slot": slot, "stage": action["stage"],
           "narrative": narr["state"], "liquidity": liq["state"],
           "hard": [c["name"] for c in liq["hard"] if c["triggered"]]}
    prev = load_state()
    changes = notify.diff_states(prev, cur)
    if changes:
        append_log(cur, changes)
        if send_email:
            try:
                subject, body = notify.compose(changes, dash, os.environ.get("SITE_URL"))
                notify.send(subject, body)
            except Exception as err:
                warnings.append(f"邮件发送失败：{err}")
    save_state(cur)
    dash["signal_log"] = read_log()

    write_json(config.SITE_DATA_DIR / "dashboard.json", dash)
    chart_tickers = list(dict.fromkeys(
        universe.get("broad_etfs", []) + [x["ticker"] for x in universe.get("indices", [])]
        + universe.get("watchlist", []) + universe.get("leveraged", []) + list(universe.get("sectors", {}))))
    write_price_files(prices, chart_tickers)
    log.info("完成：%s｜叙事 %s｜流动性 %s｜变化 %s", action["stage"], narr["state"], liq["state"], changes)
    return dash


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="忽略时间窗口，立刻运行")
    p.add_argument("--no-email", action="store_true")
    args = p.parse_args()

    cfg = config.load_all()
    slot = current_slot(datetime.now(timezone.utc), cfg["settings"], cfg["events"].get("market_holidays", []))
    if slot is None and not args.force:
        log.info("当前不在更新窗口内，跳过")
        set_output("ran", "false")
        return
    run(slot or "manual", send_email=not args.no_email)
    set_output("ran", "true")


if __name__ == "__main__":
    main()
