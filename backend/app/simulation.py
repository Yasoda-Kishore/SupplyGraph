"""What-if simulation: "what if this supplier stops delivering for N days?"

Potential supply gap is the share of modelled supply dependency associated with
the supplier. It is NOT a financial loss percentage.
"""
from __future__ import annotations

from .data_loader import Datasets
from .graph_model import blast_radius


def classify(residual_gap: float, uncovered_days: int) -> str:
    if uncovered_days <= 0:
        return "CONTAINED"
    if residual_gap >= 50:
        return "CRITICAL"
    if residual_gap >= 25:
        return "HIGH"
    return "MODERATE"


def simulate(ds: Datasets, graph, supplier_id: str, duration_days: int) -> dict:
    s = ds.supplier_row(supplier_id)
    duration = max(1, int(duration_days))
    contract = ds.one("contracts", supplier_id)
    gap = float(s.dependency_pct)
    inventory = float(s.inventory_cover_days)
    covered_days = min(inventory, duration)
    uncovered = max(0, round(duration - inventory))

    alts = ds.many("alternatives", supplier_id).sort_values("ramp_up_days")
    alt_rows, alt_cover, first_alt_day = [], 0.0, None
    for _, a in alts.iterrows():
        usable = bool(a.qualified) and a.ramp_up_days <= duration
        if usable:
            take = min(float(a.spare_capacity_pct), gap - alt_cover)
            alt_cover += max(take, 0)
            first_alt_day = a.ramp_up_days if first_alt_day is None else first_alt_day
        alt_rows.append({
            "name": a.alt_name, "country": a.alt_country, "qualified": bool(a.qualified),
            "spare_capacity_pct": int(a.spare_capacity_pct), "ramp_up_days": int(a.ramp_up_days),
            "usable_in_window": usable,
            "reason": ("Ready within window" if usable else
                       "Not qualified — needs qualification first" if not a.qualified else
                       f"Ramp-up ({a.ramp_up_days}d) longer than disruption"),
        })
    residual = max(0.0, gap - alt_cover)
    # Gap-days between inventory running out and the first alternative coming online
    bridge_days = 0
    if uncovered > 0:
        start = inventory
        end = min(first_alt_day, duration) if first_alt_day is not None else duration
        bridge_days = max(0, round(end - start))
    level = classify(residual, uncovered)
    notice = int(contract.termination_notice_days) if contract is not None else None

    timeline = [{"label": "Inventory cover", "start": 0, "end": covered_days, "kind": "inventory"}]
    if uncovered > 0:
        timeline.append({"label": "Uncovered", "start": covered_days, "end": duration, "kind": "uncovered"})
    if first_alt_day is not None:
        timeline.append({"label": "First alternative online", "at": int(first_alt_day), "kind": "marker"})

    impact = blast_radius(graph, supplier_id)
    return {
        "supplier_id": supplier_id,
        "duration_days": duration,
        "exposure_level": level,
        "potential_supply_gap_pct": round(gap),
        "inventory_cover_days": inventory,
        "uncovered_days": uncovered,
        "qualified_alternatives_pct": round(alt_cover),
        "residual_supply_gap_pct": round(residual),
        "bridge_gap_days": bridge_days,
        "termination_notice_days": notice,
        "alternatives": alt_rows,
        "timeline": timeline,
        "impact": impact,
        "recommendations": recommend(s, contract, uncovered, residual, alt_rows, notice, duration, impact),
        "note": "Potential supply gap is the percentage of modeled supply dependency associated with this "
                "supplier. It is not a financial loss percentage.",
    }


def recommend(s, contract, uncovered, residual, alts, notice, duration, impact) -> list[dict]:
    recs = []
    if contract is not None and not contract.has_continuity_clause:
        recs.append({"title": "Confirm disruption and trigger the contract's continuity notification process",
                     "detail": "The contract has no business-continuity clause — escalate through supplier "
                               "management and document the force-majeure position.", "horizon": "Day 0"})
    else:
        recs.append({"title": "Confirm disruption and invoke the business-continuity clause",
                     "detail": "Request the supplier's recovery plan and committed recovery date.", "horizon": "Day 0"})
    if uncovered > 0:
        recs.append({"title": "Ring-fence remaining inventory for critical product lines",
                     "detail": f"Inventory covers {s.inventory_cover_days:g} days of a {duration}-day disruption. "
                               f"Prioritise: {', '.join(l['name'] for l in impact['product_lines']) or 'critical lines'}.",
                     "horizon": "Day 0–2"})
    usable = [a for a in alts if a["usable_in_window"]]
    for a in usable:
        recs.append({"title": f"Activate qualified alternative: {a['name']}",
                     "detail": f"Up to {a['spare_capacity_pct']}% of category volume, online in ~{a['ramp_up_days']} days.",
                     "horizon": f"Day 1–{a['ramp_up_days']}"})
    unqualified = [a for a in alts if not a["qualified"]]
    if residual > 0 and unqualified:
        names = ", ".join(a["name"] for a in unqualified)
        recs.append({"title": "Start fast-track qualification of additional sources",
                     "detail": f"{round(residual)}% of supply remains uncovered. Candidates: {names}.",
                     "horizon": "Week 1"})
    if notice is not None and notice > duration:
        recs.append({"title": "Do not rely on contract exit during this disruption",
                     "detail": f"Termination notice ({notice} days) is longer than the disruption ({duration} days); "
                               "focus on mitigation, not exit.", "horizon": "Strategic"})
    if s.dependency_pct >= 70:
        recs.append({"title": "Reduce single-supplier concentration",
                     "detail": f"Dependency of {s.dependency_pct}% is above a 70% concentration threshold — "
                               "set a dual-sourcing target and raise safety stock.", "horizon": "Strategic"})
    return recs
