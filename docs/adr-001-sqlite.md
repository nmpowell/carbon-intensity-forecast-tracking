# ADR-001: Store all data as SQLite databases committed to the repository

Date: 2026-07-16 · Status: accepted

## Context

This repo git-scrapes the NESO Carbon Intensity API (which keeps no forecast history)
twice hourly from GitHub Actions and, once a day, turns the accumulated snapshots into
accuracy statistics, charts, and README tables. The original design committed one
pretty-printed JSON file per endpoint per scrape and wrangled those into per-snapshot
CSVs plus two ever-growing national "summary" pivot CSVs.

By the time the pipeline died (analysis 2023-10-20; scraping 2024-02-03; GitHub then
auto-disabled the schedules after 60 days without commits), the working tree held
**19 GB** of JSON/CSV — one scrape-day cost 184 MB — and the summary CSVs were becoming
impractical to load. Constraints for the redesign: GitHub-hosted ephemeral runners
(nothing persists but the repo), a 100 MB hard per-file limit, twice-hourly scrapes that
must each durably record an unrecoverable observation, and no external infrastructure.

## Decision

1. **All data lives in SQLite files under `data/db/`, committed to the repo.** No JSON
   or CSV data files are written or tracked (test fixtures excepted). Raw API responses
   are parsed in memory and never touch disk.
2. **Inbox pattern for ingestion.** Each scrape writes one small inbox database
   (`data/db/inbox/snap_<slot>.sqlite`, ~131 KB — all five endpoints, full snapshot,
   plus a `captures` provenance row per endpoint) and commits it. The twice-hourly job
   only ever *adds* files; nothing else is touched.
3. **A daily job compacts complete days of inboxes into partitioned databases,**
   deletes the consumed inboxes in the same commit, then rebuilds charts, README tables
   and stats. Partitions are keyed by **window time**, so a window's whole forecast
   trajectory lives in exactly one file:
   - `data/db/<YYYY>/national_<YYYY-MM>.sqlite` — full fidelity (~4.5 MB/month)
   - `data/db/<YYYY>/regional_<YYYY-MM>{a,b}.sqlite` — half-month, change-log (~28–34 MB)
   - `data/db/<YYYY>/generation_<YYYY>.sqlite` — change-log (~3.5 MB/year)
   - `data/db/analysis.sqlite` (derived stats) and `data/db/reference.sqlite`
     (CI index bands, region names, NGESO 2017–23 history)
4. **Change-log storage for regional and generation data**: a row is stored only when
   its value tuple differs from the previous capture (measured: only ~35–45% of values
   change between half-hourly snapshots). The `captures` table records each snapshot's
   true window coverage, so reconstruction forward-fills only across slots that actually
   observed a window; a `capture_gaps` table records (rare, migration-era) holes.
   National data stays full-fidelity, so the primary analysis never depends on
   reconstruction.
5. **Half-month regional partitions bound the worst case by construction**: even at 0%
   change-log savings a partition tops out ≈74 MiB < 100 MB. The compactor asserts an
   85 MiB tripwire.
6. **SQLite-in-git hygiene**: `*.sqlite binary` in `.gitattributes`; sidecar files
   ignored and asserted unstaged; `journal_mode=DELETE`; `page_size=4096` forever;
   `auto_vacuum=NONE`; no routine `VACUUM` (it rewrites every page and destroys git
   delta reuse) — one final VACUUM only when a partition closes.

## Measurements the decision rests on (real repo data, 2026-07)

| Quantity | Measured |
|---|---|
| One scrape as inbox SQLite vs pretty JSON | 131 KB (44 KB compressed) vs 4.3 MB |
| Regional values changed between consecutive snapshots | 35.0–37.6% (Jan), 44.5% (Jul) |
| Git pack growth, simulated 10 days / 491 commits of this pattern | ≈119 MB/month + charts |
| Regional half-month partition, zero-dedupe worst case | ≈74 MiB |

## Consequences

- Working tree shrinks ~19 GB → <700 MB; every file stays far below GitHub limits.
- Historical data (Mar 2023 – Feb 2024 JSON/CSV, including the summary matrices and the
  regional data that exists only in them) is migrated through a staged, exhaustively
  verified importer before any source file is deleted; the git history is then rewritten
  to a fresh root (~0.5 GB clones). Old raw files cease to exist after that point — the
  migration gate (set-equality, dual-implementation re-extraction, cross-path overlap
  check, golden-number reproduction) is the accepted safeguard.
- Chart PNGs become the dominant repo-growth term; DPI drops 250→125 now, and
  client-side rendering from the committed SQLite files (GitHub Pages + sqlite-wasm) is
  the recorded future direction.
- A missed scrape slot remains a permanent, visible gap (the API keeps no history);
  the schedule is offset to minutes 12/42 and both workflows share a concurrency group,
  serialising pushes; failure alerting (pinned issue + optional dead-man ping) exists
  because the 2023/24 outage went unnoticed until GitHub disabled the schedules.
