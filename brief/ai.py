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
    "Rules: use ONLY the numbers and headlines provided and copy numbers exactly as given. "
    "Never invent figures, dates, events or policy decisions; only say the SARB moved or held rates "
    "if a headline says so. Do not call a level high or low unless the changes show it. "
    "Never refer to headlines by their [index] in the text. Each bullet must agree with the numbers. "
    "No investment advice. South African English. Reply with JSON only."
)

SA_CONTEXT = (
    "Background you can rely on: South Africa is a net oil importer, so higher oil prices raise fuel "
    "and transport costs and inflation. It exports gold, platinum-group metals, coal, iron ore and "
    "other minerals, so higher metal prices help miners and the trade balance. USD/ZAR rising means "
    "a weaker rand: imports cost more and exporters earn more rand per dollar. The JSE Top 40 is "
    "heavy in miners and global stocks. Prime is the policy rate plus 3.5 percentage points."
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


NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)*(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    out = []
    for m in NUM.findall(text):
        try:
            out.append(abs(float(m.replace(",", ""))))
        except ValueError:
            pass
    return out


def fact_check(brief: dict, facts: str) -> int:
    """Remove any bullet that quotes a number not found in the source facts (within rounding).
    Small counts (1-12, e.g. "3 bullets", "10-year") are allowed. Returns bullets removed."""
    known = _numbers(facts)

    def supported(x):
        if x <= 12 and float(x).is_integer():
            return True
        return any(abs(x - k) <= max(0.051, abs(k) * 0.002) for k in known)

    removed = 0
    for key in ("what_moved", "so_what", "watch"):
        keep = []
        for b in brief.get(key, []):
            if all(supported(x) for x in _numbers(str(b))):
                keep.append(str(b))
            else:
                removed += 1
        brief[key] = keep
    if not all(supported(x) for x in _numbers(brief.get("headline", ""))):
        brief["headline"] = brief["what_moved"][0] if brief["what_moved"] else "Markets data updated"
        removed += 1
    for key in ("what_moved", "so_what", "watch"):  # strip any stray [12] style references
        brief[key] = [re.sub(r"\s*\((?:see )?headlines? [\d, ]+\)|\s*\[\d+\]", "", b) for b in brief[key]]
    return removed


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
        "temperature": 0.1,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": SA_CONTEXT + "\n\n" + _facts(snap, sarb, news) + "\n\n" + SCHEMA},
        ],
    }
    if label == "Groq" and "gpt-oss" in model:
        body["reasoning_effort"] = "low"  # reasoning model: keep thinking short so the JSON isn't cut off
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
            choice = r.json()["choices"][0]
            content = (choice["message"].get("content") or "").strip()
            if choice.get("finish_reason") == "length":
                last = "reply cut off at the token limit"
                payload_body = {**payload_body, "max_tokens": 8000}
                continue
            content = re.sub(r"^```(?:json)?|```$", "", content).strip()
            data = _parse(content)
            removed = fact_check(data, _facts(snap, sarb, news))
            data["engine"] = f"AI analyst ({model} via {label}), fact-checked by code" + (
                f": {removed} unsupported line(s) removed" if removed else ": all figures matched the source data")
            return data
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:200]
    errors.append(f"AI ({label}): {last}; used rule-based brief")
    return rule_based(snap, sarb)
