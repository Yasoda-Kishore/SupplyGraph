"""Graph-based digital twin of the supply network (networkx).

Node types : Country, Supplier, Contract, Facility, Product, ProductLine, Site,
             Alternative, Event
Edge types : LOCATED_IN, HAS_CONTRACT, HAS_FACILITY, PROVIDES, DEPENDS_ON,
             PRODUCED_AT, ALTERNATIVE_FOR, AFFECTS
"""
from __future__ import annotations

import networkx as nx

from .data_loader import Datasets
from .risk_engine import assess_supplier, recent_events


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text).strip("-").lower()


def build_graph(ds: Datasets) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    countries = ds.countries.set_index("country_code")

    def add_country(code: str):
        nid = f"country:{code}"
        if nid not in g:
            name = countries.loc[code, "country"] if code in countries.index else code
            idx = int(countries.loc[code, "country_risk_index"]) if code in countries.index else None
            g.add_node(nid, type="Country", label=name, subtitle=f"Country risk {idx}/100" if idx is not None else "",
                       risk=idx)
        return nid

    for _, s in ds.suppliers.iterrows():
        a = assess_supplier(ds, s.supplier_id)
        sid = f"supplier:{s.supplier_id}"
        g.add_node(sid, type="Supplier", label=s["name"], ref=s.supplier_id,
                   subtitle=f"{a['level']} • {s.dependency_pct}% dependency", risk=a["overall"], level=a["level"])
        g.add_edge(sid, add_country(s.country_code), type="LOCATED_IN")

    for _, e in ds.geo_events.iterrows():
        nid = f"event:{e.event_id}"
        g.add_node(nid, type="Event", label=e.type, subtitle=f"Severity {e.severity}/10 • {e.date:%Y-%m-%d}",
                   risk=int(e.severity) * 10, description=e.description)
        g.add_edge(nid, add_country(e.country_code), type="AFFECTS")

    for _, c in ds.contracts.iterrows():
        nid = f"contract:{c.contract_id}"
        flags = []
        if not c.has_continuity_clause:
            flags.append("no continuity clause")
        if c.exclusive:
            flags.append("exclusive")
        g.add_node(nid, type="Contract", label=f"Contract {c.contract_id}",
                   subtitle=f"{c.termination_notice_days}d termination" + (f" • {', '.join(flags)}" if flags else ""))
        g.add_edge(f"supplier:{c.supplier_id}", nid, type="HAS_CONTRACT")

    for _, f in ds.facilities.iterrows():
        nid = f"facility:{f.facility_id}"
        g.add_node(nid, type="Facility", label=f["name"], subtitle=f"{f.type} • {f.city}")
        g.add_edge(f"supplier:{f.supplier_id}", nid, type="HAS_FACILITY")
        g.add_edge(nid, add_country(f.country_code), type="LOCATED_IN")

    lines = ds.product_lines.set_index("line_id")
    for lid, l in lines.iterrows():
        g.add_node(f"line:{lid}", type="ProductLine", label=l["name"], subtitle=f"{l.revenue_criticality} product line")
        site_id = f"site:{_slug(l.site)}"
        g.add_node(site_id, type="Site", label=l.site, subtitle="Ericsson site (illustrative)")
        g.add_edge(f"line:{lid}", site_id, type="PRODUCED_AT")

    for _, p in ds.products.iterrows():
        nid = f"product:{p.product_id}"
        g.add_node(nid, type="Product", label=p.component, subtitle=f"{p.share_of_line_pct}% of line input")
        g.add_edge(f"supplier:{p.supplier_id}", nid, type="PROVIDES")
        g.add_edge(nid, f"line:{p.line_id}", type="DEPENDS_ON", share=int(p.share_of_line_pct))

    for _, a in ds.alternatives.iterrows():
        nid = f"alt:{_slug(a.alt_name)}"
        if nid not in g:
            g.add_node(nid, type="Alternative", label=a.alt_name, subtitle="")
        g.nodes[nid]["subtitle"] = (("Qualified" if a.qualified else "Not qualified")
                                    + f" • {a.spare_capacity_pct}% capacity • {a.ramp_up_days}d ramp-up")
        g.nodes[nid]["qualified"] = bool(a.qualified)
        g.add_edge(nid, f"supplier:{a.supplier_id}", type="ALTERNATIVE_FOR", qualified=bool(a.qualified))
        g.add_edge(nid, add_country(a.alt_country), type="LOCATED_IN")
    return g


def _serialize(g: nx.MultiDiGraph, nodes: set[str], layers: dict[str, int] | None = None) -> dict:
    out_nodes = []
    for n in nodes:
        d = dict(g.nodes[n])
        d["id"] = n
        if layers is not None:
            d["layer"] = layers.get(n, 0)
        out_nodes.append(d)
    edges = []
    for u, v, d in g.edges(data=True):
        if u in nodes and v in nodes:
            edges.append({"source": u, "target": v, **d})
    return {"nodes": out_nodes, "edges": edges}


def supplier_subgraph(g: nx.MultiDiGraph, ds: Datasets, supplier_id: str) -> dict:
    """Ego network for one supplier, with a layer index for top-down layout."""
    sid = f"supplier:{supplier_id}"
    if sid not in g:
        raise KeyError(supplier_id)
    s = ds.supplier_row(supplier_id)
    layers: dict[str, int] = {}
    country = f"country:{s.country_code}"
    layers[country] = 0
    for ev in recent_events(ds, s.country_code).event_id:
        layers[f"event:{ev}"] = 0
    layers[sid] = 1
    for _, v, d in g.out_edges(sid, data=True):
        if d["type"] in ("HAS_CONTRACT", "HAS_FACILITY", "PROVIDES"):
            layers[v] = 2
    for u, _, d in g.in_edges(sid, data=True):
        if d["type"] == "ALTERNATIVE_FOR":
            layers[u] = 1
    for n in [n for n, l in layers.items() if l == 2 and g.nodes[n]["type"] == "Product"]:
        for _, line, d in g.out_edges(n, data=True):
            if d["type"] == "DEPENDS_ON":
                layers[line] = 3
                for _, site, d2 in g.out_edges(line, data=True):
                    if d2["type"] == "PRODUCED_AT":
                        layers[site] = 4
    return _serialize(g, set(layers), layers)


def full_graph(g: nx.MultiDiGraph) -> dict:
    keep = {n for n, d in g.nodes(data=True) if d["type"] != "Event"}
    return _serialize(g, keep)


def blast_radius(g: nx.MultiDiGraph, supplier_id: str) -> dict:
    """What downstream products, product lines and sites are reached if this supplier fails."""
    sid = f"supplier:{supplier_id}"
    products, lines, sites = [], {}, set()
    for _, p, d in g.out_edges(sid, data=True):
        if d["type"] != "PROVIDES":
            continue
        products.append(g.nodes[p]["label"])
        for _, line, d2 in g.out_edges(p, data=True):
            if d2["type"] == "DEPENDS_ON":
                lines[g.nodes[line]["label"]] = lines.get(g.nodes[line]["label"], 0) + d2.get("share", 0)
                for _, site, d3 in g.out_edges(line, data=True):
                    if d3["type"] == "PRODUCED_AT":
                        sites.add(g.nodes[site]["label"])
    # Correlated exposure: other suppliers in the same country
    country = next((v for _, v, d in g.out_edges(sid, data=True) if d["type"] == "LOCATED_IN"), None)
    peers = [g.nodes[u]["label"] for u, _, d in g.in_edges(country, data=True)
             if d["type"] == "LOCATED_IN" and g.nodes[u]["type"] == "Supplier" and u != sid] if country else []
    return {
        "products": products,
        "product_lines": [{"name": k, "input_share_pct": v} for k, v in lines.items()],
        "sites": sorted(sites),
        "same_country_suppliers": peers,
    }
