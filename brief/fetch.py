"""Pull free, key-less data: Yahoo Finance (markets), ECB via Frankfurter (rand fallback),
the South African Reserve Bank web API (policy rates, CPI, bond yields) and news RSS feeds.
Every fetch is retried and failures are recorded, never raised, so one bad source can't
stop the brief."""
from __future__ import annotations

import datetime as dt
import re
import time
from email.utils import parsedate_to_datetime

import pandas as pd
import requests

from . import config

UA = {"User-Agent": "Mozilla/5.0 (sa-macro-brief; +https://github.com/sihlangu-mthembu/sa-macro-brief)"}
SAST = dt.timezone(dt.timedelta(hours=2))


def _get(url, *, params=None, tries=4, timeout=25):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:  # network blip
            last = type(e).__name__
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url.split('?')[0]}: {last}")


# ---------------------------------------------------------------- markets
def fetch_markets(errors: list[str]) -> pd.DataFrame:
    """Daily closes for ~13 months, one column per key in config.MARKETS."""
    import yfinance as yf

    cols = {}
    for key, label, ticker, *_ in config.MARKETS:
        s = None
        for attempt in range(3):
            try:
                h = yf.Ticker(ticker).history(period="400d", interval="1d", auto_adjust=False)
                if not h.empty:
                    s = h["Close"].dropna()
                    s.index = pd.to_datetime(s.index.date)
                    break
            except Exception as e:  # yfinance raises many types
                err = type(e).__name__
            time.sleep(2 * (attempt + 1))
        if s is None or s.empty:
            errors.append(f"Yahoo Finance: no data for {label} ({ticker})")
            continue
        cols[key] = s[~s.index.duplicated(keep="last")]
    df = pd.DataFrame(cols).sort_index()
    df.index.name = "date"
    return df


def fetch_ecb_fx(start: dt.date, errors: list[str]) -> pd.DataFrame:
    """ECB reference rates, rand per USD/EUR/GBP (fallback and cross-check)."""
    try:
        r = _get(f"{config.FRANKFURTER_URL}/{start.isoformat()}..", params={"from": "ZAR", "to": "USD,EUR,GBP"})
        rates = r.json()["rates"]
    except Exception as e:
        errors.append(f"ECB/Frankfurter FX: {e}")
        return pd.DataFrame()
    rows = {pd.Timestamp(d): {k: 1 / v[c] for k, c in config.ECB_FX.items() if v.get(c)} for d, v in rates.items()}
    df = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    df.index.name = "date"
    return df


# ---------------------------------------------------------------- SARB
def fetch_sarb(errors: list[str]) -> list[dict]:
    try:
        items = _get(config.SARB_URL).json()
    except Exception as e:
        errors.append(f"SARB web API: {e}")
        return []
    out = []
    for it in items:
        low = {k.lower(): v for k, v in it.items()}
        try:
            value = float(low.get("value"))
        except (TypeError, ValueError):
            continue
        name = str(low.get("name", "")).strip()
        date = str(low.get("date", ""))[:10]
        out.append({
            "name": name,
            "value": value,
            "date": date,
            "section": str(low.get("sectionname") or "").strip(),
            "code": str(low.get("timeseriescode") or "").strip(),
            "unit": "index" if "index" in name.lower() or "effective" in name.lower()
                    else ("R" if name.lower().startswith("rand per") else "%"),
        })
    if not out:
        errors.append("SARB web API: empty response")
    return out


# ---------------------------------------------------------------- news
def _tags(title: str) -> list[str]:
    t = title.lower()
    return [tag for tag, words in config.NEWS_TAGS.items()
            if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t) for w in words)]


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower())[:70]


def fetch_news(now: dt.datetime, errors: list[str], hours: int = 36) -> list[dict]:
    import feedparser

    seen, out = set(), []
    for source, url in config.NEWS_FEEDS:
        try:
            feed = feedparser.parse(_get(url).content)
        except Exception as e:
            errors.append(f"News feed {source}: {e}")
            continue
        for e in feed.entries[:60]:
            title = re.sub(r"\s+", " ", e.get("title", "")).strip()
            src = source
            if source == "Google News" and " - " in title:  # "Headline - Publisher"
                title, src = title.rsplit(" - ", 1)
            try:
                ts = parsedate_to_datetime(e.get("published") or e.get("updated")).astimezone(SAST)
            except Exception:
                continue
            if (now - ts).total_seconds() > hours * 3600 or not title:
                continue
            k = _norm(title)
            if k in seen:
                continue
            seen.add(k)
            out.append({"published": ts, "source": src, "title": title,
                        "link": e.get("link", ""), "tags": _tags(title)})
    # tagged (relevant) stories first, then newest
    out.sort(key=lambda x: (len(x["tags"]) == 0, -x["published"].timestamp()))
    return out[: config.MAX_HEADLINES]
