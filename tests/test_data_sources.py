import numpy as np
import pandas as pd

from dashboard import fetch_market, fetch_massive, fetch_treasury, notify

TREASURY_CSV = """Date,1 Mo,1.5 Month,2 Mo,3 Mo,4 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr
10/22/2026,4.10,4.08,4.05,4.00,3.95,3.90,3.80,3.50,3.55,3.70,3.85,4.10,4.50,4.60
10/21/2026,4.11,4.09,4.06,4.01,3.96,3.91,3.81,3.52,3.56,3.71,3.86,4.12,4.52,4.62
"""


def test_parse_treasury_csv():
    got = fetch_treasury.parse_csv(TREASURY_CSV, fetch_treasury.NOMINAL)
    assert set(got) == {"DGS3MO", "DGS2", "DGS10", "DGS30"}
    assert got["DGS10"].index[-1] == pd.Timestamp("2026-10-22")
    assert got["DGS2"].iloc[-1] == 3.50


def test_treasury_fallback_derives_spreads(monkeypatch):
    monkeypatch.setattr(fetch_treasury, "_fetch_kind",
                        lambda kind, cols, years: fetch_treasury.parse_csv(TREASURY_CSV, cols)
                        if kind == "daily_treasury_yield_curve" else {})
    data, warnings = fetch_treasury.fetch_yields("2026-01-01", {"DGS10", "DGS2", "DGS3MO", "T10Y2Y", "T10Y3M"})
    assert round(data["T10Y2Y"].iloc[-1], 2) == 0.60
    assert round(data["T10Y3M"].iloc[-1], 2) == 0.10
    assert warnings == []


def test_align_drops_weekend_and_premarket_rows():
    # 比特币周末和美股开盘前也有行，SPY 那几行是空的
    days = pd.date_range("2026-10-16", "2026-10-23")  # 周五到下周五，含周末
    spy = pd.Series(np.arange(len(days), dtype=float), index=days)
    spy[days.weekday >= 5] = np.nan
    spy.iloc[-1] = np.nan  # 当天还没开盘
    close = pd.DataFrame({"SPY": spy, "BTC-USD": 1.0}, index=days)
    out = fetch_market.align_to_trading_days({"Close": close, "Volume": close}, "SPY")
    assert list(out["Close"].index.weekday) == [4, 0, 1, 2, 3]
    assert out["Close"]["SPY"].notna().all()


def test_empty_smtp_port_uses_default(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.update(host=host, port=port)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a): pass
        def send_message(self, *a, **k): pass
        def sendmail(self, *a, **k): pass

    for k, v in {"SMTP_USER": "a@b.c", "SMTP_PASSWORD": "x", "MAIL_TO": "a@b.c", "SMTP_HOST": "", "SMTP_PORT": ""}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTP)
    assert notify.send("t", "b")
    assert sent == {"host": "smtp.gmail.com", "port": 465}


def _bars(n=30, base=100.0):
    start = pd.Timestamp("2026-09-01", tz="America/New_York")
    days = pd.bdate_range(start, periods=n)
    return [{"t": int(d.tz_convert("UTC").timestamp() * 1000), "o": base, "h": base + 1, "l": base - 1,
             "c": base + i, "v": 1000 + i} for i, d in enumerate(days)]


def test_parse_massive_aggs_dates_are_et_trading_days():
    df = fetch_massive.parse_aggs(_bars(3))
    assert list(df.index) == list(pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"]))
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df["Close"].iloc[-1] == 102.0


def test_massive_ticker_mapping():
    assert fetch_massive.to_massive("BRK-B") == "BRK.B"
    assert fetch_massive.supports("NVDA") and fetch_massive.supports("BRK-B")
    assert not any(fetch_massive.supports(t) for t in ["^GSPC", "CL=F", "BTC-USD", "DX-Y.NYB", "JPY=X"])


def test_router_uses_massive_then_cboe_then_yfinance(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "k")
    monkeypatch.setattr(fetch_massive, "daily_bars",
                        lambda t, s, e, k: fetch_massive.parse_aggs(_bars()) if t != "DEAD" else pd.DataFrame())
    vix = fetch_market.parse_cboe_csv("DATE,OPEN,HIGH,LOW,CLOSE\n" + "\n".join(
        f"{d:%m/%d/%Y},15,16,14,15.5" for d in pd.bdate_range("2026-09-01", periods=30)))
    monkeypatch.setattr(fetch_market, "cboe_index", lambda t: vix)
    asked = []

    def fake_yf(tickers, period):
        asked.extend(tickers)
        days = pd.bdate_range("2026-09-01", periods=30)
        frame = pd.DataFrame(1.0, index=days, columns=tickers)
        return {f: frame for f in fetch_market.FIELDS}

    monkeypatch.setattr(fetch_market, "yf_download_prices", fake_yf)
    fetch_market.SOURCES.clear()
    out = fetch_market.download_prices(["SPY", "NVDA", "DEAD", "^VIX", "^GSPC"], period="1y")
    assert sorted(asked) == ["DEAD", "^GSPC"]
    assert fetch_market.SOURCES["NVDA"] == "Massive"
    assert fetch_market.SOURCES["^VIX"] == "CBOE"
    assert fetch_market.SOURCES["^GSPC"] == "yfinance"
    assert set(out["Close"].columns) == {"SPY", "NVDA", "DEAD", "^VIX", "^GSPC"}


def test_router_falls_back_when_massive_key_rejected(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "bad")

    def denied(*a):
        raise fetch_massive.MassiveUnavailable("拒绝访问（403）")

    monkeypatch.setattr(fetch_massive, "daily_bars", denied)
    days = pd.bdate_range("2026-09-01", periods=30)
    monkeypatch.setattr(fetch_market, "yf_download_prices",
                        lambda tickers, period: {f: pd.DataFrame(1.0, index=days, columns=tickers) for f in fetch_market.FIELDS})
    fetch_market.SOURCES.clear()
    fetch_market.SOURCE_ERRORS.clear()
    out = fetch_market.download_prices(["SPY", "NVDA"], period="1y")
    assert set(out["Close"].columns) == {"SPY", "NVDA"}
    assert fetch_market.SOURCES["SPY"] == "yfinance"
    assert any("Massive" in e for e in fetch_market.SOURCE_ERRORS)
