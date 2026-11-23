"""Load and validate the SupplyGraph datasets (CSV) with pandas."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.environ.get("SUPPLYGRAPH_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

BOOL_COLS = {
    "suppliers": ["stockable"],
    "contracts": ["has_continuity_clause", "exclusive", "has_penalty_clause"],
    "operations": ["single_site"],
    "alternatives": ["qualified"],
}

REQUIRED = {
    "suppliers": ["supplier_id", "name", "country_code", "category", "criticality",
                  "annual_spend_sek", "dependency_pct", "inventory_cover_days"],
    "countries": ["country_code", "country", "country_risk_index"],
    "geo_events": ["event_id", "country_code", "date", "severity"],
    "financials": ["supplier_id", "credit_score", "debt_to_equity", "profit_margin_pct", "payment_delay_days"],
    "contracts": ["contract_id", "supplier_id", "termination_notice_days"],
    "operations": ["supplier_id", "on_time_delivery_pct", "defect_ppm", "capacity_utilization_pct"],
    "facilities": ["facility_id", "supplier_id", "name", "country_code"],
    "product_lines": ["line_id", "name"],
    "products": ["product_id", "supplier_id", "component", "line_id"],
    "alternatives": ["supplier_id", "alt_name", "qualified", "spare_capacity_pct", "ramp_up_days"],
}


def _to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "y"])


@dataclass
class Datasets:
    suppliers: pd.DataFrame
    countries: pd.DataFrame
    geo_events: pd.DataFrame
    financials: pd.DataFrame
    contracts: pd.DataFrame
    operations: pd.DataFrame
    facilities: pd.DataFrame
    product_lines: pd.DataFrame
    products: pd.DataFrame
    alternatives: pd.DataFrame

    def supplier_row(self, supplier_id: str) -> pd.Series:
        rows = self.suppliers[self.suppliers.supplier_id == supplier_id]
        if rows.empty:
            raise KeyError(supplier_id)
        return rows.iloc[0]

    def one(self, table: str, supplier_id: str) -> pd.Series | None:
        df = getattr(self, table)
        rows = df[df.supplier_id == supplier_id]
        return None if rows.empty else rows.iloc[0]

    def many(self, table: str, supplier_id: str) -> pd.DataFrame:
        df = getattr(self, table)
        return df[df.supplier_id == supplier_id]


def load_datasets(data_dir: Path | str = DATA_DIR) -> Datasets:
    data_dir = Path(data_dir)
    frames: dict[str, pd.DataFrame] = {}
    for name, cols in REQUIRED.items():
        path = data_dir / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing dataset: {path}")
        df = pd.read_csv(path)
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"{name}.csv is missing columns: {missing}")
        for col in BOOL_COLS.get(name, []):
            if col in df.columns:
                df[col] = _to_bool(df[col])
        frames[name] = df
    frames["geo_events"]["date"] = pd.to_datetime(frames["geo_events"]["date"])
    return Datasets(**frames)
