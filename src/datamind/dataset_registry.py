"""Metadata and approved query catalog for DataMind's supported datasets."""
DEFAULT_DATASET_ID = "tpch_customer"

DATASETS = {
    "tpch_customer": {
        "id": "tpch_customer",
        "name": "TPC-H Customers",
        "description": (
            "Snowflake sample CUSTOMER table from the TPC-H benchmark dataset. "
            "Contains customer demographic and account data only. "
            "No sales transactions, orders, revenue, products, dates, or pricing data."
        ),
        "source_url": "https://docs.snowflake.com/en/user-guide/sample-data",
        "documentation_url": "https://docs.snowflake.com/en/user-guide/sample-data",
        "availability": "requires_snowflake_credentials",
        "storage": "Snowflake SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER",
        "table": "SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER",
        "snowflake_database": "SNOWFLAKE_SAMPLE_DATA",
        "snowflake_schema": "TPCH_SF1",
        "fields": {
            "C_CUSTKEY": {"type": "integer", "description": "Customer key"},
            "C_NAME": {"type": "string", "description": "Customer name"},
            "C_ACCTBAL": {"type": "number", "unit": "USD", "description": "Account balance"},
            "C_MKTSEGMENT": {"type": "string", "description": "Market segment"},
        },
        "supported": {
            "filters": ["eq", "ne", "gt", "gte", "lt", "lte"],
            "groupings": ["C_MKTSEGMENT"],
            "aggregations": ["count", "sum", "avg", "min", "max"],
            "sorting": ["C_CUSTKEY", "C_NAME", "C_ACCTBAL", "C_MKTSEGMENT", "selected metrics"],
            "limit": 100,
        },
        "not_supported": [
            "sales transactions", "order history", "revenue", "product data",
            "date ranges", "year comparisons", "pricing", "supply chain",
            "temperature", "employee data",
        ],
        "license": "Snowflake sample data; accessed through user's Snowflake account.",
        "attribution": "Snowflake TPC-H sample data",
    },
    "electricity_mix": {
        "id": "electricity_mix",
        "name": "Electricity Generation and Energy Mix",
        "description": "Annual electricity generation from renewable sources for ISO-coded countries.",
        "source_url": "https://ourworldindata.org/grapher/electricity-mix",
        "documentation_url": "https://docs.owid.io/projects/etl/",
        "repository_url": "https://github.com/owid/energy-data",
        "availability": "requires_snowflake_credentials",
        "storage": "Snowflake DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX",
        "table": "DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX",
        "snowflake_database": "DATAMIND_DB",
        "snowflake_schema": "ANALYTICS",
        "reproducible_source": "data/electricity_mix.csv",
        "fields": {
            "ENTITY": {"type": "string", "description": "Country or territory name"},
            "CODE": {"type": "string", "description": "ISO alpha-3 code"},
            "YEAR": {"type": "integer", "description": "Calendar year"},
            "RENEWABLES_TWH": {"type": "number", "unit": "TWh", "description": "Renewable electricity generation"},
        },
        "units": {"RENEWABLES_TWH": "terawatt-hours (TWh)"},
        "definitions": {
            "RENEWABLES_TWH": "Electricity generation from solar, wind, hydropower, bioenergy, geothermal, wave, and tidal combined; not a percentage share or per-capita measure.",
        },
        "supported": {
            "filters": ["eq", "ne", "gt", "gte", "lt", "lte"],
            "groupings": ["ENTITY", "CODE", "YEAR"],
            "aggregations": ["count", "sum", "avg", "min", "max"],
            "sorting": ["ENTITY", "CODE", "YEAR", "RENEWABLES_TWH", "selected metrics"],
            "limit": 100,
        },
        "license": "OWID-produced data is CC BY 4.0; third-party source data remains subject to its provider's license terms.",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Ember (2026); Energy Institute – Statistical Review of World Energy (2026); Pinto et al. (2023); UK Department for Energy Security and Net Zero (2023), with major processing by Our World in Data. Source licenses may differ.",
        "retrieved_on": "2026-10-18",
        "source_metadata_downloaded_on": "2026-10-17",
        "subset": {"entities": "ISO alpha-3 coded entities only; aggregates without country codes excluded", "year_min": 2000, "year_max": 2025, "rows": 5387},
        "missing_values": "Blank numeric CSV values are stored as SQL NULL. Rows absent from OWID are not synthesized; absence does not imply zero.",
    },
}


def list_datasets():
    """Return JSON-safe metadata without exposing runtime credentials."""
    result = []
    for dataset_id, item in DATASETS.items():
        entry = {**item, "default": dataset_id == DEFAULT_DATASET_ID}
        result.append(entry)
    return result
