"""指标计算。只依赖 pandas，方便用合成数据测试。"""

import math

import numpy as np
import pandas as pd

PERIODS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63}


# ---------- 通用工具 ----------

def to_billions(s: pd.Series) -> pd.Series:
    """FRED 的资产负债表序列有的以百万美元计、有的以十亿计，统一成十亿。"""
    s = s.dropna()
    return s / 1000 if not s.empty and s.abs().median() > 50_000 else s


def pct_rank(s: pd.Series, window: int = 756) -> float | None:
    """最新值在过去 window 个观测中的分位数（0~1）。"""
    s = s.dropna().iloc[-window:]
    if len(s) < 20:
        return None
    return float((s <= s.iloc[-1]).mean())


def change(s: pd.Series, days: int, mode: str) -> float | None:
    """按日历天数回看的变化；mode = diff（差值）或 pct（百分比）。"""
    s = s.dropna()
    if s.empty:
        return None
    past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
    if past.empty:
        return None
    a, b = past.iloc[-1], s.iloc[-1]
    if mode == "pct":
        return float((b / a - 1) * 100) if a else None
    return float(b - a)


def consecutive_tail(flags: pd.Series) -> int:
    """序列末尾连续为 True 的个数。"""
    n = 0
    for v in reversed(flags.dropna().tolist()):
        if not v:
            break
        n += 1
    return n


def spark(s: pd.Series, points: int = 260, digits: int = 3) -> list:
    s = s.dropna().iloc[-points:]
    return [[d.strftime("%Y-%m-%d"), round(float(v), digits)] for d, v in s.items()]


def card(s: pd.Series, name: str, unit: str = "", mode: str = "pct", risk: str | None = None,
         digits: int = 2) -> dict:
    """指标卡片：最新值、1周/1月变化、3年分位、走势、着色。

    risk="up_is_risk_on"  上升利好风险资产（如净流动性、股指）
    risk="up_is_risk_off" 上升利空风险资产（如 VIX、信用利差、美元）
    """
    s = s.dropna()
    if s.empty:
        return {"name": name, "value": None}
    chg_1m = change(s, 30, mode)
    tone = "neutral"
    if risk and chg_1m is not None and chg_1m != 0:
        up = chg_1m > 0
        tone = "good" if up == (risk == "up_is_risk_on") else "bad"
    return {
        "name": name,
        "unit": unit,
        "mode": mode,
        "risk": risk,
        "value": round(float(s.iloc[-1]), digits),
        "date": s.index[-1].strftime("%Y-%m-%d"),
        "chg_1w": _r(change(s, 7, mode), digits),
        "chg_1m": _r(chg_1m, digits),
        "pct_3y": _r(pct_rank(s), 2),
        "tone": tone,
        "spark": spark(s, 260, digits + 1),
    }


def _r(v, digits):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v, digits)


# ---------- 流动性 ----------

def net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series) -> pd.Series:
    """净流动性 = 美联储总资产 − TGA − 逆回购（十亿美元，周三口径）。"""
    w, t, r = to_billions(walcl), to_billions(tga), to_billions(rrp)
    start = max(w.index.min(), t.index.min(), r.index.min())
    end = max(w.index.max(), t.index.max(), r.index.max())
    days = pd.date_range(start, end, freq="D")
    df = pd.DataFrame({"w": w, "t": t, "r": r}).reindex(days).ffill()
    nl = (df["w"] - df["t"] - df["r"]).dropna()
    return nl[nl.index.weekday == 2]


# ---------- 主题与轮动 ----------

def basket_index(close: pd.DataFrame, members: list[str]) -> pd.Series:
    cols = [m for m in members if m in close.columns]
    if not cols:
        return pd.Series(dtype=float)
    rets = close[cols].pct_change(fill_method=None)
    eq = rets.mean(axis=1, skipna=True).fillna(0)
    idx = (1 + eq).cumprod() * 100
    first = close[cols].dropna(how="all").index.min()
    return idx[idx.index >= first]


def period_returns(s: pd.Series, bench: pd.Series | None = None) -> dict:
    out = {}
    s = s.dropna()
    for label, n in PERIODS.items():
        if len(s) <= n:
            out[label] = None
            continue
        r = s.iloc[-1] / s.iloc[-1 - n] - 1
        if bench is not None:
            b = bench.reindex(s.index).ffill()
            r -= b.iloc[-1] / b.iloc[-1 - n] - 1
        out[label] = round(float(r) * 100, 2)
    return out


def strength_score(idx: pd.DataFrame, bench: pd.Series) -> pd.DataFrame:
    """每日主题强度 = 20 日与 60 日超额收益的平均。"""
    b = bench.reindex(idx.index).ffill()
    ex20 = idx.pct_change(20, fill_method=None).sub(b.pct_change(20, fill_method=None), axis=0)
    ex60 = idx.pct_change(60, fill_method=None).sub(b.pct_change(60, fill_method=None), axis=0)
    return (ex20 + ex60) / 2


def rrg(idx: pd.Series, bench: pd.Series, tail: int = 8) -> list[dict]:
    """相对轮动图（简化 JdK）：周线，RS-Ratio 与 RS-Momentum 都以 100 为中心。"""
    df = pd.DataFrame({"a": idx, "b": bench}).dropna()
    wk = df.resample("W-FRI").last().dropna()
    rs = wk["a"] / wk["b"]
    ratio = 100 * rs / rs.ewm(span=10, adjust=False).mean()
    mom = 100 * ratio / ratio.rolling(5).mean()
    out = pd.DataFrame({"x": ratio, "y": mom}).dropna().iloc[-tail:]
    return [{"date": d.strftime("%Y-%m-%d"), "x": round(float(r.x), 2), "y": round(float(r.y), 2)}
            for d, r in out.iterrows()]


def rrg_quadrant(x: float, y: float) -> str:
    if x >= 100 and y >= 100:
        return "领先"
    if x >= 100:
        return "转弱"
    if y >= 100:
        return "改善"
    return "落后"


def dollar_volume_share(close: pd.DataFrame, volume: pd.DataFrame, members: list[str],
                        market_total: pd.Series) -> pd.Series:
    cols = [m for m in members if m in close.columns and m in volume.columns]
    if not cols:
        return pd.Series(dtype=float)
    dv = (close[cols] * volume[cols]).sum(axis=1, min_count=1)
    share = dv / market_total.reindex(dv.index)
    return share.replace([np.inf, -np.inf], np.nan).rolling(20).mean()


def crowding(idx: pd.Series, close: pd.DataFrame, members: list[str], share20: pd.Series) -> dict:
    """拥挤度：与 200 日线乖离的分位、成分股站上 20 日线比例、成交额占比分位，三者平均。"""
    parts = {}
    sma200 = idx.rolling(200).mean()
    dist = (idx / sma200 - 1).dropna()
    parts["dist200_pct"] = pct_rank(dist)
    cols = [m for m in members if m in close.columns]
    if cols:
        last = close[cols].iloc[-1]
        sma20 = close[cols].rolling(20).mean().iloc[-1]
        ok = sma20.notna() & last.notna()
        parts["above20"] = float((last[ok] > sma20[ok]).mean()) if ok.any() else None
    parts["share_pct"] = pct_rank(share20, 252) if not share20.dropna().empty else None
    vals = [v for v in parts.values() if v is not None]
    parts["score"] = round(sum(vals) / len(vals), 2) if vals else None
    return parts


# ---------- 市场宽度 ----------

def breadth(close: pd.DataFrame, window: int) -> pd.Series:
    sma = close.rolling(window).mean()
    valid = sma.notna() & close.notna()
    above = (close > sma) & valid
    count = valid.sum(axis=1)
    return (above.sum(axis=1) / count.where(count > 0) * 100).dropna()
