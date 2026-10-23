"""判断这次定时任务对应哪个时段。

GitHub Actions 的 cron 只认 UTC，所以 workflow 里为夏令时和冬令时各排了一次，
这里按美东时间筛掉不在窗口内的那一次，并跳过周末和休市日。
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def current_slot(now_utc: datetime, settings: dict, holidays: list) -> str | None:
    sc = settings["schedule"]
    tz = ZoneInfo(sc["timezone"])
    now = now_utc.astimezone(tz)
    if now.weekday() >= 5:
        return None
    holiday_set = {d if isinstance(d, date) else date.fromisoformat(str(d)) for d in holidays}
    if now.date() in holiday_set:
        return None
    for slot, hhmm in sc["slots"].items():
        h, m = map(int, hhmm.split(":"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target - timedelta(minutes=sc["early_minutes"]) <= now <= target + timedelta(minutes=sc["late_minutes"]):
            return slot
    return None
