"""阶段判断：叙事开关 + 流动性开关 + 硬性风控开关。阈值见 config/settings.yaml。"""

import pandas as pd

from .indicators import consecutive_tail

GREEN, YELLOW, RED = "green", "yellow", "red"


def _check(key: str, name: str, triggered: bool | None, detail: str) -> dict:
    return {"key": key, "name": name, "triggered": triggered, "detail": detail}


def _diff(s: pd.Series | None, n: int) -> float | None:
    if s is None:
        return None
    s = s.dropna()
    return float(s.iloc[-1] - s.iloc[-1 - n]) if len(s) > n else None


def _pct(s: pd.Series | None, n: int) -> float | None:
    if s is None:
        return None
    s = s.dropna()
    return float((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100) if len(s) > n else None


def evaluate_liquidity(d: dict, cfg: dict) -> dict:
    """d 需要的键：net_liq（周）、hy_oas、dxy、vix、vix3m、spx、breadth50、usdjpy（日）。缺失的项跳过。"""
    lc, hc = cfg["liquidity"], cfg["hard_switches"]
    soft, hard = [], []

    weeks = lc["net_liquidity_weeks"]
    nl_chg = _diff(d.get("net_liq"), weeks)
    soft.append(_check("net_liq", f"净流动性 {weeks} 周变化",
                       None if nl_chg is None else nl_chg < 0,
                       "无数据" if nl_chg is None else f"{nl_chg:+,.0f} 十亿美元"))

    hy20 = _diff(d.get("hy_oas"), 20)
    soft.append(_check("hy_widen", "高收益债利差 20 日变化",
                       None if hy20 is None else hy20 > lc["hy_oas_widen_pp"],
                       "无数据" if hy20 is None else f"{hy20:+.2f} 个百分点"))

    dxy20 = _pct(d.get("dxy"), 20)
    soft.append(_check("dxy_up", "美元指数 20 日涨幅",
                       None if dxy20 is None else dxy20 > lc["dxy_up_pct"],
                       "无数据" if dxy20 is None else f"{dxy20:+.2f}%"))

    hard.append(_check("hy_spike", f"HY 利差 20 日走阔 ≥ {hc['hy_oas_spike_pp']:.2f}pp",
                       None if hy20 is None else hy20 >= hc["hy_oas_spike_pp"],
                       "无数据" if hy20 is None else f"{hy20:+.2f}pp"))

    vix, vix3m = d.get("vix"), d.get("vix3m")
    if vix is not None and vix3m is not None:
        ratio = (vix / vix3m.reindex(vix.index)).dropna()
        days = consecutive_tail(ratio > 1)
        hard.append(_check("vix_inversion", f"VIX 期限结构倒挂 ≥ {hc['vix_term_inversion_days']} 天",
                           days >= hc["vix_term_inversion_days"],
                           f"VIX/VIX3M = {ratio.iloc[-1]:.2f}，连续倒挂 {days} 天"))
    else:
        hard.append(_check("vix_inversion", "VIX 期限结构倒挂", None, "无数据"))

    spx, b50 = d.get("spx"), d.get("breadth50")
    if spx is not None and b50 is not None and len(spx.dropna()) >= 200 and not b50.empty:
        below200 = bool(spx.dropna().iloc[-1] < spx.dropna().rolling(200).mean().iloc[-1])
        weak = float(b50.iloc[-1]) < hc["breadth_floor_pct"]
        hard.append(_check("trend_breadth", f"标普跌破 200 日线且宽度 < {hc['breadth_floor_pct']}%",
                           below200 and weak,
                           f"{'低于' if below200 else '高于'} 200 日线，站上 50 日线比例 {b50.iloc[-1]:.0f}%"))
    else:
        hard.append(_check("trend_breadth", "标普跌破 200 日线且宽度不足", None, "无数据"))

    jpy5 = _pct(d.get("usdjpy"), 5)
    hard.append(_check("carry_unwind", f"美元/日元 5 日跌幅 ≥ {hc['usdjpy_drop_pct']:.0f}%",
                       None if jpy5 is None else jpy5 <= -hc["usdjpy_drop_pct"],
                       "无数据" if jpy5 is None else f"{jpy5:+.2f}%"))

    n_soft = sum(1 for c in soft if c["triggered"])
    fired = [c for c in hard if c["triggered"]]
    if fired or n_soft >= 3:
        state = RED
    elif n_soft == 2:
        state = YELLOW
    else:
        state = GREEN
    reasons = [c["name"] + "：" + c["detail"] for c in fired + [c for c in soft if c["triggered"]]]
    return {"state": state, "soft": soft, "hard": hard, "reasons": reasons}


def evaluate_theme(name: str, rank: pd.Series, idx: pd.Series, share20: pd.Series,
                   crowd: float | None, cfg: dict) -> dict:
    nc = cfg["narrative"]
    top_n = nc["top_n"]
    rank = rank.dropna()
    days_out = consecutive_tail(rank > top_n) if not rank.empty else 0
    cur_rank = int(rank.iloc[-1]) if not rank.empty else None

    idx = idx.dropna()
    sma50 = idx.rolling(50).mean()
    below50 = bool(idx.iloc[-1] < sma50.iloc[-1]) if len(idx) >= 50 else None

    s = share20.dropna()
    share_down = bool(s.iloc[-1] < s.iloc[-21]) if len(s) > 21 else None

    checks = [
        _check("rank", f"强度排名跌出前 {top_n}", days_out > 0,
               f"当前第 {cur_rank} 名，已连续 {days_out} 天在前 {top_n} 之外" if cur_rank else "无数据"),
        _check("below50", "主题指数跌破 50 日线", below50, "无数据" if below50 is None else ("是" if below50 else "否")),
        _check("share_down", "成交额占比 20 日下降", share_down,
               "无数据" if share_down is None else ("是" if share_down else "否")),
        _check("crowding", f"拥挤度 ≥ {nc['crowding_yellow']}",
               None if crowd is None else crowd >= nc["crowding_yellow"],
               "无数据" if crowd is None else f"{crowd:.2f}"),
    ]

    if days_out >= nc["red_days_out_of_top"] and below50 and share_down is not False:
        state = RED
    elif (days_out >= nc["yellow_days_out_of_top"] or below50
          or (crowd is not None and crowd >= nc["crowding_yellow"])):
        state = YELLOW
    else:
        state = GREEN
    reasons = [c["name"] + "：" + c["detail"] for c in checks if c["triggered"]]
    return {"theme": name, "state": state, "rank": cur_rank, "days_out_of_top": days_out,
            "checks": checks, "reasons": reasons}


def evaluate_narrative(themes: list[dict]) -> dict:
    """叙事开关看你持有的第一个主线；其余主线作为参考列出。"""
    if not themes:
        return {"state": YELLOW, "primary": None, "themes": [], "reasons": ["未配置持有主线"]}
    primary = themes[0]
    return {"state": primary["state"], "primary": primary["theme"], "themes": themes,
            "reasons": primary["reasons"]}


def decide_action(narrative: str, liquidity: str) -> dict:
    n_ok, l_ok = narrative != RED, liquidity != RED
    if n_ok and l_ok:
        if narrative == GREEN and liquidity == GREEN:
            return {"stage": "进攻", "action": "持有，允许在主线内加仓", "position": "80–100%"}
        return {"stage": "谨慎持有", "action": "持有，不追高；关注黄灯项，加仓只加回调", "position": "60–80%"}
    if n_ok:
        return {"stage": "防守持有", "action": "持有但不加仓，收紧止损，先减杠杆 ETF 和期权", "position": "40–60%"}
    if l_ok:
        return {"stage": "换主线", "action": "减掉旧主线，关注轮动图领先/改善象限的新主题", "position": "40–60%"}
    return {"stage": "清仓", "action": "叙事和流动性都转红：按你的规则清仓", "position": "0–20%"}
