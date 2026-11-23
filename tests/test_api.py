from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health").json()
    assert r["status"] == "ready" and r["suppliers"] == 6 and r["nodes"] > 0


def test_risk_scores_are_explainable():
    d = client.get("/api/suppliers/SUP-003").json()
    assert d["risk"]["overall"] == 78 and d["risk"]["level"] == "HIGH"
    for dim in d["risk"]["dimensions"]:
        assert 0 <= dim["score"] <= 100
        assert dim["factors"], "every score must list its factors"


def test_nordic_matches_demo():
    d = client.get("/api/suppliers/SUP-001").json()
    assert d["risk"]["overall"] == 50 and d["risk"]["level"] == "MEDIUM"


def test_simulation_30_days():
    r = client.post("/api/simulate", json={"supplier_id": "SUP-003", "duration_days": 30}).json()
    assert r["potential_supply_gap_pct"] == 91
    assert r["uncovered_days"] == 27
    assert r["qualified_alternatives_pct"] == 30
    assert r["residual_supply_gap_pct"] == 61
    assert r["exposure_level"] == "CRITICAL"
    assert r["recommendations"]


def test_short_disruption_is_contained():
    r = client.post("/api/simulate", json={"supplier_id": "SUP-002", "duration_days": 5}).json()
    assert r["uncovered_days"] == 0 and r["exposure_level"] == "CONTAINED"


def test_alternatives_need_time_to_ramp_up():
    short = client.post("/api/simulate", json={"supplier_id": "SUP-003", "duration_days": 10}).json()
    assert short["qualified_alternatives_pct"] == 0


def test_graph_and_blast_radius():
    g = client.get("/api/suppliers/SUP-003/graph").json()
    types = {n["type"] for n in g["nodes"]}
    assert {"Supplier", "Country", "Contract", "Product", "ProductLine", "Alternative"} <= types
    d = client.get("/api/suppliers/SUP-003").json()
    assert "Radio access units" in [l["name"] for l in d["impact"]["product_lines"]]


def test_advisor_intents():
    for q, intent in [("Why am I exposed?", "why"), ("What does the contract say?", "contract"),
                      ("What should we do next?", "next"), ("Which alternatives can we use?", "alternatives")]:
        a = client.post("/api/advisor", json={"supplier_id": "SUP-003", "question": q}).json()
        assert a["intent"] == intent and a["bullets"]


def test_unknown_supplier_404():
    assert client.get("/api/suppliers/NOPE").status_code == 404
