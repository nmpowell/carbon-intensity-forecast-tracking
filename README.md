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
| 2026-08-27 |      65 |  10.14 |  1.18 |         7.78 |         12.5  |
| 2026-08-28 |     535 |  27.84 |  0.83 |        26.21 |         29.46 |
| 2026-08-29 |     383 |  31.59 |  1.23 |        29.17 |         34.01 |
| 2026-08-30 |     556 |  33.8  |  1.04 |        31.76 |         35.84 |
| 2026-08-31 |     638 |  39.11 |  0.91 |        37.32 |         40.89 |
| 2026-09-01 |     306 |  35.66 |  1.53 |        32.65 |         38.66 |
| 2026-09-02 |     363 |  39.02 |  0.97 |        37.12 |         40.92 |
| 2026-09-03 |     516 |  11.31 |  0.34 |        10.64 |         11.98 |
<!-- cift:daily-stats:end -->

#### Absolute percentage error

<!-- cift:daily-stats-pc:start -->
|            |   mean |   sem |   95% CI low |   95% CI high |
|:-----------|-------:|------:|-------------:|--------------:|
| 2026-08-27 |   6.05 |  0.72 |         4.61 |          7.5  |
| 2026-08-28 |  36.7  |  1.5  |        33.75 |         39.65 |
| 2026-08-29 |  32.17 |  1.47 |        29.28 |         35.07 |
| 2026-08-30 |  32.79 |  1    |        30.82 |         34.77 |
| 2026-08-31 |  51.64 |  1.19 |        49.31 |         53.97 |
| 2026-09-01 |  49.41 |  2.42 |        44.64 |         54.17 |
| 2026-09-02 |  27.43 |  0.58 |        26.29 |         28.57 |
| 2026-09-03 |  17.87 |  0.52 |        16.85 |         18.9  |
<!-- cift:daily-stats-pc:end -->

### 30 days

![CI error 30d](./charts/national_ci_error_boxplot_30days.png)

### All data — absolute error

<!-- cift:all-data-summary:start -->
| n | mean | median | std | sem |
|---|---|---|---|---|
| 1355503 | 24.3952 | 20.0 | 19.6150 | 0.016848 |
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
|           100 |                0.00414752 |          0.000743348 |             0.0338609 |
|            90 |                0.00807349 |          0.00240174  |             0.0475378 |
|            80 |                0.0157139  |          0.00697727  |             0.0667391 |
|            70 |                0.0303506  |          0.018251    |             0.0936962 |
|            60 |                0.0576271  |          0.0430606   |             0.131542  |
|            50 |                0.106376   |          0.0918293   |             0.184673  |
|            40 |                0.18858    |          0.177469    |             0.259266  |
|            30 |                0.317108   |          0.311826    |             0.363988  |
|            20 |                0.500237   |          0.500155    |             0.511008  |
|            10 |                0.734395   |          0.736029    |             0.717413  |
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
