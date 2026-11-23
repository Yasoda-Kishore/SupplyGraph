"""SupplyGraph REST API + static frontend.

Run:  uvicorn backend.app.main:app --reload   (from the project root)
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import advisor
from .data_loader import load_datasets
from .graph_model import blast_radius, build_graph, full_graph, supplier_subgraph
from .risk_engine import assess_supplier, evidence_trail, portfolio
from .simulation import simulate

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="SupplyGraph API", version="1.0.0",
              description="Supplier digital twin and exposure command center (synthetic demo data).")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

state: dict = {}


def reload_data() -> None:
    ds = load_datasets()
    state["ds"] = ds
    state["graph"] = build_graph(ds)


reload_data()


def _ds():
    return state["ds"]


def _check(supplier_id: str) -> None:
    if supplier_id not in set(_ds().suppliers.supplier_id):
        raise HTTPException(404, f"Unknown supplier {supplier_id}")


class SimulationRequest(BaseModel):
    supplier_id: str
    duration_days: int = Field(30, ge=1, le=365)


class AdvisorRequest(BaseModel):
    supplier_id: str
    question: str = "Why am I exposed?"
    duration_days: int = Field(30, ge=1, le=365)


@app.get("/api/health")
def health():
    g = state["graph"]
    return {"status": "ready", "suppliers": len(_ds().suppliers), "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges()}


@app.get("/api/suppliers")
def list_suppliers():
    return [{"supplier_id": r.supplier_id, "name": r["name"], "country_code": r.country_code}
            for _, r in _ds().suppliers.iterrows()]


@app.get("/api/suppliers/{supplier_id}")
def supplier_detail(supplier_id: str):
    _check(supplier_id)
    ds = _ds()
    s = ds.supplier_row(supplier_id)
    country = ds.countries.set_index("country_code").country.get(s.country_code, s.country_code)
    return {
        "supplier_id": supplier_id, "name": s["name"], "country": country, "country_code": s.country_code,
        "category": s.category, "criticality": s.criticality, "annual_spend_sek": int(s.annual_spend_sek),
        "dependency_pct": int(s.dependency_pct), "inventory_cover_days": float(s.inventory_cover_days),
        "risk": assess_supplier(ds, supplier_id),
        "evidence": evidence_trail(ds, supplier_id),
        "impact": blast_radius(state["graph"], supplier_id),
    }


@app.get("/api/suppliers/{supplier_id}/graph")
def supplier_graph(supplier_id: str):
    _check(supplier_id)
    return supplier_subgraph(state["graph"], _ds(), supplier_id)


@app.get("/api/graph")
def network_graph():
    return full_graph(state["graph"])


@app.get("/api/portfolio")
def portfolio_view():
    return portfolio(_ds())


@app.post("/api/simulate")
def run_simulation(req: SimulationRequest):
    _check(req.supplier_id)
    return simulate(_ds(), state["graph"], req.supplier_id, req.duration_days)


@app.post("/api/advisor")
def ask_advisor(req: AdvisorRequest):
    _check(req.supplier_id)
    return advisor.ask(_ds(), state["graph"], req.supplier_id, req.question, req.duration_days)


@app.post("/api/reload")
def reload():
    reload_data()
    return health()


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
