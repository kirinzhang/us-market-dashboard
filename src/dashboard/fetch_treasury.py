"""美国财政部官网的每日收益率曲线（免费、无需 key），在 FRED 拉不到时补上美债收益率和利差。"""

import io
import logging
from datetime import date

import pandas as pd
import requests

log = logging.getLogger(__name__)

_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        "daily-treasury-rates.csv/{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
_HEADERS = {"User-Agent": "Mozilla/5.0 (us-market-dashboard)"}

# 财政部 CSV 的列名 → FRED 序列代码
NOMINAL = {"3 Mo": "DGS3MO", "2 Yr": "DGS2", "10 Yr": "DGS10", "30 Yr": "DGS30"}
REAL = {"10 YR": "DFII10"}


def parse_csv(text: str, columns: dict[str, str]) -> dict[str, pd.Series]:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    lookup = {c.upper(): c for c in df.columns}
    idx = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    out = {}
    for col, sid in columns.items():
        real_col = lookup.get(col.upper())
        if real_col is None:
            continue
        s = pd.Series(pd.to_numeric(df[real_col], errors="coerce").values, index=idx, name=sid)
        out[sid] = s.dropna().sort_index()
    return out


def _fetch_kind(kind: str, columns: dict[str, str], years: list[int]) -> dict[str, pd.Series]:
    parts: dict[str, list[pd.Series]] = {}
    for y in years:
        resp = requests.get(_URL.format(year=y, kind=kind), headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        for sid, s in parse_csv(resp.text, columns).items():
            parts.setdefault(sid, []).append(s)
    return {sid: pd.concat(v).sort_index().loc[lambda s: ~s.index.duplicated()] for sid, v in parts.items()}


def fetch_yields(start: str, need: set[str]) -> tuple[dict[str, pd.Series], list[str]]:
    """只补 need 里缺的序列。返回（数据，警告）。"""
    years = list(range(pd.Timestamp(start).year, date.today().year + 1))
    data, warnings = {}, []
    jobs = [("daily_treasury_yield_curve", NOMINAL), ("daily_treasury_real_yield_curve", REAL)]
    for kind, columns in jobs:
        if not need & set(columns.values()):
            continue
        try:
            got = _fetch_kind(kind, columns, years)
            data.update({k: v for k, v in got.items() if k in need})
            log.info("财政部 %s：%s", kind, "、".join(got))
        except Exception as err:
            warnings.append(f"财政部收益率备用源失败（{kind}）：{err}")
    if "DGS10" in data and "DGS2" in data and "T10Y2Y" in need:
        data["T10Y2Y"] = (data["DGS10"] - data["DGS2"]).dropna()
    if "DGS10" in data and "DGS3MO" in data and "T10Y3M" in need:
        data["T10Y3M"] = (data["DGS10"] - data["DGS3MO"]).dropna()
    return data, warnings
