# Carbon Intensity Forecast Tracking

Tracking differences between the [UK grid's carbon intensity forecast](https://carbonintensity.org.uk/)
and its eventual recorded value.

## What is this?

See the accompanying [blog post](https://nickmp.com/posts/carbon-intensity-forecast-tracking).

The carbon intensity of electricity is a measure of the $CO_2$ emissions produced per
kilowatt-hour consumed. NESO publishes [an API](https://carbon-intensity.github.io/api-definitions/)
with half-hourly carbon intensity and a 48-hour forecast — but keeps no forecast history:
old forecasts are overwritten. This repo scrapes the API twice an hour from GitHub
Actions and commits what it sees, so the git history *is* the record, then publishes
daily accuracy statistics and charts.

![Published CI values](./charts/national_ci_lines.png)

Each half-hour window is forecast about 96 times over the preceding 48 hours and revised
for 24 hours afterwards; the fan above shows those trajectories converging.

## How it works

Everything lives in SQLite databases committed to the repo — no JSON or CSV data files
(design and measurements: [ADR-001](./docs/adr-001-sqlite.md)):

- **Twice hourly** (`ingest.yaml`): all five API endpoints are fetched in memory,
  validated, and written as one small inbox database (`data/db/inbox/snap_<slot>.sqlite`,
  ~130 KB).
- **Daily** (`daily.yaml`): complete days of inboxes fold into window-partitioned
  databases — `national_<YYYY-MM>` (full fidelity), `regional_<YYYY-MM>{a,b}` and
  `generation_<YYYY>` (change-log: a row is stored only when its values differ from the
  previous capture; recorded coverage makes reconstruction exact) — then every chart,
  the tables below, and `data/db/analysis.sqlite` are rebuilt.

## Forecast accuracy — national

### 24 hours

![Published CI values 24h](./charts/national_ci_boxplot.png)

![CI error 24h](./charts/national_ci_error_boxplot.png)

### Daily summaries

#### Absolute error, gCO2/kWh

<!-- cift:daily-stats:start -->
|            |   count |   mean |   sem |   95% CI low |   95% CI high |
|:-----------|--------:|-------:|------:|-------------:|--------------:|
| 2026-08-06 |     905 |  12.25 |  0.32 |        11.61 |         12.88 |
| 2026-08-07 |    1096 |  26.92 |  0.56 |        25.82 |         28.02 |
| 2026-08-08 |    1476 |  18.43 |  0.37 |        17.69 |         19.16 |
| 2026-08-09 |    2173 |  23.05 |  0.29 |        22.48 |         23.61 |
| 2026-08-10 |    2175 |  16.45 |  0.27 |        15.91 |         16.98 |
| 2026-08-11 |    1930 |  17.15 |  0.27 |        16.61 |         17.69 |
| 2026-08-12 |    1936 |  26.5  |  0.38 |        25.75 |         27.25 |
| 2026-08-13 |     283 |  43.13 |  0.84 |        41.48 |         44.78 |
<!-- cift:daily-stats:end -->

#### Absolute percentage error

<!-- cift:daily-stats-pc:start -->
|            |   mean |    sem |   95% CI low |   95% CI high |
|:-----------|-------:|-------:|-------------:|--------------:|
| 2026-08-06 | inf    | nan    |       nan    |        nan    |
| 2026-08-07 |  22.91 |   0.45 |        22.03 |         23.78 |
| 2026-08-08 |  21.22 |   0.38 |        20.48 |         21.96 |
| 2026-08-09 |  25.39 |   0.37 |        24.66 |         26.12 |
| 2026-08-10 |  12.62 |   0.22 |        12.2  |         13.04 |
| 2026-08-11 |  17.9  |   0.35 |        17.21 |         18.59 |
| 2026-08-12 |  20.23 |   0.3  |        19.64 |         20.82 |
| 2026-08-13 |  21    |   0.37 |        20.28 |         21.73 |
<!-- cift:daily-stats-pc:end -->

### 30 days

![CI error 30d](./charts/national_ci_error_boxplot_30days.png)

### All data — absolute error

<!-- cift:all-data-summary:start -->
| n | mean | median | std | sem |
|---|---|---|---|---|
| 1319436 | 24.2334 | 20.0 | 19.4829 | 0.016961 |
<!-- cift:all-data-summary:end -->

## Forecast reliability

![CI forecast error distribution](./charts/national_ci_forecast_error_distribution.png)

By fitting distributions to the error history we can estimate the probability of a
forecast error large enough to cross the published CI index bands (stored in
`data/db/reference.sqlite`).

#### Error magnitudes and their probabilities

<!-- cift:error-probabilities:start -->
|   error value |   Student's t probability |   Normal probability |   Laplace probability |
|--------------:|--------------------------:|---------------------:|----------------------:|
|           100 |                0.00380594 |          0.000682488 |             0.0331454 |
|            90 |                0.0075163  |          0.00223897  |             0.0466336 |
|            80 |                0.0148286  |          0.00659397  |             0.0656107 |
|            70 |                0.0289979  |          0.017459    |             0.0923103 |
|            60 |                0.055671   |          0.0416313   |             0.129875  |
|            50 |                0.103753   |          0.0895934   |             0.182726  |
|            40 |                0.185403   |          0.174475    |             0.257085  |
|            30 |                0.313759   |          0.308474    |             0.361703  |
|            20 |                0.497361   |          0.49718     |             0.508894  |
|            10 |                0.732714   |          0.734263    |             0.715983  |
<!-- cift:error-probabilities:end -->

The daily history of these statistics lives in `data/db/analysis.sqlite`
(`stats_history`, `error_probabilities`, `all_data_error_summary`).

## Usage

Expects Python 3.13+.

```sh
python3 -m venv venv && source venv/bin/activate
make install-dev        # or install / install-minimal
make check              # linters + the test suite

python run.py ingest  --db_root data/db                   # one snapshot now
python run.py compact --db_root data/db                   # fold complete days
python run.py analyse --db_root data/db --charts charts --readme README.md
```

The one-off historical migration (JSON/CSV era → SQLite) is `python run.py migrate`;
it stages every legacy source, emits through the production write path, and refuses to
pass unless an exhaustive verification gate — including reproducing the frozen 2023
README totals — holds.

## Runbook

- **Scheduled workflows** are auto-disabled by GitHub after 60 days without commits.
  Re-enable with `gh workflow enable ingest.yaml daily.yaml`. Failure emails go to
  whoever last edited the cron lines; failures and data-health alerts also open issues.
- **A missed scrape slot is permanently lost** (the API keeps no history); ~90% capture
  is normal and reconstruction treats gaps as gaps, never as unchanged values.
- **Backlog recovery**: if the daily job is down for a while, inboxes accumulate
  harmlessly; each daily run folds up to 600, oldest first — just let it catch up or
  dispatch it repeatedly.
- **Quarantine**: an inbox older than already-merged captures is moved to
  `data/db/inbox/quarantine/` rather than corrupting the change-log; inspect manually.
- **Size tripwire**: compaction fails loudly if a partition would exceed 85 MiB
  (GitHub blocks files at 100 MB); see ADR-001 before changing anything.

## Prior work

Kate Rose Morley's [grid.iamkate.com](https://grid.iamkate.com/) is the canonical live
view. NESO's [data portal](https://www.neso.energy/data-portal) publishes final values;
this project tracks the accuracy of forecasts *as they were published*.
