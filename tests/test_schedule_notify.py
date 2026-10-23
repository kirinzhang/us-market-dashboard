from datetime import datetime, timezone

import yaml

from dashboard import notify
from dashboard.config import CONFIG_DIR
from dashboard.schedule import current_slot

CFG = yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_summer_time_slots():
    # 2026-10-22 周四，美东夏令时 UTC-4
    assert current_slot(utc(2026, 10, 22, 9, 30), CFG, []) == "premarket"
    assert current_slot(utc(2026, 10, 22, 10, 30), CFG, []) is None
    assert current_slot(utc(2026, 10, 22, 21, 0), CFG, []) == "postclose"
    assert current_slot(utc(2026, 10, 22, 22, 0), CFG, []) is None


def test_winter_time_slots():
    # 2026-12-02 周三，美东冬令时 UTC-5
    assert current_slot(utc(2026, 12, 2, 9, 30), CFG, []) is None
    assert current_slot(utc(2026, 12, 2, 10, 30), CFG, []) == "premarket"
    assert current_slot(utc(2026, 12, 2, 21, 0), CFG, []) is None
    assert current_slot(utc(2026, 12, 2, 22, 0), CFG, []) == "postclose"


def test_delayed_run_still_counts():
    assert current_slot(utc(2026, 10, 22, 21, 50), CFG, []) == "postclose"


def test_weekend_and_holiday_skip():
    assert current_slot(utc(2026, 10, 24, 21, 0), CFG, []) is None
    assert current_slot(utc(2026, 11, 26, 22, 0), CFG, ["2026-11-26"]) is None


def test_diff_states():
    assert notify.diff_states(None, {"liquidity": "green"}) == ["首次运行，以下为当前状态"]
    prev = {"liquidity": "green", "narrative": "green", "stage": "进攻", "hard": []}
    same = dict(prev)
    assert notify.diff_states(prev, same) == []
    cur = {"liquidity": "red", "narrative": "green", "stage": "防守持有", "hard": ["VIX 倒挂"]}
    changes = notify.diff_states(prev, cur)
    assert any("流动性开关" in c for c in changes)
    assert any("硬性风控开关触发" in c for c in changes)
