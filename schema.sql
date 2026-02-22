-- SQLite schema for Carbon Intensity Forecast Tracking
--
-- Replaces the wide-format CSV summary files with a normalized relational schema.
-- The key concept "time_difference" (forecast lead time in hours) is no longer stored
-- but derived at query time: (period_from - scraped_at) in hours.
--
-- Design goals:
--   1. Normalised storage — one row per observation, not pivoted columns
--   2. Idempotent ingestion — UNIQUE constraints prevent duplicate inserts
--   3. Efficient queries — indexes on the most common access patterns
--   4. Append-only — new scrapes INSERT without touching existing rows

PRAGMA journal_mode = WAL;            -- better concurrency for concurrent reads/writes
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. scrapes — metadata for each API call
-- ---------------------------------------------------------------------------
-- Each JSON file downloaded from the API is one scrape. The filename encodes
-- the approximate datetime the scrape was made and which endpoint was called.

CREATE TABLE IF NOT EXISTS scrapes (
    scrape_id       INTEGER PRIMARY KEY,
    endpoint        TEXT    NOT NULL,      -- e.g. 'national_fw48h', 'regional_pt24h'
    scraped_at      TEXT    NOT NULL,      -- ISO 8601 UTC, e.g. '2023-10-20T02:01Z'
    filename        TEXT,                  -- original JSON filename for traceability

    UNIQUE (endpoint, scraped_at)
);

CREATE INDEX IF NOT EXISTS idx_scrapes_endpoint   ON scrapes (endpoint);
CREATE INDEX IF NOT EXISTS idx_scrapes_scraped_at ON scrapes (scraped_at);

-- ---------------------------------------------------------------------------
-- 2. regions — static lookup for the 18 GB DNO regions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS regions (
    region_id       INTEGER PRIMARY KEY,  -- 1–18 as defined by the API
    dno_region      TEXT    NOT NULL,      -- e.g. 'Scottish Hydro Electric Power Distribution'
    shortname       TEXT    NOT NULL       -- e.g. 'North Scotland'
);

-- Pre-populate from API data (regionid values are stable)
INSERT OR IGNORE INTO regions (region_id, dno_region, shortname) VALUES
    ( 1, 'Scottish Hydro Electric Power Distribution',  'North Scotland'),
    ( 2, 'SP Distribution',                             'South Scotland'),
    ( 3, 'Electricity North West',                      'North West England'),
    ( 4, 'Northern Powergrid',                          'North East England'),
    ( 5, 'Northern Powergrid',                          'Yorkshire'),
    ( 6, 'Western Power Distribution',                  'North Wales, Merseyside and Cheshire'),
    ( 7, 'SP Manweb',                                   'South Wales'),
    ( 8, 'Western Power Distribution',                  'West Midlands'),
    ( 9, 'Western Power Distribution',                  'East Midlands'),
    (10, 'UK Power Networks',                           'East England'),
    (11, 'UK Power Networks',                           'South East England'),
    (12, 'UK Power Networks',                           'South London'),
    (13, 'Southern Electric Power Distribution',        'South West England'),
    (14, 'Southern Electric Power Distribution',        'South England'),
    (15, 'London Power Networks',                       'London'),
    (16, 'SSE Power Distribution',                      'South East England'),
    (17, 'Western Power Distribution',                  'England'),
    (18, 'National Grid',                               'GB');

-- ---------------------------------------------------------------------------
-- 3. national_intensity — half-hourly national forecast & actual values
-- ---------------------------------------------------------------------------
-- Stores data from both national_fw48h and national_pt24h endpoints.
-- The endpoint distinction is available via the scrapes table.
-- "actual" is NULL for forward-looking forecasts that haven't occurred yet.

CREATE TABLE IF NOT EXISTS national_intensity (
    id              INTEGER PRIMARY KEY,
    scrape_id       INTEGER NOT NULL REFERENCES scrapes (scrape_id),
    period_from     TEXT    NOT NULL,      -- ISO 8601 UTC, start of 30-min period
    period_to       TEXT    NOT NULL,      -- ISO 8601 UTC, end of 30-min period
    forecast        REAL,                  -- gCO2/kWh forecast intensity
    actual          REAL,                  -- gCO2/kWh actual intensity (NULL if not yet known)
    index_label     TEXT,                  -- 'very low', 'low', 'moderate', 'high', 'very high'

    UNIQUE (scrape_id, period_from)
);

CREATE INDEX IF NOT EXISTS idx_national_period   ON national_intensity (period_from);
CREATE INDEX IF NOT EXISTS idx_national_scrape   ON national_intensity (scrape_id);

-- ---------------------------------------------------------------------------
-- 4. regional_intensity — half-hourly per-region forecast & generation mix
-- ---------------------------------------------------------------------------
-- Stores data from regional_fw48h and regional_pt24h endpoints.
-- Generation mix fuel percentages are stored as columns (9 fixed fuel types).
-- Regional data does not include "actual" intensity from the API.

CREATE TABLE IF NOT EXISTS regional_intensity (
    id              INTEGER PRIMARY KEY,
    scrape_id       INTEGER NOT NULL REFERENCES scrapes (scrape_id),
    region_id       INTEGER NOT NULL REFERENCES regions (region_id),
    period_from     TEXT    NOT NULL,      -- ISO 8601 UTC
    period_to       TEXT    NOT NULL,      -- ISO 8601 UTC
    forecast        REAL,                  -- gCO2/kWh forecast intensity
    index_label     TEXT,                  -- intensity index category

    -- Generation mix (percentage of total generation from each fuel)
    biomass         REAL,
    coal            REAL,
    gas             REAL,
    hydro           REAL,
    imports         REAL,
    nuclear         REAL,
    other           REAL,
    solar           REAL,
    wind            REAL,

    UNIQUE (scrape_id, region_id, period_from)
);

CREATE INDEX IF NOT EXISTS idx_regional_period    ON regional_intensity (period_from);
CREATE INDEX IF NOT EXISTS idx_regional_region    ON regional_intensity (region_id, period_from);
CREATE INDEX IF NOT EXISTS idx_regional_scrape    ON regional_intensity (scrape_id);

-- ---------------------------------------------------------------------------
-- 5. national_generation_mix — half-hourly national fuel mix
-- ---------------------------------------------------------------------------
-- Stores data from national_generation_pt24h endpoint.
-- Separate from national_intensity because the API returns them independently.

CREATE TABLE IF NOT EXISTS national_generation_mix (
    id              INTEGER PRIMARY KEY,
    scrape_id       INTEGER NOT NULL REFERENCES scrapes (scrape_id),
    period_from     TEXT    NOT NULL,      -- ISO 8601 UTC
    period_to       TEXT    NOT NULL,      -- ISO 8601 UTC

    -- Generation mix (percentage of total generation from each fuel)
    biomass         REAL,
    coal            REAL,
    gas             REAL,
    hydro           REAL,
    imports         REAL,
    nuclear         REAL,
    other           REAL,
    solar           REAL,
    wind            REAL,

    UNIQUE (scrape_id, period_from)
);

CREATE INDEX IF NOT EXISTS idx_genmix_period ON national_generation_mix (period_from);
CREATE INDEX IF NOT EXISTS idx_genmix_scrape ON national_generation_mix (scrape_id);

-- ---------------------------------------------------------------------------
-- 6. ci_index_bands — reference thresholds for intensity classification
-- ---------------------------------------------------------------------------
-- Defines the gCO2/kWh boundaries for each intensity category per year.
-- Band thresholds narrow over time as the UK grid decarbonises.

CREATE TABLE IF NOT EXISTS ci_index_bands (
    year                INTEGER PRIMARY KEY,
    very_low_from       INTEGER NOT NULL DEFAULT 0,
    very_low_to         INTEGER NOT NULL,
    low_from            INTEGER NOT NULL,
    low_to              INTEGER NOT NULL,
    moderate_from       INTEGER NOT NULL,
    moderate_to         INTEGER NOT NULL,
    high_from           INTEGER NOT NULL,
    high_to             INTEGER NOT NULL,
    very_high_from      INTEGER NOT NULL
);

-- Pre-populate from data/artifacts/ci_index_numerical_bands.csv
INSERT OR IGNORE INTO ci_index_bands VALUES (2017, 0,  99, 100, 199, 200, 299, 300, 400, 401);
INSERT OR IGNORE INTO ci_index_bands VALUES (2018, 0,  79,  80, 179, 180, 279, 280, 380, 381);
INSERT OR IGNORE INTO ci_index_bands VALUES (2019, 0,  59,  60, 159, 160, 259, 260, 360, 361);
INSERT OR IGNORE INTO ci_index_bands VALUES (2020, 0,  54,  55, 149, 150, 229, 230, 350, 351);
INSERT OR IGNORE INTO ci_index_bands VALUES (2021, 0,  49,  50, 139, 140, 219, 220, 330, 331);
INSERT OR IGNORE INTO ci_index_bands VALUES (2022, 0,  44,  45, 129, 130, 209, 210, 310, 311);
INSERT OR IGNORE INTO ci_index_bands VALUES (2023, 0,  39,  40, 119, 120, 199, 200, 290, 291);
INSERT OR IGNORE INTO ci_index_bands VALUES (2024, 0,  34,  35, 109, 110, 189, 190, 270, 271);
INSERT OR IGNORE INTO ci_index_bands VALUES (2025, 0,  29,  30,  99, 100, 179, 180, 250, 251);
INSERT OR IGNORE INTO ci_index_bands VALUES (2026, 0,  24,  25,  89,  90, 169, 170, 230, 231);
INSERT OR IGNORE INTO ci_index_bands VALUES (2027, 0,  19,  20,  79,  80, 159, 160, 210, 211);
INSERT OR IGNORE INTO ci_index_bands VALUES (2028, 0,  14,  15,  69,  70, 149, 150, 190, 191);
INSERT OR IGNORE INTO ci_index_bands VALUES (2029, 0,   9,  10,  59,  60, 139, 140, 170, 171);
INSERT OR IGNORE INTO ci_index_bands VALUES (2030, 0,   4,   5,  49,  50, 129, 130, 150, 151);

-- ---------------------------------------------------------------------------
-- 7. daily_statistics — daily accuracy metrics (replaces stats_history_national.csv)
-- ---------------------------------------------------------------------------
-- Pre-computed daily accuracy metrics. Can also be derived from national_intensity
-- but stored for fast dashboard access and historical continuity.

CREATE TABLE IF NOT EXISTS daily_statistics (
    date                    TEXT PRIMARY KEY,   -- ISO 8601 date, e.g. '2023-03-14'
    forecast_count          INTEGER,
    mean_absolute_error     REAL,               -- gCO2/kWh
    sem_absolute_error      REAL,               -- standard error of the mean
    ci_95_lower_absolute    REAL,               -- 95% confidence interval lower bound
    ci_95_upper_absolute    REAL,               -- 95% confidence interval upper bound
    mean_pct_absolute_error REAL,               -- percentage
    sem_pct_absolute_error  REAL,
    ci_95_lower_pct         REAL,
    ci_95_upper_pct         REAL
);

-- ---------------------------------------------------------------------------
-- Useful views
-- ---------------------------------------------------------------------------

-- Derive time_difference (forecast lead time in hours) at query time.
-- Positive = forecast is looking ahead; negative = looking at past data.
CREATE VIEW IF NOT EXISTS national_forecast_lead AS
SELECT
    ni.id,
    s.endpoint,
    s.scraped_at,
    ni.period_from,
    ni.period_to,
    ni.forecast,
    ni.actual,
    ni.index_label,
    ROUND(
        (julianday(ni.period_from) - julianday(s.scraped_at)) * 24,
        1
    ) AS time_difference_hours
FROM national_intensity ni
JOIN scrapes s ON s.scrape_id = ni.scrape_id;

-- Same for regional data
CREATE VIEW IF NOT EXISTS regional_forecast_lead AS
SELECT
    ri.id,
    s.endpoint,
    s.scraped_at,
    ri.region_id,
    r.shortname,
    r.dno_region,
    ri.period_from,
    ri.period_to,
    ri.forecast,
    ri.index_label,
    ri.biomass, ri.coal, ri.gas, ri.hydro, ri.imports,
    ri.nuclear, ri.other, ri.solar, ri.wind,
    ROUND(
        (julianday(ri.period_from) - julianday(s.scraped_at)) * 24,
        1
    ) AS time_difference_hours
FROM regional_intensity ri
JOIN scrapes s ON s.scrape_id = ri.scrape_id
JOIN regions r ON r.region_id = ri.region_id;

-- Forecast accuracy: for each half-hour period, compare the earliest forecast
-- against the most recent actual value.
CREATE VIEW IF NOT EXISTS national_forecast_accuracy AS
SELECT
    ni.period_from,
    ni.forecast,
    ni.actual,
    ni.forecast - ni.actual                         AS error,
    ABS(ni.forecast - ni.actual)                    AS absolute_error,
    ROUND(
        (julianday(ni.period_from) - julianday(s.scraped_at)) * 24,
        1
    ) AS time_difference_hours
FROM national_intensity ni
JOIN scrapes s ON s.scrape_id = ni.scrape_id
WHERE ni.actual IS NOT NULL;
