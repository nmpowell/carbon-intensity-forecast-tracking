"""End-to-end analyse: store in, charts + README tables + recorded stats out."""

import sqlite3
from datetime import timedelta
from pathlib import Path
from unittest import mock

import cift.analyse
from cift.analyse import run_analyse
from cift.parse import floor_to_slot
from cift.parse import parse_snapshot
from cift.store import Store
from tests.conftest import national_payload
from tests.conftest import utc

README = """# title
<!-- cift:daily-stats:start -->
old
<!-- cift:daily-stats:end -->
<!-- cift:daily-stats-pc:start -->
old
<!-- cift:daily-stats-pc:end -->
<!-- cift:error-probabilities:start -->
old
<!-- cift:error-probabilities:end -->
<!-- cift:all-data-summary:start -->
old
<!-- cift:all-data-summary:end -->
"""


def slot_time(base: str, slots: int) -> str:
    return (utc(base) + timedelta(minutes=30 * slots)).strftime("%Y-%m-%dT%H:%MZ")


def build_four_days(db_root: Path) -> Store:
    """Per capture slot: a 4-window forward horizon and a 4-window post-hoc
    revision horizon with actuals — a miniature of the real fw48h/pt24h pair."""
    store = Store(db_root)
    base = "2023-03-18T00:00Z"
    for index in range(48 * 4):
        slot = floor_to_slot(utc(slot_time(base, index)))
        forward = national_payload(
            *[(slot_time(base, index + i), 100 + index % 7, None) for i in range(4)]
        )
        past = national_payload(
            *[
                (
                    slot_time(base, index - 48 + i),
                    100 + (index - 48 + i) % 7,
                    103 + (index - 48 + i) % 5,
                )
                for i in range(4)
            ]
        )
        store.write_inbox(
            [
                parse_snapshot("national_fw48h", forward, slot, slot),
                parse_snapshot("national_pt24h", past, slot, slot),
            ]
        )
    # One wild forecast beyond +/-300 error: it must reach the all-data summary
    # but stay out of the distribution fit. Forecast 999 at lead zero, final
    # actual 100 revised in later: error +899.
    forecast_slot = floor_to_slot(utc("2023-03-22T00:01Z"))
    wild = national_payload(("2023-03-22T00:00Z", 999, None))
    store.write_inbox(
        [parse_snapshot("national_fw48h", wild, forecast_slot, forecast_slot)]
    )
    revision_slot = floor_to_slot(utc("2023-03-22T12:01Z"))
    revised = national_payload(("2023-03-22T00:00Z", 999, 100))
    store.write_inbox(
        [parse_snapshot("national_pt24h", revised, revision_slot, revision_slot)]
    )
    store.compact(now=utc("2023-03-23T00:00Z"))
    return store


class TestRunAnalyse:
    def test_analyse_produces_charts_readme_tables_and_stats(
        self, tmp_path: Path
    ) -> None:
        db_root = tmp_path / "db"
        charts_dir = tmp_path / "charts"
        readme = tmp_path / "README.md"
        readme.write_text(README)
        store = build_four_days(db_root)
        store.record_reference_bands(
            [
                (2023, position, band, position * 60, position * 60 + 59)
                for position, band in enumerate(
                    ["very low", "low", "moderate", "high", "very high"]
                )
            ]
        )
        with (
            mock.patch.object(
                cift.analyse.graph,
                "generate_boxplot_ci_error_for_days",
                wraps=cift.analyse.graph.generate_boxplot_ci_error_for_days,
            ) as history_chart,
            mock.patch.object(
                cift.analyse.graph,
                "generate_distribution_plots",
                wraps=cift.analyse.graph.generate_distribution_plots,
            ) as distribution,
        ):
            report = run_analyse(
                db_root=db_root,
                charts_dir=charts_dir,
                readme_path=readme,
                now=utc("2023-03-22T02:12Z"),
                days=2,
                hours_of_data=2,
            )
        assert history_chart.call_args.kwargs["days"] == 30
        fitted_errors = distribution.call_args.args[0]
        assert (abs(fitted_errors) <= 300).all()

        summary_connection = sqlite3.connect(db_root / "analysis.sqlite")
        n, mean = summary_connection.execute(
            "SELECT n, mean FROM all_data_error_summary"
        ).fetchone()
        (probability_rows,) = summary_connection.execute(
            "SELECT COUNT(*) FROM error_probabilities"
        ).fetchone()
        summary_connection.close()
        assert probability_rows == 10  # one row per requested magnitude, persisted
        assert n == len(fitted_errors) + 1  # the 899-point outlier is counted
        assert mean > 0

        produced = {path.name for path in charts_dir.glob("*.png")}
        assert "national_ci_lines.png" in produced
        assert "national_ci_error_boxplot.png" in produced
        assert "national_ci_forecast_error_distribution.png" in produced

        text = readme.read_text()
        assert "old" not in text
        assert "| error value |" in text or "error value" in text

        history = Store(db_root).stats_history()
        assert len(history) >= 2
        assert all(row["forecast_count"] > 0 for row in history)

        assert not report.health.healthy  # 4-window horizons are truncated: alerts fire
