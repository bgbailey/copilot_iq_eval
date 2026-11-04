# Source of fabric/notebooks/nb_02_build_models.ipynb. Build with: python scripts/build_notebooks.py
# %% [markdown]
# # nb_02 · Build the semantic models
#
# Backlog task **P1.3** · PLAN §4.2. Run after nb_01. Creates four Direct Lake semantic models
# over the Delta tables nb_01 wrote, with business-friendly names:
#
# | Model | Workspace | Tables | Role in the tests |
# |---|---|---|---|
# | **Sales Analytics** | `ws-eval-certified` | Date, Region, Product, Customer, Sales | owns gross revenue |
# | **Finance** | `ws-eval-certified` | Date, Region, GL | owns net revenue and margin |
# | **Service Operations** | `ws-eval-certified` | Date, Region, Service, Incident | owns incidents and MTTR |
# | **Sales Sandbox** | `ws-eval-sandbox` | Date, Sales (stale snapshot) | the decoy; must never be used |
#
# Each certified model gets relationships, a marked date table, measures with descriptions and
# two row-level security roles: `AllRegions` (the exec persona) and `RegionScope` (the east
# persona, filtered through the hidden `security_user_region` table).
#
# **Idempotent.** With `overwrite = True` an existing model of the same name is rebuilt in place.
# Workspace roles and dataset permissions are granted by `evals deploy fabric`, not here.
# **Still manual (PLAN §4.2):** Prep data for AI, endorsement and one report per model.
#
# The model definitions are plain data in the cell tagged `logic`; `tests/unit/test_notebooks.py`
# checks them against the golden-set DAX and the tables nb_01 writes.

# %% [parameters]
certified_workspace = "ws-eval-certified"
sandbox_workspace = "ws-eval-sandbox"
gold_lakehouse = "lh_gold"
sandbox_lakehouse = "lh_sandbox"
all_regions_members = ""  # comma-separated UPNs for role AllRegions (the exec persona)
region_scope_members = ""  # comma-separated UPNs for role RegionScope (the east persona)
direct_lake_mode = "sql_endpoint"  # sql_endpoint (default) or onelake; see fabric/README.md
overwrite = True

# %% [logic]
# The models, as data. Model table and column names are the business names every DAX query in
# the golden set uses ('Date'[Fiscal Year], [Gross Revenue]).

CURRENCY = "\\$#,0.00;(\\$#,0.00);\\$#,0.00"
WHOLE = "#,0"
PERCENT = "0.0%"
HOURS = "#,0.0"

# Lakehouse column -> model column. Columns not listed keep their lakehouse name.
COLUMN_NAMES = {
    "CalendarYear": "Calendar Year",
    "MonthNumber": "Month Number",
    "YearMonth": "Year Month",
    "FiscalYear": "Fiscal Year",
    "FiscalQuarter": "Fiscal Quarter",
    "FiscalMonthNumber": "Fiscal Month Number",
    "DayOfWeek": "Day of Week",
    "ListPrice": "List Price",
    "GrossAmount": "Gross Amount",
    "DiscountAmount": "Discount Amount",
    "ReturnsAmount": "Returns Amount",
    "OpenedAt": "Opened At",
    "ClosedAt": "Closed At",
    "OpenedDate": "Opened Date",
    "SeverityLabel": "Severity Label",
    "ImpactedCustomers": "Impacted Customers",
    "ResolutionHours": "Resolution Hours",
}

# Keys used only for relationships are hidden from report authors and from Copilot.
HIDDEN_COLUMNS = {"OrderID", "ProductID", "CustomerID", "ServiceID", "IncidentID"}

COLUMN_DESCRIPTIONS = {
    ("Date", "Date"): "Calendar date. The fiscal year runs from 1 July to 30 June.",
    ("Date", "Fiscal Year"): "Fiscal year label. FY2025 is 1 July 2024 to 30 June 2025.",
    ("Date", "Fiscal Quarter"): "Fiscal quarter label, for example FY2025 Q2 (October to December 2024).",
    ("Region", "Region"): "Sales region: East, West, Central or International.",
    ("Region", "Area"): "Group of regions: Americas or International.",
    ("Sales", "Gross Amount"): "Order value before discounts and returns, in US dollars.",
    ("Sales", "Discount Amount"): "Discounts given on the order, in US dollars.",
    ("Sales", "Returns Amount"): "Value of goods returned from the order, in US dollars.",
    ("GL", "Account"): "General ledger account: Revenue (net of discounts and returns), COGS or OpEx.",
    ("GL", "Amount"): "Posted amount in US dollars. Costs are positive amounts.",
    ("Incident", "Severity"): "Incident severity from 1 (most severe) to 4.",
    ("Incident", "Resolution Hours"): "Hours from opening to resolving the incident.",
    ("Incident", "Opened Date"): "Date the incident was opened; incidents are counted in this period.",
}

# The RegionScope filter: the signed-in user sees the regions listed for them in security_user_region.
REGION_SCOPE_FILTER = (
    "'Region'[Region] IN CALCULATETABLE(VALUES(security_user_region[Region]), "
    "security_user_region[UserPrincipalName] = USERPRINCIPALNAME())"
)

MODELS = {
    "Sales Analytics": {
        "workspace": "certified",
        "description": "Certified. Owner of revenue (gross), units and orders for Contoso. "
        "Revenue means gross revenue unless the user says net; net revenue is in the Finance model.",
        "tables": {
            "Date": "dim_date",
            "Region": "dim_region",
            "Product": "dim_product",
            "Customer": "dim_customer",
            "Sales": "fact_sales",
            "security_user_region": "security_user_region",
        },
        "relationships": [
            ("Sales", "Date", "Date", "Date"),
            ("Sales", "ProductID", "Product", "ProductID"),
            ("Sales", "CustomerID", "Customer", "CustomerID"),
            ("Sales", "Region", "Region", "Region"),
        ],
        "measures": [
            ("Sales", "Gross Revenue", "SUM(Sales[Gross Amount])", CURRENCY,
             "Sales before discounts and returns. Revenue means this measure unless the user says net."),
            ("Sales", "Units", "SUM(Sales[Units])", WHOLE, "Units sold."),
            ("Sales", "Orders", "COUNTROWS(Sales)", WHOLE, "Number of orders."),
            ("Sales", "Avg Order Value", "DIVIDE([Gross Revenue], [Orders])", CURRENCY,
             "Gross revenue per order."),
            ("Sales", "Gross Revenue FYTD", "TOTALYTD([Gross Revenue], 'Date'[Date], \"6/30\")", CURRENCY,
             "Gross revenue from 1 July of the fiscal year to date."),
            ("Sales", "Gross Revenue PY", "CALCULATE([Gross Revenue], SAMEPERIODLASTYEAR('Date'[Date]))",
             CURRENCY, "Gross revenue in the same period of the previous year."),
            ("Sales", "Gross Revenue YoY %",
             "DIVIDE([Gross Revenue] - [Gross Revenue PY], [Gross Revenue PY])", PERCENT,
             "Year-over-year growth of gross revenue."),
        ],
        "rls": True,
    },
    "Finance": {
        "workspace": "certified",
        "description": "Certified. Owner of net revenue, cost of goods sold, gross margin and operating "
        "expense from the general ledger.",
        "tables": {
            "Date": "dim_date",
            "Region": "dim_region",
            "GL": "fact_gl",
            "security_user_region": "security_user_region",
        },
        "relationships": [
            ("GL", "Date", "Date", "Date"),
            ("GL", "Region", "Region", "Region"),
        ],
        "measures": [
            ("GL", "Net Revenue", "CALCULATE(SUM(GL[Amount]), GL[Account] = \"Revenue\")", CURRENCY,
             "Revenue after discounts and returns, from the general ledger."),
            ("GL", "COGS", "CALCULATE(SUM(GL[Amount]), GL[Account] = \"COGS\")", CURRENCY,
             "Cost of goods sold."),
            ("GL", "Gross Margin", "[Net Revenue] - [COGS]", CURRENCY, "Net revenue minus cost of goods sold."),
            ("GL", "Gross Margin %", "DIVIDE([Gross Margin], [Net Revenue])", PERCENT,
             "Gross margin as a share of net revenue."),
            ("GL", "Operating Expense", "CALCULATE(SUM(GL[Amount]), GL[Account] = \"OpEx\")", CURRENCY,
             "Operating expense."),
            ("GL", "Operating Margin %", "DIVIDE([Gross Margin] - [Operating Expense], [Net Revenue])",
             PERCENT, "Gross margin less operating expense, as a share of net revenue."),
        ],
        "rls": True,
    },
    "Service Operations": {
        "workspace": "certified",
        "description": "Certified. Owner of service incidents, severity, mean time to resolve (MTTR) and "
        "impacted customers.",
        "tables": {
            "Date": "dim_date",
            "Region": "dim_region",
            "Service": "dim_service",
            "Incident": "fact_incident",
            "security_user_region": "security_user_region",
        },
        "relationships": [
            ("Incident", "Opened Date", "Date", "Date"),
            ("Incident", "Region", "Region", "Region"),
            ("Incident", "ServiceID", "Service", "ServiceID"),
        ],
        "measures": [
            ("Incident", "Incidents", "COUNTROWS(Incident)", WHOLE, "Number of incidents opened."),
            ("Incident", "Sev1 Incidents", "CALCULATE([Incidents], Incident[Severity] = 1)", WHOLE,
             "Number of severity 1 incidents opened."),
            ("Incident", "MTTR Hours", "AVERAGE(Incident[Resolution Hours])", HOURS,
             "Mean time to resolve, in hours, for incidents opened in the period."),
            ("Incident", "Impacted Customers", "SUM(Incident[Impacted Customers])", WHOLE,
             "Customers affected by incidents."),
        ],
        "rls": True,
    },
    "Sales Sandbox": {
        "workspace": "sandbox",
        "description": "Uncertified scratch copy of sales to 31 March 2025. Not maintained.",
        "tables": {"Date": "dim_date", "Sales": "fact_sales_snapshot_2025q1"},
        "relationships": [("Sales", "Date", "Date", "Date")],
        "measures": [
            ("Sales", "Revenue", "SUM(Sales[Gross Amount])", CURRENCY, "Revenue."),
            ("Sales", "Units", "SUM(Sales[Units])", WHOLE, "Units."),
        ],
        "rls": False,
    },
}


def members(csv: str) -> list[str]:
    """Split a comma-separated parameter into UPNs."""
    return [upn.strip() for upn in csv.split(",") if upn.strip()]


def model_column(lakehouse_column: str) -> str:
    return COLUMN_NAMES.get(lakehouse_column, lakehouse_column)


# %%
# Install the pinned semantic-link-labs release if this runtime does not have it.
import importlib
import importlib.metadata
import inspect

SEMPY_LABS_VERSION = "0.18.0"


def installed_version():
    try:
        return importlib.metadata.version("semantic-link-labs")
    except importlib.metadata.PackageNotFoundError:
        return None


if installed_version() != SEMPY_LABS_VERSION:
    get_ipython().run_line_magic("pip", f"install --quiet semantic-link-labs=={SEMPY_LABS_VERSION}")
    importlib.invalidate_caches()
if installed_version() != SEMPY_LABS_VERSION:
    raise RuntimeError(
        f"semantic-link-labs {SEMPY_LABS_VERSION} is not available and inline installation did not work. "
        "Attach a Fabric environment with that library to nb_02, or run nb_02 once interactively. "
        "See fabric/README.md, Troubleshooting."
    )

import sempy_labs  # noqa: E402
from sempy_labs.directlake import generate_direct_lake_semantic_model  # noqa: E402
from sempy_labs.tom import connect_semantic_model  # noqa: E402

WORKSPACES = {"certified": certified_workspace, "sandbox": sandbox_workspace}
LAKEHOUSES = {"certified": gold_lakehouse, "sandbox": sandbox_lakehouse}
ROLE_MEMBERS = {"AllRegions": members(all_regions_members), "RegionScope": members(region_scope_members)}


def call_supported(function, **kwargs):
    """Call a semantic-link-labs function with only the arguments this release accepts."""
    accepted = inspect.signature(function).parameters
    return function(**{name: value for name, value in kwargs.items() if name in accepted})


def generate(name, spec):
    workspace, lakehouse = WORKSPACES[spec["workspace"]], LAKEHOUSES[spec["workspace"]]
    call_supported(
        generate_direct_lake_semantic_model,
        dataset=name,
        tables=spec["tables"],  # 0.18: {model table: lakehouse table}
        lakehouse_tables=list(spec["tables"].values()),  # earlier releases
        source=lakehouse,
        source_type="Lakehouse",
        source_workspace=workspace,
        lakehouse=lakehouse,
        lakehouse_workspace=workspace,
        use_sql_endpoint=direct_lake_mode == "sql_endpoint",
        workspace=workspace,
        overwrite=overwrite,
        refresh=False,
    )


def shape(name, spec):
    """Names, descriptions, relationships, measures, the date table and RLS, applied with TOM."""
    workspace = WORKSPACES[spec["workspace"]]
    with connect_semantic_model(dataset=name, workspace=workspace, readonly=False) as tom:
        tom.model.Description = spec["description"]
        by_source = {source: table for table, source in spec["tables"].items()}
        for table in list(tom.model.Tables):
            if table.Name in by_source and table.Name != by_source[table.Name]:
                table.Name = by_source[table.Name]  # older releases keep the lakehouse table name
        for table in tom.model.Tables:
            for column in list(table.Columns):
                if column.Name.startswith("RowNumber"):
                    continue
                source = column.Name
                column.Name = model_column(source)
                column.IsHidden = source in HIDDEN_COLUMNS or table.Name == "security_user_region"
                described = COLUMN_DESCRIPTIONS.get((table.Name, column.Name))
                if described:
                    column.Description = described
            if table.Name == "security_user_region":
                table.IsHidden = True
        for from_table, from_column, to_table, to_column in spec["relationships"]:
            tom.add_relationship(
                from_table=from_table, from_column=from_column, to_table=to_table, to_column=to_column,
                from_cardinality="Many", to_cardinality="One",
            )
        tom.mark_as_date_table(table_name="Date", column_name="Date")
        for table, measure, expression, format_string, description in spec["measures"]:
            tom.add_measure(
                table_name=table, measure_name=measure, expression=expression,
                format_string=format_string, description=description,
            )
        if spec["rls"]:
            tom.add_role(role_name="AllRegions", model_permission="Read",
                         description="Every region. Members: the exec persona.")
            tom.add_role(role_name="RegionScope", model_permission="Read",
                         description="Regions listed for the user in security_user_region.")
            tom.set_rls(role_name="RegionScope", table_name="Region", filter_expression=REGION_SCOPE_FILTER)
            for role, upns in ROLE_MEMBERS.items():
                if upns:
                    tom.add_role_member(role_name=role, member=upns, role_member_type="User")


for model_name, model_spec in MODELS.items():
    print(f"Building {model_name} ...")
    generate(model_name, model_spec)
    shape(model_name, model_spec)
    sempy_labs.refresh_semantic_model(dataset=model_name, workspace=WORKSPACES[model_spec["workspace"]])
    print(f"  {len(model_spec['measures'])} measures, {len(model_spec['relationships'])} relationships, "
          f"RLS {'on' if model_spec['rls'] else 'off'}")
print("Semantic models ready. Next: nb_03_validate_and_snapshot.")
