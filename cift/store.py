"""Partitioned SQLite storage: inbox files per scrape, window-keyed partitions.

Layout under a db root (see docs/adr-001-sqlite.md):
    inbox/snap_<slot>.sqlite          one full snapshot per scrape, merged then deleted
    <YYYY>/national_<YYYY-MM>.sqlite  full-fidelity national trajectories
    <YYYY>/regional_<YYYY-MM>{a,b}.sqlite
    <YYYY>/generation_<YYYY>.sqlite
"""

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Sequence

from cift.parse import Snapshot

SCHEMA_VERSION = 1


class SchemaVersionError(Exception):
    """The database was written by a newer schema than this code understands."""


class PartitionSizeError(Exception):
    """A partition file has grown past the safe limit; refuse to continue."""


@dataclass(frozen=True)
class CompactReport:
    """What one compaction run did, for job summaries and tests."""

    merged_inboxes: int
    remaining_inboxes: int
    quarantined: tuple[str, ...] = ()


_PRAGMAS = """
PRAGMA page_size = 4096;
PRAGMA journal_mode = DELETE;
PRAGMA auto_vacuum = NONE;
PRAGMA synchronous = NORMAL;
PRAGMA application_id = 0x43494654;
"""

_FUEL_COLUMNS = (
    "biomass INTEGER, coal INTEGER, gas INTEGER, hydro INTEGER, imports INTEGER,"
    " nuclear INTEGER, other INTEGER, solar INTEGER, wind INTEGER"
)

_DDL = f"""
CREATE TABLE IF NOT EXISTS national_intensity (
    window_utc  INTEGER NOT NULL,
    capture_utc INTEGER NOT NULL,
    forecast    INTEGER,
    actual      INTEGER,
    PRIMARY KEY (window_utc, capture_utc)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS regional_intensity (
    window_utc  INTEGER NOT NULL,
    region_id   INTEGER NOT NULL,
    capture_utc INTEGER NOT NULL,
    forecast    INTEGER,
    {_FUEL_COLUMNS},
    PRIMARY KEY (window_utc, region_id, capture_utc)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS generation_mix (
    window_utc  INTEGER NOT NULL,
    capture_utc INTEGER NOT NULL,
    {_FUEL_COLUMNS},
    PRIMARY KEY (window_utc, capture_utc)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS captures (
    capture_utc      INTEGER NOT NULL,
    endpoint         TEXT    NOT NULL,
    window_first_utc INTEGER NOT NULL,
    window_last_utc  INTEGER NOT NULL,
    observed_utc     INTEGER,
    source           TEXT    NOT NULL DEFAULT 'live',
    PRIMARY KEY (capture_utc, endpoint)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS capture_gaps (
    capture_utc INTEGER NOT NULL,
    endpoint    TEXT    NOT NULL,
    window_utc  INTEGER NOT NULL,
    region_id   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (capture_utc, endpoint, window_utc, region_id)
) WITHOUT ROWID;
"""

# Merging replays are idempotent, so partition inserts ignore duplicates; building
# an inbox must NOT — a key collision there means two endpoints claimed the same
# observation and the whole snapshot is untrustworthy.
_INSERT = {
    "national_intensity": "INSERT OR IGNORE INTO national_intensity VALUES (?, ?, ?, ?)",
    "regional_intensity": (
        "INSERT OR IGNORE INTO regional_intensity VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ),
    "generation_mix": (
        "INSERT OR IGNORE INTO generation_mix VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ),
    "captures": "INSERT OR IGNORE INTO captures VALUES (?, ?, ?, ?, ?, ?)",
    "capture_gaps": "INSERT OR IGNORE INTO capture_gaps VALUES (?, ?, ?, ?)",
}

_INSERT_STRICT = {
    table: statement.replace("INSERT OR IGNORE", "INSERT", 1)
    for table, statement in _INSERT.items()
}


class ConflictingObservationsError(Exception):
    """Two snapshots in one scrape claimed the same (window, capture) key."""


# Change-logged tables store a row only when its value tuple differs from the
# previous capture's: (number of leading key columns, index of the capture column).
_CHANGE_LOGGED = {
    "regional_intensity": (2, 2),
    "generation_mix": (1, 1),
}


def _changed_rows_only(
    target: sqlite3.Connection, table: str, rows: list[tuple[Any, ...]]
) -> list[tuple[Any, ...]]:
    """Keep only rows whose values differ from the latest stored capture for their key."""
    key_width, capture_index = _CHANGE_LOGGED[table]
    values_start = capture_index + 1

    lo = min(row[0] for row in rows)
    hi = max(row[0] for row in rows)
    tail: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    columns = target.execute(f"SELECT * FROM {table} LIMIT 0").description
    names = [column[0] for column in columns]
    key_names = ", ".join(names[:key_width])
    value_names = ", ".join(names[values_start:])
    for stored in target.execute(
        f"SELECT {key_names}, {value_names}, MAX(capture_utc) FROM {table}"
        f" WHERE window_utc BETWEEN ? AND ? GROUP BY {key_names}",
        (lo, hi),
    ):
        tail[stored[:key_width]] = stored[key_width:-1]

    kept = []
    for row in sorted(rows, key=lambda r: r[capture_index]):
        key, values = row[:key_width], row[values_start:]
        if tail.get(key) != values:
            kept.append(row)
            tail[key] = values
    return kept


def _slot_name(capture_utc: int) -> str:
    dt = datetime.fromtimestamp(capture_utc, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H%MZ")


STATS_COLUMNS = (
    "forecast_count",
    "abs_err_mean",
    "abs_err_sem",
    "abs_err_ci95_lo",
    "abs_err_ci95_hi",
    "pc_err_mean",
    "pc_err_sem",
    "pc_err_ci95_lo",
    "pc_err_ci95_hi",
)

_ANALYSIS_DDL = """
CREATE TABLE IF NOT EXISTS stats_history (
    stat_date       TEXT PRIMARY KEY,
    forecast_count  INTEGER,
    abs_err_mean REAL, abs_err_sem REAL, abs_err_ci95_lo REAL, abs_err_ci95_hi REAL,
    pc_err_mean  REAL, pc_err_sem  REAL, pc_err_ci95_lo  REAL, pc_err_ci95_hi  REAL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS error_probabilities (
    run_date    TEXT    NOT NULL,
    error_value INTEGER NOT NULL,
    p_students_t REAL, p_normal REAL, p_laplace REAL,
    PRIMARY KEY (run_date, error_value)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS all_data_error_summary (
    run_date TEXT PRIMARY KEY,
    n INTEGER, mean REAL, median REAL, std REAL, sem REAL
) WITHOUT ROWID;
"""

_REFERENCE_DDL = """
CREATE TABLE IF NOT EXISTS ci_index_bands (
    year     INTEGER NOT NULL,
    position INTEGER NOT NULL,
    band     TEXT    NOT NULL,
    lo       INTEGER NOT NULL,
    hi       INTEGER,
    PRIMARY KEY (year, position)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS ci_band_error_scales (
    year       INTEGER NOT NULL,
    transition TEXT    NOT NULL,
    difference REAL,
    percentage REAL,
    PRIMARY KEY (year, transition)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS ngeso_history (
    window_utc  INTEGER PRIMARY KEY,
    actual      INTEGER,
    forecast    INTEGER,
    index_label TEXT
) WITHOUT ROWID;
"""


class ReferenceDataMissingError(Exception):
    """reference.sqlite has no data for the request; the migration seeds it."""


def _open(path: Path, ddl: str = _DDL) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    (version,) = connection.execute("PRAGMA user_version").fetchone()
    if version > SCHEMA_VERSION:
        connection.close()
        raise SchemaVersionError(
            f"{path.name} has schema version {version}; this code supports {SCHEMA_VERSION}"
        )
    connection.executescript(_PRAGMAS + ddl)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return connection


class Store:
    """All storage policy: inbox writing, partition routing, compaction, reads."""

    # 85 MiB: well under GitHub's 100 MB hard limit; a breach means the sizing
    # assumptions in docs/adr-001-sqlite.md no longer hold and needs a human.
    def __init__(self, db_root: Path, partition_size_limit: int = 85 * 2**20) -> None:
        self.db_root = Path(db_root)
        self.inbox_dir = self.db_root / "inbox"
        self.partition_size_limit = partition_size_limit

    # -- ingest side ---------------------------------------------------------

    def inbox_path(self, capture_utc: int) -> Path:
        """Where the inbox for a capture slot lives; existence means first-wins."""
        return self.inbox_dir / f"snap_{_slot_name(capture_utc)}.sqlite"

    def write_inbox(self, snapshots: Sequence[Snapshot]) -> Path:
        """Write one scrape's snapshots (all endpoints) as a single inbox database.

        Written under a writer-unique temporary name and published with an atomic
        no-clobber link: a crash can never leave a partial inbox, and two racing
        writers for the same slot both succeed with exactly one of them published.
        """
        path = self.inbox_path(snapshots[0].capture_utc)
        scratch = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        connection = _open(scratch)
        try:
            with connection:
                self._insert_snapshot_rows(connection, snapshots)
        except sqlite3.IntegrityError as error:
            connection.close()
            scratch.unlink(missing_ok=True)
            raise ConflictingObservationsError(
                "two endpoints supplied the same (window, capture) observation in"
                f" slot {_slot_name(snapshots[0].capture_utc)}: {error}"
            ) from error
        connection.close()
        try:
            os.link(scratch, path)
        except FileExistsError:
            pass  # another writer published this slot first; first wins
        scratch.unlink()
        return path

    def _insert_snapshot_rows(
        self, connection: sqlite3.Connection, snapshots: Iterable[Snapshot]
    ) -> None:
        for snapshot in snapshots:
            connection.executemany(
                _INSERT_STRICT["national_intensity"], snapshot.national
            )
            connection.executemany(
                _INSERT_STRICT["regional_intensity"], snapshot.regional
            )
            connection.executemany(
                _INSERT_STRICT["generation_mix"], snapshot.generation
            )
            connection.execute(
                _INSERT_STRICT["captures"],
                (
                    snapshot.capture_utc,
                    snapshot.endpoint,
                    snapshot.window_first_utc,
                    snapshot.window_last_utc,
                    snapshot.observed_utc,
                    snapshot.source,
                ),
            )

    # -- compaction ----------------------------------------------------------

    def compact(self, now: datetime, max_inboxes: int | None = None) -> CompactReport:
        """Fold complete days of inbox files into the window partitions, then delete them.

        Processes oldest slots first and stops cleanly after `max_inboxes`, so a
        backlog is recoverable in bounded, resumable batches.
        """
        day_start = int(
            now.astimezone(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )
        merged = 0
        quarantined: list[str] = []
        for inbox_path in sorted(self.inbox_dir.glob("snap_*.sqlite")):
            if max_inboxes is not None and merged >= max_inboxes:
                break
            source = sqlite3.connect(inbox_path)
            (slot,) = source.execute("SELECT MIN(capture_utc) FROM captures").fetchone()
            if slot >= day_start:
                source.close()
                continue
            if self._arrived_after_later_captures(source, slot):
                source.close()
                self._quarantine(inbox_path)
                quarantined.append(inbox_path.name)
                continue
            try:
                self._merge_inbox(source)
            finally:
                source.close()
            inbox_path.unlink()
            merged += 1
        remaining = len(list(self.inbox_dir.glob("snap_*.sqlite")))
        return CompactReport(
            merged_inboxes=merged,
            remaining_inboxes=remaining,
            quarantined=tuple(quarantined),
        )

    def _arrived_after_later_captures(
        self, source: sqlite3.Connection, slot: int
    ) -> bool:
        """An inbox older than already-merged captures would corrupt the change-log."""
        for endpoint, first, last in source.execute(
            "SELECT endpoint, window_first_utc, window_last_utc FROM captures"
        ).fetchall():
            kind = "generation" if "generation" in endpoint else endpoint.split("_")[0]
            for path in self.partitions_overlapping(kind, first, last):
                if not path.exists():
                    continue
                target = _open(path)
                (newest,) = target.execute(
                    "SELECT MAX(capture_utc) FROM captures"
                ).fetchone()
                target.close()
                if newest is not None and slot < newest:
                    return True
        return False

    def _quarantine(self, inbox_path: Path) -> None:
        quarantine_dir = self.inbox_dir / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        inbox_path.rename(quarantine_dir / inbox_path.name)

    def _merge_inbox(self, source: sqlite3.Connection) -> list[Path]:
        by_partition: dict[Path, dict[str, list[tuple[Any, ...]]]] = {}

        def stage(path: Path, table: str, row: tuple[Any, ...]) -> None:
            by_partition.setdefault(path, {}).setdefault(table, []).append(row)

        for table, kind in (
            ("national_intensity", "national"),
            ("regional_intensity", "regional"),
            ("generation_mix", "generation"),
        ):
            for row in source.execute(f"SELECT * FROM {table} ORDER BY capture_utc"):
                stage(self._partition_path(kind, window_utc=row[0]), table, row)

        for capture in source.execute("SELECT * FROM captures").fetchall():
            endpoint = capture[1]
            kind = "generation" if "generation" in endpoint else endpoint.split("_")[0]
            for path in self.partitions_overlapping(kind, capture[2], capture[3]):
                stage(path, "captures", capture)

        for gap in source.execute("SELECT * FROM capture_gaps").fetchall():
            endpoint = gap[1]
            kind = "generation" if "generation" in endpoint else endpoint.split("_")[0]
            stage(self._partition_path(kind, window_utc=gap[2]), "capture_gaps", gap)

        for path, tables in by_partition.items():
            target = _open(path)
            try:
                with target:
                    for table, rows in tables.items():
                        if table in _CHANGE_LOGGED:
                            rows = _changed_rows_only(target, table, rows)
                        target.executemany(_INSERT[table], rows)
                    # Projected size is checked inside the transaction so an
                    # oversized partition rolls back instead of being committed.
                    (pages,) = target.execute("PRAGMA page_count").fetchone()
                    projected = pages * 4096
                    if projected > self.partition_size_limit:
                        raise PartitionSizeError(
                            f"{path.name} would be {projected} bytes, over the"
                            f" {self.partition_size_limit} byte limit"
                        )
            finally:
                target.close()
        return list(by_partition)

    # -- partition routing ---------------------------------------------------

    def _partition_path(self, kind: str, window_utc: int) -> Path:
        dt = datetime.fromtimestamp(window_utc, tz=timezone.utc)
        year_dir = self.db_root / f"{dt.year}"
        if kind == "national":
            return year_dir / f"national_{dt:%Y-%m}.sqlite"
        if kind == "regional":
            half = "a" if dt.day <= 15 else "b"
            return year_dir / f"regional_{dt:%Y-%m}{half}.sqlite"
        return year_dir / f"generation_{dt.year}.sqlite"

    def partitions_overlapping(
        self, kind: str, first_utc: int, last_utc: int
    ) -> list[Path]:
        paths = []
        window = first_utc
        while window <= last_utc:
            path = self._partition_path(kind, window)
            if path not in paths:
                paths.append(path)
            window += 86400
        last_path = self._partition_path(kind, last_utc)
        if last_path not in paths:
            paths.append(last_path)
        return paths

    # -- reads ----------------------------------------------------------------

    def capture_records(
        self, include_inbox: bool = True
    ) -> list[tuple[int, str, int, int]]:
        """(slot, endpoint, first_window, last_window) for every recorded capture."""
        paths = sorted(self.db_root.glob("[0-9][0-9][0-9][0-9]/*.sqlite"))
        if include_inbox and self.inbox_dir.exists():
            paths += sorted(self.inbox_dir.glob("snap_*.sqlite"))
        seen: dict[tuple[int, str], tuple[int, str, int, int]] = {}
        for path in paths:
            connection = _open(path)
            for row in connection.execute(
                "SELECT capture_utc, endpoint, window_first_utc, window_last_utc"
                " FROM captures"
            ):
                seen.setdefault((row[0], row[1]), row)
            connection.close()
        return sorted(seen.values())

    # -- derived statistics ----------------------------------------------------

    def record_stats(self, stat_date: str, values: dict[str, float]) -> None:
        """Upsert one day's error statistics into analysis.sqlite."""
        connection = _open(self.db_root / "analysis.sqlite", ddl=_ANALYSIS_DDL)
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO stats_history VALUES"
                " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (stat_date, *[values[column] for column in STATS_COLUMNS]),
            )
        connection.close()

    def record_probabilities(
        self, run_date: str, rows: Sequence[tuple[int, float, float, float]]
    ) -> None:
        """Store the error-magnitude probability table for this run."""
        connection = _open(self.db_root / "analysis.sqlite", ddl=_ANALYSIS_DDL)
        with connection:
            connection.executemany(
                "INSERT OR REPLACE INTO error_probabilities VALUES (?, ?, ?, ?, ?)",
                [(run_date, *row) for row in rows],
            )
        connection.close()

    def record_error_summary(self, run_date: str, values: dict[str, float]) -> None:
        connection = _open(self.db_root / "analysis.sqlite", ddl=_ANALYSIS_DDL)
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO all_data_error_summary VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_date,
                    values["n"],
                    values["mean"],
                    values["median"],
                    values["std"],
                    values["sem"],
                ),
            )
        connection.close()

    def record_reference_bands(
        self, rows: Sequence[tuple[int, int, str, int, int | None]]
    ) -> None:
        """Seed CI index bands: (year, position, band, lo, hi) with hi NULL open-ended."""
        connection = _open(self.db_root / "reference.sqlite", ddl=_REFERENCE_DDL)
        with connection:
            connection.executemany(
                "INSERT OR REPLACE INTO ci_index_bands VALUES (?, ?, ?, ?, ?)", rows
            )
        connection.close()

    def record_band_error_scales(
        self, rows: Sequence[tuple[int, str, float, float]]
    ) -> None:
        connection = _open(self.db_root / "reference.sqlite", ddl=_REFERENCE_DDL)
        with connection:
            connection.executemany(
                "INSERT OR REPLACE INTO ci_band_error_scales VALUES (?, ?, ?, ?)", rows
            )
        connection.close()

    def record_ngeso_history(
        self, rows: Sequence[tuple[int, int | None, int | None, str]]
    ) -> None:
        connection = _open(self.db_root / "reference.sqlite", ddl=_REFERENCE_DDL)
        with connection:
            connection.executemany(
                "INSERT OR REPLACE INTO ngeso_history VALUES (?, ?, ?, ?)", rows
            )
        connection.close()

    def reference_bands(self, year: int) -> tuple[list[str], list[int]]:
        """Band labels and lower bounds for a year, for the chart colourmap."""
        path = self.db_root / "reference.sqlite"
        if not path.exists():
            raise ReferenceDataMissingError(
                "reference.sqlite does not exist; run the migration importer first"
            )
        connection = _open(path, ddl=_REFERENCE_DDL)
        rows = connection.execute(
            "SELECT band, lo FROM ci_index_bands WHERE year = ? ORDER BY position",
            (year,),
        ).fetchall()
        connection.close()
        if not rows:
            raise ReferenceDataMissingError(f"no CI index bands stored for {year}")
        return [band for band, _lo in rows], [lo for _band, lo in rows]

    def stats_history(self) -> list[dict[str, Any]]:
        connection = _open(self.db_root / "analysis.sqlite", ddl=_ANALYSIS_DDL)
        rows = connection.execute(
            "SELECT * FROM stats_history ORDER BY stat_date"
        ).fetchall()
        connection.close()
        return [
            dict(zip(("stat_date", *STATS_COLUMNS), row, strict=True)) for row in rows
        ]

    def national_rows(
        self, include_inbox: bool = True
    ) -> list[tuple[int, int, int | None, int | None]]:
        """Every stored (window, capture, forecast, actual) row, partitions plus
        unmerged inboxes — the read set for analysis, never mutating either."""
        paths = sorted(self.db_root.glob("*/national_*.sqlite"))
        if include_inbox and self.inbox_dir.exists():
            paths += sorted(self.inbox_dir.glob("snap_*.sqlite"))
        rows: list[tuple[int, int, int | None, int | None]] = []
        for path in paths:
            connection = _open(path)
            rows.extend(
                connection.execute(
                    "SELECT window_utc, capture_utc, forecast, actual"
                    " FROM national_intensity"
                ).fetchall()
            )
            connection.close()
        return rows

    def regional_trajectory(
        self, window: datetime, region_id: int
    ) -> list[tuple[datetime, int | None, tuple[int, ...]]]:
        """Reconstruct one region's full (capture, forecast, mix) trajectory for a window.

        The change-log stores only changed rows; every capture slot whose recorded
        coverage includes the window (and is not excluded by capture_gaps) is a real
        observation, forward-filled from the latest stored change at or before it.
        """
        window_utc = int(window.timestamp())
        path = self._partition_path("regional", window_utc)
        if not path.exists():
            return []
        connection = _open(path)
        slots = [
            slot
            for (slot,) in connection.execute(
                """
                SELECT DISTINCT c.capture_utc FROM captures c
                WHERE c.window_first_utc <= :w AND c.window_last_utc >= :w
                  AND NOT EXISTS (
                      SELECT 1 FROM capture_gaps g
                      WHERE g.capture_utc = c.capture_utc AND g.endpoint = c.endpoint
                        AND g.window_utc = :w AND g.region_id IN (0, :r)
                  )
                ORDER BY c.capture_utc
                """,
                {"w": window_utc, "r": region_id},
            )
        ]
        changes = connection.execute(
            "SELECT capture_utc, forecast, biomass, coal, gas, hydro, imports,"
            " nuclear, other, solar, wind FROM regional_intensity"
            " WHERE window_utc = ? AND region_id = ? ORDER BY capture_utc",
            (window_utc, region_id),
        ).fetchall()
        connection.close()

        trajectory = []
        index = -1
        for slot in slots:
            while index + 1 < len(changes) and changes[index + 1][0] <= slot:
                index += 1
            if index < 0:
                continue
            _, forecast, *mix = changes[index]
            trajectory.append(
                (datetime.fromtimestamp(slot, tz=timezone.utc), forecast, tuple(mix))
            )
        return trajectory

    def national_trajectory(
        self, window: datetime
    ) -> list[tuple[datetime, int | None, int | None]]:
        """Every stored (capture, forecast, actual) point for one half-hour window."""
        window_utc = int(window.timestamp())
        path = self._partition_path("national", window_utc)
        if not path.exists():
            return []
        connection = _open(path)
        rows = connection.execute(
            "SELECT capture_utc, forecast, actual FROM national_intensity"
            " WHERE window_utc = ? ORDER BY capture_utc",
            (window_utc,),
        ).fetchall()
        connection.close()
        return [
            (datetime.fromtimestamp(capture, tz=timezone.utc), forecast, actual)
            for capture, forecast, actual in rows
        ]
