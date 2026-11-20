"""Turn raw series into a snapshot: latest value plus the reference values used for
1-day, 1-week, 1-month, year-to-date and 1-year changes."""
from __future__ import annotations

import os

import pandas as pd

from . import config

PERIODS = ["1D", "1W", "1M", "YTD", "1Y"]


def _on_or_before(s: pd.Series, when: pd.Timestamp):
    s = s[s.index <= when]
    return (s.index[-1], float(s.iloc[-1])) if len(s) else (None, None)


def merge_fx_fallback(markets: pd.DataFrame, ecb: pd.DataFrame, errors: list[str]) -> pd.DataFrame:
    for key in config.ECB_FX:
        if (key not in markets or markets[key].dropna().empty) and key in ecb:
            markets[key] = ecb[key]
            errors.append(f"{key.upper()}: used ECB reference rate instead of Yahoo")
    return markets.sort_index()


def snapshot(markets: pd.DataFrame) -> list[dict]:
    rows = []
    for key, label, ticker, unit, kind, group in config.MARKETS:
        if key not in markets:
            continue
        s = markets[key].dropna()
        if len(s) < 2:
            continue
        d0, v0 = s.index[-1], float(s.iloc[-1])
        refs = {
            "1D": (s.index[-2], float(s.iloc[-2])),
            "1W": _on_or_before(s, d0 - pd.Timedelta(days=7)),
            "1M": _on_or_before(s, d0 - pd.DateOffset(months=1)),
            "YTD": _on_or_before(s, pd.Timestamp(d0.year - 1, 12, 31)),
            "1Y": _on_or_before(s, d0 - pd.DateOffset(years=1)),
        }
        chg = {}
        for p, (_, v) in refs.items():
            if v is None or v == 0:
                chg[p] = None
            else:
                chg[p] = (v0 - v) if kind == "yield" else (v0 / v - 1)
        rows.append(dict(key=key, label=label, ticker=ticker, unit=unit, kind=kind, group=group,
                         date=d0, value=v0, refs=refs, chg=chg))
    return rows


def update_history(path: str, run_date: str, snap: list[dict], sarb: list[dict]) -> pd.DataFrame:
    """Append today's values to a long CSV (date, series, value) kept in the repo."""
    new = [{"run_date": run_date, "series": r["label"], "value": round(r["value"], 6)} for r in snap]
    new += [{"run_date": run_date, "series": f"SARB: {x['name']}", "value": x["value"]} for x in sarb]
    df_new = pd.DataFrame(new)
    if os.path.exists(path):
        df = pd.concat([pd.read_csv(path), df_new], ignore_index=True)
    else:
        df = df_new
    df = df.drop_duplicates(["run_date", "series"], keep="last").sort_values(["run_date", "series"])
    df.to_csv(path, index=False)
    return df


def fmt_change(c, kind):
    if c is None:
        return "n/a"
    return f"{c:+.2f} pp" if kind == "yield" else f"{c * 100:+.1f}%"
