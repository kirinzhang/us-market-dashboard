import numpy as np
import pandas as pd

from dashboard import indicators as ind


def test_to_billions_detects_millions():
    s = pd.Series([6_600_000.0, 6_610_000.0])
    assert ind.to_billions(s).iloc[-1] == 6_610.0
    rrp = pd.Series([120.0, 80.0])
    assert ind.to_billions(rrp).iloc[-1] == 80.0


def test_net_liquidity_weekly_and_units():
    days = pd.date_range("2026-01-01", "2026-03-31", freq="D")
    weds = days[days.weekday == 2]
    walcl = pd.Series(6_600_000.0, index=weds)
    tga = pd.Series(800_000.0, index=weds)
    rrp = pd.Series(100.0, index=days)
    nl = ind.net_liquidity(walcl, tga, rrp)
    assert (nl.index.weekday == 2).all()
    assert nl.iloc[-1] == 6_600 - 800 - 100


def test_consecutive_tail():
    assert ind.consecutive_tail(pd.Series([True, False, True, True])) == 2
    assert ind.consecutive_tail(pd.Series([True, False])) == 0


def test_pct_rank_and_change():
    idx = pd.bdate_range("2025-01-01", periods=100)
    s = pd.Series(np.arange(100, dtype=float), index=idx)
    assert ind.pct_rank(s) == 1.0
    assert ind.change(s, 7, "diff") == 5.0


def test_period_returns_excess():
    idx = pd.bdate_range("2025-01-01", periods=70)
    a = pd.Series(np.linspace(100, 120, 70), index=idx)
    b = pd.Series(np.linspace(100, 110, 70), index=idx)
    r = ind.period_returns(a, b)
    assert r["1M"] > 0 and r["3M"] > 0


def test_breadth():
    idx = pd.bdate_range("2025-01-01", periods=60)
    up = pd.Series(np.linspace(10, 20, 60), index=idx)
    down = pd.Series(np.linspace(20, 10, 60), index=idx)
    b = ind.breadth(pd.DataFrame({"A": up, "B": down}), 50)
    assert b.iloc[-1] == 50.0


def test_rrg_quadrants():
    assert ind.rrg_quadrant(101, 101) == "领先"
    assert ind.rrg_quadrant(101, 99) == "转弱"
    assert ind.rrg_quadrant(99, 99) == "落后"
    assert ind.rrg_quadrant(99, 101) == "改善"


def test_rrg_leader_is_right_side():
    idx = pd.bdate_range("2025-01-01", periods=300)
    bench = pd.Series(np.linspace(100, 110, 300), index=idx)
    leader = pd.Series(100 * np.exp(np.linspace(0, 0.6, 300) ** 1.5), index=idx)
    tail = ind.rrg(leader, bench)
    assert len(tail) == 8 and tail[-1]["x"] > 100
