"""Migration staging: every historical source normalises into one candidates stream."""

import sqlite3
from pathlib import Path

import pytest

from cift.migrate import MigrationError
from cift.migrate import Staging
from cift.migrate import emit
from cift.migrate import golden_corpus
from cift.migrate import preflight
from cift.migrate import reextract_sample
from cift.migrate import resolve
from cift.migrate import run_migration
from cift.migrate import stage_json_backlog
from cift.migrate import stage_national_summary
from cift.migrate import stage_regional_summary
from cift.migrate import stage_wrangled_csvs
from cift.migrate import verify_overlap
from cift.migrate import verify_provenance
from cift.migrate import verify_reconstruction
from cift.store import Store
from tests.conftest import FIXTURES
from tests.conftest import utc


class TestJsonBacklogStaging:
    def test_backlog_files_go_through_the_live_parser_into_candidates(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        files = sorted((FIXTURES / "real_day" / "regional_fw48h").glob("*.json"))

        report = stage_json_backlog(staging, files, endpoint="regional_fw48h")

        assert report.staged == 6
        assert report.excluded == ()
        connection = sqlite3.connect(staging.path)
        (candidates,) = connection.execute(
            "SELECT COUNT(*) FROM candidates WHERE source = 'json_backlog'"
        ).fetchone()
        (captures,) = connection.execute(
            "SELECT COUNT(*) FROM candidate_captures"
        ).fetchone()
        connection.close()
        assert candidates == 6 * 8 * 18  # six snapshots, eight windows, 18 regions
        assert captures == 6

    def test_malformed_and_empty_files_are_reported_not_silently_skipped(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        malformed = tmp_path / "2024-01-12T0901Z.json"
        malformed.write_text("{ not json")
        empty = tmp_path / "2024-01-12T0931Z.json"
        empty.write_text('{"data": []}')

        report = stage_json_backlog(
            staging, [malformed, empty], endpoint="regional_fw48h"
        )

        assert report.staged == 0
        assert [name for name, _reason in report.excluded] == [
            "2024-01-12T0901Z.json",
            "2024-01-12T0931Z.json",
        ]


REGIONAL_CSV = """from,regions.regionid,regions.intensity.forecast,biomass,coal,gas,hydro,imports,nuclear,other,solar,wind
2023-05-15T16:30Z,1,55,0.0,0.0,10.0,0.0,0.0,0.0,0.0,0.0,90.0
2023-05-15T16:30Z,2,60,0.0,0.0,20.0,0.0,0.0,0.0,0.0,0.0,80.0
2023-05-15T17:00Z,1,56,0.0,0.0,10.0,0.0,0.0,0.0,0.0,0.0,90.0
2023-05-15T17:00Z,2,61,0.0,0.0,20.0,0.0,0.0,0.0,0.0,0.0,80.0
"""


class TestWrangledCsvStaging:
    def test_capture_slot_comes_from_the_filename_and_observed_utc_is_null(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        csv_path = tmp_path / "2023-05-15T1601Z.csv"
        csv_path.write_text(REGIONAL_CSV)

        report = stage_wrangled_csvs(staging, [csv_path], endpoint="regional_fw48h")

        assert report.staged == 1
        connection = sqlite3.connect(staging.path)
        rows = connection.execute(
            "SELECT capture_utc, window_utc, region_id, forecast, wind"
            " FROM candidates ORDER BY window_utc, region_id"
        ).fetchall()
        capture_row = connection.execute(
            "SELECT capture_utc, window_first_utc, window_last_utc, observed_utc"
            " FROM candidate_captures"
        ).fetchone()
        connection.close()

        slot = int(utc("2023-05-15T16:00Z").timestamp())
        first_window = int(utc("2023-05-15T16:30Z").timestamp())
        assert rows[0] == (slot, first_window, 1, 55, 900)
        assert len(rows) == 4
        assert capture_row == (slot, first_window, first_window + 1800, None)


NATIONAL_SUMMARY = """,intensity.forecast,intensity.forecast,intensity.actual,intensity.actual
time_difference,000.5,000.0,000.5,000.0
2023-03-14T03:00Z,68.0,69.0,,70.0
2023-03-14T03:30Z,71.0,,,,
"""


class TestNationalSummaryStaging:
    def test_summary_cells_invert_to_observations_at_window_minus_lead(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        summary = tmp_path / "summary_national_fw48h.csv"
        summary.write_text(NATIONAL_SUMMARY)

        report = stage_national_summary(staging, summary, endpoint="national_fw48h")

        assert report.staged == 1
        connection = sqlite3.connect(staging.path)
        rows = connection.execute(
            "SELECT window_utc, capture_utc, forecast, actual FROM candidates"
            " ORDER BY window_utc, capture_utc"
        ).fetchall()
        captures = connection.execute(
            "SELECT capture_utc, window_first_utc, window_last_utc, observed_utc"
            " FROM candidate_captures ORDER BY capture_utc"
        ).fetchall()
        connection.close()

        window = int(utc("2023-03-14T03:00Z").timestamp())
        assert rows == [
            (window, window - 1800, 68, None),  # lead +0.5h
            (window, window, 69, 70),  # lead 0h: forecast and actual cells merge
            (window + 1800, window, 71, None),  # second row's +0.5h cell, same capture
        ]
        assert captures == [
            (window - 1800, window, window, None),
            (window, window, window + 1800, None),
        ]


class TestStagingIntegrity:
    def test_a_csv_with_a_conflicting_duplicate_row_is_excluded_whole(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        duplicated = (
            REGIONAL_CSV
            + "2023-05-15T16:30Z,1,99,0.0,0.0,10.0,0.0,0.0,0.0,0.0,0.0,90.0\n"
        )
        csv_path = tmp_path / "2023-05-15T1601Z.csv"
        csv_path.write_text(duplicated)

        report = stage_wrangled_csvs(staging, [csv_path], endpoint="regional_fw48h")

        assert report.staged == 0
        assert report.excluded[0][0] == "2023-05-15T1601Z.csv"
        connection = sqlite3.connect(staging.path)
        (count,) = connection.execute("SELECT COUNT(*) FROM candidates").fetchone()
        connection.close()
        assert count == 0  # nothing from the contradicting file was kept

    @pytest.mark.parametrize("bad_region", [19, 0, -1])
    def test_preflight_rejects_region_ids_outside_the_valid_range(
        self, tmp_path: Path, bad_region: int
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        window = int(utc("2023-03-14T03:00Z").timestamp())
        connection = staging.connect()
        with connection:
            connection.execute(
                "INSERT INTO candidates VALUES ('wrangled_csv', 'regional_fw48h',"
                " ?, ?, ?, 50, NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
                (window, bad_region, window),
            )
            connection.execute(
                "INSERT INTO candidate_captures VALUES"
                " ('wrangled_csv', 'regional_fw48h', ?, ?, ?, NULL)",
                (window, window, window),
            )
        connection.close()

        with pytest.raises(MigrationError, match="region ids"):
            preflight(staging)

    def test_resolution_fails_when_a_loser_holds_observations_the_winner_lacks(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        base = int(utc("2023-04-06T10:00Z").timestamp())
        slot = base
        connection = staging.connect()
        with connection:
            # Winner (per-snapshot) saw windows base and base+1h; the summary also
            # saw base+30m inside that span. Equal spans, hidden observation.
            for source, windows in (
                ("wrangled_csv", (base, base + 3600)),
                ("summary_csv", (base, base + 1800, base + 3600)),
            ):
                for window in windows:
                    connection.execute(
                        "INSERT INTO candidates VALUES (?, 'regional_fw48h', ?, 1,"
                        " ?, 50, NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
                        (source, window, slot),
                    )
                connection.execute(
                    "INSERT INTO candidate_captures VALUES"
                    " (?, 'regional_fw48h', ?, ?, ?, NULL)",
                    (source, slot, base, base + 3600),
                )
        connection.close()

        with pytest.raises(MigrationError, match="refusing to discard"):
            resolve(staging)


class TestPreflight:
    def test_interior_holes_and_missing_regions_become_gap_records(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        window = int(utc("2023-03-14T03:00Z").timestamp())
        connection = staging.connect()
        with connection:
            # A summary-derived national capture that saw w and w+2 but not w+1.
            for observed_window in (window, window + 3600):
                connection.execute(
                    "INSERT INTO candidates VALUES ('summary_csv', 'national_fw48h',"
                    " ?, 0, ?, 68, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,"
                    " NULL, NULL)",
                    (observed_window, window),
                )
            connection.execute(
                "INSERT INTO candidate_captures VALUES"
                " ('summary_csv', 'national_fw48h', ?, ?, ?, NULL)",
                (window, window, window + 3600),
            )
            # A regional capture missing region 18 for its single window.
            for region_id in range(1, 18):
                connection.execute(
                    "INSERT INTO candidates VALUES ('wrangled_csv', 'regional_fw48h',"
                    " ?, ?, ?, 50, NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
                    (window, region_id, window),
                )
            connection.execute(
                "INSERT INTO candidate_captures VALUES"
                " ('wrangled_csv', 'regional_fw48h', ?, ?, ?, NULL)",
                (window, window, window),
            )
        connection.close()

        report = preflight(staging)

        connection = sqlite3.connect(staging.path)
        gaps = connection.execute(
            "SELECT endpoint, capture_utc, window_utc, region_id FROM candidate_gaps"
            " ORDER BY endpoint"
        ).fetchall()
        connection.close()
        assert report.gap_count == 2
        assert gaps == [
            ("national_fw48h", window, window + 1800, 0),
            ("regional_fw48h", window, window, 18),
        ]


class TestEmit:
    def test_an_a_b_a_trajectory_spanning_two_source_types_emits_the_right_change_log(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        window = int(utc("2023-04-06T12:00Z").timestamp())
        slots = [window - 3 * 1800, window - 2 * 1800, window - 1800]
        plan = [
            ("wrangled_csv", slots[0], 100),
            (
                "summary_csv",
                slots[1],
                200,
            ),  # the middle capture survives only in the summary
            ("wrangled_csv", slots[2], 100),  # back to the first value: a real change
        ]
        connection = staging.connect()
        with connection:
            for source, slot, forecast in plan:
                connection.execute(
                    "INSERT INTO candidates VALUES (?, 'regional_fw48h', ?, 1, ?, ?,"
                    " NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
                    (source, window, slot, forecast),
                )
                connection.execute(
                    "INSERT INTO candidate_captures VALUES"
                    " (?, 'regional_fw48h', ?, ?, ?, NULL)",
                    (source, slot, window, window),
                )
        connection.close()
        preflight(staging)
        resolve(staging)
        store = Store(tmp_path / "db")

        emitted = emit(staging, store, compact_now=utc("2023-04-09T02:12Z"))

        trajectory = store.regional_trajectory(utc("2023-04-06T12:00Z"), region_id=1)
        assert emitted == 3
        assert [(int(c.timestamp()), f) for c, f, _m in trajectory] == [
            (slots[0], 100),
            (slots[1], 200),
            (slots[2], 100),
        ]
        assert not list((tmp_path / "db" / "inbox").glob("snap_*.sqlite"))


class TestResolutionFieldCoverage:
    def test_resolution_fails_when_the_winner_lacks_a_field_the_loser_has(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        window = int(utc("2023-04-06T10:00Z").timestamp())
        connection = staging.connect()
        with connection:
            for source, actual in (("wrangled_csv", None), ("summary_csv", 95)):
                connection.execute(
                    "INSERT INTO candidates VALUES (?, 'national_fw48h', ?, 0, ?,"
                    " 100, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
                    (source, window, window, actual),
                )
                connection.execute(
                    "INSERT INTO candidate_captures VALUES"
                    " (?, 'national_fw48h', ?, ?, ?, NULL)",
                    (source, window, window, window),
                )
        connection.close()

        with pytest.raises(MigrationError, match="refusing to discard"):
            resolve(staging)

        connection = sqlite3.connect(staging.path)
        (resolved_rows,) = connection.execute(
            "SELECT COUNT(*) FROM resolved"
        ).fetchone()
        connection.close()
        assert resolved_rows == 0

    def test_a_summary_with_a_duplicate_cell_for_one_observation_is_rejected(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        summary = tmp_path / "summary_national_fw48h.csv"
        # Two forecast columns with the same lead: the same cell twice.
        summary.write_text(
            ",intensity.forecast,intensity.forecast\n"
            "time_difference,000.0,000.0\n"
            "2023-03-14T03:00Z,68.0,69.0\n"
        )

        with pytest.raises(MigrationError, match="duplicate forecast cell"):
            stage_national_summary(staging, summary, endpoint="national_fw48h")

        connection = sqlite3.connect(staging.path)
        (count,) = connection.execute("SELECT COUNT(*) FROM candidates").fetchone()
        connection.close()
        assert count == 0


REGIONAL_SUMMARY = """,regions.intensity.forecast,regions.intensity.forecast,wind,wind
,1,2,1,2
time_difference,000.0,000.0,000.0,000.0
2023-03-13T13:00Z,55,60,90.0,80.0
"""


class TestRegionalSummaryStaging:
    def test_regional_summary_cells_invert_and_merge_per_region(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        summary = tmp_path / "summary_regional_fw48h.csv"
        summary.write_text(REGIONAL_SUMMARY)

        report = stage_regional_summary(staging, summary, endpoint="regional_fw48h")

        assert report.staged == 1
        connection = sqlite3.connect(staging.path)
        rows = connection.execute(
            "SELECT window_utc, region_id, capture_utc, forecast, wind, biomass"
            " FROM candidates ORDER BY region_id"
        ).fetchall()
        connection.close()
        window = int(utc("2023-03-13T13:00Z").timestamp())
        assert rows == [
            (window, 1, window, 55, 900, None),
            (window, 2, window, 60, 800, None),
        ]


def build_mini_corpus(tmp_path: Path) -> Path:
    """A tiny but complete data_dir: two real snapshots, one summary, reference CSVs."""
    data_dir = tmp_path / "data"
    for endpoint in ("regional_fw48h",):
        (data_dir / endpoint).mkdir(parents=True)
        for source in sorted((FIXTURES / "real_day" / "regional_fw48h").glob("*.json"))[
            :2
        ]:
            (data_dir / endpoint / source.name).write_bytes(source.read_bytes())
    (data_dir / "summary_national_fw48h.csv").write_text(NATIONAL_SUMMARY)
    (data_dir / "artifacts").mkdir()
    (data_dir / "artifacts" / "ci_index_numerical_bands.csv").write_text(
        ",very low,very low,low,low\nYear / Index,from,to,from,to\n2023,0,49,50,129\n"
    )
    (data_dir / "artifacts" / "ci_index_numerical_band_error_scales.csv").write_text(
        ",moderate - very low,moderate - very low\n,difference,percentage\n2023,101,50.5\n"
    )
    (data_dir / "samples").mkdir()
    (data_dir / "samples" / "Carbon_Intensity_Data_2017-09.csv").write_text(
        "Datetime (UTC),Actual Carbon Intensity (gCO2/kWh),"
        "Forecast Carbon Intensity (gCO2/kWh),Index\n"
        "2017-09-11T23:30Z,140,134,low\n"
    )
    return data_dir


class TestRunner:
    def test_the_runner_stages_all_sources_and_reports_the_gate(
        self, tmp_path: Path
    ) -> None:
        data_dir = build_mini_corpus(tmp_path)

        report = run_migration(
            data_dir=data_dir,
            db_root=tmp_path / "db",
            staging_path=tmp_path / "staging.sqlite",
        )

        assert report.staged["regional_fw48h/json"].staged == 2
        assert report.emitted > 0
        assert report.overlap.fatal == 0
        assert set(report.reconstruction.values()) == {0}
        assert report.reextraction_mismatches == 0
        assert report.provenance_mismatches == 0
        assert report.leftover_inboxes == 0
        assert report.gate_passed
        assert report.reference_counts["ngeso_history"] == 1
        assert (tmp_path / "db" / "reference.sqlite").exists()

    def test_a_rerun_over_existing_state_fails_before_touching_anything(
        self, tmp_path: Path
    ) -> None:
        data_dir = build_mini_corpus(tmp_path)
        first = run_migration(
            data_dir=data_dir,
            db_root=tmp_path / "db",
            staging_path=tmp_path / "staging.sqlite",
        )
        assert first.emitted > 0
        before = sorted(
            (path, path.stat().st_mtime_ns)
            for path in (tmp_path / "db").glob("**/*.sqlite")
        )

        with pytest.raises(MigrationError, match="already exists"):
            run_migration(
                data_dir=data_dir,
                db_root=tmp_path / "db",
                staging_path=tmp_path / "staging.sqlite",
            )
        with pytest.raises(MigrationError, match="fresh root"):
            run_migration(
                data_dir=data_dir,
                db_root=tmp_path / "db",
                staging_path=tmp_path / "staging2.sqlite",
            )

        after = sorted(
            (path, path.stat().st_mtime_ns)
            for path in (tmp_path / "db").glob("**/*.sqlite")
        )
        assert after == before
        assert not list((tmp_path / "db" / "inbox").glob("quarantine/*"))


class TestVerificationGate:
    def build_emitted_corpus(self, tmp_path: Path) -> tuple[Staging, Store]:
        staging = Staging(tmp_path / "staging.sqlite")
        files = sorted((FIXTURES / "real_day" / "regional_fw48h").glob("*.json"))
        stage_json_backlog(staging, files, endpoint="regional_fw48h")
        preflight(staging)
        resolve(staging)
        store = Store(tmp_path / "db")
        emit(staging, store, compact_now=utc("2024-01-14T02:12Z"))
        return staging, store

    def test_exhaustive_verification_passes_on_an_emitted_corpus(
        self, tmp_path: Path
    ) -> None:
        staging, store = self.build_emitted_corpus(tmp_path)

        mismatches = verify_reconstruction(staging, store)

        assert set(mismatches.values()) == {0}

    def test_exhaustive_verification_fails_on_a_seeded_corruption(
        self, tmp_path: Path
    ) -> None:
        staging, store = self.build_emitted_corpus(tmp_path)
        partition = next(store.db_root.glob("2024/regional_*.sqlite"))
        connection = sqlite3.connect(partition)
        with connection:
            connection.execute(
                "UPDATE regional_intensity SET forecast = forecast + 1"
                " WHERE (window_utc, region_id, capture_utc) IN"
                " (SELECT window_utc, region_id, capture_utc"
                "  FROM regional_intensity LIMIT 1)"
            )
        connection.close()

        mismatches = verify_reconstruction(staging, store)

        assert sum(mismatches.values()) > 0

    def test_a_mislabelled_capture_source_is_counted(self, tmp_path: Path) -> None:
        staging, store = self.build_emitted_corpus(tmp_path)
        partition = next(store.db_root.glob("2024/regional_*.sqlite"))
        connection = sqlite3.connect(partition)
        with connection:
            connection.execute(
                "UPDATE captures SET source = 'live' WHERE (capture_utc, endpoint) IN"
                " (SELECT capture_utc, endpoint FROM captures LIMIT 1)"
            )
        connection.close()

        # Symmetric comparison: a relabel is one missing expected row plus one
        # unexpected stored row.
        assert verify_provenance(staging, store) == 2

    def test_a_deleted_capture_row_fails_the_provenance_gate(
        self, tmp_path: Path
    ) -> None:
        staging, store = self.build_emitted_corpus(tmp_path)
        partition = next(store.db_root.glob("2024/regional_*.sqlite"))
        connection = sqlite3.connect(partition)
        with connection:
            connection.execute(
                "DELETE FROM captures WHERE (capture_utc, endpoint) IN"
                " (SELECT capture_utc, endpoint FROM captures LIMIT 1)"
            )
        connection.close()

        assert verify_provenance(staging, store) == 1

    def test_an_unexpected_inserted_capture_fails_the_provenance_gate(
        self, tmp_path: Path
    ) -> None:
        staging, store = self.build_emitted_corpus(tmp_path)
        partition = next(store.db_root.glob("2024/regional_*.sqlite"))
        connection = sqlite3.connect(partition)
        with connection:
            connection.execute(
                "INSERT INTO captures VALUES"
                " (9999999999, 'regional_fw48h', 9999999999, 9999999999, NULL,"
                " 'json_backlog')"
            )
        connection.close()

        assert verify_provenance(staging, store) == 1

    def test_a_missing_cross_partition_capture_copy_fails_the_provenance_gate(
        self, tmp_path: Path
    ) -> None:
        # A capture whose coverage spans the half-month boundary must appear in
        # both partitions; deleting one copy is a routing failure.
        staging = Staging(tmp_path / "staging.sqlite")
        first = int(utc("2023-03-15T23:30Z").timestamp())
        second = int(utc("2023-03-16T00:00Z").timestamp())
        connection = staging.connect()
        with connection:
            for window in (first, second):
                connection.execute(
                    "INSERT INTO candidates VALUES ('json_backlog', 'regional_fw48h',"
                    " ?, 1, ?, 50, NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
                    (window, first),
                )
            connection.execute(
                "INSERT INTO candidate_captures VALUES"
                " ('json_backlog', 'regional_fw48h', ?, ?, ?, NULL)",
                (first, first, second),
            )
        connection.close()
        preflight(staging)
        resolve(staging)
        store = Store(tmp_path / "db")
        emit(staging, store, compact_now=utc("2023-03-18T12:00Z"))
        assert verify_provenance(staging, store) == 0

        one_copy = tmp_path / "db" / "2023" / "regional_2023-03b.sqlite"
        connection = sqlite3.connect(one_copy)
        with connection:
            connection.execute("DELETE FROM captures")
        connection.close()

        assert verify_provenance(staging, store) == 1

    def test_dual_implementation_reextraction_catches_a_parser_level_defect(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        files = sorted((FIXTURES / "real_day" / "regional_fw48h").glob("*.json"))[:2]
        stage_json_backlog(staging, files, endpoint="regional_fw48h")

        clean = reextract_sample(staging, files, endpoint="regional_fw48h")

        connection = staging.connect()
        with connection:
            connection.execute(
                "UPDATE candidates SET wind = wind + 1 WHERE rowid IN"
                " (SELECT rowid FROM candidates LIMIT 1)"
            )
        connection.close()

        corrupted = reextract_sample(staging, files, endpoint="regional_fw48h")

        assert clean == 0
        assert corrupted == 1

    def test_reextraction_skips_files_that_staging_consistently_excluded(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        malformed = tmp_path / "2024-01-12T0901Z.json"
        malformed.write_text("{ not json")

        mismatches = reextract_sample(staging, [malformed], endpoint="regional_fw48h")

        assert mismatches == 0  # excluded from staging AND unreadable now: consistent

    def test_reextraction_counts_an_unreadable_file_that_was_somehow_staged(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        slot = int(utc("2024-01-12T09:00Z").timestamp())
        connection = staging.connect()
        with connection:
            connection.execute(
                "INSERT INTO candidates VALUES ('json_backlog', 'regional_fw48h',"
                " ?, 1, ?, 50, NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
                (slot, slot),
            )
        connection.close()
        unreadable = tmp_path / "2024-01-12T0901Z.json"
        unreadable.write_text("{ not json")

        mismatches = reextract_sample(staging, [unreadable], endpoint="regional_fw48h")

        assert mismatches == 1  # staged rows exist but the source no longer parses

    def test_the_golden_corpus_totals_match_hand_computed_values(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        summary = tmp_path / "summary_national_fw48h.csv"
        summary.write_text(NATIONAL_SUMMARY)
        stage_national_summary(staging, summary, endpoint="national_fw48h")

        count, mean_abs_error = golden_corpus(staging)

        # Window one: forecasts 68 and 69 against final actual 70 -> errors -2, -1.
        # Window two has no actual, so its forecast contributes nothing.
        assert count == 2
        assert mean_abs_error == 1.5

    def test_only_the_two_frozen_known_disagreements_are_accepted(
        self, tmp_path: Path
    ) -> None:
        """The legacy pipeline's dying night fetched twice inside the 2023-10-20
        02:00 slot; exactly those two observations may disagree across sources."""
        staging = Staging(tmp_path / "staging.sqlite")
        connection = staging.connect()
        with connection:
            for window in (1697763600, 1697765400):
                for source, forecast in (("json_backlog", 50), ("summary_csv", 51)):
                    connection.execute(
                        "INSERT INTO candidates VALUES (?, 'national_pt24h', ?, 0, ?,"
                        " ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,"
                        " NULL)",
                        (source, window, 1697767200, forecast),
                    )
        connection.close()

        overlap = verify_overlap(staging)

        assert overlap.fatal == 0
        assert len(overlap.accepted) == 2

    def test_any_other_summary_disagreement_is_fatal(self, tmp_path: Path) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        window = int(utc("2023-04-06T10:00Z").timestamp())
        connection = staging.connect()
        with connection:
            for source, forecast in (("wrangled_csv", 50), ("summary_csv", 51)):
                connection.execute(
                    "INSERT INTO candidates VALUES (?, 'regional_fw48h', ?, 1, ?,"
                    " ?, NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
                    (source, window, window, forecast),
                )
        connection.close()

        overlap = verify_overlap(staging)

        assert overlap.fatal == 1
        assert overlap.accepted == ()

    def test_two_raw_snapshot_sources_that_disagree_are_fatal(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        window = int(utc("2023-10-20T01:00Z").timestamp())
        connection = staging.connect()
        with connection:
            for source, actual in (("json_backlog", 70), ("wrangled_csv", 71)):
                connection.execute(
                    "INSERT INTO candidates VALUES (?, 'national_pt24h', ?, 0, ?,"
                    " 79, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
                    (source, window, window + 1800, actual),
                )
        connection.close()

        overlap = verify_overlap(staging)

        assert overlap.fatal == 1


class TestSelection:
    def test_a_capture_held_by_a_per_snapshot_source_takes_every_observation_from_it(
        self, tmp_path: Path
    ) -> None:
        staging = Staging(tmp_path / "staging.sqlite")
        window = int(utc("2023-04-06T10:00Z").timestamp())
        slot = window
        connection = staging.connect()
        with connection:
            for source, forecast in (("wrangled_csv", 50), ("summary_csv", 51)):
                connection.execute(
                    "INSERT INTO candidates VALUES"
                    " (?, 'regional_fw48h', ?, 1, ?, ?, NULL,"
                    " 0, 0, 0, 0, 0, 0, 0, 0, 0)",
                    (source, window, slot, forecast),
                )
                connection.execute(
                    "INSERT INTO candidate_captures VALUES"
                    " (?, 'regional_fw48h', ?, ?, ?, NULL)",
                    (source, slot, window, window),
                )
        connection.close()

        resolve(staging)

        connection = sqlite3.connect(staging.path)
        resolved = connection.execute(
            "SELECT source, forecast FROM resolved_captures"
            " JOIN resolved USING (endpoint, capture_utc)"
        ).fetchall()
        connection.close()
        assert resolved == [("wrangled_csv", 50)]
