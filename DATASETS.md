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

## Electricity Generation and Energy Mix (`electricity_mix`)

- Explorer: <https://ourworldindata.org/grapher/electricity-mix>
- OWID energy-data repository: <https://github.com/owid/energy-data>
- OWID technical documentation: <https://docs.owid.io/projects/etl/>
- Requested downloadable CSV view: <https://ourworldindata.org/grapher/electricity-mix.csv?v=1&csvType=full&useColumnShortNames=false&source=renewables&metric=generation&frequency=annual>
- Retrieved locally: 2026-10-18. The returned OWID metadata reports its own `dateDownloaded` as 2026-10-17.
- The verified source CSV columns were `Entity`, `Code`, `Year`, and `Renewables`. The chart metadata describes the measure as annual electricity generation from renewables in terawatt-hours (TWh), combining solar, wind, hydropower, bioenergy, geothermal, wave and tidal. It is not generation by each individual source, a percentage share, or a per-capita measure.
- Underlying indicator sources listed by OWID include Ember (2026), the Energy Institute (2026), Pinto et al. (2023), and the UK Department for Energy Security and Net Zero (2023). The source data is not a single-producer series across all years and countries; consult the explorer's source notes for methodology and source changes.
- Processed file: [`data/electricity_mix.csv`](data/electricity_mix.csv). It contains 5,387 rows from 214 ISO alpha-3-coded entities for 2000–2025. Non-coded aggregate regions are excluded; India is retained. The processed file contains only `entity`, `code`, `year`, and `renewables_twh`, with the OWID labels mapped to application field names `ENTITY`, `CODE`, `YEAR`, and `RENEWABLES_TWH`.
- The process is reproducible from the full-data CSV: keep rows with a three-letter alphabetic `Code` and `Year >= 2000`, preserve the measure unchanged, then sort by entity and year. No application-start or per-query download occurs.
- OWID states its own produced data, visualizations and code are CC BY 4.0 with attribution. OWID also states that third-party data remains under original provider terms. Therefore redistribution of the combined source may depend on those underlying terms; see the [chart reuse and source notes](https://ourworldindata.org/grapher/electricity-mix) and verify provider-specific conditions before reuse beyond this educational subset. Attribution: “Ember (2026); Energy Institute – Statistical Review of World Energy (2026); Pinto et al. (2023); UK Department for Energy Security and Net Zero (2023), with major processing by Our World in Data.”
- Missingness: blank numeric cells are loaded as SQL `NULL`; they are not converted to zero. This subset currently has no blank `renewables_twh` values. Missing country-year rows remain absent and are not imputed.
- Queries run against an ephemeral, read-only SQLite database created from the bundled CSV. This dataset does not return a Snowflake query ID.
