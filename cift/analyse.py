"""The daily job: rebuild every chart, README table, and stored statistic."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib
import pandas as pd
import scipy.stats

from cift import graph
from cift.analysis import HealthReport
from cift.analysis import daily_stats
from cift.analysis import error_frames
from cift.analysis import error_probabilities
from cift.analysis import horizon_health
from cift.analysis import national_matrix
from cift.readme import splice
from cift.store import Store

# Headless by default: the daily job runs on a runner with no display, and the
# backend must be chosen before any figure is created.
matplotlib.use("Agg")

PROBABILITY_MAGNITUDES = list(range(100, 0, -10))

# The history boxplot always shows a month, independent of the README stats window.
HISTORY_CHART_DAYS = 30


@dataclass(frozen=True)
class AnalyseReport:
    charts: tuple[str, ...]
    health: HealthReport
    stats_dates: tuple[str, ...]


def _readable(frame_columns: dict[str, str], frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(columns=frame_columns)


def run_analyse(
    db_root: Path,
    charts_dir: Path,
    readme_path: Path,
    now: datetime,
    days: int = 7,
    hours_of_data: int = 24,
) -> AnalyseReport:
    store = Store(db_root)
    matrix = national_matrix(store)
    charts_dir.mkdir(parents=True, exist_ok=True)

    dates = graph.get_dates(matrix, num_hours=hours_of_data)
    selected = matrix.loc[dates]
    charts = []

    def save(figure: object, name: str) -> None:
        graph.save_figure(figure, charts_dir, name)
        charts.append(name)

    save(graph.generate_plot_ci_lines(selected, dates=dates), "national_ci_lines.png")
    save(
        graph.generate_boxplot_ci(
            selected,
            dates=dates,
            colourmap=True,
            boundaries=store.reference_bands(dates[0].year),
        ),
        "national_ci_boxplot.png",
    )
    save(
        graph.generate_boxplot_ci_error(selected, dates=dates),
        "national_ci_error_boxplot.png",
    )
    save(
        graph.generate_boxplot_ci_error_for_days(matrix, days=HISTORY_CHART_DAYS),
        "national_ci_error_boxplot_30days.png",
    )
    save(
        graph.generate_boxplot_ci_error_per_hour(matrix, days),
        "national_ci_error_boxplot_per_hour.png",
    )
    scatter, _pearson = graph.generate_ci_error_relationship(matrix)
    save(scatter, "national_ci_vs_error_scatter_relationship.png")

    errors, _pc = error_frames(matrix)
    all_errors = errors.stack().dropna()
    # Only the distribution FIT excludes extreme outliers; the all-data summary
    # counts every error, as the legacy pipeline did.
    distribution_errors = all_errors[all_errors.abs() <= 300]
    figure, _table = graph.generate_distribution_plots(
        distribution_errors.to_numpy(),
        x_label="error, $gCO_2/kWh$",
        hist_label="error data",
        x_min=-150,
        x_max=150,
        lookup_extreme_values=PROBABILITY_MAGNITUDES,
    )
    save(figure, "national_ci_forecast_error_distribution.png")

    probabilities = error_probabilities(distribution_errors, PROBABILITY_MAGNITUDES)
    stats = daily_stats(matrix, days)
    absolute_summary = {
        "n": int(all_errors.abs().count()),
        "mean": float(all_errors.abs().mean()),
        "median": float(all_errors.abs().median()),
        "std": float(all_errors.abs().std()),
        "sem": float(scipy.stats.sem(all_errors.abs())),
    }

    text = readme_path.read_text()
    text = splice(
        text,
        "daily-stats",
        _readable(
            {
                "forecast_count": "count",
                "abs_err_mean": "mean",
                "abs_err_sem": "sem",
                "abs_err_ci95_lo": "95% CI low",
                "abs_err_ci95_hi": "95% CI high",
            },
            stats[
                [
                    "forecast_count",
                    "abs_err_mean",
                    "abs_err_sem",
                    "abs_err_ci95_lo",
                    "abs_err_ci95_hi",
                ]
            ],
        ).to_markdown(),
    )
    text = splice(
        text,
        "daily-stats-pc",
        _readable(
            {
                "pc_err_mean": "mean",
                "pc_err_sem": "sem",
                "pc_err_ci95_lo": "95% CI low",
                "pc_err_ci95_hi": "95% CI high",
            },
            stats[["pc_err_mean", "pc_err_sem", "pc_err_ci95_lo", "pc_err_ci95_hi"]],
        ).to_markdown(),
    )
    text = splice(text, "error-probabilities", probabilities.to_markdown())
    text = splice(
        text,
        "all-data-summary",
        f"| n | mean | median | std | sem |\n|---|---|---|---|---|\n"
        f"| {absolute_summary['n']} | {absolute_summary['mean']:.4f}"
        f" | {absolute_summary['median']:.1f} | {absolute_summary['std']:.4f}"
        f" | {absolute_summary['sem']:.6f} |",
    )
    readme_path.write_text(text)

    for stat_date, row in stats.iterrows():
        store.record_stats(str(stat_date), row.to_dict())
    run_date = now.date().isoformat()
    store.record_probabilities(
        run_date,
        [
            (int(magnitude), float(row[0]), float(row[1]), float(row[2]))
            for magnitude, row in zip(
                probabilities.index, probabilities.to_numpy(), strict=True
            )
        ],
    )
    store.record_error_summary(run_date, absolute_summary)

    return AnalyseReport(
        charts=tuple(charts),
        health=horizon_health(store, now),
        stats_dates=tuple(str(index) for index in stats.index),
    )
