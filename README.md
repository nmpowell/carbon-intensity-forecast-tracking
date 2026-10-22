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
| 2026-10-14 |     353 |  24.91 |  0.84 |        23.25 |         26.56 |
| 2026-10-15 |     608 |  23.99 |  0.7  |        22.62 |         25.36 |
| 2026-10-16 |     651 |  25.42 |  0.76 |        23.93 |         26.91 |
| 2026-10-17 |     680 |  27.07 |  0.57 |        25.95 |         28.18 |
| 2026-10-18 |     754 |  24.98 |  0.5  |        24.01 |         25.96 |
| 2026-10-19 |     767 |  37.71 |  0.83 |        36.07 |         39.34 |
| 2026-10-20 |     654 |  26.42 |  0.6  |        25.25 |         27.58 |
| 2026-10-21 |     175 |  22.14 |  1.09 |        20    |         24.29 |
<!-- cift:daily-stats:end -->

#### Absolute percentage error

<!-- cift:daily-stats-pc:start -->
|            |   mean |   sem |   95% CI low |   95% CI high |
|:-----------|-------:|------:|-------------:|--------------:|
| 2026-10-14 |  26.54 |  0.76 |        25.04 |         28.04 |
| 2026-10-15 |  21.3  |  0.51 |        20.29 |         22.31 |
| 2026-10-16 |  23.14 |  0.7  |        21.77 |         24.52 |
| 2026-10-17 |  45.79 |  1.01 |        43.81 |         47.77 |
| 2026-10-18 |  29.23 |  0.65 |        27.95 |         30.51 |
| 2026-10-19 |  23.77 |  0.46 |        22.86 |         24.68 |
| 2026-10-20 |  21.23 |  0.4  |        20.45 |         22.02 |
| 2026-10-21 |  23.78 |  0.98 |        21.85 |         25.71 |
<!-- cift:daily-stats-pc:end -->

### 30 days

![CI error 30d](./charts/national_ci_error_boxplot_30days.png)

### All data — absolute error

<!-- cift:all-data-summary:start -->
| n | mean | median | std | sem |
|---|---|---|---|---|
| 1383959 | 24.3876 | 20.0 | 19.5892 | 0.016652 |
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
|           100 |                0.00394879 |          0.000747525 |             0.0339902 |
|            90 |                0.007785   |          0.00241325  |             0.0477125 |
|            80 |                0.0153202  |          0.00700509  |             0.0669746 |
|            70 |                0.0298605  |          0.0183098   |             0.094013  |
|            60 |                0.0570958  |          0.043169    |             0.131967  |
|            50 |                0.105917   |          0.0920018   |             0.185244  |
|            40 |                0.188336   |          0.177704    |             0.260029  |
|            30 |                0.317159   |          0.312091    |             0.365007  |
|            20 |                0.500502   |          0.500393    |             0.512364  |
|            10 |                0.734636   |          0.736171    |             0.719212  |
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
