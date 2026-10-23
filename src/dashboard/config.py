from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
SITE_DATA_DIR = ROOT / "site" / "data"
STATE_DIR = ROOT / "state"


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_all() -> dict:
    return {
        "universe": load_yaml("universe.yaml"),
        "settings": load_yaml("settings.yaml"),
        "events": load_yaml("events.yaml"),
    }


def all_market_tickers(universe: dict) -> list[str]:
    """关注范围内所有需要拉行情的代码（去重，保持顺序）。"""
    tickers: list[str] = [universe["benchmark"]]
    tickers += universe.get("broad_etfs", [])
    tickers += [x["ticker"] for x in universe.get("indices", [])]
    tickers += [x["ticker"] for x in universe.get("macro_assets", [])]
    tickers += list(universe.get("sectors", {}).keys())
    for style in universe.get("styles", []):
        tickers += [style["num"], style["den"]]
    for members in universe.get("themes", {}).values():
        tickers += members
    tickers += universe.get("watchlist", [])
    tickers += universe.get("leveraged", [])
    tickers += universe.get("options", [])
    return list(dict.fromkeys(tickers))
