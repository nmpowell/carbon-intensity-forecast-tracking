"""One-off historical migration: normalise every source into a staging stream of
candidates, select one source per capture, emit through the production store, and
verify exhaustively before anything is deleted (docs/adr-001-sqlite.md)."""

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from typing import Any
from typing import Iterable

from cift.parse import FUELS
from cift.parse import HALF_HOUR_SECONDS
from cift.parse import MalformedSnapshotError
from cift.parse import Snapshot
from cift.parse import parse_snapshot
from cift.parse import to_epoch
from cift.store import Store

_STAGING_DDL = """
CREATE TABLE IF NOT EXISTS candidates (
    source      TEXT    NOT NULL,
    endpoint    TEXT    NOT NULL,
    window_utc  INTEGER NOT NULL,
    region_id   INTEGER NOT NULL DEFAULT 0,
    capture_utc INTEGER NOT NULL,
    forecast    INTEGER,
    actual      INTEGER,
    biomass INTEGER, coal INTEGER, gas INTEGER, hydro INTEGER, imports INTEGER,
    nuclear INTEGER, other INTEGER, solar INTEGER, wind INTEGER,
    PRIMARY KEY (source, endpoint, window_utc, region_id, capture_utc)
);

CREATE TABLE IF NOT EXISTS candidate_captures (
    source           TEXT    NOT NULL,
    endpoint         TEXT    NOT NULL,
    capture_utc      INTEGER NOT NULL,
    window_first_utc INTEGER NOT NULL,
    window_last_utc  INTEGER NOT NULL,
    observed_utc     INTEGER,
    PRIMARY KEY (source, endpoint, capture_utc)
);

-- Covering index: preflight streams (source, endpoint, capture, window, region)
-- in this exact order as a pure index scan, never touching the main table.
CREATE INDEX IF NOT EXISTS candidates_by_capture
    ON candidates (source, endpoint, capture_utc, window_utc, region_id);
CREATE INDEX IF NOT EXISTS candidates_by_observation
    ON candidates (endpoint, capture_utc, window_utc, region_id);
"""

# Strict inserts: a duplicate key while staging means a source contradicts itself,
# which must surface as an exclusion or error, never a silent overwrite.
_CANDIDATE_INSERT = (
    "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_CAPTURE_INSERT = "INSERT INTO candidate_captures VALUES (?, ?, ?, ?, ?, ?)"

_NO_FUELS = (None,) * 9


@dataclass(frozen=True)
class StageReport:
    """How one source staged: files in, files excluded (name, reason)."""

    staged: int
    excluded: tuple[tuple[str, str], ...] = ()


class Staging:
    """The temporary, uncommitted full-fidelity candidates database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.executescript(_STAGING_DDL)
        connection.close()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        # The real corpus is tens of millions of rows in a multi-gigabyte file;
        # the default 2 MB page cache turns any indexed lookup loop into hours
        # of page thrash (measured). Generous cache + mmap keep reads in memory.
        connection.execute("PRAGMA cache_size = -1048576")  # 1 GiB
        connection.execute("PRAGMA mmap_size = 17179869184")  # 16 GiB
        return connection


def _slot_from_filename(path: Path) -> int:
    """Legacy filenames carry the query time (slot + 1 minute); floor to the slot."""
    stamp = datetime.strptime(path.stem, "%Y-%m-%dT%H%MZ").replace(tzinfo=timezone.utc)
    epoch = int(stamp.timestamp())
    return epoch - epoch % HALF_HOUR_SECONDS


def _candidate_rows(source: str, snapshot: Snapshot) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for window_utc, capture_utc, forecast, actual in snapshot.national:
        rows.append(
            (source, snapshot.endpoint, window_utc, 0, capture_utc, forecast, actual)
            + _NO_FUELS
        )
    for row in snapshot.regional:
        rows.append(
            (source, snapshot.endpoint, row[0], row[1], row[2], row[3], None)
            + tuple(row[4:])
        )
    for row in snapshot.generation:
        rows.append(
            (source, snapshot.endpoint, row[0], 0, row[1], None, None) + tuple(row[2:])
        )
    return rows


def stage_json_backlog(
    staging: Staging, files: Iterable[Path], endpoint: str
) -> StageReport:
    """Stage raw API JSON through the same parser live ingestion uses. Files the
    live parser would reject become documented exclusions, never silent skips."""
    staged = 0
    excluded: list[tuple[str, str]] = []
    connection = staging.connect()
    with connection:
        for path in files:
            slot = _slot_from_filename(path)
            connection.execute("SAVEPOINT stage_file")
            try:
                payload = json.loads(path.read_text())
                snapshot = parse_snapshot(endpoint, payload, slot, slot)
                connection.executemany(
                    _CANDIDATE_INSERT, _candidate_rows("json_backlog", snapshot)
                )
                connection.execute(
                    _CAPTURE_INSERT,
                    (
                        "json_backlog",
                        endpoint,
                        slot,
                        snapshot.window_first_utc,
                        snapshot.window_last_utc,
                        None,  # the true fetch minute was never persisted historically
                    ),
                )
            except (
                json.JSONDecodeError,
                MalformedSnapshotError,
                KeyError,
                ValueError,
                sqlite3.IntegrityError,
            ) as error:
                connection.execute("ROLLBACK TO stage_file")
                connection.execute("RELEASE stage_file")
                excluded.append((path.name, f"{type(error).__name__}: {error}"))
                continue
            connection.execute("RELEASE stage_file")
            staged += 1
    connection.close()
    return StageReport(staged=staged, excluded=tuple(excluded))


class MigrationError(Exception):
    """The sources contradict an invariant; stop rather than emit doubtful data."""


def stage_national_summary(staging: Staging, path: Path, endpoint: str) -> StageReport:
    """Invert the legacy national summary pivot: a cell at (window, lead) becomes an
    observation captured at window - lead. Forecast and actual cells for the same
    (window, capture) merge into one candidate row."""
    observations: dict[tuple[int, int], dict[str, int]] = {}
    coverage: dict[int, set[int]] = {}
    with path.open() as handle:
        reader = csv.reader(handle)
        value_names = next(reader)
        leads = next(reader)
        for record in reader:
            window_utc = to_epoch(record[0])
            for column in range(1, len(value_names)):
                cell = record[column] if column < len(record) else ""
                if not cell:
                    continue
                capture_utc = window_utc - int(float(leads[column]) * 3600)
                field = (
                    "actual"
                    if value_names[column] == "intensity.actual"
                    else "forecast"
                )
                cell_values = observations.setdefault((window_utc, capture_utc), {})
                if field in cell_values:
                    raise MigrationError(
                        f"{path.name}: duplicate {field} cell for window"
                        f" {record[0]} at capture {capture_utc}"
                    )
                cell_values[field] = int(float(cell))
                coverage.setdefault(capture_utc, set()).add(window_utc)

    connection = staging.connect()
    with connection:
        connection.executemany(
            _CANDIDATE_INSERT,
            [
                (
                    "summary_csv",
                    endpoint,
                    window_utc,
                    0,
                    capture_utc,
                    values.get("forecast"),
                    values.get("actual"),
                )
                + _NO_FUELS
                for (window_utc, capture_utc), values in sorted(observations.items())
            ],
        )
        connection.executemany(
            _CAPTURE_INSERT,
            [
                ("summary_csv", endpoint, capture_utc, min(windows), max(windows), None)
                for capture_utc, windows in sorted(coverage.items())
            ],
        )
    connection.close()
    return StageReport(staged=1)


_GAPS_DDL = """
CREATE TABLE IF NOT EXISTS candidate_gaps (
    source      TEXT    NOT NULL,
    endpoint    TEXT    NOT NULL,
    capture_utc INTEGER NOT NULL,
    window_utc  INTEGER NOT NULL,
    region_id   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, endpoint, capture_utc, window_utc, region_id)
);
"""

ALL_REGIONS = frozenset(range(1, 19))


@dataclass(frozen=True)
class PreflightReport:
    gap_count: int


def preflight(staging: Staging) -> PreflightReport:
    """Validate every candidate capture against the single-interval coverage model.

    Legacy code never enforced contiguity or dimensional completeness, so a
    reconstructed capture may have holes; each becomes an explicit gap record —
    "not observed", which reconstruction must never confuse with "unchanged".
    """
    connection = staging.connect()
    gap_count = 0
    with connection:
        connection.executescript(_GAPS_DDL)
        connection.execute("DELETE FROM candidate_gaps")
        coverage = {
            (source, endpoint, capture_utc): (first_utc, last_utc)
            for source, endpoint, capture_utc, first_utc, last_utc in connection.execute(
                "SELECT source, endpoint, capture_utc, window_first_utc,"
                " window_last_utc FROM candidate_captures"
            )
        }

        def flush_group(key: tuple[str, str, int], present: dict[int, set[int]]) -> int:
            source, endpoint, capture_utc = key
            first_utc, last_utc = coverage[key]
            regional = endpoint.startswith("regional")
            gaps: list[tuple[int, int]] = []
            for window_utc in range(first_utc, last_utc + 1, HALF_HOUR_SECONDS):
                regions = present.get(window_utc)
                if regions is None:
                    gaps.append((window_utc, 0))
                elif regional:
                    unknown = regions - ALL_REGIONS
                    if unknown:
                        raise MigrationError(
                            f"{source}/{endpoint} capture {capture_utc}: region ids"
                            f" {sorted(unknown)} are outside 1-18"
                        )
                    gaps.extend(
                        (window_utc, region_id)
                        for region_id in sorted(ALL_REGIONS - regions)
                    )
            connection.executemany(
                "INSERT INTO candidate_gaps VALUES (?, ?, ?, ?, ?)",
                [(source, endpoint, capture_utc, w, r) for w, r in gaps],
            )
            return len(gaps)

        # One pass over the covering index in its own order: the whole corpus
        # streams sequentially instead of one random lookup per capture.
        rows = connection.execute(
            "SELECT source, endpoint, capture_utc, window_utc, region_id"
            " FROM candidates ORDER BY source, endpoint, capture_utc, window_utc"
        )
        seen: set[tuple[str, str, int]] = set()
        for key, group in groupby(rows, key=itemgetter(0, 1, 2)):
            present: dict[int, set[int]] = {}
            for _s, _e, _c, window_utc, region_id in group:
                present.setdefault(window_utc, set()).add(region_id)
            seen.add(key)
            gap_count += flush_group(key, present)

        for key in coverage.keys() - seen:  # captures with zero surviving rows
            gap_count += flush_group(key, {})
    connection.close()
    return PreflightReport(gap_count=gap_count)


_RESOLVED_DDL = """
CREATE TABLE IF NOT EXISTS resolved (
    endpoint    TEXT    NOT NULL,
    window_utc  INTEGER NOT NULL,
    region_id   INTEGER NOT NULL DEFAULT 0,
    capture_utc INTEGER NOT NULL,
    forecast    INTEGER,
    actual      INTEGER,
    biomass INTEGER, coal INTEGER, gas INTEGER, hydro INTEGER, imports INTEGER,
    nuclear INTEGER, other INTEGER, solar INTEGER, wind INTEGER,
    PRIMARY KEY (capture_utc, endpoint, window_utc, region_id)
);

CREATE TABLE IF NOT EXISTS resolved_captures (
    endpoint         TEXT    NOT NULL,
    capture_utc      INTEGER NOT NULL,
    source           TEXT    NOT NULL,
    window_first_utc INTEGER NOT NULL,
    window_last_utc  INTEGER NOT NULL,
    observed_utc     INTEGER,
    PRIMARY KEY (endpoint, capture_utc)
);
"""

# Per-snapshot sources are the truth for any capture they hold; the reconstructed
# summary cells fill only captures no snapshot survives for.
SOURCE_PRIORITY = ("json_backlog", "wrangled_csv", "summary_csv")


def resolve(staging: Staging) -> None:
    """Select one source per (endpoint, capture) and materialise the resolved stream."""
    connection = staging.connect()
    with connection:
        connection.executescript(_RESOLVED_DDL)
        connection.execute("DELETE FROM resolved")
        connection.execute("DELETE FROM resolved_captures")

        connection.executescript("""
            DROP TABLE IF EXISTS winners;
            CREATE TABLE winners (
                source      TEXT    NOT NULL,
                endpoint    TEXT    NOT NULL,
                capture_utc INTEGER NOT NULL,
                PRIMARY KEY (source, endpoint, capture_utc)
            ) WITHOUT ROWID;
            """)
        groups = connection.execute(
            "SELECT endpoint, capture_utc, GROUP_CONCAT(source),"
            " MIN(window_first_utc), MAX(window_last_utc)"
            " FROM candidate_captures GROUP BY endpoint, capture_utc"
        ).fetchall()
        field_coverage = " AND ".join(
            f"(l.{column} IS NULL OR w.{column} IS NOT NULL)"
            for column in _VALUE_COLUMNS.split(", ")
        )
        for endpoint, capture_utc, sources_text, span_first, span_last in groups:
            sources = set(sources_text.split(","))
            winner = next(s for s in SOURCE_PRIORITY if s in sources)
            first, last, observed = connection.execute(
                "SELECT window_first_utc, window_last_utc, observed_utc"
                " FROM candidate_captures WHERE source = ? AND endpoint = ?"
                " AND capture_utc = ?",
                (winner, endpoint, capture_utc),
            ).fetchone()
            if first > span_first or last < span_last:
                raise MigrationError(
                    f"{endpoint} capture {capture_utc}: winning source {winner!r}"
                    f" covers [{first}, {last}] but another source saw"
                    f" [{span_first}, {span_last}]"
                )
            # The expensive cross-source checks only run for the rare captures
            # more than one source survives for (the Apr-2023 overlap).
            for loser in sources - {winner}:
                (hidden,) = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM candidates l
                    WHERE l.source = ? AND l.endpoint = ? AND l.capture_utc = ?
                      AND NOT EXISTS (
                        SELECT 1 FROM candidates w
                        WHERE w.source = ? AND w.endpoint = l.endpoint
                          AND w.window_utc = l.window_utc
                          AND w.region_id = l.region_id
                          AND w.capture_utc = l.capture_utc
                          AND {field_coverage}
                      )
                    """,
                    (loser, endpoint, capture_utc, winner),
                ).fetchone()
                if hidden:
                    raise MigrationError(
                        f"{endpoint} capture {capture_utc}: source {loser!r} holds"
                        f" {hidden} observation(s) the winning source {winner!r}"
                        " lacks; refusing to discard them"
                    )
            connection.execute(
                "INSERT INTO winners VALUES (?, ?, ?)", (winner, endpoint, capture_utc)
            )
            connection.execute(
                "INSERT INTO resolved_captures VALUES (?, ?, ?, ?, ?, ?)",
                (endpoint, capture_utc, winner, first, last, observed),
            )

        # One sequential scan of candidates; each row does a tiny indexed lookup
        # into the fully-cached winners table. The ORDER BY matches resolved's
        # primary key, so the b-tree fills by append instead of random inserts.
        connection.execute(
            "INSERT INTO resolved SELECT c.endpoint, c.window_utc, c.region_id,"
            " c.capture_utc, c.forecast, c.actual, c.biomass, c.coal, c.gas,"
            " c.hydro, c.imports, c.nuclear, c.other, c.solar, c.wind"
            " FROM candidates c WHERE EXISTS ("
            "   SELECT 1 FROM winners w WHERE w.source = c.source"
            "   AND w.endpoint = c.endpoint AND w.capture_utc = c.capture_utc)"
            " ORDER BY c.capture_utc, c.endpoint, c.window_utc, c.region_id"
        )
    connection.close()


def emit(
    staging: Staging,
    store: Store,
    compact_now: datetime,
    batch_slots: int = 500,
) -> int:
    """Replay the resolved stream through the production write path, oldest slot
    first, compacting in bounded batches. Returns the number of captures emitted."""
    connection = staging.connect()
    meta = {
        (capture_utc, endpoint): (source, first, last, observed)
        for endpoint, capture_utc, source, first, last, observed in connection.execute(
            "SELECT endpoint, capture_utc, source, window_first_utc,"
            " window_last_utc, observed_utc FROM resolved_captures"
        )
    }
    gaps_by_capture: dict[tuple[int, str], list[tuple[int, int]]] = {}
    for endpoint, capture_utc, window_utc, region_id in connection.execute(
        "SELECT endpoint, capture_utc, window_utc, region_id FROM candidate_gaps g"
        " WHERE EXISTS (SELECT 1 FROM resolved_captures r WHERE r.endpoint ="
        " g.endpoint AND r.capture_utc = g.capture_utc AND r.source = g.source)"
    ):
        gaps_by_capture.setdefault((capture_utc, endpoint), []).append(
            (window_utc, region_id)
        )

    emitted = 0
    pending_slots = 0
    # A single scan in the resolved table's primary-key order: every capture's
    # rows arrive together, so no per-capture queries against the big table.
    rows = connection.execute(
        "SELECT capture_utc, endpoint, window_utc, region_id, forecast, actual,"
        " biomass, coal, gas, hydro, imports, nuclear, other, solar, wind"
        " FROM resolved ORDER BY capture_utc, endpoint, window_utc, region_id"
    )
    for slot, slot_group in groupby(rows, key=itemgetter(0)):
        snapshots = []
        for endpoint, capture_group in groupby(slot_group, key=itemgetter(1)):
            snapshots.append(
                _snapshot_from_rows(
                    slot, endpoint, capture_group, meta, gaps_by_capture
                )
            )
        store.write_inbox(snapshots)
        emitted += len(snapshots)
        pending_slots += 1
        if pending_slots >= batch_slots:
            store.compact(now=compact_now)
            pending_slots = 0
            print(f"[migrate] emitted {emitted} captures...", flush=True)
    connection.close()
    store.compact(now=compact_now)
    return emitted


def _snapshot_from_rows(
    slot: int,
    endpoint: str,
    capture_rows: Iterable[tuple[Any, ...]],
    meta: dict[tuple[int, str], tuple[Any, ...]],
    gaps_by_capture: dict[tuple[int, str], list[tuple[int, int]]],
) -> Snapshot:
    """Assemble one capture's Snapshot from its streamed resolved rows."""
    source, first, last, observed = meta[(slot, endpoint)]
    national: list[tuple[int, int, int | None, int | None]] = []
    regional: list[tuple[int | None, ...]] = []
    generation: list[tuple[int | None, ...]] = []
    for (
        _slot,
        _endpoint,
        window_utc,
        region_id,
        forecast,
        actual,
        *fuels,
    ) in capture_rows:
        if endpoint == "national_generation_pt24h":
            generation.append((window_utc, slot, *fuels))
        elif endpoint.startswith("national"):
            national.append((window_utc, slot, forecast, actual))
        else:
            regional.append((window_utc, region_id, slot, forecast, *fuels))
    return Snapshot(
        endpoint=endpoint,
        capture_utc=slot,
        observed_utc=None if observed is None else int(observed),
        window_first_utc=int(first),
        window_last_utc=int(last),
        national=tuple(national),
        regional=tuple(regional),
        generation=tuple(generation),
        source=str(source),
        gaps=tuple(gaps_by_capture.get((slot, endpoint), ())),
    )


def stage_regional_summary(staging: Staging, path: Path, endpoint: str) -> StageReport:
    """Invert the legacy regional summary pivot (three header rows: value name,
    region id, lead). This is the ONLY surviving source for regional data before
    the per-snapshot CSVs begin (2023-03-12 to 2023-04-05/08)."""
    observations: dict[tuple[int, int, int], dict[str, int]] = {}
    coverage: dict[int, set[int]] = {}
    with path.open() as handle:
        reader = csv.reader(handle)
        value_names = next(reader)
        region_ids = next(reader)
        leads = next(reader)
        for record in reader:
            if not record or not record[0]:
                continue
            window_utc = to_epoch(record[0])
            for column in range(1, len(value_names)):
                cell = record[column] if column < len(record) else ""
                if not cell:
                    continue
                capture_utc = window_utc - int(float(leads[column]) * 3600)
                region_id = int(float(region_ids[column]))
                name = value_names[column]
                field = "forecast" if name == "regions.intensity.forecast" else name
                value = int(float(cell)) if field == "forecast" else _tenths(cell)
                cell_values = observations.setdefault(
                    (window_utc, region_id, capture_utc), {}
                )
                if field in cell_values:
                    raise MigrationError(
                        f"{path.name}: duplicate {field} cell for window"
                        f" {record[0]} region {region_id} at capture {capture_utc}"
                    )
                cell_values[field] = value
                coverage.setdefault(capture_utc, set()).add(window_utc)

    connection = staging.connect()
    with connection:
        connection.executemany(
            _CANDIDATE_INSERT,
            [
                (
                    "summary_csv",
                    endpoint,
                    window_utc,
                    region_id,
                    capture_utc,
                    values.get("forecast"),
                    None,
                    *[values.get(fuel) for fuel in FUELS],
                )
                for (window_utc, region_id, capture_utc), values in sorted(
                    observations.items()
                )
            ],
        )
        connection.executemany(
            _CAPTURE_INSERT,
            [
                ("summary_csv", endpoint, capture_utc, min(windows), max(windows), None)
                for capture_utc, windows in sorted(coverage.items())
            ],
        )
    connection.close()
    return StageReport(staged=1)


def import_reference_data(
    store: Store, artifacts_dir: Path, samples_dir: Path
) -> dict[str, int]:
    """Seed reference.sqlite from the small legacy reference CSVs."""
    counts = {}
    bands_rows: list[tuple[int, int, str, int, int | None]] = []
    with (artifacts_dir / "ci_index_numerical_bands.csv").open(
        encoding="utf-8-sig"
    ) as handle:
        reader = csv.reader(handle)
        band_names = next(reader)
        kinds = next(reader)
        for record in reader:
            year = int(record[0])
            position = 0
            for column in range(1, len(kinds), 2):
                lo = int(record[column])
                hi_column = column + 1
                hi = (
                    int(record[hi_column])
                    if hi_column < len(kinds) and kinds[hi_column] == "to"
                    else None
                )
                bands_rows.append((year, position, band_names[column], lo, hi))
                position += 1
    store.record_reference_bands(bands_rows)
    counts["ci_index_bands"] = len(bands_rows)

    scales_rows: list[tuple[int, str, float, float]] = []
    with (artifacts_dir / "ci_index_numerical_band_error_scales.csv").open(
        encoding="utf-8-sig"
    ) as handle:
        reader = csv.reader(handle)
        transitions = next(reader)
        kinds = next(reader)
        for record in reader:
            year = int(record[0])
            for column in range(1, len(kinds), 2):
                scales_rows.append(
                    (
                        year,
                        transitions[column],
                        float(record[column]),
                        float(record[column + 1]),
                    )
                )
    store.record_band_error_scales(scales_rows)
    counts["ci_band_error_scales"] = len(scales_rows)

    history_rows: list[tuple[int, int | None, int | None, str]] = []
    for sample in sorted(samples_dir.glob("Carbon_Intensity_Data_*.csv")):
        with sample.open(encoding="utf-8-sig") as handle:
            for entry in csv.DictReader(handle):
                history_rows.append(
                    (
                        to_epoch(entry["Datetime (UTC)"]),
                        int(entry["Actual Carbon Intensity (gCO2/kWh)"] or 0) or None,
                        int(entry["Forecast Carbon Intensity (gCO2/kWh)"] or 0) or None,
                        entry["Index"],
                    )
                )
    store.record_ngeso_history(history_rows)
    counts["ngeso_history"] = len(history_rows)
    return counts


_VALUE_COLUMNS = (
    "forecast, actual, biomass, coal, gas, hydro, imports, nuclear, other, solar, wind"
)


@dataclass(frozen=True)
class OverlapReport:
    """Cross-source disagreements on shared observation keys.

    A summary cell losing to a per-snapshot source is documented but acceptable:
    the legacy pipeline could genuinely fetch twice in one slot (its final run
    did), so the summary reconstruction and the raw snapshot record different
    real API responses. Raw sources disagreeing with each other is always fatal.
    """

    fatal: int
    accepted: tuple[str, ...] = ()


# The complete, frozen set of known cross-source disagreements. The legacy
# pipeline's final wrangle fetched twice inside the 2023-10-20 02:00 slot, so the
# summary reconstruction and the raw snapshot record two REAL, different API
# responses for these two observations. Anything else is fatal.
KNOWN_OVERLAP_EXCEPTIONS = frozenset(
    {
        ("national_pt24h", 1697763600, 0, 1697767200),
        ("national_pt24h", 1697765400, 0, 1697767200),
    }
)


def verify_overlap(staging: Staging) -> OverlapReport:
    """Find observation keys where two sources disagree on any value."""
    connection = staging.connect()
    comparisons = " OR ".join(
        f"a.{column} IS NOT b.{column}" for column in _VALUE_COLUMNS.split(", ")
    )
    rows = connection.execute(f"""
        SELECT a.source, b.source, a.endpoint, a.window_utc, a.region_id,
               a.capture_utc
        FROM candidates a JOIN candidates b
          ON a.endpoint = b.endpoint AND a.window_utc = b.window_utc
         AND a.region_id = b.region_id AND a.capture_utc = b.capture_utc
         AND a.source < b.source
        WHERE {comparisons}
        """).fetchall()
    connection.close()

    fatal = 0
    accepted = []
    for source_a, source_b, endpoint, window_utc, region_id, capture_utc in rows:
        described = (
            f"{endpoint} window={window_utc} region={region_id}"
            f" capture={capture_utc}: {source_a} vs {source_b}"
        )
        if (endpoint, window_utc, region_id, capture_utc) in KNOWN_OVERLAP_EXCEPTIONS:
            accepted.append(described)
        else:
            fatal += 1
    return OverlapReport(fatal=fatal, accepted=tuple(accepted))


def golden_corpus(staging: Staging) -> tuple[int, float]:
    """The legacy error population over the staged national summaries: its count and
    mean absolute error must reproduce the frozen README totals before anything is
    deleted (849,545 and 24.4642 on the real corpus)."""
    from cift.analysis import error_frames
    from cift.analysis import matrix_from_rows

    connection = staging.connect()
    rows = connection.execute(
        "SELECT window_utc, capture_utc, forecast, actual FROM candidates"
        " WHERE source = 'summary_csv' AND endpoint LIKE 'national_%'"
    ).fetchall()
    connection.close()
    errors, _ = error_frames(matrix_from_rows(rows))
    stacked = errors.stack().dropna()
    return int(stacked.count()), float(stacked.abs().mean())


def verify_provenance(staging: Staging, store: Store) -> int:
    """Mismatches between the expected physical capture set and the stored one.

    Expected = every resolved capture routed to every partition its coverage
    overlaps, with its source and coverage. Compared symmetrically, so missing,
    extra, misrouted, and relabelled capture rows all count. Valid only at
    migration time, when no live captures exist yet."""
    connection = staging.connect()
    expected: set[tuple[str, int, str, str, int, int]] = set()
    for endpoint, capture_utc, source, first_utc, last_utc in connection.execute(
        "SELECT endpoint, capture_utc, source, window_first_utc, window_last_utc"
        " FROM resolved_captures"
    ):
        kind = "generation" if "generation" in endpoint else endpoint.split("_")[0]
        for path in store.partitions_overlapping(kind, first_utc, last_utc):
            expected.add(
                (path.name, capture_utc, endpoint, source, first_utc, last_utc)
            )
    connection.close()

    stored: set[tuple[str, int, str, str, int, int]] = set()
    for partition in sorted(store.db_root.glob("[0-9][0-9][0-9][0-9]/*.sqlite")):
        p_connection = sqlite3.connect(partition)
        for capture_utc, endpoint, first_utc, last_utc, source in p_connection.execute(
            "SELECT capture_utc, endpoint, window_first_utc, window_last_utc, source"
            " FROM captures"
        ):
            stored.add(
                (partition.name, capture_utc, endpoint, source, first_utc, last_utc)
            )
        p_connection.close()
    return len(expected ^ stored)


def verify_reconstruction(staging: Staging, store: Store) -> dict[str, int]:
    """Expand the emitted partitions back to full fidelity and compare, in both
    directions, against the resolved observation stream. Every count must be zero;
    this — not sampling — is the gate for deleting source files."""
    connection = staging.connect()
    connection.executescript("""
        DROP TABLE IF EXISTS reconstructed;
        CREATE TABLE reconstructed (
            family      TEXT    NOT NULL,
            window_utc  INTEGER NOT NULL,
            region_id   INTEGER NOT NULL DEFAULT 0,
            capture_utc INTEGER NOT NULL,
            forecast    INTEGER,
            actual      INTEGER,
            biomass INTEGER, coal INTEGER, gas INTEGER, hydro INTEGER, imports INTEGER,
            nuclear INTEGER, other INTEGER, solar INTEGER, wind INTEGER,
            PRIMARY KEY (family, window_utc, region_id, capture_utc)
        );
        """)
    with connection:
        for partition in sorted(store.db_root.glob("[0-9][0-9][0-9][0-9]/*.sqlite")):
            _expand_partition(connection, partition)

    mismatches = {}
    for family, endpoint_filter in (
        ("national", "endpoint LIKE 'national_%' AND endpoint NOT LIKE '%generation%'"),
        ("regional", "endpoint LIKE 'regional_%'"),
        ("generation", "endpoint = 'national_generation_pt24h'"),
    ):
        resolved = (
            f"SELECT window_utc, region_id, capture_utc, {_VALUE_COLUMNS}"
            f" FROM resolved WHERE {endpoint_filter}"
        )
        rebuilt = (
            f"SELECT window_utc, region_id, capture_utc, {_VALUE_COLUMNS}"
            f" FROM reconstructed WHERE family = {family!r}"
        )
        (missing,) = connection.execute(
            f"SELECT COUNT(*) FROM ({resolved} EXCEPT {rebuilt})"
        ).fetchone()
        (extra,) = connection.execute(
            f"SELECT COUNT(*) FROM ({rebuilt} EXCEPT {resolved})"
        ).fetchone()
        mismatches[f"{family}_missing"] = int(missing)
        mismatches[f"{family}_extra"] = int(extra)
    connection.close()
    return mismatches


def _expand_partition(target: sqlite3.Connection, partition: Path) -> None:
    """Rebuild every observation a partition implies: full national rows, and
    change-log rows forward-filled across each capture's coverage minus gaps."""
    source = sqlite3.connect(partition)
    rows = source.execute(
        "SELECT window_utc, capture_utc, forecast, actual FROM national_intensity"
    ).fetchall()
    target.executemany(
        "INSERT OR IGNORE INTO reconstructed VALUES ('national', ?, 0, ?, ?, ?,"
        " NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
        rows,
    )

    gaps = {
        (capture, endpoint, window, region)
        for capture, endpoint, window, region in source.execute(
            "SELECT capture_utc, endpoint, window_utc, region_id FROM capture_gaps"
        )
    }
    captures = source.execute(
        "SELECT capture_utc, endpoint, window_first_utc, window_last_utc FROM captures"
    ).fetchall()

    for family, table, key_width in (
        ("regional", "regional_intensity", 2),
        ("generation", "generation_mix", 1),
    ):
        changes: dict[tuple[int, int], list[tuple[int, tuple[int, ...]]]] = {}
        for row in source.execute(f"SELECT * FROM {table} ORDER BY capture_utc"):
            if key_width == 2:
                key, capture, values = (row[0], row[1]), row[2], tuple(row[3:])
            else:
                key, capture, values = (row[0], 0), row[1], tuple(row[2:])
            changes.setdefault(key, []).append((capture, values))

        family_endpoints = [
            (capture, endpoint, first, last)
            for capture, endpoint, first, last in captures
            if (endpoint.startswith("regional")) == (family == "regional")
            and ("generation" in endpoint) == (family == "generation")
        ]
        expanded: list[tuple[Any, ...]] = []
        region_ids = range(1, 19) if family == "regional" else (0,)
        for capture, endpoint, first, last in family_endpoints:
            for window in range(first, last + 1, HALF_HOUR_SECONDS):
                if (capture, endpoint, window, 0) in gaps and family == "regional":
                    continue
                for region_id in region_ids:
                    if (capture, endpoint, window, region_id) in gaps:
                        continue
                    trail = changes.get((window, region_id), [])
                    value = None
                    for change_capture, values in trail:
                        if change_capture <= capture:
                            value = values
                        else:
                            break
                    if value is None:
                        continue
                    if family == "regional":
                        forecast, fuels = value[0], value[1:]
                    else:
                        forecast, fuels = None, value
                    expanded.append(
                        (family, window, region_id, capture, forecast, None, *fuels)
                    )
        target.executemany(
            "INSERT OR IGNORE INTO reconstructed VALUES"
            " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            expanded,
        )
    source.close()


def reextract_sample(staging: Staging, files: Iterable[Path], endpoint: str) -> int:
    """Dual-implementation check: re-extract sampled raw JSON files with direct
    dict access (no shared parser code) and count disagreements with staging."""
    connection = staging.connect()
    mismatches = 0
    for path in files:
        slot = _slot_from_filename(path)
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            (staged_rows,) = connection.execute(
                "SELECT COUNT(*) FROM candidates WHERE source = 'json_backlog'"
                " AND endpoint = ? AND capture_utc = ?",
                (endpoint, slot),
            ).fetchone()
            # An unreadable file that staging also excluded is consistent; one
            # that somehow produced staged rows is a discrepancy.
            mismatches += 1 if staged_rows else 0
            continue
        for window in payload["data"]:
            window_utc = to_epoch(window["from"])
            if endpoint.startswith("national") and "generation" not in endpoint:
                expected = (
                    window["intensity"]["forecast"],
                    window["intensity"].get("actual"),
                )
                stored = connection.execute(
                    "SELECT forecast, actual FROM candidates"
                    " WHERE source = 'json_backlog' AND endpoint = ?"
                    " AND window_utc = ? AND capture_utc = ? AND region_id = 0",
                    (endpoint, window_utc, slot),
                ).fetchone()
                mismatches += stored != expected
            elif endpoint.startswith("regional"):
                for region in window["regions"]:
                    percs = {m["fuel"]: m["perc"] for m in region["generationmix"]}
                    expected = (
                        region["intensity"]["forecast"],
                        *[round(percs[f] * 10) for f in FUELS],
                    )
                    stored = connection.execute(
                        "SELECT forecast, biomass, coal, gas, hydro, imports, nuclear,"
                        " other, solar, wind FROM candidates"
                        " WHERE source = 'json_backlog' AND endpoint = ?"
                        " AND window_utc = ? AND capture_utc = ? AND region_id = ?",
                        (endpoint, window_utc, slot, region["regionid"]),
                    ).fetchone()
                    mismatches += stored != expected
            else:
                percs = {m["fuel"]: m["perc"] for m in window["generationmix"]}
                expected = tuple(round(percs[f] * 10) for f in FUELS)
                stored = connection.execute(
                    "SELECT biomass, coal, gas, hydro, imports, nuclear, other,"
                    " solar, wind FROM candidates"
                    " WHERE source = 'json_backlog' AND endpoint = ?"
                    " AND window_utc = ? AND capture_utc = ? AND region_id = 0",
                    (endpoint, window_utc, slot),
                ).fetchone()
                mismatches += stored != expected
    connection.close()
    return mismatches


# The frozen README totals the migrated national summaries must reproduce.
GOLDEN_COUNT = 849_545
GOLDEN_MEAN = 24.4642


@dataclass(frozen=True)
class MigrationReport:
    staged: dict[str, StageReport]
    gap_count: int
    emitted: int
    overlap: "OverlapReport"
    reconstruction: dict[str, int]
    reextraction_mismatches: int
    provenance_mismatches: int
    leftover_inboxes: int
    golden: tuple[int, float]
    reference_counts: dict[str, int]

    @property
    def gate_passed(self) -> bool:
        return (
            self.overlap.fatal == 0
            and set(self.reconstruction.values()) == {0}
            and self.reextraction_mismatches == 0
            and self.provenance_mismatches == 0
            and self.leftover_inboxes == 0
        )


def run_migration(
    data_dir: Path,
    db_root: Path,
    staging_path: Path,
    reextract_per_month: int = 3,
) -> MigrationReport:
    """Stage every historical source, resolve, emit, and run the verification gate.

    Returns the raw report; callers decide whether the gate (including the golden
    totals, which only apply to the full real corpus) permits deletion.
    """
    from cift.parse import ENDPOINTS

    # A rerun over existing state is exactly how the 709-file incident happened:
    # stale candidates, re-emitted inboxes, quarantine flood. Refuse up front.
    if staging_path.exists():
        raise MigrationError(
            f"staging database {staging_path} already exists; the migration"
            " requires a fresh staging path"
        )
    if db_root.exists() and any(db_root.glob("**/*.sqlite")):
        raise MigrationError(
            f"db_root {db_root} already contains databases; the migration emits"
            " into a fresh root"
        )

    staging = Staging(staging_path)
    staged: dict[str, StageReport] = {}
    reextract_files: list[tuple[Path, str]] = []
    for endpoint in ENDPOINTS:
        endpoint_dir = data_dir / endpoint
        files = sorted(endpoint_dir.glob("*.json")) if endpoint_dir.exists() else []
        if files:
            print(f"staging {endpoint}: {len(files)} json files...", flush=True)
            staged[f"{endpoint}/json"] = stage_json_backlog(staging, files, endpoint)
            by_month: dict[str, int] = {}
            for path in files:
                month = path.name[:7]
                if by_month.get(month, 0) < reextract_per_month:
                    by_month[month] = by_month.get(month, 0) + 1
                    reextract_files.append((path, endpoint))
        csv_files = sorted(endpoint_dir.glob("*.csv")) if endpoint_dir.exists() else []
        if csv_files:
            staged[f"{endpoint}/csv"] = stage_wrangled_csvs(
                staging, csv_files, endpoint
            )

    for name, stager in (
        ("summary_national_fw48h.csv", stage_national_summary),
        ("summary_national_pt24h.csv", stage_national_summary),
        ("summary_regional_fw48h.csv", stage_regional_summary),
        ("summary_regional_pt24h.csv", stage_regional_summary),
    ):
        summary_path = data_dir / name
        if summary_path.exists():
            endpoint = name.removeprefix("summary_").removesuffix(".csv")
            print(f"staging {name}...", flush=True)
            staged[f"{endpoint}/summary"] = stager(staging, summary_path, endpoint)

    print("preflight...", flush=True)
    gap_report = preflight(staging)
    print("resolve...", flush=True)
    resolve(staging)

    connection = staging.connect()
    (last_slot,) = connection.execute(
        "SELECT MAX(capture_utc) FROM resolved_captures"
    ).fetchone()
    connection.close()
    compact_now = datetime.fromtimestamp(last_slot, tz=timezone.utc) + timedelta(days=2)

    print("emit...", flush=True)
    store = Store(db_root)
    emitted = emit(staging, store, compact_now=compact_now)
    print(f"emitted {emitted} captures; verifying...", flush=True)

    mismatched_reextractions = 0
    for path, endpoint in reextract_files:
        mismatched_reextractions += reextract_sample(staging, [path], endpoint)

    print("[migrate] verifying reconstruction (both directions)", flush=True)
    reconstruction = verify_reconstruction(staging, store)
    print(f"[migrate] reconstruction: {reconstruction}; golden corpus", flush=True)
    golden = golden_corpus(staging)

    reference_counts = {}
    if (data_dir / "artifacts").exists():
        reference_counts = import_reference_data(
            store, data_dir / "artifacts", data_dir / "samples"
        )

    return MigrationReport(
        staged=staged,
        gap_count=gap_report.gap_count,
        emitted=emitted,
        overlap=verify_overlap(staging),
        reconstruction=reconstruction,
        reextraction_mismatches=mismatched_reextractions,
        provenance_mismatches=verify_provenance(staging, store),
        leftover_inboxes=len(list(store.inbox_dir.glob("**/*.sqlite"))),
        golden=golden,
        reference_counts=reference_counts,
    )


def _tenths(value: str) -> int:
    scaled = float(value) * 10
    if abs(scaled - round(scaled)) > 1e-9:
        raise ValueError(f"fuel percentage {value} has more than one decimal")
    return round(scaled)


def stage_wrangled_csvs(
    staging: Staging, files: Iterable[Path], endpoint: str
) -> StageReport:
    """Stage the per-snapshot CSVs the legacy wrangle step produced (2023 era).

    The capture slot comes from the filename — the only provenance those files
    carry; the exact fetch minute never existed, so observed_utc stays NULL.
    """
    staged = 0
    excluded: list[tuple[str, str]] = []
    connection = staging.connect()
    with connection:
        for path in files:
            slot = _slot_from_filename(path)
            connection.execute("SAVEPOINT stage_file")
            try:
                rows, first, last = _read_wrangled_csv(path, endpoint, slot)
                connection.executemany(_CANDIDATE_INSERT, rows)
                connection.execute(
                    _CAPTURE_INSERT, ("wrangled_csv", endpoint, slot, first, last, None)
                )
            except (ValueError, KeyError, sqlite3.IntegrityError) as error:
                connection.execute("ROLLBACK TO stage_file")
                connection.execute("RELEASE stage_file")
                excluded.append((path.name, f"{type(error).__name__}: {error}"))
                continue
            connection.execute("RELEASE stage_file")
            staged += 1
    connection.close()
    return StageReport(staged=staged, excluded=tuple(excluded))


def _read_wrangled_csv(
    path: Path, endpoint: str, slot: int
) -> tuple[list[tuple[object, ...]], int, int]:
    rows: list[tuple[object, ...]] = []
    windows: set[int] = set()
    with path.open() as handle:
        for record in csv.DictReader(handle):
            window_utc = to_epoch(record["from"])
            windows.add(window_utc)
            fuels = tuple(_tenths(record[fuel]) for fuel in FUELS)
            if endpoint == "national_generation_pt24h":
                rows.append(
                    ("wrangled_csv", endpoint, window_utc, 0, slot, None, None) + fuels
                )
            else:
                rows.append(
                    (
                        "wrangled_csv",
                        endpoint,
                        window_utc,
                        int(record["regions.regionid"]),
                        slot,
                        int(record["regions.intensity.forecast"]),
                        None,
                    )
                    + fuels
                )
    if not windows:
        raise ValueError("no rows in file")
    return rows, min(windows), max(windows)
