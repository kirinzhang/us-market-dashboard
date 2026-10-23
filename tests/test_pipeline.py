"""用合成数据跑通完整流程（不联网）。"""

import json

import synthetic
from dashboard import build, config, fetch_fred, fetch_market


def test_full_run_writes_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITE_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(fetch_fred, "fetch_all", synthetic.fake_fred)
    monkeypatch.setattr(fetch_market, "download_prices", synthetic.fake_prices)
    monkeypatch.setattr(fetch_market, "sp500_constituents", lambda: [f"S{i}" for i in range(60)])
    monkeypatch.setattr(fetch_market, "next_earnings", lambda t: "2026-11-19" if t == "NVDA" else None)
    monkeypatch.setattr(fetch_market, "option_snapshot", lambda t, spot: {
        "ticker": t, "expiry": "2026-11-20", "spot": spot, "pc_volume": 0.8, "pc_oi": 1.1,
        "atm_iv": 22.0, "max_pain": spot})

    build.run("manual", send_email=False)
    dash = json.loads((tmp_path / "data" / "dashboard.json").read_text(encoding="utf-8"))
    assert dash["regime"]["action"]["stage"]
    assert dash["regime"]["narrative"]["primary"] == "AI 算力"
    assert len(dash["rotation"]["themes"]) >= 10
    assert dash["charts"]["net_liq"] and dash["charts"]["breadth50"]
    assert (tmp_path / "data" / "prices" / "NVDA.json").exists()
    assert (tmp_path / "state" / "signal_log.csv").exists()

    # 第二次运行状态不变，不应新增日志
    build.run("manual", send_email=False)
    lines = (tmp_path / "state" / "signal_log.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
