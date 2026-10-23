"""行情数据：yfinance（免费，非官方接口，做了分批和重试）。"""

import io
import logging
import time
from datetime import date, datetime

import pandas as pd
import requests
import yfinance as yf

log = logging.getLogger(__name__)

FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def _download_chunk(tickers: list[str], period: str) -> pd.DataFrame:
    last_err = None
    for attempt in range(3):
        try:
            df = yf.download(
                tickers,
                period=period,
                interval="1d",
                auto_adjust=True,
                group_by="column",
                threads=True,
                progress=False,
                timeout=20,
            )
            if df is not None and not df.empty:
                return df
            last_err = "返回为空"
        except Exception as err:
            last_err = err
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"yfinance 下载失败 {tickers[:3]}…: {last_err}")


def download_prices(tickers: list[str], period: str = "3y", chunk: int = 80) -> dict[str, pd.DataFrame]:
    """返回 {字段: DataFrame(日期 × 代码)}。下载失败的代码会被丢弃。"""
    frames: dict[str, list[pd.DataFrame]] = {f: [] for f in FIELDS}
    for i in range(0, len(tickers), chunk):
        part = tickers[i : i + chunk]
        log.info("行情 %d-%d / %d", i + 1, i + len(part), len(tickers))
        df = _download_chunk(part, period)
        if not isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_product([df.columns, part])
        for f in FIELDS:
            if f in df.columns.get_level_values(0):
                frames[f].append(df[f])
        if i + chunk < len(tickers):
            time.sleep(2)
    out = {}
    for f, parts in frames.items():
        if parts:
            merged = pd.concat(parts, axis=1)
            merged = merged.loc[:, ~merged.columns.duplicated()]
            merged.index = pd.to_datetime(merged.index).tz_localize(None)
            out[f] = merged.sort_index()
    if "Close" in out:
        valid = out["Close"].columns[out["Close"].notna().sum() > 20]
        out = {f: d.reindex(columns=valid) for f, d in out.items()}
    return out


def align_to_trading_days(prices: dict[str, pd.DataFrame], benchmark: str) -> dict[str, pd.DataFrame]:
    """只保留基准有收盘价的美股交易日。比特币等 7×24 资产会带来周末行和盘前空行，会把滚动窗口和涨跌幅算错。"""
    days = prices["Close"].index[prices["Close"][benchmark].notna()]
    return {f: d.reindex(days) for f, d in prices.items()}


def sp500_constituents() -> list[str]:
    """标普 500 成分股（维基百科），用于计算市场宽度。"""
    html = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers={"User-Agent": "Mozilla/5.0 (us-market-dashboard)"},
        timeout=30,
    ).text
    table = pd.read_html(io.StringIO(html))[0]
    return sorted(table["Symbol"].astype(str).str.replace(".", "-", regex=False).unique().tolist())


def option_snapshot(ticker: str, spot: float | None) -> dict:
    """取约 2~6 周后到期的那一期期权，算 Put/Call、平值隐含波动率和最大痛点。"""
    tk = yf.Ticker(ticker)
    expiries = list(tk.options or [])
    today = date.today()
    chosen = None
    for exp in expiries:
        days = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        if days >= 14:
            chosen = exp
            break
    if chosen is None and expiries:
        chosen = expiries[-1]
    if chosen is None:
        raise RuntimeError(f"{ticker} 无期权数据")
    chain = tk.option_chain(chosen)
    calls, puts = chain.calls.fillna(0), chain.puts.fillna(0)
    if spot is None:
        spot = float(tk.fast_info["last_price"])

    def _sum(df, col):
        return float(df[col].sum()) if col in df else 0.0

    def _atm_iv(df):
        if df.empty:
            return None
        row = df.iloc[(df["strike"] - spot).abs().argsort().iloc[0]]
        return float(row["impliedVolatility"]) * 100

    strikes = sorted(set(calls["strike"]).union(puts["strike"]))
    pain = []
    for k in strikes:
        call_loss = ((k - calls["strike"]).clip(lower=0) * calls["openInterest"]).sum()
        put_loss = ((puts["strike"] - k).clip(lower=0) * puts["openInterest"]).sum()
        pain.append((call_loss + put_loss, k))
    max_pain = min(pain)[1] if pain else None

    call_vol, put_vol = _sum(calls, "volume"), _sum(puts, "volume")
    call_oi, put_oi = _sum(calls, "openInterest"), _sum(puts, "openInterest")
    ivs = [v for v in (_atm_iv(calls), _atm_iv(puts)) if v]
    return {
        "ticker": ticker,
        "expiry": chosen,
        "spot": spot,
        "pc_volume": put_vol / call_vol if call_vol else None,
        "pc_oi": put_oi / call_oi if call_oi else None,
        "atm_iv": sum(ivs) / len(ivs) if ivs else None,
        "max_pain": max_pain,
    }


def next_earnings(ticker: str) -> str | None:
    cal = yf.Ticker(ticker).calendar
    dates = []
    if isinstance(cal, dict):
        dates = cal.get("Earnings Date") or []
    elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
        dates = list(cal.loc["Earnings Date"].values)
    dates = [pd.Timestamp(d).date() for d in dates if d is not None]
    future = sorted(d for d in dates if d >= date.today())
    return future[0].isoformat() if future else None
