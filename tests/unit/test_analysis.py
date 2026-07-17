"""Analysis behaviours: the legacy window-by-lead matrix, errors, and daily stats."""

from pathlib import Path

import pandas as pd
import pytest

from cift.analysis import FINAL_ACTUAL
from cift.analysis import daily_stats
from cift.analysis import error_frames
from cift.analysis import get_dates
from cift.analysis import national_matrix
from cift.store import Store
from tests.conftest import utc
from tests.unit.test_store import ingest_national

WINDOW = "2023-03-22T11:30Z"


def build_store(tmp_path: Path) -> Store:
    """Three captures of one window: lead 0h, then post-hoc revisions at -0.5h and -1h."""
    ingest_national(tmp_path, "2023-03-22T11:31Z", (WINDOW, 41, None))
    ingest_national(
        tmp_path, "2023-03-22T12:01Z", (WINDOW, 41, 43), endpoint="national_pt24h"
    )
    ingest_national(
        tmp_path, "2023-03-22T12:31Z", (WINDOW, 41, 45), endpoint="national_pt24h"
    )
    store = Store(tmp_path)
    store.compact(now=utc("2023-03-24T02:12Z"))
    return store


class TestNationalMatrix:
    def test_matrix_matches_the_legacy_summary_shape(self, tmp_path: Path) -> None:
        store = build_store(tmp_path)

        matrix = national_matrix(store)

        assert list(matrix.columns) == [
            ("intensity.forecast", 0.0),
            ("intensity.forecast", -0.5),
            ("intensity.forecast", -1.0),
            ("intensity.actual", 0.0),
            ("intensity.actual", -0.5),
            ("intensity.actual", -1.0),
            ("intensity.actual.final", ""),
        ]
        row = matrix.loc[utc(WINDOW).replace(tzinfo=None)]
        assert row[("intensity.forecast", 0.0)] == 41
        assert row[("intensity.actual", -1.0)] == 45
        assert row[("intensity.actual.final", "")] == 45

    def test_matrix_overlays_unmerged_inbox_snapshots_read_only(
        self, tmp_path: Path
    ) -> None:
        store = build_store(tmp_path)
        ingest_national(
            tmp_path, "2023-03-22T13:01Z", (WINDOW, 41, 46), endpoint="national_pt24h"
        )  # not compacted

        matrix = national_matrix(store)
        inboxes_after = list((tmp_path / "inbox").glob("snap_*.sqlite"))

        assert (
            matrix.loc[utc(WINDOW).replace(tzinfo=None), ("intensity.actual", -1.5)]
            == 46
        )
        assert (
            matrix.loc[utc(WINDOW).replace(tzinfo=None), ("intensity.actual.final", "")]
            == 46
        )
        assert len(inboxes_after) == 1


class TestDailyStatsWindow:
    def test_daily_stats_uses_the_exact_legacy_completed_window(self) -> None:
        """Hand-computed boundaries: 12 continuous days, days=2. The legacy selector
        starts at (latest - 72h) - 2d inclusive and caps at 96 slots, so the window
        runs Jan 7 23:30 through Jan 9 23:00 -> dates 07 (1), 08 (48), 09 (47)."""
        index = pd.date_range("2026-01-01", periods=12 * 48, freq="30min")
        frame = pd.DataFrame(
            {
                ("intensity.forecast", 0.0): 105.0,
                ("intensity.actual", -24.0): 100.0,
                FINAL_ACTUAL: 100.0,
            },
            index=index,
        )
        frame.columns = pd.MultiIndex.from_tuples(frame.columns)

        selected = get_dates(frame, num_days=2)
        stats = daily_stats(frame, days=2)

        assert selected[0] == pd.Timestamp("2026-01-07 23:30")
        assert selected[-1] == pd.Timestamp("2026-01-09 23:00")
        assert list(stats.index) == ["2026-01-07", "2026-01-08", "2026-01-09"]
        assert list(stats["forecast_count"]) == [1, 48, 47]
        assert set(stats["abs_err_mean"]) == {5.0}


class TestErrorFrames:
    def test_error_uses_final_actual_and_excludes_post_hoc_leads(
        self, tmp_path: Path
    ) -> None:
        store = build_store(tmp_path)

        errors, percentage_errors = error_frames(national_matrix(store))

        assert list(errors.columns) == [0.0]
        assert errors.loc[utc(WINDOW).replace(tzinfo=None), 0.0] == 41 - 45
        assert percentage_errors.loc[
            utc(WINDOW).replace(tzinfo=None), 0.0
        ] == pytest.approx(100.0 * (41 - 45) / 45)
