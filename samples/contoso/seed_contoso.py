"""Verify Contoso CSV aggregates against data/golden/contoso.yaml or export a Lakehouse seed folder.

Uses only the Python standard library (with optional PyYAML support when available).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TABLES_DIR = HERE / "tables"
DEFAULT_GOLDEN = ROOT / "data" / "golden" / "contoso.yaml"

TABLE_FILES = (
    "dim_region.csv",
    "dim_product.csv",
    "dim_date.csv",
    "fact_sales_summary.csv",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_golden_questions(golden_path: Path) -> dict[str, dict[str, Any]]:
    text = golden_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]

        doc = yaml.safe_load(text)
        items = doc.get("questions", [])
        return {str(item["id"]): dict(item) for item in items}
    except ImportError:
        # Minimal stdlib fallback parser for id + expected scalar lines
        questions: dict[str, dict[str, Any]] = {}
        current_id: str | None = None
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("- id:"):
                current_id = stripped.split(":", 1)[1].strip()
                questions[current_id] = {"id": current_id}
            elif current_id and stripped.startswith("expected:"):
                val = stripped.split(":", 1)[1].strip()
                if val not in ("null", "", "~"):
                    questions[current_id]["expected"] = float(val)
        return questions


def compute_aggregates(tables_dir: Path = TABLES_DIR) -> dict[str, Any]:
    regions = {r["region_code"]: r for r in _read_csv(tables_dir / "dim_region.csv")}
    products = {p["product_code"]: p for p in _read_csv(tables_dir / "dim_product.csv")}
    dates = {d["period_key"]: d for d in _read_csv(tables_dir / "dim_date.csv")}
    facts = _read_csv(tables_dir / "fact_sales_summary.csv")

    fy25_facts = [f for f in facts if dates[f["period_key"]]["fiscal_year"] == "FY2025"]
    fy24_facts = [f for f in facts if dates[f["period_key"]]["fiscal_year"] == "FY2024"]
    q2_fy25_facts = [f for f in facts if dates[f["period_key"]]["fiscal_quarter"] == "FY2025 Q2"]
    q3_fy25_facts = [f for f in facts if dates[f["period_key"]]["fiscal_quarter"] == "FY2025 Q3"]
    q1_fy27_facts = [f for f in facts if dates[f["period_key"]]["fiscal_quarter"] == "FY2027 Q1"]
    fy25_dates = [d for d in dates.values() if d["fiscal_year"] == "FY2025"]

    gross_fy25 = sum(float(f["gross_revenue"]) for f in fy25_facts)
    gross_fy24 = sum(float(f["gross_revenue"]) for f in fy24_facts)
    net_fy25 = sum(float(f["net_revenue"]) for f in fy25_facts)
    gp_fy25 = sum(float(f["gross_profit"]) for f in fy25_facts)
    gp_fy24 = sum(float(f["gross_profit"]) for f in fy24_facts)
    discounts_fy25 = sum(float(f["discounts"]) for f in fy25_facts)
    returns_fy25 = sum(float(f["returns"]) for f in fy25_facts)
    orders_fy25 = sum(int(f["order_count"]) for f in fy25_facts)
    units_q2_fy25 = sum(int(f["units"]) for f in q2_fy25_facts)
    gross_q2_fy25 = sum(float(f["gross_revenue"]) for f in q2_fy25_facts)
    gross_q3_fy25 = sum(float(f["gross_revenue"]) for f in q3_fy25_facts)
    gross_q1_fy27 = sum(float(f["gross_revenue"]) for f in q1_fy27_facts)

    margin_fy25_pct = round((gp_fy25 / gross_fy25) * 100.0, 4)
    margin_fy24_pct = round((gp_fy24 / gross_fy24) * 100.0, 4)
    margin_bps = round((margin_fy25_pct - margin_fy24_pct) * 100.0, 2)
    yoy_growth_pct = round(((gross_fy25 - gross_fy24) / gross_fy24) * 100.0, 4)
    qoq_q3_pct = round(((gross_q3_fy25 - gross_q2_fy25) / gross_q2_fy25) * 100.0, 4)

    total_quota = sum(float(r["annual_quota_fy25"]) for r in regions.values())
    headcount_fy25 = sum(int(r["ending_headcount_fy25"]) for r in regions.values())
    sev1_fy25 = sum(int(d["sev1_incidents"]) for d in fy25_dates)
    mttr_fy25 = round(sum(float(d["mttr_hours"]) for d in fy25_dates) / len(fy25_dates), 4)
    dio_fy25 = round(sum(float(d["inventory_days"]) for d in fy25_dates) / len(fy25_dates), 4)
    otif_fy25 = round(sum(float(d["otif_pct"]) for d in fy25_dates) / len(fy25_dates), 4)
    q4_date = dates["2025Q4"]

    by_region_rev = {
        regions[code]["region_name"]: sum(float(f["gross_revenue"]) for f in fy25_facts if f["region_code"] == code)
        for code in regions
    }
    by_product_rev = {
        products[code]["category"]: sum(float(f["gross_revenue"]) for f in fy25_facts if f["product_code"] == code)
        for code in products
    }

    # Row-level accounting invariant: net_revenue == gross_revenue - discounts - returns
    for row in facts:
        lhs = round(float(row["gross_revenue"]) - float(row["discounts"]) - float(row["returns"]), 2)
        rhs = round(float(row["net_revenue"]), 2)
        if lhs != rhs:
            raise ValueError(f"Row net_revenue mismatch in {row}: expected {lhs}, got {rhs}")

    # Structured expectations for Q24-Q37
    ranked_products = [
        cat for cat, _ in sorted(by_product_rev.items(), key=lambda kv: kv[1], reverse=True)
    ][:3]
    by_region_margin = {
        regions[code]["region_name"]: round(
            (
                sum(float(f["gross_profit"]) for f in fy25_facts if f["region_code"] == code)
                / by_region_rev[regions[code]["region_name"]]
            )
            * 100.0,
            2,
        )
        for code in regions
    }
    ranked_margin_regions = [
        reg for reg, _ in sorted(by_region_margin.items(), key=lambda kv: kv[1], reverse=True)
    ][:3]
    ranked_rev_regions = [
        reg for reg, _ in sorted(by_region_rev.items(), key=lambda kv: kv[1], reverse=True)
    ][:3]
    by_wh_units = {
        regions[code]["warehouse_code"]: sum(int(f["units"]) for f in fy25_facts if f["region_code"] == code)
        for code in regions
    }
    ranked_warehouses = [
        wh for wh, _ in sorted(by_wh_units.items(), key=lambda kv: kv[1], reverse=True)
    ][:3]
    quota_exceeded = {
        regions[code]["region_name"]
        for code in regions
        if by_region_rev[regions[code]["region_name"]] > float(regions[code]["annual_quota_fy25"])
    }
    stockout_warehouses = {
        regions[code]["warehouse_code"]
        for code in regions
        if regions[code]["stockout_alert"].strip().lower() == "true"
    }
    high_margin_products = {
        products[code]["category"]
        for code in products
        if float(products[code]["target_margin_pct"]) > 45.0
    }
    if ranked_products != ["Cloud Platform", "Analytics Suite", "Connected Devices"]:
        raise ValueError(f"Q24 mismatch: {ranked_products}")
    if ranked_margin_regions != ["North America", "EMEA", "APAC"]:
        raise ValueError(f"Q25 mismatch: {ranked_margin_regions}")
    if ranked_rev_regions != ["North America", "EMEA", "APAC"]:
        raise ValueError(f"Q26 mismatch: {ranked_rev_regions}")
    if ranked_warehouses != ["WH-ORD", "WH-AMS", "WH-SIN"]:
        raise ValueError(f"Q27 mismatch: {ranked_warehouses}")
    if quota_exceeded != {"North America", "EMEA"}:
        raise ValueError(f"Q28 mismatch: {quota_exceeded}")
    if stockout_warehouses != {"WH-AMS", "WH-SIN"}:
        raise ValueError(f"Q29 mismatch: {stockout_warehouses}")
    if high_margin_products != {"Cloud Platform", "Analytics Suite"}:
        raise ValueError(f"Q30 mismatch: {high_margin_products}")

    return {
        "Q01": gross_fy25,
        "Q02": gross_fy25,
        "Q03": net_fy25,
        "Q04": units_q2_fy25,
        "Q05": margin_fy25_pct,
        "Q06": sev1_fy25,
        "Q07": mttr_fy25,
        "Q08": gross_q1_fy27,
        "Q09": yoy_growth_pct,
        "Q10": qoq_q3_pct,
        "Q11": margin_bps,
        "Q12": headcount_fy25,
        "Q13": dio_fy25,
        "Q14": int(q4_date["active_customers"]),
        "Q15": round(gross_fy25 / orders_fy25, 4),
        "Q16": by_region_rev["North America"],
        "Q17": by_region_rev["EMEA"],
        "Q18": returns_fy25,
        "Q19": discounts_fy25,
        "Q20": round((gross_fy25 / total_quota) * 100.0, 1),
        "Q21": by_product_rev["Cloud Platform"],
        "Q22": int(q4_date["open_backlog"]),
        "Q23": otif_fy25,
    }


def verify_seed(tables_dir: Path = TABLES_DIR, golden_path: Path = DEFAULT_GOLDEN) -> list[str]:
    errors: list[str] = []
    for filename in TABLE_FILES:
        if not (tables_dir / filename).is_file():
            errors.append(f"Missing table CSV: {tables_dir / filename}")
    if errors:
        return errors

    computed = compute_aggregates(tables_dir)
    questions = _load_golden_questions(golden_path)
    for qid, actual in sorted(computed.items()):
        q = questions.get(qid)
        if q is None:
            errors.append(f"{qid}: missing from {golden_path}")
            continue
        expected = q.get("expected")
        if expected is None:
            errors.append(f"{qid}: expected scalar value is null in {golden_path}")
            continue
        rel_tol = float(q.get("tolerance", 0.005) or 0.0)
        abs_tol = float(q.get("abs_tol", 0.0) or 0.0)
        allowed = max(abs_tol, rel_tol * abs(float(expected)), 1e-6)
        if abs(float(actual) - float(expected)) > allowed:
            errors.append(f"{qid}: CSV aggregate {actual} != golden expected {expected} (tol={allowed})")
    return errors


def export_seed(out_dir: Path, tables_dir: Path = TABLES_DIR) -> Path:
    dest_tables = out_dir / "tables"
    dest_tables.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, Any]] = []
    for filename in TABLE_FILES:
        src = tables_dir / filename
        dst = dest_tables / filename
        shutil.copy2(src, dst)
        rows = _read_csv(dst)
        digest = hashlib.sha256(dst.read_bytes()).hexdigest()
        manifest_entries.append({"table": dst.stem, "file": f"tables/{filename}", "rows": len(rows), "sha256": digest})
    manifest = {
        "suite": "contoso-fabric-iq",
        "version": 2,
        "tables": manifest_entries,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Verify CSV aggregates match data/golden/contoso.yaml")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN, help="Path to contoso.yaml")
    parser.add_argument("--out-dir", type=Path, default=None, help="Export Lakehouse-ready CSV folder and manifest")
    args = parser.parse_args(argv)

    if not args.verify and args.out_dir is None:
        args.verify = True

    if args.verify:
        errors = verify_seed(TABLES_DIR, args.golden.resolve())
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        computed = compute_aggregates(TABLES_DIR)
        print(f"Verified {len(computed)} scalar KPI aggregates against {args.golden.name} (0 mismatches).")

    if args.out_dir is not None:
        manifest_path = export_seed(args.out_dir.resolve(), TABLES_DIR)
        print(f"Exported Contoso Lakehouse seed bundle to {manifest_path.parent}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
