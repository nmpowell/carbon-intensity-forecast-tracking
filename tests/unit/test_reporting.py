"""Distribution fits, stats history, README splicing, and horizon health."""

from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from cift.analysis import error_probabilities
from cift.analysis import horizon_health
from cift.parse import floor_to_slot
from cift.parse import parse_snapshot
from cift.readme import splice
from cift.store import Store
from tests.conftest import regional_payload
from tests.conftest import utc


class TestErrorProbabilities:
    def test_fit_returns_probabilities_for_requested_magnitudes(self) -> None:
        values = np.arange(-60, 61)
        rng_free_errors = np.repeat(values, 61 - np.abs(values))  # triangular, fixed

        table = error_probabilities(rng_free_errors, magnitudes=[50, 10])

        assert list(table.columns) == [
            "Student's t probability",
            "Normal probability",
            "Laplace probability",
        ]
        assert list(table.index) == [50, 10]
        assert ((table > 0) & (table < 1)).all().all()
        assert (table.loc[50] < table.loc[10]).all()


class TestStatsHistory:
    def test_stats_history_upserts_by_date(self, tmp_path: Path) -> None:
        store = Store(tmp_path)
        first = {
            "forecast_count": 100,
            "abs_err_mean": 20.0,
            "abs_err_sem": 0.5,
            "abs_err_ci95_lo": 19.0,
            "abs_err_ci95_hi": 21.0,
            "pc_err_mean": 10.0,
            "pc_err_sem": 0.2,
            "pc_err_ci95_lo": 9.6,
            "pc_err_ci95_hi": 10.4,
        }

        store.record_stats("2023-10-17", first)
        store.record_stats("2023-10-17", {**first, "abs_err_mean": 22.0})

        history = store.stats_history()
        assert len(history) == 1
        assert history[0]["stat_date"] == "2023-10-17"
        assert history[0]["abs_err_mean"] == 22.0


class TestReadmeSplice:
    def test_sections_are_replaced_between_markers(self) -> None:
        text = "intro\n<!-- cift:stats:start -->\nold\n<!-- cift:stats:end -->\noutro\n"

        result = splice(text, "stats", "| new table |")

        assert result == (
            "intro\n<!-- cift:stats:start -->\n| new table |\n"
            "<!-- cift:stats:end -->\noutro\n"
        )

    def test_a_missing_marker_raises_rather_than_prepending(self) -> None:
        with pytest.raises(ValueError, match="cift:absent"):
            splice("no markers here\n", "absent", "content")


class TestHorizonHealth:
    def test_alerts_on_immediate_and_sustained_truncation_and_resets(
        self, tmp_path: Path
    ) -> None:
        store = Store(tmp_path)
        full = [
            (f"2023-03-22T{h:02d}:{m}Z", 100)
            for h in range(10, 12)
            for m in ("00", "30")
        ]

        def snap(captured: str, windows: int) -> None:
            slot = floor_to_slot(utc(captured))
            payload = regional_payload(*full[:windows])
            store.write_inbox([parse_snapshot("regional_fw48h", payload, slot, slot)])

        snap("2023-03-22T10:01Z", 1)  # 1/96 windows: immediate alert
        report = horizon_health(store, now=utc("2023-03-22T12:00Z"))

        assert not report.healthy
        assert any(
            "regional_fw48h" in alert and "1/96" in alert for alert in report.alerts
        )

    def test_six_consecutive_short_captures_alert_and_five_do_not(
        self, tmp_path: Path
    ) -> None:
        store = Store(tmp_path)
        base = utc("2023-03-22T08:00Z")
        for index in range(6):
            captured = base + timedelta(minutes=30 * index)
            slot = floor_to_slot(captured)
            windows = [
                (
                    (captured + timedelta(minutes=30 * offset)).strftime(
                        "%Y-%m-%dT%H:%MZ"
                    ),
                    100,
                )
                for offset in range(60)  # 60/96 windows: short but above 50%
            ]
            store.write_inbox(
                [
                    parse_snapshot(
                        "regional_fw48h", regional_payload(*windows), slot, slot
                    )
                ]
            )
            if index == 4:
                after_five = horizon_health(store, now=utc("2023-03-22T12:00Z"))

        after_six = horizon_health(store, now=utc("2023-03-22T12:00Z"))

        assert after_five.healthy
        assert [alert for alert in after_six.alerts if "sustained" in alert]

    def test_a_full_horizon_capture_resets_the_short_streak(
        self, tmp_path: Path
    ) -> None:
        store = Store(tmp_path)
        base = utc("2023-03-22T08:00Z")

        def snap(index: int, window_count: int) -> None:
            captured = base + timedelta(minutes=30 * index)
            slot = floor_to_slot(captured)
            windows = [
                (
                    (captured + timedelta(minutes=30 * offset)).strftime(
                        "%Y-%m-%dT%H:%MZ"
                    ),
                    100,
                )
                for offset in range(window_count)
            ]
            store.write_inbox(
                [
                    parse_snapshot(
                        "regional_fw48h", regional_payload(*windows), slot, slot
                    )
                ]
            )

        for index in range(3):
            snap(index, 60)  # three short
        snap(3, 96)  # full horizon: streak resets
        for index in range(4, 7):
            snap(index, 60)  # three more short: streak is 3, not 6

        report = horizon_health(store, now=utc("2023-03-22T12:00Z"))

        assert report.healthy

    def test_full_horizons_are_healthy(self, tmp_path: Path) -> None:
        store = Store(tmp_path)
        windows = [
            (
                f"2023-03-2{2 + (10 + i // 2) // 24}T{(10 + i // 2) % 24:02d}:{'30' if i % 2 else '00'}Z",
                100,
            )
            for i in range(96)
        ]
        slot = floor_to_slot(utc("2023-03-22T10:01Z"))
        store.write_inbox(
            [parse_snapshot("regional_fw48h", regional_payload(*windows), slot, slot)]
        )

        report = horizon_health(store, now=utc("2023-03-22T12:00Z"))

        assert report.healthy
        assert report.alerts == ()
