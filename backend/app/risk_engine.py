"""Explainable risk engine.

Every score is 0-100 (higher = riskier) and is built from named, weighted
factors so the UI can show *why* a supplier is risky, not just a number.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pandas as pd

from .data_loader import Datasets

DIMENSION_WEIGHTS = {
    "financial": 0.2,
    "geopolitical": 0.2,
    "dependency": 0.2,
    "contract": 0.2,
    "operational": 0.2,
}
EVENT_WINDOW_DAYS = 365


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


def level_for(score: float) -> str:
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


@dataclass
class Factor:
    name: str
    value: str
    contribution: float  # points added to the dimension score

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "contribution": round(self.contribution, 1)}


@dataclass
class Dimension:
    key: str
    label: str
    score: float
    factors: list[Factor] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(self.score),
            "level": level_for(self.score),
            "factors": [f.to_dict() for f in self.factors],
        }


def as_of_date(ds: Datasets) -> pd.Timestamp:
    env = os.environ.get("SUPPLYGRAPH_AS_OF")
    if env:
        return pd.Timestamp(env)
    # Reproducible demo: evaluate relative to the latest event in the dataset.
    return ds.geo_events["date"].max() if not ds.geo_events.empty else pd.Timestamp.today()


def recent_events(ds: Datasets, country_code: str) -> pd.DataFrame:
    ref = as_of_date(ds)
    ev = ds.geo_events
    mask = (ev.country_code == country_code) & (ev.date <= ref) & (ev.date > ref - pd.Timedelta(days=EVENT_WINDOW_DAYS))
    return ev[mask].sort_values("severity", ascending=False)


# --------------------------------------------------------------------------- dimensions

def financial_risk(ds: Datasets, sid: str) -> Dimension:
    f = ds.one("financials", sid)
    if f is None:
        return Dimension("financial", "Financial", 50, [Factor("No financial data", "unknown", 50)])
    credit = 0.45 * (100 - f.credit_score)
    leverage = 0.25 * clamp(f.debt_to_equity / 3 * 100)
    margin = 0.15 * clamp((10 - f.profit_margin_pct) / 20 * 100)
    delay = 0.15 * clamp(f.payment_delay_days / 60 * 100)
    return Dimension("financial", "Financial", clamp(credit + leverage + margin + delay), [
        Factor("Credit score", f"{f.credit_score}/100", credit),
        Factor("Debt-to-equity", f"{f.debt_to_equity:.1f}x", leverage),
        Factor("Profit margin", f"{f.profit_margin_pct}%", margin),
        Factor("Payment delay", f"{f.payment_delay_days} days", delay),
    ])


def geopolitical_risk(ds: Datasets, sid: str) -> Dimension:
    s = ds.supplier_row(sid)
    c = ds.countries[ds.countries.country_code == s.country_code]
    index = float(c.iloc[0].country_risk_index) if not c.empty else 50.0
    events = recent_events(ds, s.country_code)
    max_sev = int(events.severity.max()) if not events.empty else 0
    base = 0.6 * index
    ev = 0.4 * max_sev * 10
    return Dimension("geopolitical", "Geopolitical", clamp(base + ev), [
        Factor("Country risk index", f"{index:.0f}/100", base),
        Factor("Max event severity (12 mo)", f"{max_sev}/10 ({len(events)} events)", ev),
    ])


def dependency_risk(ds: Datasets, sid: str) -> Dimension:
    s = ds.supplier_row(sid)
    return Dimension("dependency", "Dependency", clamp(s.dependency_pct), [
        Factor("Share of category supply", f"{s.dependency_pct}%", float(s.dependency_pct)),
    ])


def contract_risk(ds: Datasets, sid: str) -> Dimension:
    c = ds.one("contracts", sid)
    if c is None:
        return Dimension("contract", "Contract", 60, [Factor("No contract on file", "missing", 60)])
    notice = 0.40 * clamp(c.termination_notice_days / 150 * 100)
    continuity = 0.0 if c.has_continuity_clause else 25.0
    exclusive = 20.0 if c.exclusive else 0.0
    penalty = 0.0 if c.has_penalty_clause else 15.0
    return Dimension("contract", "Contract", clamp(notice + continuity + exclusive + penalty), [
        Factor("Termination notice", f"{c.termination_notice_days} days", notice),
        Factor("Business continuity clause", "yes" if c.has_continuity_clause else "missing", continuity),
        Factor("Exclusivity", "exclusive" if c.exclusive else "non-exclusive", exclusive),
        Factor("Delivery penalty clause", "yes" if c.has_penalty_clause else "missing", penalty),
    ])


def operational_risk(ds: Datasets, sid: str) -> Dimension:
    o = ds.one("operations", sid)
    if o is None:
        return Dimension("operational", "Operational", 50, [Factor("No operations data", "unknown", 50)])
    delivery = 0.35 * clamp((100 - o.on_time_delivery_pct) * 4)
    quality = 0.20 * clamp(o.defect_ppm / 1000 * 100)
    capacity = 0.25 * clamp((o.capacity_utilization_pct - 70) / 30 * 100)
    site = 20.0 if bool(o.single_site) else 0.0
    return Dimension("operational", "Operational", clamp(delivery + quality + capacity + site), [
        Factor("On-time delivery", f"{o.on_time_delivery_pct}%", delivery),
        Factor("Defect rate", f"{o.defect_ppm} ppm", quality),
        Factor("Capacity utilisation", f"{o.capacity_utilization_pct}%", capacity),
        Factor("Single production site", "yes" if o.single_site else "no", site),
    ])


# --------------------------------------------------------------------------- assessment

def assess_supplier(ds: Datasets, sid: str) -> dict:
    dims = [
        financial_risk(ds, sid),
        geopolitical_risk(ds, sid),
        dependency_risk(ds, sid),
        contract_risk(ds, sid),
        operational_risk(ds, sid),
    ]
    overall = sum(DIMENSION_WEIGHTS[d.key] * d.score for d in dims)
    ranked = sorted(dims, key=lambda d: d.score, reverse=True)
    return {
        "overall": round(overall),
        "level": level_for(overall),
        "dimensions": [d.to_dict() for d in dims],
        "top_drivers": [d.key for d in ranked if d.score >= 60][:3] or [ranked[0].key],
    }


def evidence_trail(ds: Datasets, sid: str) -> list[dict]:
    s = ds.supplier_row(sid)
    c = ds.one("contracts", sid)
    f = ds.one("financials", sid)
    events = recent_events(ds, s.country_code)
    max_sev = int(events.severity.max()) if not events.empty else 0
    trail = [
        {"key": "dependency", "label": "Dependency concentration", "value": f"{s.dependency_pct}%",
         "source": "Synthetic procurement dataset", "tag": "SYNTHETIC"},
        {"key": "inventory", "label": "Inventory coverage", "value": f"{float(s.inventory_cover_days):.1f} days",
         "source": "Synthetic inventory dataset", "tag": "SYNTHETIC"},
    ]
    if c is not None:
        trail.append({"key": "termination", "label": "Termination notice", "value": f"{c.termination_notice_days} days",
                      "source": "Synthetic contract dataset", "tag": "SYNTHETIC"})
    trail.append({"key": "events", "label": "Geopolitical events", "value": f"max severity {max_sev}/10",
                  "source": "Synthetic event dataset", "tag": "SYNTHETIC",
                  "detail": events.head(3).assign(date=events.head(3).date.dt.strftime("%Y-%m-%d"))
                  [["date", "type", "severity", "description"]].to_dict("records")})
    if f is not None:
        trail.append({"key": "financial", "label": "Financial source", "value": f.get("source", "Financial data"),
                      "source": "Synthetic financial dataset", "tag": "SYNTHETIC"})
    return trail


def portfolio(ds: Datasets) -> list[dict]:
    out = []
    for sid in ds.suppliers.supplier_id:
        s = ds.supplier_row(sid)
        a = assess_supplier(ds, sid)
        out.append({
            "supplier_id": sid, "name": s["name"], "country_code": s.country_code,
            "category": s.category, "annual_spend_sek": int(s.annual_spend_sek),
            "overall": a["overall"], "level": a["level"],
            "dimensions": {d["key"]: d["score"] for d in a["dimensions"]},
        })
    return sorted(out, key=lambda r: r["overall"], reverse=True)
