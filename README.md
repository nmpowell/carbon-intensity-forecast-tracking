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
| 2026-08-30 |     424 |  24.26 |  0.73 |        22.83 |         25.69 |
| 2026-08-31 |     638 |  39.11 |  0.91 |        37.32 |         40.89 |
| 2026-09-01 |     306 |  35.66 |  1.53 |        32.65 |         38.66 |
| 2026-09-02 |     363 |  39.02 |  0.97 |        37.12 |         40.92 |
| 2026-09-03 |     546 |  11.74 |  0.34 |        11.06 |         12.41 |
| 2026-09-04 |     661 |  20.54 |  0.64 |        19.27 |         21.8  |
| 2026-09-05 |     792 |  23.89 |  0.65 |        22.62 |         25.15 |
| 2026-09-06 |     230 |  36.49 |  1.4  |        33.74 |         39.25 |
<!-- cift:daily-stats:end -->

#### Absolute percentage error

<!-- cift:daily-stats-pc:start -->
|            |   mean |   sem |   95% CI low |   95% CI high |
|:-----------|-------:|------:|-------------:|--------------:|
| 2026-08-30 |  24.36 |  0.8  |        22.78 |         25.93 |
| 2026-08-31 |  51.64 |  1.19 |        49.31 |         53.97 |
| 2026-09-01 |  49.41 |  2.42 |        44.64 |         54.17 |
| 2026-09-02 |  27.43 |  0.58 |        26.29 |         28.57 |
| 2026-09-03 |  18.24 |  0.51 |        17.24 |         19.24 |
| 2026-09-04 |  26.3  |  0.62 |        25.08 |         27.53 |
| 2026-09-05 |  29.72 |  0.7  |        28.34 |         31.09 |
| 2026-09-06 |  52.12 |  1.9  |        48.38 |         55.86 |
<!-- cift:daily-stats-pc:end -->

### 30 days

![CI error 30d](./charts/national_ci_error_boxplot_30days.png)

### All data — absolute error

<!-- cift:all-data-summary:start -->
| n | mean | median | std | sem |
|---|---|---|---|---|
| 1356176 | 24.3966 | 20.0 | 19.6189 | 0.016847 |
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
|           100 |                0.00417283 |           0.00074315 |             0.0338575 |
|            90 |                0.00811028 |           0.00240121 |             0.0475335 |
|            80 |                0.0157644  |           0.00697602 |             0.0667335 |
|            70 |                0.0304146  |           0.0182484  |             0.0936889 |
|            60 |                0.057699   |           0.0430559  |             0.131532  |
|            50 |                0.106443   |           0.091822   |             0.184662  |
|            40 |                0.188626   |           0.177459   |             0.259252  |
|            30 |                0.317122   |           0.311815   |             0.36397   |
|            20 |                0.500225   |           0.500146   |             0.510987  |
|            10 |                0.734379   |           0.736023   |             0.717389  |
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
