"""Chart smoke tests: figures build from the matrix shape; no pixel assertions."""

import numpy as np
import pandas as pd

from cift import graph
from cift.analysis import FINAL_ACTUAL


def synthetic_matrix(windows: int = 96) -> pd.DataFrame:
    index = pd.date_range("2023-03-20", periods=windows, freq="30min")
    actual = pd.Series(np.linspace(50, 250, windows), index=index)
    columns = {
        ("intensity.forecast", 47.5): actual + 30,
        ("intensity.forecast", 24.0): actual + 15,
        ("intensity.forecast", 0.0): actual - 30,
        ("intensity.actual", 0.0): actual - 2,
        ("intensity.actual", -24.0): actual,
        FINAL_ACTUAL: actual,
    }
    frame = pd.DataFrame(columns, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    return frame


class TestChartSmoke:
    def test_dpi_is_halved_to_tame_git_growth(self) -> None:
        assert graph.DPI == 125

    def test_ci_lines_figure_builds(self) -> None:
        matrix = synthetic_matrix()
        dates = list(matrix.index[:4])

        figure = graph.generate_plot_ci_lines(matrix, dates=dates)

        assert "carbon intensity" in figure.axes[0].get_figure().get_supylabel()

    def test_error_boxplot_figure_builds(self) -> None:
        matrix = synthetic_matrix()
        dates = list(matrix.index[:4])

        figure = graph.generate_boxplot_ci_error(matrix.loc[dates], dates=dates)

        assert figure.axes[0].get_ylabel() == "forecast % error"

    def test_per_hour_boxplot_figure_builds(self) -> None:
        matrix = synthetic_matrix(windows=96 * 5)

        figure = graph.generate_boxplot_ci_error_per_hour(matrix, days=1)

        assert figure.axes


class TestScatterPearson:
    def test_pearson_r_covers_all_lead_columns_not_the_loop_leftover(self) -> None:
        index = pd.date_range("2023-03-20", periods=50, freq="30min")
        actual = pd.Series(np.linspace(50, 250, 50), index=index)
        frame = pd.DataFrame(
            {
                ("intensity.forecast", 1.0): actual * 1.5,  # error +0.5x: corr +1
                ("intensity.forecast", 0.0): actual * 0.5,  # error -0.5x: corr -1
                ("intensity.actual", -24.0): actual,
                FINAL_ACTUAL: actual,
            },
            index=index,
        )
        frame.columns = pd.MultiIndex.from_tuples(frame.columns)

        _figure, pearson_r = graph.generate_ci_error_relationship(frame)

        # Stacked over both lead columns the +1 and -1 correlations cancel; the
        # legacy loop-leftover bug reported one column's +/-1 instead.
        assert abs(pearson_r) < 0.1
