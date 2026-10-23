import numpy as np
import pandas as pd

from dashboard import fetch_market, fetch_treasury, notify

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
