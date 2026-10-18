# Data Sources and Attribution

## Snowflake Sample Data

DataMind currently queries the `CUSTOMER` table from:

- Database: `SNOWFLAKE_SAMPLE_DATA`
- Schema: `TPCH_SF1`
- Table: `CUSTOMER`
- Fully qualified table: `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.CUSTOMER`

Official reference:
https://docs.snowflake.com/en/user-guide/sample-data

### How the data is used

DataMind sends validated SQL queries to Snowflake and derives its results
from the rows returned at query time. The application does not use a local
copy of this table as its answer source.

### Access and redistribution

The sample data is accessed through the user's Snowflake account. This
repository does not include a dump or copy of the dataset. Consult
Snowflake's current documentation and applicable terms for details about
sample-data use and any redistribution restrictions.

### Reproducibility

To reproduce the demo, configure Snowflake credentials and access to the
sample database using the environment-variable names documented in
`.env.example` and `README.md`. Never commit credentials or the `.env` file.

The current implementation is configured for the `CUSTOMER` table. Support
for other datasets or schemas should not be assumed unless documented and
tested.
