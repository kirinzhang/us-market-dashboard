"""Massive（原 Polygon.io）官方行情 API：美股和 ETF 的日线主数据源，需要 MASSIVE_API_KEY。

Stocks Starter 套餐不限调用次数，这里按代码逐个拉日线，8 线程并发。
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import requests

log = logging.getLogger(__name__)

BASES = ["https://api.massive.com", "https://api.polygon.io"]
FIELDS = {"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"}


def api_key() -> str | None:
    return os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY") or None


def supports(ticker: str) -> bool:
    """yfinance 风格的指数（^）、期货/外汇（=）、加密（-USD）和美元指数不走 Massive 股票接口。"""
    return not (ticker.startswith("^") or "=" in ticker or ticker.endswith("-USD") or ticker.endswith(".NYB"))


def to_massive(ticker: str) -> str:
    # 维基百科成分股里的 BRK-B 在 Massive 写作 BRK.B
    return ticker.replace("-", ".")


class MassiveUnavailable(Exception):
    """key 无效、套餐不含该数据或频率超限：整体放弃 Massive，交给 yfinance。"""


def _get(path: str, params: dict, key: str) -> dict:
    last_err = None
    for attempt in range(3):
        for base in BASES:
            try:
                resp = requests.get(base + path, params={**params, "apiKey": key}, timeout=20)
                if resp.status_code == 429:
                    if attempt:
                        raise MassiveUnavailable("调用频率超限（免费套餐每分钟只有 5 次，需要 Stocks Starter）")
                    last_err = "429 调用频率超限"
                    time.sleep(12)
                    continue
                if resp.status_code in (401, 403):
                    raise MassiveUnavailable(f"拒绝访问（{resp.status_code}）：{resp.text[:200]}")
                resp.raise_for_status()
                return resp.json()
            except MassiveUnavailable:
                raise
            except Exception as err:
                last_err = err
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Massive {path} 失败：{last_err}")


def parse_aggs(results: list[dict]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame(columns=list(FIELDS.values()))
    df = pd.DataFrame(results)
    # t 是该交易日美东 0 点对应的 UTC 毫秒
    idx = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    out = df.rename(columns=FIELDS)[list(FIELDS.values())]
    out.index = idx
    return out[~out.index.duplicated(keep="last")].sort_index()


def daily_bars(ticker: str, start: str, end: str, key: str) -> pd.DataFrame:
    data = _get(f"/v2/aggs/ticker/{to_massive(ticker)}/range/1/day/{start}/{end}",
                {"adjusted": "true", "sort": "asc", "limit": 50000}, key)
    return parse_aggs(data.get("results") or [])


def download_prices(tickers: list[str], start: str, key: str, workers: int = 8) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """返回（{字段: DataFrame(日期 × 代码)}，没拿到的代码）。"""
    end = date.today().isoformat()
    frames: dict[str, pd.DataFrame] = {}
    failed: list[str] = []

    stop = threading.Event()
    fatal: list[Exception] = []

    def one(t):
        if stop.is_set():
            return t, None
        try:
            return t, daily_bars(t, start, end, key)
        except MassiveUnavailable as err:
            stop.set()
            fatal.append(err)
            return t, None
        except Exception as err:
            log.warning("Massive %s：%s", t, err)
            return t, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (t, df) in enumerate(pool.map(one, tickers), 1):
            if df is None or df.empty:
                failed.append(t)
            else:
                frames[t] = df
            if i % 100 == 0:
                log.info("Massive 行情 %d / %d", i, len(tickers))
    if fatal:
        raise fatal[0]
    out = {}
    for f in FIELDS.values():
        if frames:
            out[f] = pd.DataFrame({t: df[f] for t, df in frames.items()}).sort_index()
    return out, failed
