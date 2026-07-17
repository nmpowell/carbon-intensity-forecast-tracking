"""Store behaviours: schema, routing, idempotency, change-log, reconstruction."""

import sqlite3
import threading
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest

import cift.store
from cift.ingest import run_ingest
from cift.parse import Snapshot
from cift.parse import floor_to_slot
from cift.parse import parse_snapshot
from cift.store import ConflictingObservationsError
from cift.store import PartitionSizeError
from cift.store import SchemaVersionError
from cift.store import Store
from tests.conftest import FixtureClient
from tests.conftest import load_fixture
from tests.conftest import national_payload
from tests.conftest import regional_payload
from tests.conftest import utc


class TestSchema:
    def test_files_created_by_the_store_carry_schema_pragmas_and_version(
        self, tmp_path: Path, five_endpoint_payloads: dict[str, Any]
    ) -> None:
        inbox = run_ingest(
            db_root=tmp_path,
            now=utc("2023-03-22T11:33Z"),
            client=FixtureClient(five_endpoint_payloads),
        )

        connection = sqlite3.connect(inbox)
        tables = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        pragma = {
            key: connection.execute(f"PRAGMA {key}").fetchone()[0]
            for key in ("user_version", "page_size", "journal_mode", "application_id")
        }
        connection.close()

        assert tables == {
            "national_intensity",
            "regional_intensity",
            "generation_mix",
            "captures",
            "capture_gaps",
        }
        assert pragma == {
            "user_version": 1,
            "page_size": 4096,
            "journal_mode": "delete",
            "application_id": 0x43494654,
        }

    def test_opening_a_newer_schema_version_raises_a_descriptive_error(
        self, tmp_path: Path
    ) -> None:
        partition = tmp_path / "2023" / "national_2023-03.sqlite"
        partition.parent.mkdir(parents=True)
        connection = sqlite3.connect(partition)
        connection.execute("PRAGMA user_version = 99")
        connection.close()

        store = Store(tmp_path)

        with pytest.raises(SchemaVersionError, match="version 99.*supports 1"):
            store.national_trajectory(utc("2023-03-22T11:30Z"))


def ingest_national(
    db_root: Path,
    captured: str,
    *windows: tuple[str, int | None, int | None],
    endpoint: str = "national_fw48h",
) -> None:
    """Write one national snapshot into the inbox via the parse path."""
    slot = floor_to_slot(utc(captured))
    snapshot = parse_snapshot(endpoint, national_payload(*windows), slot, slot)
    Store(db_root).write_inbox([snapshot])


class TestProvenance:
    def test_a_snapshot_source_is_carried_into_the_inbox_and_partition(
        self, tmp_path: Path
    ) -> None:
        slot = floor_to_slot(utc("2023-03-22T11:31Z"))
        snapshot = parse_snapshot(
            "national_fw48h",
            national_payload(("2023-03-22T11:30Z", 41, None)),
            slot,
            None,
        )
        migrated = Snapshot(**{**snapshot.__dict__, "source": "wrangled_csv"})
        store = Store(tmp_path)

        inbox = store.write_inbox([migrated])
        connection = sqlite3.connect(inbox)
        (inbox_source,) = connection.execute("SELECT source FROM captures").fetchone()
        connection.close()
        store.compact(now=utc("2023-03-24T02:12Z"))
        partition = sqlite3.connect(tmp_path / "2023" / "national_2023-03.sqlite")
        (stored_source,) = partition.execute("SELECT source FROM captures").fetchone()
        partition.close()

        assert inbox_source == "wrangled_csv"
        assert stored_source == "wrangled_csv"


class TestPartitionRouting:
    def test_snapshots_route_to_the_partition_of_their_window_not_their_capture(
        self, tmp_path: Path
    ) -> None:
        ingest_national(tmp_path, "2023-03-31T23:31Z", ("2023-04-01T10:00Z", 55, None))

        store = Store(tmp_path)
        store.compact(now=utc("2023-04-03T02:12Z"))

        assert (tmp_path / "2023" / "national_2023-04.sqlite").exists()
        assert not (tmp_path / "2023" / "national_2023-03.sqlite").exists()
        assert store.national_trajectory(utc("2023-04-01T10:00Z")) == [
            (utc("2023-03-31T23:30Z"), 55, None)
        ]

    def test_a_forecast_horizon_crossing_the_partition_boundary_writes_both_files(
        self, tmp_path: Path
    ) -> None:
        ingest_national(
            tmp_path,
            "2023-03-31T23:31Z",
            ("2023-03-31T23:30Z", 40, None),
            ("2023-04-01T00:00Z", 41, None),
        )

        store = Store(tmp_path)
        store.compact(now=utc("2023-04-03T02:12Z"))

        march = sqlite3.connect(tmp_path / "2023" / "national_2023-03.sqlite")
        april = sqlite3.connect(tmp_path / "2023" / "national_2023-04.sqlite")
        march_captures = march.execute("SELECT endpoint FROM captures").fetchall()
        april_captures = april.execute("SELECT endpoint FROM captures").fetchall()
        march_windows = march.execute(
            "SELECT window_utc FROM national_intensity"
        ).fetchall()
        april_windows = april.execute(
            "SELECT window_utc FROM national_intensity"
        ).fetchall()
        march.close()
        april.close()

        assert march_captures == [("national_fw48h",)] and april_captures == [
            ("national_fw48h",)
        ]
        assert len(march_windows) == 1 and len(april_windows) == 1


def ingest_regional(
    db_root: Path, captured: str, forecast: int, mix: dict[str, float] | None = None
) -> None:
    """One regional snapshot, single window at the capture slot, all 18 regions."""
    slot = floor_to_slot(utc(captured))
    payload = regional_payload(
        (captured.replace(":31Z", ":30Z").replace(":01Z", ":00Z"), forecast), mix=mix
    )
    snapshot = parse_snapshot("regional_fw48h", payload, slot, slot)
    Store(db_root).write_inbox([snapshot])


class TestTrajectories:
    def test_actual_value_revisions_are_kept_per_capture(self, tmp_path: Path) -> None:
        window = ("2023-03-22T11:30Z", 41, None)
        ingest_national(tmp_path, "2023-03-22T11:31Z", window)
        ingest_national(
            tmp_path,
            "2023-03-22T12:01Z",
            ("2023-03-22T11:30Z", 41, 43),
            endpoint="national_pt24h",
        )
        ingest_national(
            tmp_path,
            "2023-03-22T12:31Z",
            ("2023-03-22T11:30Z", 41, 45),
            endpoint="national_pt24h",
        )

        store = Store(tmp_path)
        store.compact(now=utc("2023-03-24T02:12Z"))

        assert store.national_trajectory(utc("2023-03-22T11:30Z")) == [
            (utc("2023-03-22T11:30Z"), 41, None),
            (utc("2023-03-22T12:00Z"), 41, 43),
            (utc("2023-03-22T12:30Z"), 41, 45),
        ]


class TestRegionalChangeLog:
    def test_regional_rows_are_stored_only_when_their_ten_tuple_changed(
        self, tmp_path: Path
    ) -> None:
        window = "2023-03-22T14:00Z"
        slot0 = floor_to_slot(utc("2023-03-22T11:31Z"))
        store = Store(tmp_path)
        for captured, forecast in (
            ("2023-03-22T11:31Z", 100),  # first sighting: stored
            ("2023-03-22T12:01Z", 100),  # unchanged: not stored
            ("2023-03-22T12:31Z", 120),  # changed: stored
        ):
            snapshot = parse_snapshot(
                "regional_fw48h",
                regional_payload((window, forecast)),
                floor_to_slot(utc(captured)),
                floor_to_slot(utc(captured)),
            )
            store.write_inbox([snapshot])

        store.compact(now=utc("2023-03-24T02:12Z"))

        partition = sqlite3.connect(tmp_path / "2023" / "regional_2023-03b.sqlite")
        stored = partition.execute(
            "SELECT capture_utc, forecast FROM regional_intensity"
            " WHERE region_id = 1 ORDER BY capture_utc"
        ).fetchall()
        partition.close()

        assert stored == [(slot0, 100), (slot0 + 3600, 120)]


def ingest_regional_windows(
    db_root: Path, captured: str, *windows: tuple[str, int]
) -> None:
    slot = floor_to_slot(utc(captured))
    snapshot = parse_snapshot("regional_fw48h", regional_payload(*windows), slot, slot)
    Store(db_root).write_inbox([snapshot])


class TestRegionalReconstruction:
    def test_reconstruction_fills_only_within_recorded_coverage(
        self, tmp_path: Path
    ) -> None:
        first, second = "2023-03-22T13:00Z", "2023-03-22T13:30Z"
        ingest_regional_windows(
            tmp_path, "2023-03-22T11:31Z", (first, 100), (second, 200)
        )
        ingest_regional_windows(tmp_path, "2023-03-22T12:01Z", (first, 100))

        store = Store(tmp_path)
        store.compact(now=utc("2023-03-24T02:12Z"))

        second_window = store.regional_trajectory(utc(second), region_id=1)
        first_window = store.regional_trajectory(utc(first), region_id=1)

        assert [(capture, forecast) for capture, forecast, _mix in second_window] == [
            (utc("2023-03-22T11:30Z"), 200)
        ]
        assert [(capture, forecast) for capture, forecast, _mix in first_window] == [
            (utc("2023-03-22T11:30Z"), 100),
            (utc("2023-03-22T12:00Z"), 100),
        ]

    def test_reconstruction_does_not_fill_across_a_missed_capture_slot(
        self, tmp_path: Path
    ) -> None:
        window = "2023-03-22T14:00Z"
        ingest_regional_windows(tmp_path, "2023-03-22T11:31Z", (window, 100))
        # 12:01Z scrape never happened
        ingest_regional_windows(tmp_path, "2023-03-22T12:31Z", (window, 100))

        store = Store(tmp_path)
        store.compact(now=utc("2023-03-24T02:12Z"))

        trajectory = store.regional_trajectory(utc(window), region_id=1)

        assert [capture for capture, _f, _m in trajectory] == [
            utc("2023-03-22T11:30Z"),
            utc("2023-03-22T12:30Z"),
        ]

    def test_reconstruction_skips_an_interior_recorded_gap_and_resumes_after_it(
        self, tmp_path: Path
    ) -> None:
        window = "2023-03-22T14:00Z"
        for captured in ("2023-03-22T11:31Z", "2023-03-22T12:01Z", "2023-03-22T12:31Z"):
            ingest_regional_windows(tmp_path, captured, (window, 100))
        store = Store(tmp_path)
        store.compact(now=utc("2023-03-24T02:12Z"))
        partition = tmp_path / "2023" / "regional_2023-03b.sqlite"
        connection = sqlite3.connect(partition)
        with connection:
            connection.execute(
                "INSERT INTO capture_gaps VALUES (?, 'regional_fw48h', ?, 5)",
                (floor_to_slot(utc("2023-03-22T12:01Z")), floor_to_slot(utc(window))),
            )
        connection.close()

        gapped = Store(tmp_path).regional_trajectory(utc(window), region_id=5)
        untouched = Store(tmp_path).regional_trajectory(utc(window), region_id=1)

        assert [capture for capture, _f, _m in gapped] == [
            utc("2023-03-22T11:30Z"),
            utc("2023-03-22T12:30Z"),
        ]
        assert len(untouched) == 3


class TestCompaction:
    def test_compact_consumes_only_complete_days_and_reports_what_remains(
        self, tmp_path: Path
    ) -> None:
        ingest_national(tmp_path, "2023-03-22T11:31Z", ("2023-03-22T11:30Z", 41, None))
        ingest_national(tmp_path, "2023-03-23T09:01Z", ("2023-03-23T09:00Z", 50, None))

        report = Store(tmp_path).compact(now=utc("2023-03-23T12:00Z"))

        assert report.merged_inboxes == 1
        assert report.remaining_inboxes == 1
        assert (tmp_path / "inbox" / "snap_2023-03-23T0900Z.sqlite").exists()

    def test_compact_batches_stop_cleanly_and_resume_idempotently(
        self, tmp_path: Path
    ) -> None:
        window = "2023-03-20T12:00Z"
        for captured, forecast in (
            ("2023-03-20T10:01Z", 10),
            ("2023-03-20T10:31Z", 11),
            ("2023-03-20T11:01Z", 12),
        ):
            ingest_national(tmp_path, captured, (window, forecast, None))
        store = Store(tmp_path)

        first = store.compact(now=utc("2023-03-23T12:00Z"), max_inboxes=2)
        second = store.compact(now=utc("2023-03-23T12:00Z"), max_inboxes=2)

        assert (first.merged_inboxes, first.remaining_inboxes) == (2, 1)
        assert (second.merged_inboxes, second.remaining_inboxes) == (1, 0)
        assert [f for _c, f, _a in store.national_trajectory(utc(window))] == [
            10,
            11,
            12,
        ]


class TestCompactionGuards:
    def test_an_out_of_order_late_inbox_is_quarantined_not_misapplied(
        self, tmp_path: Path
    ) -> None:
        window = "2023-03-20T11:00Z"
        ingest_national(tmp_path, "2023-03-20T10:31Z", (window, 11, None))
        store = Store(tmp_path)
        store.compact(now=utc("2023-03-23T12:00Z"))
        ingest_national(tmp_path, "2023-03-20T10:01Z", (window, 10, None))

        report = store.compact(now=utc("2023-03-23T12:00Z"))

        assert report.quarantined == ("snap_2023-03-20T1000Z.sqlite",)
        assert (
            tmp_path / "inbox" / "quarantine" / "snap_2023-03-20T1000Z.sqlite"
        ).exists()
        assert [f for _c, f, _a in store.national_trajectory(utc(window))] == [11]

    def test_a_partition_approaching_the_size_limit_fails_the_merge_loudly(
        self, tmp_path: Path
    ) -> None:
        ingest_national(tmp_path, "2023-03-20T10:01Z", ("2023-03-20T10:00Z", 10, None))
        store = Store(tmp_path, partition_size_limit=1024)
        inbox = store.inbox_path(floor_to_slot(utc("2023-03-20T10:01Z")))

        with pytest.raises(PartitionSizeError, match="national_2023-03.sqlite"):
            store.compact(now=utc("2023-03-23T12:00Z"))

        assert inbox.exists()  # nothing destroyed: the breach is retryable
        partition = tmp_path / "2023" / "national_2023-03.sqlite"
        offender = sqlite3.connect(partition)
        (facts,) = offender.execute(
            "SELECT COUNT(*) FROM national_intensity"
        ).fetchone()
        (records,) = offender.execute("SELECT COUNT(*) FROM captures").fetchone()
        offender.close()
        assert (facts, records) == (0, 0)  # the offending transaction rolled back

        recovered = Store(tmp_path).compact(now=utc("2023-03-23T12:00Z"))

        assert recovered.merged_inboxes == 1
        assert not inbox.exists()
        assert store.national_trajectory(utc("2023-03-20T10:00Z")) == [
            (utc("2023-03-20T10:00Z"), 10, None)
        ]

    def test_conflicting_observations_across_endpoints_abort_the_whole_inbox(
        self, tmp_path: Path
    ) -> None:
        slot = floor_to_slot(utc("2023-03-22T11:31Z"))
        colliding = [
            Snapshot(
                endpoint="national_fw48h",
                capture_utc=slot,
                observed_utc=slot,
                window_first_utc=slot,
                window_last_utc=slot,
                national=((slot, slot, 11, None),),
                regional=(),
                generation=(),
            ),
            Snapshot(
                endpoint="national_pt24h",
                capture_utc=slot,
                observed_utc=slot,
                window_first_utc=slot,
                window_last_utc=slot,
                national=((slot, slot, 99, 42),),
                regional=(),
                generation=(),
            ),
        ]

        with pytest.raises(
            ConflictingObservationsError, match="same .window, capture."
        ):
            Store(tmp_path).write_inbox(colliding)

        assert not list((tmp_path / "inbox").glob("snap_*.sqlite"))

    def test_racing_writers_for_one_slot_both_succeed_and_one_wins_wholly(
        self, tmp_path: Path
    ) -> None:
        slot = floor_to_slot(utc("2023-03-22T11:31Z"))

        def snapshot(forecast: int) -> Snapshot:
            return Snapshot(
                endpoint="national_fw48h",
                capture_utc=slot,
                observed_utc=slot,
                window_first_utc=slot,
                window_last_utc=slot,
                national=((slot, slot, forecast, None),),
                regional=(),
                generation=(),
            )

        barrier = threading.Barrier(2)
        results: list[Path] = []

        def write(forecast: int) -> None:
            store = Store(tmp_path)
            barrier.wait()
            results.append(store.write_inbox([snapshot(forecast)]))

        writers = [threading.Thread(target=write, args=(value,)) for value in (10, 20)]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join()

        inboxes = list((tmp_path / "inbox").glob("snap_*"))
        assert len(results) == 2 and results[0] == results[1]
        assert inboxes == [results[0]]
        connection = sqlite3.connect(results[0])
        forecasts = connection.execute(
            "SELECT forecast FROM national_intensity"
        ).fetchall()
        connection.close()
        assert forecasts in ([(10,)], [(20,)])

    def test_a_crash_between_partition_commits_recovers_on_the_retained_inbox(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # One regional snapshot whose horizon crosses the half-month a/b boundary.
        ingest_regional_windows(
            tmp_path,
            "2023-03-15T23:31Z",
            ("2023-03-15T23:30Z", 100),
            ("2023-03-16T00:00Z", 200),
        )
        store = Store(tmp_path)
        real_open = cift.store._open
        opened: list[str] = []

        def failing_open(path: Path, ddl: str = cift.store._DDL) -> object:
            if path.name.startswith("regional_") and path.name not in opened:
                opened.append(path.name)
                if len(opened) == 2:
                    raise RuntimeError("injected crash before the second partition")
            return real_open(path, ddl)

        monkeypatch.setattr(cift.store, "_open", failing_open)
        with pytest.raises(RuntimeError, match="injected crash"):
            store.compact(now=utc("2023-03-18T12:00Z"))
        monkeypatch.undo()

        assert len(list((tmp_path / "inbox").glob("snap_*.sqlite"))) == 1

        report = Store(tmp_path).compact(now=utc("2023-03-18T12:00Z"))

        assert report.merged_inboxes == 1
        capture = utc("2023-03-15T23:30Z")
        zero_mix = (0,) * 9
        for window, forecast in (
            (utc("2023-03-15T23:30Z"), 100),
            (utc("2023-03-16T00:00Z"), 200),
        ):
            for region_id in range(1, 19):
                trajectory = store.regional_trajectory(window, region_id=region_id)
                assert trajectory == [(capture, forecast, zero_mix)], (
                    window,
                    region_id,
                )


class TestReconstructionProperty:
    def test_reconstruction_equals_full_fidelity_for_a_real_day(
        self, tmp_path: Path
    ) -> None:
        """Property over six real consecutive snapshots: the change-log plus coverage
        reconstructs, for every (window, region) observed, exactly the trajectory the
        raw snapshots contain. The loop is the property's corpus, not test logic."""
        slots = ["0601Z", "0631Z", "0701Z", "0731Z", "0801Z", "0831Z"]
        store = Store(tmp_path)
        expected: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
        for slot_name in slots:
            captured = utc(f"2024-01-12T{slot_name[:2]}:{slot_name[2:4]}Z")
            slot = floor_to_slot(captured)
            snapshots = [
                parse_snapshot(
                    endpoint,
                    load_fixture(f"real_day/{endpoint}/2024-01-12T{slot_name}.json"),
                    slot,
                    slot,
                )
                for endpoint in ("regional_fw48h", "regional_pt24h")
            ]
            store.write_inbox(snapshots)
            for snapshot in snapshots:
                for row in snapshot.regional:
                    window_utc, region_id, capture_utc, forecast = row[:4]
                    assert window_utc is not None and region_id is not None
                    expected.setdefault((window_utc, region_id), []).append(
                        (capture_utc, forecast, tuple(row[4:]))
                    )

        store.compact(now=utc("2024-01-14T02:12Z"))

        for (window_utc, region_id), full_fidelity in expected.items():
            reconstructed = [
                (int(capture.timestamp()), forecast, mix)
                for capture, forecast, mix in store.regional_trajectory(
                    datetime.fromtimestamp(window_utc, tz=timezone.utc), region_id
                )
            ]
            assert reconstructed == sorted(full_fidelity), (window_utc, region_id)
