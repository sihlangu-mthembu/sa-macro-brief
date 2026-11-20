"""AI analyst step. Uses a free OpenAI-compatible API: Groq (default) or Google Gemini,
whichever key is set as a repository secret. If no key is set or the call fails, a
rule-based brief is written instead, so the workbook always goes out."""
from __future__ import annotations

import json
import os
import re
import time

import requests

from . import config
from .analyse import fmt_change

SYSTEM = (
    "You are a South African macro and markets analyst at a consulting firm. "
    "You write a short morning brief for business clients (strategy, M&A, finance teams). "
    "Use ONLY the numbers and headlines provided. Never invent figures, dates or events. "
    "No investment advice. South African English. Reply with JSON only."
)

SCHEMA = """Return exactly this JSON:
{"headline": "one line, max 16 words, the single most important takeaway",
 "what_moved": ["3-4 bullets, each max 25 words, citing the numbers given"],
 "so_what": ["3 bullets, max 25 words each: what this means for SA businesses (importers, exporters, borrowers, miners, deal teams)"],
 "watch": ["2-3 bullets, max 20 words: things to watch, only if supported by the headlines"],
 "headline_refs": [indices of the headlines you relied on]}"""


def _facts(snap, sarb, news) -> str:
    lines = ["MARKETS (latest close; changes over 1 day, 1 week, 1 month, year-to-date, 1 year):"]
    for r in snap:
        ch = ", ".join(f"{p} {fmt_change(r['chg'][p], r['kind'])}" for p in r["chg"])
        lines.append(f"- {r['label']}: {r['value']:.4g} {r['unit']} on {r['date']:%d %b %Y} ({ch})")
    lines.append("\nSARB INDICATORS:")
    for x in sarb:
        lines.append(f"- {x['name']}: {x['value']:g} (as of {x['date']})")
    lines.append("\nHEADLINES (last 36 hours):")
    for i, n in enumerate(news):
        lines.append(f"[{i}] {n['title']} ({n['source']})")
    return "\n".join(lines)


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0) if m else text)
    for k in ("what_moved", "so_what", "watch", "headline_refs"):
        data.setdefault(k, [])
    if not data.get("headline"):
        raise ValueError("no headline")
    return data


def rule_based(snap, sarb) -> dict:
    by = {r["key"]: r for r in snap}
    movers = sorted([r for r in snap if r["chg"]["1D"] is not None and r["kind"] == "price"],
                    key=lambda r: abs(r["chg"]["1D"]), reverse=True)
    moved = [f"{r['label']} {fmt_change(r['chg']['1D'], 'price')} on the day to {r['value']:.4g} {r['unit']}."
             for r in movers[:4]]
    head = moved[0].rstrip(".") if moved else "Markets data updated"
    so = []
    if "usdzar" in by and by["usdzar"]["chg"]["1M"] is not None:
        c = by["usdzar"]["chg"]["1M"]
        so.append(("A weaker" if c > 0 else "A firmer") + f" rand over the month ({fmt_change(c, 'price')} USD/ZAR) "
                  + ("raises import costs and helps exporters." if c > 0 else "eases import costs and fuel pressure."))
    rate = next((x for x in sarb if "policy" in x["name"].lower() or "repo" in x["name"].lower()), None)
    if rate:
        so.append(f"The SARB policy rate is {rate['value']:g}% (prime {next((x['value'] for x in sarb if 'prime' in x['name'].lower()), 'n/a')}%): the base for borrowing costs and deal financing.")
    return {"headline": head, "what_moved": moved, "so_what": so, "watch": [], "headline_refs": [],
            "engine": "Rule-based fallback (AI unavailable)"}


PROVIDERS = [
    # (secret name, endpoint, model, label) - the first one with a key set is used
    ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-120b", "Groq"),
    ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "gemini-flash-latest", "Google Gemini"),
]


def write_brief(snap, sarb, news, errors: list[str]) -> dict:
    provider = next(((k, url, model, label) for k, url, model, label in PROVIDERS if os.environ.get(k)), None)
    if not provider:
        errors.append("AI: no GROQ_API_KEY or GEMINI_API_KEY secret set, used rule-based brief")
        return rule_based(snap, sarb)
    key, url, model, label = provider
    model = os.environ.get("AI_MODEL") or model
    body = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _facts(snap, sarb, news) + "\n\n" + SCHEMA},
        ],
    }
    headers = {"Authorization": f"Bearer {os.environ[key]}", "Content-Type": "application/json"}
    attempts = [body, body, {k: v for k, v in body.items() if k != "response_format"}]
    last = None
    for i, payload_body in enumerate(attempts):
        if i:
            time.sleep(4 * i)
        try:
            r = requests.post(url, json=payload_body, headers=headers, timeout=90)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:160]}"
                continue
            content = (r.json()["choices"][0]["message"].get("content") or "").strip()
            content = re.sub(r"^```(?:json)?|```$", "", content).strip()
            data = _parse(content)
            data["engine"] = f"AI analyst ({model} via {label})"
            return data
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:200]
    errors.append(f"AI ({label}): {last}; used rule-based brief")
    return rule_based(snap, sarb)
