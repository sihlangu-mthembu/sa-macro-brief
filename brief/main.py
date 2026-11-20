"""Run the whole brief:  python -m brief.main            (live data)
                         python -m brief.main --offline  (synthetic data, for testing)"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import smtplib
from email.message import EmailMessage

import numpy as np
import pandas as pd

from . import ai, analyse, config, excel, fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sample_data(now):
    """Synthetic but realistic inputs so the pipeline can be tested without a network."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(end=now.date() - dt.timedelta(days=1), periods=280)
    start = {"usdzar": 17.9, "eurzar": 19.4, "gbpzar": 23.1, "top40": 9800, "sp500": 6100, "em": 47,
             "gold": 3300, "platinum": 1100, "brent": 70, "copper": 4.6, "us10y": 4.3}
    df = pd.DataFrame({k: v * np.exp(np.cumsum(rng.normal(0, 0.009, len(idx)))) for k, v in start.items()}, index=idx)
    df["us10y"] = 4.3 + np.cumsum(rng.normal(0, 0.03, len(idx)))
    df.loc[df.index[-3], "top40"] = np.nan  # a JSE holiday
    sarb = [{"name": n, "value": v, "date": d, "section": s, "code": "", "unit": u} for n, v, d, s, u in [
        ("SARB Policy Rate", 7.25, "2026-11-19", "Rates", "%"), ("Prime lending rate", 10.75, "2026-11-19", "Rates", "%"),
        ("CPI", 5.2, "2026-10-31", "Inflation", "%"), ("PPI", 6.1836, "2026-09-30", "Inflation", "%"),
        ("8.00% 2030 (R2030) (closing yields)", 8.02, "2026-11-18", "Bonds", "%"),
        ("Zaronia", 7.098, "2026-11-18", "Rates", "%"), ("Rand per US Dollar", 17.2532, "2026-11-19", "Exchange rates", "R")]]
    news = [{"published": now - dt.timedelta(hours=h), "source": s, "title": t, "link": "https://example.com/" + str(h),
             "tags": fetch._tags(t)} for h, s, t in [
        (3, "Moneyweb", "SARB keeps repo rate at 7.25% as inflation edges up"),
        (5, "BusinessTech", "Rand firms against the dollar after strong retail sales data"),
        (8, "Daily Maverick", "Sibanye-Stillwater announces acquisition of US recycling business"),
        (12, "Google News", "Eskom says no load shedding expected this weekend"),
        (20, "Moneyweb", "JSE closes higher as gold miners rally")]]
    return df, pd.DataFrame(), sarb, news


def to_markdown(run_ts, snap, sarb, news, brief, errors) -> str:
    out = [f"# SA Macro & Markets Brief: {run_ts:%A %d %B %Y}", "", f"**{brief['headline']}**", ""]
    for h, items in (("What moved", brief["what_moved"]), ("So what for business", brief["so_what"]), ("Watch", brief["watch"])):
        if items:
            out += [f"### {h}"] + [f"- {x}" for x in items] + [""]
    out += ["### Markets", "| Indicator | Latest | As of | 1D | 1W | 1M | YTD | 1Y |", "|---|---:|---|---:|---:|---:|---:|---:|"]
    for r in snap:
        out.append(f"| {r['label']} | {r['value']:,.4g} {r['unit']} | {r['date']:%d %b} | "
                   + " | ".join(analyse.fmt_change(r["chg"][p], r["kind"]) for p in analyse.PERIODS) + " |")
    if sarb:
        out += ["", "### SARB indicators", "| Indicator | Value | As of |", "|---|---:|---|"]
        out += [f"| {x['name']} | {x['value']:g} | {x['date']} |" for x in sarb]
    if news:
        out += ["", "### Headlines"] + [f"- [{n['title']}]({n['link']}) ({n['source']})" for n in news[:10]]
    out += ["", f"_{brief.get('engine', '')}. Not investment advice._"]
    if errors:
        out += ["", "<details><summary>Data issues this run</summary>", ""] + [f"- {e}" for e in errors] + ["", "</details>"]
    return "\n".join(out) + "\n"


def maybe_email(xlsx_path, md_text, subject, errors):
    """Optional: set GMAIL_USER, GMAIL_APP_PASSWORD and BRIEF_TO as repository secrets."""
    user, pwd, to = (os.environ.get(k) for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "BRIEF_TO"))
    if not (user and pwd and to):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(md_text)
    with open(xlsx_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename=os.path.basename(xlsx_path))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
        return True
    except Exception as e:
        errors.append(f"Email: {type(e).__name__}")
        return False


def run(offline=False):
    now = dt.datetime.now(fetch.SAST).replace(microsecond=0)
    errors: list[str] = []
    if offline:
        markets, ecb, sarb, news = sample_data(now)
    else:
        markets = fetch.fetch_markets(errors)
        ecb = fetch.fetch_ecb_fx((now - dt.timedelta(days=400)).date(), errors)
        sarb = fetch.fetch_sarb(errors)
        news = fetch.fetch_news(now, errors)
    markets = analyse.merge_fx_fallback(markets, ecb, errors)
    snap = analyse.snapshot(markets)
    if not snap:
        raise SystemExit("No market data at all; stopping so a blank brief is not published. " + "; ".join(errors))

    data_dir = os.path.join(ROOT, "data" if not offline else "data/offline")
    os.makedirs(data_dir, exist_ok=True)
    history = analyse.update_history(os.path.join(data_dir, "history.csv"), now.date().isoformat(), snap, sarb)
    brief = ai.write_brief(snap, sarb, news, errors) if not offline else ai.rule_based(snap, sarb)

    rep = os.path.join(ROOT, "reports" if not offline else "reports/offline")
    os.makedirs(os.path.join(rep, f"{now:%Y}"), exist_ok=True)
    dated = os.path.join(rep, f"{now:%Y}", f"SA-Macro-Brief-{now:%Y-%m-%d}.xlsx")
    excel.build(dated, now, markets, snap, sarb, news, brief, history, errors)
    shutil.copyfile(dated, os.path.join(rep, "latest.xlsx"))
    md = to_markdown(now, snap, sarb, news, brief, errors)
    with open(os.path.join(rep, "latest.md"), "w") as f:
        f.write(md)
    with open(os.path.join(data_dir, "latest.json"), "w") as f:
        json.dump({"run": now.isoformat(), "brief": brief, "errors": errors,
                   "markets": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items() if k not in ("refs",)} for r in snap],
                   "sarb": sarb}, f, indent=2, default=str)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md)
    sent = maybe_email(dated, md, f"SA Macro & Markets Brief: {brief['headline']}", errors)
    print(f"Wrote {dated}; {len(snap)} market series, {len(sarb)} SARB indicators, {len(news)} headlines; "
          f"brief by {brief.get('engine')}; emailed={sent}; issues={len(errors)}")
    for e in errors:
        print("  issue:", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    run(ap.parse_args().offline)
