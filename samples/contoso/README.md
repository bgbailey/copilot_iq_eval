# Contoso Fabric IQ Sample Seed Kit

This directory contains a deterministic, 100% synthetic Contoso star-schema dataset (`@contoso.com`) whose aggregates match `data/golden/contoso.yaml` (`Q01`–`Q42`) and `data/golden/contoso-smoke.yaml` (`Q01`–`Q08`).

## Contents

| Path | Description |
|---|---|
| `tables/dim_region.csv` | Four commercial regions (`NA`, `EMEA`, `APAC`, `LATAM`), annual FY25 quotas, ending headcount (`380`), warehouse hub codes, and stockout alert flags. |
| `tables/dim_product.csv` | Four product categories (`Cloud Platform`, `Analytics Suite`, `Connected Devices`, `Advisory Services`) and target margin percentages. |
| `tables/dim_date.csv` | Fiscal quarters (`FY2024 Q1`–`Q4`, `FY2025 Q1`–`Q4`, `FY2027 Q1`) with operational KPIs (`Sev1 Incidents = 312`, `MTTR = 6.4h`, `Inventory Days = 38.5`, `OTIF = 96.4%`, `Open Backlog`). |
| `tables/fact_sales_summary.csv` | Quarterly × regional × product revenue, discount, return, net-revenue, gross-profit, unit, and order-count facts. |
| `seed_contoso.py` | Pure Python stdlib script to verify CSV totals against `data/golden/contoso.yaml` (`--verify`) or stage a Lakehouse-ready bundle (`--out-dir`). |
| `transcript_sample.jsonl` | Pre-captured 8-turn (`Q01`–`Q08`) synthetic transcript for zero-tenant scoring via `transcript-import`. |

## Option A: Run Offline with Zero Tenant Setup (60 Seconds)

1. **Verify synthetic star-schema integrity** against `data/golden/contoso.yaml`:

   ```powershell
   python samples/contoso/seed_contoso.py --verify
   ```

2. **Score the pre-captured transcript** without Azure, Graph, or Fabric credentials:

   ```powershell
   python -m cfeval run --target transcript-import --transcript samples/contoso/transcript_sample.jsonl --golden data/golden/contoso-smoke.yaml --no-publish
   ```

3. **Run the simulated tenant** across all 42 cases:

   ```powershell
   python -m cfeval run --mock --golden data/golden/contoso.yaml --no-publish
   ```

## Option B: Seed into a Demo-Tenant Fabric Lakehouse and Semantic Model

If you want to exercise live Copilot Chat + Workspace Monitoring against synthetic Contoso data rather than your own business models:

1. **Export a Lakehouse staging folder** with a checksum manifest:

   ```powershell
   python samples/contoso/seed_contoso.py --out-dir build/contoso-lakehouse-seed
   ```

2. **Upload CSVs to a Fabric Lakehouse**:
   - In your demo-tenant workspace, open an existing Lakehouse (preserve existing workspaces; never delete workspaces during teardown).
   - Upload the four CSV files from `build/contoso-lakehouse-seed/tables/` to `Files/contoso_seed/` and use **Load to Tables** (`dim_region`, `dim_product`, `dim_date`, `fact_sales_summary`).

3. **Create relationships and core DAX measures** in the semantic model:
   - Join `fact_sales_summary[period_key]` → `dim_date[period_key]`, `fact_sales_summary[region_code]` → `dim_region[region_code]`, and `fact_sales_summary[product_code]` → `dim_product[product_code]`.
   - Add core measures matching `contoso.yaml`:
     - `Gross Revenue = SUM(fact_sales_summary[gross_revenue])` (`$12,840,000` in `FY2025`)
     - `Net Revenue = SUM(fact_sales_summary[net_revenue])` (`$11,950,000` in `FY2025`)
     - `Gross Margin % = DIVIDE(SUM(fact_sales_summary[gross_profit]), [Gross Revenue])` (`41.6%` in `FY2025`)
     - `Units = SUM(fact_sales_summary[units])` (`48,210` in `FY2025 Q2`)
     - `Product Returns = SUM(fact_sales_summary[returns])` (`$320,000` in `FY2025`)
     - `Discounts = SUM(fact_sales_summary[discounts])` (`$570,000` in `FY2025`)
     - `Order Count = SUM(fact_sales_summary[order_count])` (`6,420` in `FY2025`, `AOV = $2,000`)

4. **Optional decoy model**: publish a stale copy named `Sales Sandbox` (for example filtered or scaled to FY2024 figures) in a monitored workspace accessible to `eval.tester@contoso.com` so decoy-avoidance gates are exercised end to end.
