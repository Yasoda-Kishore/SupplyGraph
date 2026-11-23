# SupplyGraph — AI-Powered Supply Chain Risk Intelligence

**Supplier digital twin and exposure command center.**
Built for the Ericsson Challenge at the Malmö Industrial AI Hackathon.

> SupplyGraph is more than a supplier dashboard. It shows how one supplier's problem can spread through the whole supply chain, so a company can prepare before it happens.

All data in this repository is **synthetic and illustrative**. It is not real Ericsson supplier data.

---

## What it does

| Feature | What you see |
|---|---|
| **Supplier risk identification** | Scores from 0 to 100 on five dimensions: financial, geopolitical, dependency, contract and operational |
| **Explainable risk engine** | Each score breaks down into named factors with point contributions. Click a bar in the left panel to see them |
| **Graph-based digital twin** | A networkx graph that links suppliers, countries, events, contracts, facilities, components, Ericsson product lines, sites and alternative suppliers |
| **What-if simulation** | "What if this supplier stops delivering for N days?" It shows the supply gap, inventory cover, uncovered days, qualified alternatives that can ramp up in time, the residual gap, the timeline and a recommended response |
| **AI advisor (evidence-first)** | Answers "Why am I exposed?", "Contract", "What next?", "Alternatives" and "Impact" using only the engine's evidence, and lists the evidence it used |
| **Portfolio view** | An exposure heatmap across all suppliers, plus spend concentration by country |

## Architecture

```
 data/*.csv ──► data_loader (pandas, validation)
                   │
                   ├─► risk_engine     explainable 5-dimension scoring + evidence trail
                   ├─► graph_model     networkx MultiDiGraph digital twin + blast radius
                   ├─► simulation      what-if disruption model + recommendations
                   └─► advisor         rule-based evidence-first answers (optional LLM phrasing)
                   │
             FastAPI REST API  (/api/...)  ──►  frontend (HTML/CSS/JS, served at /)
```

```
supplygraph/
├── backend/app/
│   ├── main.py          FastAPI app + static frontend
│   ├── data_loader.py   CSV loading & schema validation
│   ├── risk_engine.py   scoring formulas, evidence trail, portfolio
│   ├── graph_model.py   digital-twin graph, subgraphs, blast radius
│   ├── simulation.py    what-if simulator & recommended response
│   └── advisor.py       AI advisor
├── frontend/            index.html, styles.css, app.js (no build step)
├── data/                10 synthetic CSV datasets
├── tests/test_api.py    pytest suite
├── requirements.txt, run.sh, run.bat, Dockerfile
```

## Run it

You need Python 3.10 or newer.

**macOS / Linux**
```bash
./run.sh
```
**Windows**
```bat
run.bat
```
**Manual**
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```
Then open **http://localhost:8000**. Interactive API docs are at **http://localhost:8000/docs**.

**Docker**
```bash
docker build -t supplygraph . && docker run -p 8000:8000 supplygraph
```

**Tests**
```bash
pytest -q
```

### Optional: LLM-phrased advisor
The advisor works fully offline and doesn't need a key. If you set `ANTHROPIC_API_KEY` in your environment, an LLM phrases the answer. It receives only the evidence bundle and is told not to add facts. If the call fails, the advisor falls back to the rule-based answer.
```bash
export ANTHROPIC_API_KEY=sk-...      # optional
export SUPPLYGRAPH_LLM_MODEL=claude-sonnet-5-5
```

## REST API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Status, graph size |
| GET | `/api/suppliers` | Supplier list |
| GET | `/api/suppliers/{id}` | Profile, risk breakdown, evidence trail, impact radius |
| GET | `/api/suppliers/{id}/graph` | Supplier's digital-twin subgraph (layered) |
| GET | `/api/graph` | Full network graph |
| GET | `/api/portfolio` | All suppliers ranked by exposure |
| POST | `/api/simulate` | `{supplier_id, duration_days}` → what-if result |
| POST | `/api/advisor` | `{supplier_id, question, duration_days}` → evidence-based answer |
| POST | `/api/reload` | Reload CSVs after you edit them |

## How the scores work

Overall exposure is the equal-weighted mean of the five dimensions. HIGH means 70 or more, MEDIUM means 40 to 69, and LOW means under 40.

- **Financial** = 0.45·(100 − credit score) + 0.25·leverage (D/E, where 3x = 100) + 0.15·margin pressure + 0.15·payment delay (60 days = 100)
- **Geopolitical** = 0.6·country risk index + 0.4·(max event severity in the last 12 months × 10)
- **Dependency** = the supplier's share of category supply (%)
- **Contract** = 0.4·termination notice (150 days = 100) + 25 if there is no continuity clause + 20 if the contract is exclusive + 15 if there is no penalty clause
- **Operational** = 0.35·late deliveries + 0.20·defect rate + 0.25·capacity strain (above 70% utilisation) + 20 if the supplier has a single site

**Simulation for a disruption of N days**
- Potential supply gap = dependency %. This is a share of modelled supply, **not a financial loss**.
- Uncovered period = N − inventory cover days
- Qualified alternatives = spare capacity of *qualified* alternatives whose ramp-up time is at most N days
- Residual supply gap = gap − qualified alternatives
- Exposure level: CONTAINED (no uncovered days), MODERATE, HIGH (residual of 25% or more), or CRITICAL (residual of 50% or more)

Worked example: Shenzhen Electronics, 30 days. The gap is 91%. Inventory covers 3 days, so 27 days are uncovered. Alternatives cover 30% (Malaysia 20% at 21 days, Poland 10% at 28 days). That leaves a **61% residual gap**, which is **CRITICAL**.

## Datasets (`data/`)
`suppliers`, `countries`, `geo_events`, `financials`, `contracts`, `operations`, `facilities`, `products`, `product_lines` and `alternatives`. They are plain CSVs, so you can edit them and call `POST /api/reload` or restart the server. Real data sources, such as ERP exports, credit-rating APIs or news and event feeds, could replace these files without changing the engine.

## 60-second pitch
> Large companies depend on suppliers across many countries. When one supplier has financial trouble, a geopolitical issue or a production stop, the effect spreads through the supply chain. SupplyGraph links supplier, country, contract, product and facility data into a graph-based digital twin. It scores each supplier on five explainable risk dimensions, shows exactly why a supplier is risky, and runs what-if simulations. Those simulations show the timing gap between inventory, qualified alternatives and contract terms, and suggest a concrete response. The goal is to spot supply chain exposure early and act before a disruption turns into a crisis.

## Roadmap ideas
- Live data connectors (credit ratings, news/event APIs, ERP)
- Multi-tier suppliers (tier-2/3) in the graph
- Monte-Carlo durations and cost-of-disruption estimates
- Graph database (Neo4j) for larger networks

## Team
Yashoda, Swaroop, Suvarna
