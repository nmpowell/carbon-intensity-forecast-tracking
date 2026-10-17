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
| 2026-10-09 |     358 |   7.15 |  0.33 |         6.51 |          7.79 |
| 2026-10-10 |     510 |  15.24 |  0.46 |        14.34 |         16.14 |
| 2026-10-11 |     559 |  15.03 |  0.39 |        14.26 |         15.79 |
| 2026-10-12 |     558 |  25.56 |  0.64 |        24.31 |         26.81 |
| 2026-10-13 |     471 |  17.27 |  0.56 |        16.17 |         18.37 |
| 2026-10-14 |     484 |  26.13 |  0.82 |        24.51 |         27.75 |
| 2026-10-15 |     608 |  23.99 |  0.7  |        22.62 |         25.36 |
| 2026-10-16 |     175 |  43.86 |  1.43 |        41.03 |         46.69 |
<!-- cift:daily-stats:end -->

#### Absolute percentage error

<!-- cift:daily-stats-pc:start -->
|            |   mean |   sem |   95% CI low |   95% CI high |
|:-----------|-------:|------:|-------------:|--------------:|
| 2026-10-09 |  15.03 |  0.68 |        13.7  |         16.36 |
| 2026-10-10 |  27.07 |  0.73 |        25.64 |         28.51 |
| 2026-10-11 |  14.09 |  0.46 |        13.18 |         14.99 |
| 2026-10-12 |  21.01 |  0.42 |        20.18 |         21.84 |
| 2026-10-13 |  21    |  0.62 |        19.79 |         22.21 |
| 2026-10-14 |  25.1  |  0.65 |        23.83 |         26.38 |
| 2026-10-15 |  21.3  |  0.51 |        20.29 |         22.31 |
| 2026-10-16 |  29.54 |  0.92 |        27.71 |         31.36 |
<!-- cift:daily-stats-pc:end -->

### 30 days

![CI error 30d](./charts/national_ci_error_boxplot_30days.png)

### All data — absolute error

<!-- cift:all-data-summary:start -->
| n | mean | median | std | sem |
|---|---|---|---|---|
| 1380519 | 24.3789 | 20.0 | 19.5928 | 0.016675 |
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
|           100 |                0.00401338 |          0.000740578 |             0.0339079 |
|            90 |                0.00787409 |          0.0023948   |             0.0476084 |
|            80 |                0.0154323  |          0.0069619   |             0.0668446 |
|            70 |                0.0299813  |          0.0182211   |             0.0938531 |
|            60 |                0.0571908  |          0.0430096   |             0.131775  |
|            50 |                0.105931   |          0.0917535   |             0.185018  |
|            40 |                0.188216   |          0.177372    |             0.259775  |
|            30 |                0.316899   |          0.311721    |             0.364737  |
|            20 |                0.500183   |          0.500065    |             0.512109  |
|            10 |                0.734413   |          0.735976    |             0.719027  |
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
