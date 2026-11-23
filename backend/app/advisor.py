"""AI advisor with evidence-first reasoning.

By default the advisor is deterministic and rule-based: every sentence it
returns is built from the risk engine, the simulation and the graph, and each
answer lists the evidence it used. If ANTHROPIC_API_KEY is set, an LLM is asked
to phrase the answer, but it only receives the same evidence bundle and is told
not to add facts. Any LLM error falls back to the rule-based answer.
"""
from __future__ import annotations

import json
import os
import urllib.request

from .data_loader import Datasets
from .risk_engine import assess_supplier, evidence_trail, recent_events
from .simulation import simulate

INTENTS = {
    "contract": ["contract", "termination", "clause", "notice", "exit", "penalty", "exclusiv"],
    "next": ["what next", "next", "do now", "action", "recommend", "mitigat", "should we", "plan"],
    "alternatives": ["alternative", "backup", "second source", "dual", "switch", "other supplier"],
    "impact": ["impact", "affect", "product", "line", "site", "blast", "downstream"],
    "geo": ["geopolit", "country", "event", "political", "war", "tariff", "trade"],
    "financial": ["financ", "credit", "bankrupt", "debt", "margin", "money"],
    "inventory": ["inventory", "stock", "buffer", "cover"],
    "why": ["why", "expos", "risky", "risk", "explain", "score"],
}


def detect_intent(question: str) -> str:
    q = question.lower()
    for intent, words in INTENTS.items():
        if any(w in q for w in words):
            return intent
    return "why"


def _dims(assessment: dict) -> dict:
    return {d["key"]: d for d in assessment["dimensions"]}


def rule_based_answer(ds: Datasets, graph, supplier_id: str, question: str, duration: int) -> dict:
    s = ds.supplier_row(supplier_id)
    a = assess_supplier(ds, supplier_id)
    dims = _dims(a)
    sim = simulate(ds, graph, supplier_id, duration)
    c = ds.one("contracts", supplier_id)
    intent = detect_intent(question)
    name = s["name"]
    bullets: list[str] = []
    used: list[str] = []

    if intent == "why":
        headline = f"{name} has {a['level'].lower()} overall exposure ({a['overall']}/100)."
        for key in sorted(dims, key=lambda k: dims[k]["score"], reverse=True)[:3]:
            d = dims[key]
            top = max(d["factors"], key=lambda f: f["contribution"])
            bullets.append(f"{d['label']} risk {d['score']}/100 — driven mainly by {top['name'].lower()} ({top['value']}).")
            used.append(key)
        bullets.append(f"Inventory covers only {s.inventory_cover_days:g} days, so a {duration}-day stop leaves "
                       f"{sim['uncovered_days']} days uncovered.")
        used.append("inventory")
    elif intent == "contract":
        headline = f"The contract limits how fast you can react to a disruption at {name}." if c is not None else \
            f"No contract is on file for {name}."
        if c is not None:
            bullets.append(f"Termination notice is {c.termination_notice_days} days.")
            bullets.append("No business-continuity clause." if not c.has_continuity_clause else "A business-continuity clause exists.")
            bullets.append("The agreement is exclusive, which can restrict dual sourcing." if c.exclusive else "The agreement is non-exclusive.")
            bullets.append("There is no delivery-penalty clause." if not c.has_penalty_clause else "A delivery-penalty clause exists.")
            bullets.append(f"Contract expires {c.expiry_date} — a natural point to renegotiate.")
        used += ["termination", "contract"]
    elif intent == "next":
        headline = f"Recommended response for a {duration}-day disruption ({sim['exposure_level'].lower()} exposure):"
        bullets = [f"{r['horizon']}: {r['title']}." for r in sim["recommendations"][:5]]
        used += ["dependency", "inventory", "termination"]
    elif intent == "alternatives":
        headline = f"Qualified alternatives can cover {sim['qualified_alternatives_pct']}% of the {sim['potential_supply_gap_pct']}% gap within {duration} days."
        for alt in sim["alternatives"]:
            bullets.append(f"{alt['name']} ({alt['country']}): {alt['spare_capacity_pct']}% capacity, "
                           f"{alt['ramp_up_days']}d ramp-up — {alt['reason'].lower()}.")
        used.append("dependency")
    elif intent == "impact":
        imp = sim["impact"]
        headline = f"If {name} stops, the twin traces impact to {len(imp['product_lines'])} product line(s)."
        bullets.append("Components: " + ", ".join(imp["products"]) + ".")
        for line in imp["product_lines"]:
            bullets.append(f"{line['name']}: {line['input_share_pct']}% of its modelled input comes from this supplier.")
        if imp["sites"]:
            bullets.append("Sites: " + ", ".join(imp["sites"]) + ".")
        if imp["same_country_suppliers"]:
            bullets.append("Correlated risk — same country as: " + ", ".join(imp["same_country_suppliers"]) + ".")
        used.append("dependency")
    elif intent == "geo":
        d = dims["geopolitical"]
        headline = f"Geopolitical risk is {d['score']}/100 for {name}."
        for _, e in recent_events(ds, s.country_code).head(3).iterrows():
            bullets.append(f"{e.date:%Y-%m-%d} — {e.type} (severity {e.severity}/10): {e.description}.")
        if not bullets:
            bullets.append("No events in the last 12 months.")
        used.append("events")
    elif intent == "financial":
        d = dims["financial"]
        headline = f"Financial risk is {d['score']}/100 for {name}."
        bullets = [f"{f['name']}: {f['value']} (+{f['contribution']} pts)" for f in d["factors"]]
        used.append("financial")
    else:  # inventory
        headline = f"Inventory covers {s.inventory_cover_days:g} days of supply from {name}."
        bullets.append(f"For a {duration}-day disruption, {sim['uncovered_days']} days are uncovered.")
        if sim["bridge_gap_days"]:
            bullets.append(f"There are {sim['bridge_gap_days']} days between stock running out and the first alternative coming online.")
        used.append("inventory")

    trail = {e["key"]: e for e in evidence_trail(ds, supplier_id)}
    evidence = [{"label": trail[k]["label"], "value": trail[k]["value"]} for k in dict.fromkeys(used) if k in trail]
    return {"intent": intent, "headline": headline, "bullets": bullets, "evidence": evidence,
            "engine": "rule-based", "disclaimer": "Based on synthetic demo data."}


def llm_answer(base: dict, question: str) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.environ.get("SUPPLYGRAPH_LLM_MODEL", "claude-sonnet-5-5")
    prompt = (
        "You are a supply chain risk advisor. Answer the user's question using ONLY the evidence JSON. "
        "Do not invent numbers or facts. Reply in at most 5 short bullet points.\n\n"
        f"Question: {question}\n\nEvidence JSON:\n{json.dumps(base)}"
    )
    body = json.dumps({"model": model, "max_tokens": 400,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            text = json.loads(r.read())["content"][0]["text"]
    except Exception:
        return None
    lines = [l.strip(" -•*") for l in text.splitlines() if l.strip()]
    return {**base, "bullets": lines, "engine": f"llm:{model}"}


def ask(ds: Datasets, graph, supplier_id: str, question: str, duration: int = 30) -> dict:
    question = (question or "Why am I exposed?").strip()
    base = rule_based_answer(ds, graph, supplier_id, question, duration)
    return llm_answer(base, question) or base
