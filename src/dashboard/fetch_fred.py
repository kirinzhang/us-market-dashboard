"""从 FRED 拉宏观序列。默认用公开 CSV（无需 key），设置了 FRED_API_KEY 时改用官方 API。"""

import io
import logging
import os
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)

FRED_SERIES = {
    "WALCL": "美联储总资产",
    "WTREGEN": "财政部 TGA 账户",
    "RRPONTSYD": "隔夜逆回购",
    "WRESBAL": "银行准备金",
    "DGS3MO": "3个月美债",
    "DGS2": "2年美债",
    "DGS10": "10年美债",
    "DGS30": "30年美债",
    "T10Y2Y": "10Y-2Y 利差",
    "T10Y3M": "10Y-3M 利差",
    "DFII10": "10年实际利率",
    "T10YIE": "10年盈亏平衡通胀",
    "BAMLH0A0HYM2": "高收益债利差",
    "BAMLC0A0CM": "投资级利差",
    "NFCI": "芝加哥联储金融条件",
    "SOFR": "SOFR",
    "IORB": "准备金利率 IORB",
    "DTWEXBGS": "广义美元指数（美元指数备用）",
    "DEXJPUS": "美元/日元（备用）",
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (us-market-dashboard)"}


def _fetch_csv(series_id: str, start: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    date_col = df.columns[0]
    values = pd.to_numeric(df[series_id], errors="coerce")
    return pd.Series(values.values, index=pd.to_datetime(df[date_col]), name=series_id).dropna()


def _fetch_api(series_id: str, start: str, key: str) -> pd.Series:
    resp = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": key, "file_type": "json", "observation_start": start},
        timeout=30,
    )
    resp.raise_for_status()
    obs = resp.json()["observations"]
    s = pd.Series(
        pd.to_numeric([o["value"] for o in obs], errors="coerce"),
        index=pd.to_datetime([o["date"] for o in obs]),
        name=series_id,
    )
    return s.dropna()


def fetch_series(series_id: str, start: str) -> pd.Series:
    key = os.environ.get("FRED_API_KEY")
    last_err = None
    for attempt in range(2):
        try:
            return _fetch_api(series_id, start, key) if key else _fetch_csv(series_id, start)
        except Exception as err:  # 网络抖动重试
            last_err = err
            time.sleep(3)
    raise RuntimeError(f"FRED {series_id} 拉取失败: {last_err}")


def fetch_all(start: str) -> tuple[dict[str, pd.Series], list[str]]:
    data, warnings = {}, []
    failures = 0
    for sid in FRED_SERIES:
        if failures >= 3 and not data:
            warnings.append("FRED 连续 3 个序列拉取失败，跳过其余序列")
            break
        try:
            data[sid] = fetch_series(sid, start)
            log.info("FRED %s：%d 条，最新 %s", sid, len(data[sid]), data[sid].index[-1].date())
        except Exception as err:
            failures += 1
            log.warning("%s", err)
            warnings.append(str(err))
    return data, warnings
