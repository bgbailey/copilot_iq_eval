# Source of fabric/notebooks/nb_01_generate_data.ipynb. Build with: python scripts/build_notebooks.py
# %% [markdown]
# # nb_01 · Generate the synthetic Contoso data
#
# Backlog task **P1.2** · PLAN §4.1. Builds every gold table the semantic models read, from a fixed
# seed, and writes them as Delta tables:
#
# | Table | Lakehouse | Rows |
# |---|---|---|
# | `dim_date`, `dim_region`, `dim_product` | `lh_gold` (default) | 1,461 · 4 · 40 |
# | `dim_customer`, `dim_service` | `lh_gold` | 2,000 · 25 |
# | `fact_sales` | `lh_gold` | about 500,000 order rows, 2023-01-01 to 2026-10-31 |
# | `fact_gl` | `lh_gold` | Revenue, COGS and OpEx by day and region |
# | `fact_incident` | `lh_gold` | about 6,000 incidents |
# | `security_user_region` | `lh_gold` | one row per persona and region it may see (RLS) |
# | `fact_sales_snapshot_2025q1`, `dim_date` | `lh_sandbox` in `ws-eval-sandbox` | the stale decoy copy |
#
# **Calibrated figures.** Documents seeded for the joint Work IQ evaluation quote real figures
# (`workiq/content.yaml`), so FY2025 gross revenue by region and the FY2025 Sev1 mean time to
# resolve are scaled to fixed totals, to the cent. Every other figure follows from the seed.
#
# Run it from `evals deploy fabric`, or open it in Fabric with `lh_gold` attached and select **Run all**.
# Every cell tagged `logic` is plain pandas and numpy, and `tests/unit/test_notebooks.py` runs it
# outside Fabric.

# %% [parameters]
seed = 20261103
first_date = "2023-01-01"  # first day with sales and incidents
last_date = "2026-10-31"  # data freeze: the last day with sales and incidents
calendar_end = "2026-12-31"  # the Date table runs to the end of the calendar year
sales_rows = 500_000
customer_count = 2_000
incident_count = 6_000
security_user_region_json = "{}"  # {"<persona UPN>": ["East"]}; evals deploy fabric fills it in
sandbox_workspace = "ws-eval-sandbox"
sandbox_lakehouse = "lh_sandbox"
write_tables = True

# %% [logic]
import json

import numpy as np
import pandas as pd

REGIONS = ["East", "West", "Central", "International"]
REGION_SHARE = [0.33, 0.28, 0.23, 0.16]
REGION_AREA = {"East": "Americas", "West": "Americas", "Central": "Americas", "International": "International"}

#: FY2025 gross revenue by region, in cents. FY2025 sales are scaled to these totals exactly (12,840,000.00 in all).
FY2025_GROSS_REVENUE_CENTS = {
    "East": 420_000_000, "West": 360_000_000, "Central": 294_000_000, "International": 210_000_000,
}

#: FY2025 mean time to resolve Sev1 incidents, in hours, also scaled exactly.
FY2025_SEV1_MTTR_HOURS = 7.2

#: Category -> (share of order rows, COGS as a share of net revenue, list price range in USD, products).
CATEGORIES = {
    "Bikes": (0.04, 0.62, (220, 900), ["Road 100", "Road 200", "Road 500", "Mountain 100",
                                         "Mountain 300", "Touring 100", "Touring 300", "City 200"]),
    "Components": (0.20, 0.60, (15, 160), ["Chain", "Crankset", "Derailleur", "Brake Set",
                                            "Wheel Set", "Saddle", "Handlebar", "Pedals"]),
    "Clothing": (0.30, 0.58, (8, 70), ["Jersey", "Bib Shorts", "Gloves", "Jacket",
                                        "Socks", "Cap", "Vest", "Tights"]),
    "Accessories": (0.30, 0.59, (6, 90), ["Helmet", "Lock", "Lights", "Pump",
                                           "Bottle Cage", "Bike Rack", "Panniers", "Computer"]),
    "Services": (0.16, 0.61, (20, 110), ["Tune-Up", "Bike Fitting", "Repair", "Warranty Plus",
                                          "Assembly", "Winter Storage", "Skills Course", "Rental"]),
}

SEGMENTS = ["Enterprise", "Mid-Market", "Small Business", "Consumer"]
SEGMENT_SHARE = [0.15, 0.25, 0.35, 0.25]

SERVICES = [  # (service, tier)
    ("Online Store", 1), ("Payments", 1), ("Order Management", 1), ("Identity", 1), ("Inventory", 1),
    ("Warehouse Scanning", 2), ("Shipping Labels", 2), ("Returns Portal", 2), ("Store Point of Sale", 1),
    ("Customer Support Portal", 2), ("Loyalty", 2), ("Product Catalog", 1), ("Pricing Engine", 1),
    ("Email Notifications", 3), ("Mobile App", 1), ("Dealer Portal", 2), ("Service Booking", 2),
    ("Rental Booking", 2), ("Data Platform", 2), ("Reporting", 3), ("Single Sign-On", 1),
    ("Network", 1), ("Telephony", 3), ("Field Service App", 2), ("Partner API", 2),
]
SEVERITY_SHARE = {1: 0.05, 2: 0.20, 3: 0.40, 4: 0.35}
SEVERITY_MEDIAN_HOURS = {1: 6.0, 2: 14.0, 3: 30.0, 4: 72.0}
SEVERITY_IMPACT = {1: (50, 600), 2: (10, 150), 3: (1, 40), 4: (0, 10)}

#: Monthly operating expense by region in USD, before noise and growth.
MONTHLY_OPEX_USD = {"East": 88_000, "West": 77_000, "Central": 64_000, "International": 52_000}

# %% [logic]


def fiscal_year(when: pd.Series) -> pd.Series:
    """Fiscal year label such as "FY2025"; the fiscal year runs July to June."""
    return "FY" + (when.dt.year + (when.dt.month >= 7).astype(int)).astype(str)


def fiscal_quarter(when: pd.Series) -> pd.Series:
    """Fiscal quarter label such as "FY2025 Q2" (Q1 is July to September)."""
    return fiscal_year(when) + " Q" + (((when.dt.month - 7) % 12) // 3 + 1).astype(str)


def calibrate(values: np.ndarray, target: int) -> np.ndarray:
    """Scale non-negative integers so they sum to ``target`` exactly; the rounding residual goes to the largest."""
    scaled = np.rint(values * (target / values.sum())).astype(np.int64)
    scaled[np.argmax(scaled)] += target - scaled.sum()
    return scaled


# %% [logic]
def build_dim_date(first: str, last: str) -> pd.DataFrame:
    days = pd.Series(pd.date_range(first, last, freq="D"))
    return pd.DataFrame({
        "Date": days,
        "CalendarYear": days.dt.year.astype("int32"),
        "MonthNumber": days.dt.month.astype("int32"),
        "Month": days.dt.strftime("%B"),
        "YearMonth": days.dt.strftime("%Y-%m"),
        "FiscalYear": fiscal_year(days),
        "FiscalQuarter": fiscal_quarter(days),
        "FiscalMonthNumber": ((days.dt.month - 7) % 12 + 1).astype("int32"),
        "DayOfWeek": days.dt.day_name(),
    })


def build_dim_region() -> pd.DataFrame:
    return pd.DataFrame({"Region": REGIONS, "Area": [REGION_AREA[region] for region in REGIONS]})


def build_dim_product() -> pd.DataFrame:
    rows = []
    for category, (_, _, (low, high), names) in CATEGORIES.items():
        prices = np.linspace(low, high, len(names))
        rows += [(category, name, round(float(price), 2)) for name, price in zip(names, prices, strict=True)]
    products = pd.DataFrame(rows, columns=["Category", "Product", "ListPrice"])
    products.insert(0, "ProductID", np.arange(1, len(products) + 1, dtype="int32"))
    return products


def build_dim_customer(rng: np.random.Generator, count: int) -> pd.DataFrame:
    return pd.DataFrame({
        "CustomerID": np.arange(1, count + 1, dtype="int32"),
        "Customer": [f"Customer {number:04d}" for number in range(1, count + 1)],
        "Segment": rng.choice(SEGMENTS, size=count, p=SEGMENT_SHARE),
        "Region": rng.choice(REGIONS, size=count, p=REGION_SHARE),
    })


def build_dim_service() -> pd.DataFrame:
    return pd.DataFrame({
        "ServiceID": np.arange(1, len(SERVICES) + 1, dtype="int32"),
        "Service": [name for name, _ in SERVICES],
        "Tier": [tier for _, tier in SERVICES],
    })


# %% [logic]
def build_fact_sales(rng: np.random.Generator, products: pd.DataFrame, customers: pd.DataFrame,
                     rows: int, first: str, last: str) -> pd.DataFrame:
    """Order rows with growth, seasonality and weekday effects; FY2025 is calibrated by region."""
    days = pd.date_range(first, last, freq="D")
    years = np.asarray((days - days[0]).days) / 365.25
    weight = 1.10**years * (1 + 0.18 * np.cos(2 * np.pi * (np.asarray(days.month) - 5) / 12))
    weight = weight * np.where(np.asarray(days.dayofweek) >= 5, 0.6, 1.0)
    day = rng.choice(len(days), size=rows, p=weight / weight.sum())

    names = list(CATEGORIES)
    category = rng.choice(len(names), size=rows, p=[CATEGORIES[name][0] for name in names])
    by_category = {name: products.index[products["Category"] == name].to_numpy() for name in names}
    product_row = np.empty(rows, dtype=np.int64)
    for index, name in enumerate(names):
        chosen = category == index
        product_row[chosen] = rng.choice(by_category[name], size=int(chosen.sum()))
    customer_row = rng.integers(0, len(customers), size=rows)

    units = np.minimum(rng.geometric(0.65, size=rows), 10)
    price = products["ListPrice"].to_numpy()[product_row] * rng.uniform(0.90, 1.05, size=rows)
    sales = pd.DataFrame({
        "Date": days[day],
        "ProductID": products["ProductID"].to_numpy()[product_row],
        "CustomerID": customers["CustomerID"].to_numpy()[customer_row],
        "Region": customers["Region"].to_numpy()[customer_row],
        "Units": units.astype("int32"),
        "GrossCents": np.rint(units * price * 100).astype(np.int64),
    }).sort_values(["Date", "CustomerID"], kind="stable", ignore_index=True)

    # Scale each region so FY2025 hits its designed total; other years keep the same growth path.
    in_fy2025 = (fiscal_year(sales["Date"]) == "FY2025").to_numpy()
    for region, target in FY2025_GROSS_REVENUE_CENTS.items():
        in_region = (sales["Region"] == region).to_numpy()
        factor = target / sales.loc[in_region & in_fy2025, "GrossCents"].sum()
        sales.loc[in_region, "GrossCents"] = np.rint(sales.loc[in_region, "GrossCents"] * factor).astype(np.int64)
        mask = in_region & in_fy2025
        largest = sales.loc[mask, "GrossCents"].idxmax()
        sales.loc[largest, "GrossCents"] += target - sales.loc[mask, "GrossCents"].sum()

    gross = sales["GrossCents"].to_numpy()
    sales["DiscountCents"] = np.rint(gross * rng.uniform(0.02, 0.08, size=rows)).astype(np.int64)
    sales["ReturnsCents"] = np.rint(gross * rng.uniform(0.0, 0.04, size=rows)).astype(np.int64)
    sales.insert(0, "OrderID", np.arange(1, rows + 1, dtype=np.int64))
    return sales


def build_fact_gl(rng: np.random.Generator, sales: pd.DataFrame, products: pd.DataFrame,
                  first: str, last: str) -> pd.DataFrame:
    """Daily general ledger by region: Revenue (net), COGS (58-62% of net by category) and OpEx."""
    cogs_rate = products["Category"].map({name: spec[1] for name, spec in CATEGORIES.items()})
    rate = sales["ProductID"].map(dict(zip(products["ProductID"], cogs_rate, strict=True)))
    net = sales["GrossCents"] - sales["DiscountCents"] - sales["ReturnsCents"]
    lines = pd.DataFrame({"Date": sales["Date"], "Region": sales["Region"], "Revenue": net,
                          "COGS": np.rint(net * rate).astype(np.int64)})
    daily = lines.groupby(["Date", "Region"], as_index=False)[["Revenue", "COGS"]].sum()
    gl = daily.melt(id_vars=["Date", "Region"], var_name="Account", value_name="AmountCents")

    days = pd.Series(pd.date_range(first, last, freq="D"))
    month = days.dt.year * 100 + days.dt.month
    opex = []
    for region, base in MONTHLY_OPEX_USD.items():
        for key, group in days.groupby(month):
            growth = 1.06 ** ((key // 100 - 2023) + (key % 100 - 1) / 12)
            total = int(round(base * growth * rng.uniform(0.95, 1.05) * 100))
            daily_cents = np.full(len(group), total // len(group), dtype=np.int64)
            daily_cents[-1] += total - daily_cents.sum()
            opex.append(pd.DataFrame({"Date": group.to_numpy(), "Region": region, "Account": "OpEx",
                                      "AmountCents": daily_cents}))
    return pd.concat([gl, *opex], ignore_index=True).sort_values(["Date", "Region", "Account"], ignore_index=True)


# %% [logic]
def build_fact_incident(rng: np.random.Generator, services: pd.DataFrame, count: int,
                        first: str, last: str) -> pd.DataFrame:
    """Incidents with severity mix and lognormal resolution times; FY2025 Sev1 MTTR is calibrated."""
    start = pd.Timestamp(first)
    span_minutes = int((pd.Timestamp(last) + pd.Timedelta(days=1) - start) / pd.Timedelta(minutes=1))
    opened = start + pd.to_timedelta(np.sort(rng.integers(0, span_minutes, size=count)), unit="min")
    severity = rng.choice(list(SEVERITY_SHARE), size=count, p=list(SEVERITY_SHARE.values()))
    median = np.array([SEVERITY_MEDIAN_HOURS[level] for level in severity])
    hundredths = np.maximum(np.rint(rng.lognormal(np.log(median), 0.6) * 100), 25).astype(np.int64)

    sev1_fy2025 = (severity == 1) & (fiscal_year(pd.Series(opened)) == "FY2025").to_numpy()
    target = int(round(FY2025_SEV1_MTTR_HOURS * 100)) * int(sev1_fy2025.sum())
    hundredths[sev1_fy2025] = calibrate(hundredths[sev1_fy2025], target)

    low = np.array([SEVERITY_IMPACT[level][0] for level in severity])
    high = np.array([SEVERITY_IMPACT[level][1] for level in severity])
    resolution = pd.to_timedelta(hundredths * 36, unit="s")  # 1/100 hour = 36 seconds
    return pd.DataFrame({
        "IncidentID": np.arange(1, count + 1, dtype="int32"),
        "OpenedAt": opened,
        "ClosedAt": opened + resolution,
        "OpenedDate": opened.normalize(),
        "Severity": severity.astype("int32"),
        "SeverityLabel": [f"Sev{level}" for level in severity],
        "ServiceID": rng.choice(services["ServiceID"].to_numpy(), size=count),
        "Region": rng.choice(REGIONS, size=count, p=REGION_SHARE),
        "ImpactedCustomers": rng.integers(low, high + 1).astype("int32"),
        "ResolutionHours": hundredths / 100,
    })


def build_security_user_region(mapping_json: str) -> pd.DataFrame:
    """RLS table: one row per persona UPN and region it may see (role RegionScope, PLAN §4.2)."""
    mapping = json.loads(mapping_json)
    rows = [(upn, region) for upn, regions in mapping.items() for region in regions]
    for _, region in rows:
        if region not in REGIONS:
            raise ValueError(f"unknown region {region!r} in security_user_region_json")
    return pd.DataFrame(rows, columns=["UserPrincipalName", "Region"])


def build_sales_snapshot(sales: pd.DataFrame) -> pd.DataFrame:
    """The decoy: sales to 2025-03-31 only, with a 3% uplift so its answers differ (PLAN §4.1)."""
    snapshot = sales[sales["Date"] <= pd.Timestamp("2025-03-31")].copy()
    for column in ("GrossCents", "DiscountCents", "ReturnsCents"):
        snapshot[column] = np.rint(snapshot[column] * 1.03).astype(np.int64)
    return snapshot.reset_index(drop=True)


def to_usd(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace integer cents columns with USD amount columns, written as decimal(18,2): GrossCents -> GrossAmount."""
    frame = frame.copy()
    for column in [name for name in frame.columns if name.endswith("Cents")]:
        stem = column.removesuffix("Cents")
        frame[stem if stem.endswith("Amount") else stem + "Amount"] = frame.pop(column) / 100
    return frame


# %% [logic]
rng = np.random.default_rng(seed)
dim_date = build_dim_date(first_date, calendar_end)
dim_region = build_dim_region()
dim_product = build_dim_product()
dim_customer = build_dim_customer(rng, customer_count)
dim_service = build_dim_service()
fact_sales_cents = build_fact_sales(rng, dim_product, dim_customer, sales_rows, first_date, last_date)
fact_gl_cents = build_fact_gl(rng, fact_sales_cents, dim_product, first_date, last_date)
fact_incident = build_fact_incident(rng, dim_service, incident_count, first_date, last_date)
security_user_region = build_security_user_region(security_user_region_json)

gold_tables = {
    "dim_date": dim_date,
    "dim_region": dim_region,
    "dim_product": dim_product,
    "dim_customer": dim_customer,
    "dim_service": dim_service,
    "fact_sales": to_usd(fact_sales_cents),
    "fact_gl": to_usd(fact_gl_cents),
    "fact_incident": fact_incident,
    "security_user_region": security_user_region,
}
sandbox_tables = {
    "fact_sales_snapshot_2025q1": to_usd(build_sales_snapshot(fact_sales_cents)),
    "dim_date": dim_date,
}

# %% [logic]
# Check the calibrated figures before anything is written.
fy2025_sales = fact_sales_cents[fiscal_year(fact_sales_cents["Date"]) == "FY2025"]
by_region = fy2025_sales.groupby("Region")["GrossCents"].sum().to_dict()
assert by_region == FY2025_GROSS_REVENUE_CENTS, by_region
sev1 = fact_incident[(fact_incident["Severity"] == 1) & (fiscal_year(fact_incident["OpenedAt"]) == "FY2025")]
assert round(float(sev1["ResolutionHours"].mean()), 2) == FY2025_SEV1_MTTR_HOURS

for name, table in {**gold_tables, **{f"sandbox.{key}": value for key, value in sandbox_tables.items()}}.items():
    print(f"{name:<34} {len(table):>9,} rows")
print(f"FY2025 gross revenue: {sum(by_region.values()) / 100:,.2f} USD by region {by_region}")
print(f"FY2025 Sev1 MTTR: {sev1['ResolutionHours'].mean():.2f} hours over {len(sev1)} incidents")

# %%
# Write Delta tables: gold to the attached lakehouse, the decoy to the sandbox lakehouse.
from pyspark.sql import functions as F  # noqa: E402, N812

DECIMAL_COLUMNS = {"GrossAmount", "DiscountAmount", "ReturnsAmount", "Amount", "ListPrice", "ResolutionHours"}
DATE_COLUMNS = {"Date", "OpenedDate"}
EMPTY_SCHEMAS = {"security_user_region": "UserPrincipalName string, Region string"}


def to_spark(name, frame):
    if frame.empty:
        return spark.createDataFrame([], EMPTY_SCHEMAS[name])
    df = spark.createDataFrame(frame)
    for column in df.columns:
        if column in DECIMAL_COLUMNS:
            df = df.withColumn(column, F.round(F.col(column), 2).cast("decimal(18,2)"))
        elif column in DATE_COLUMNS:
            df = df.withColumn(column, F.to_date(F.col(column)))
    return df


if write_tables:
    for name, frame in gold_tables.items():
        writer = to_spark(name, frame).write.mode("overwrite").option("overwriteSchema", "true").format("delta")
        writer.saveAsTable(name)
    sandbox_root = f"abfss://{sandbox_workspace}@onelake.dfs.fabric.microsoft.com/{sandbox_lakehouse}.Lakehouse/Tables"
    for name, frame in sandbox_tables.items():
        writer = to_spark(name, frame).write.mode("overwrite").option("overwriteSchema", "true").format("delta")
        writer.save(f"{sandbox_root}/{name}")
    print("Delta tables written.")
