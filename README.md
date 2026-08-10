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
| 2026-08-02 |    1201 |  24.21 |  0.41 |        23.42 |         25.01 |
| 2026-08-03 |    1400 |  13.91 |  0.35 |        13.23 |         14.59 |
| 2026-08-04 |    1191 |  23.63 |  0.54 |        22.58 |         24.68 |
| 2026-08-05 |    1081 |  18.41 |  0.46 |        17.5  |         19.31 |
| 2026-08-06 |    1066 |  11.87 |  0.29 |        11.3  |         12.45 |
| 2026-08-07 |    1096 |  26.92 |  0.56 |        25.82 |         28.02 |
| 2026-08-08 |    1476 |  18.43 |  0.37 |        17.69 |         19.16 |
| 2026-08-09 |     262 |  39.86 |  0.51 |        38.85 |         40.87 |
<!-- cift:daily-stats:end -->

#### Absolute percentage error

<!-- cift:daily-stats-pc:start -->
|            |   mean |    sem |   95% CI low |   95% CI high |
|:-----------|-------:|-------:|-------------:|--------------:|
| 2026-08-02 |  19.59 |   0.31 |        18.98 |         20.2  |
| 2026-08-03 |  11.05 |   0.25 |        10.56 |         11.54 |
| 2026-08-04 |  18.1  |   0.39 |        17.33 |         18.86 |
| 2026-08-05 |  27.06 |   0.56 |        25.97 |         28.15 |
| 2026-08-06 | inf    | nan    |       nan    |        nan    |
| 2026-08-07 |  22.91 |   0.45 |        22.03 |         23.78 |
| 2026-08-08 |  21.22 |   0.38 |        20.48 |         21.96 |
| 2026-08-09 |  55.98 |   0.74 |        54.53 |         57.44 |
<!-- cift:daily-stats-pc:end -->

### 30 days

![CI error 30d](./charts/national_ci_error_boxplot_30days.png)

### All data — absolute error

<!-- cift:all-data-summary:start -->
| n | mean | median | std | sem |
|---|---|---|---|---|
| 1311587 | 24.2236 | 20.0 | 19.4908 | 0.017019 |
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
|           100 |                0.003947   |          0.000672507 |             0.0330594 |
|            90 |                0.00771569 |          0.00221185  |             0.0465238 |
|            80 |                0.0150895  |          0.00652924  |             0.065472  |
|            70 |                0.0292998  |          0.0173236   |             0.0921375 |
|            60 |                0.0559523  |          0.0413842   |             0.129663  |
|            50 |                0.103906   |          0.0892032   |             0.182473  |
|            40 |                0.185312   |          0.173949    |             0.25679   |
|            30 |                0.313387   |          0.307881    |             0.361375  |
|            20 |                0.496843   |          0.496652    |             0.508556  |
|            10 |                0.732333   |          0.733948    |             0.715681  |
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
