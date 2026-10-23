import numpy as np
import pandas as pd
import yaml

from dashboard import regime
from dashboard.config import CONFIG_DIR

CFG = yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))
DAYS = pd.bdate_range("2024-01-01", periods=400)


def calm_inputs():
    weds = DAYS[DAYS.weekday == 2]
    return {
        "net_liq": pd.Series(np.linspace(5_500, 5_800, len(weds)), index=weds),
        "hy_oas": pd.Series(3.0, index=DAYS),
        "dxy": pd.Series(100.0, index=DAYS),
        "vix": pd.Series(14.0, index=DAYS),
        "vix3m": pd.Series(17.0, index=DAYS),
        "spx": pd.Series(np.linspace(4_000, 6_000, len(DAYS)), index=DAYS),
        "breadth50": pd.Series(65.0, index=DAYS),
        "usdjpy": pd.Series(150.0, index=DAYS),
    }


def test_calm_market_is_green():
    r = regime.evaluate_liquidity(calm_inputs(), CFG)
    assert r["state"] == "green"
    assert not any(c["triggered"] for c in r["hard"])


def test_vix_inversion_hard_switch_is_red():
    d = calm_inputs()
    vix = d["vix"].copy()
    vix.iloc[-3:] = 25.0
    d["vix"] = vix
    r = regime.evaluate_liquidity(d, CFG)
    assert r["state"] == "red"
    assert any(c["key"] == "vix_inversion" and c["triggered"] for c in r["hard"])


def test_two_soft_signals_is_yellow():
    d = calm_inputs()
    hy = d["hy_oas"].copy()
    hy.iloc[-10:] = 3.5
    dxy = d["dxy"].copy()
    dxy.iloc[-5:] = 103.0
    d["hy_oas"], d["dxy"] = hy, dxy
    assert regime.evaluate_liquidity(d, CFG)["state"] == "yellow"


def test_missing_data_does_not_crash():
    r = regime.evaluate_liquidity({}, CFG)
    assert r["state"] == "green"
    assert all(c["triggered"] is None for c in r["soft"])


def test_theme_red_when_out_of_top_and_below_50dma():
    rank = pd.Series([1.0] * 380 + [9.0] * 20, index=DAYS)
    idx = pd.Series(np.r_[np.linspace(100, 200, 350), np.linspace(200, 150, 50)], index=DAYS)
    share = pd.Series(np.r_[np.full(370, 0.05), np.linspace(0.05, 0.03, 30)], index=DAYS)
    r = regime.evaluate_theme("AI", rank, idx, share, 0.4, CFG)
    assert r["state"] == "red"


def test_theme_green_when_leading():
    rank = pd.Series(1.0, index=DAYS)
    idx = pd.Series(np.linspace(100, 200, 400), index=DAYS)
    share = pd.Series(np.linspace(0.03, 0.05, 400), index=DAYS)
    assert regime.evaluate_theme("AI", rank, idx, share, 0.5, CFG)["state"] == "green"


def test_action_matrix():
    assert regime.decide_action("green", "green")["stage"] == "进攻"
    assert regime.decide_action("yellow", "green")["stage"] == "谨慎持有"
    assert regime.decide_action("green", "red")["stage"] == "防守持有"
    assert regime.decide_action("red", "yellow")["stage"] == "换主线"
    assert regime.decide_action("red", "red")["stage"] == "清仓"
