"""合成数据，用来在没有网络的情况下跑通整个流程。"""

import numpy as np
import pandas as pd

from dashboard.fetch_fred import FRED_SERIES


def business_days(years: int = 3) -> pd.DatetimeIndex:
    end = pd.Timestamp.today().normalize()
    return pd.bdate_range(end - pd.DateOffset(years=years), end)


def walk(n: int, start: float, vol: float, drift: float, rng) -> np.ndarray:
    return start * np.exp(np.cumsum(rng.normal(drift, vol, n)))


def fake_prices(tickers: list[str], period: str = "3y") -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(len(tickers))
    days = business_days(int(period[0]))
    close = pd.DataFrame({t: walk(len(days), 100, 0.015, 0.0004, rng) for t in tickers}, index=days)
    if "^VIX" in close:
        close["^VIX"] = 15 + 5 * np.sin(np.linspace(0, 12, len(days)))
        close["^VIX3M"] = 17 + 4 * np.sin(np.linspace(0, 12, len(days)))
    noise = lambda: 1 + rng.normal(0, 0.005, close.shape)  # noqa: E731
    return {
        "Open": close * noise(),
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": pd.DataFrame(rng.integers(1e6, 5e7, close.shape), index=days, columns=tickers).astype(float),
    }


def fake_fred(start: str) -> tuple[dict[str, pd.Series], list[str]]:
    rng = np.random.default_rng(7)
    days = business_days(4)
    weds = days[days.weekday == 2]
    out = {}
    for sid in FRED_SERIES:
        if sid == "WALCL":
            out[sid] = pd.Series(np.linspace(7_000_000, 6_600_000, len(weds)), index=weds)
        elif sid == "WTREGEN":
            out[sid] = pd.Series(800_000 + rng.normal(0, 30_000, len(weds)), index=weds)
        elif sid == "WRESBAL":
            out[sid] = pd.Series(3_200 + rng.normal(0, 50, len(weds)), index=weds)
        elif sid == "NFCI":
            out[sid] = pd.Series(-0.5 + rng.normal(0, 0.02, len(weds)), index=weds)
        elif sid == "RRPONTSYD":
            out[sid] = pd.Series(np.linspace(2000, 50, len(days)), index=days)
        else:
            base = {"BAMLH0A0HYM2": 3.0, "BAMLC0A0CM": 1.0, "T10Y2Y": 0.5, "T10Y3M": 0.3}.get(sid, 4.0)
            out[sid] = pd.Series(base + np.cumsum(rng.normal(0, 0.02, len(days))), index=days)
    return out, []
