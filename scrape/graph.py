# Show some graphs

import os
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from itertools import cycle

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scrape.files import get_data_files

# TODO:
# check the merge of summaries doesn't require a known order
# How complete is the data?


DPI = 250

HOURS_OF_DATA = 12

NOW = datetime.utcnow().replace(tzinfo=timezone.utc)


def save_figure(fig, output_directory, filename):
    fig.savefig(os.path.join(output_directory, filename), bbox_inches="tight", dpi=DPI)


def format_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Given a summary dataframe, format appropriately for plotting."""
    new_df = df.copy()
    new_df.index = pd.to_datetime(new_df.index)

    # one subset of columns in a multi-index
    new_df.columns = new_df.columns.set_levels(
        new_df.columns.levels[1].astype(float), level=1
    )
    new_df = new_df.reindex(sorted(new_df.columns, reverse=True), axis=1)
    return new_df


def load_summaries(directory: str) -> list:
    files = get_data_files(directory, extension=".csv", filter="summary_national")
    return [pd.read_csv(f, index_col=0, header=[0, 1]) for f in files]


def load_forward_summary(directory: str) -> pd.DataFrame:
    files = get_data_files(directory, extension=".csv", filter="summary_national_fw48h")
    return pd.read_csv(files[0], index_col=0, header=[0, 1])


def _ftime(dt):
    return datetime.strftime(dt, "%Y-%m-%d %H:%M")


def get_dates(df: pd.DataFrame, num_plots: int) -> list:
    """Get the dates to plot.

    Args:
        df (pd.DataFrame): dataframe with datetime index
        num_plots (int): number of plots to generate

    Returns:
        list: list of datetimes
    """
    # Want to show N hours of data. The most recent timepoint for which all data is available will be now - 24 hours.
    # The first timepoint will be now - 24 hours - N hours.
    hours_prior_to_now = 24 + HOURS_OF_DATA
    dt_pastpoint = NOW - timedelta(hours=hours_prior_to_now)

    # pick datetimes
    return [d for d in df.index if d >= dt_pastpoint][:num_plots]


def generate_plot_ci_lines(
    input_directory: str,
):
    """Generate plots from summaries.

    Args:
        input_directory (str): _description_
        output_directory (str, optional): _description_. Defaults to None.
    """

    summaries = load_summaries(input_directory)
    merged_df = pd.merge(*summaries, left_index=True, right_index=True, how="outer")
    merged_df = format_dataframe(merged_df)

    dates = get_dates(merged_df, HOURS_OF_DATA * 2)

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    # Don't start opacity from 0
    alphas = iter(np.linspace(0.1, 1, len(dates)))
    colours = cycle(["tab:blue", "tab:orange"])

    fig, ax = plt.subplots(1, 1)
    for ix, dt in enumerate(dates):
        alpha = next(alphas)

        # set label to empty string unless it is the last iteration
        plot_defs = {"ax": ax, "linewidth": 1, "alpha": alpha, "label": ""}

        # Forecast
        if dt == dates[-1]:
            plot_defs["label"] = "forecast"
        plot_defs["c"] = next(colours)
        fct = merged_df["intensity.forecast"].loc[dt].plot(**plot_defs)

        # Actual
        if dt == dates[-1]:
            plot_defs["label"] = "actual"
        plot_defs["c"] = next(colours)
        act = merged_df["intensity.actual"].loc[dt].plot(**plot_defs)

        # legend
        if dt == dates[-1]:
            ax.legend()

    plt.gca().invert_xaxis()
    ax.vlines(
        0.0,
        ax.get_ylim()[0],
        ax.get_ylim()[-1],
        color="k",
        linestyle="--",
        linewidth=0.5,
    )
    ax.set_xlabel("hours before forecasted window")
    ax.set_ylabel("carbon intensity")
    ax.set_title(
        f"Published CI values, {len(dates)} time windows {_ftime(dates[0])} - {_ftime(dates[-1])} UTC"
    )

    return fig


def generate_boxplot_ci(
    input_directory: str,
):
    """Generate boxplot of CI values.
    Boxplots for all of the forecasts for a list of given windows

    Also overlay the actual values.
    """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    dffw = load_forward_summary(input_directory)

    # We don't get "actual" intensity from the fw48h endpoint
    dffw = dffw.drop("intensity.actual", level=0, axis=1)

    # Use only forecasts for measuring prediction quality
    forecast_df = format_dataframe(dffw)

    dates = get_dates(forecast_df, HOURS_OF_DATA * 2)

    fig, ax = plt.subplots(1, 1)
    forecast_df["intensity.forecast"].loc[dates].T.boxplot(rot=90, sym="r.", ax=ax)
    ax.set_title(
        f"Carbon intensity forecast ranges, {len(dates)} half-hour windows {_ftime(dates[0])} - {_ftime(dates[-1])}"
    )
    ax.set_ylabel("carbon intensity")
    ax.grid("on", linestyle="--", alpha=0.33)

    return fig


def generate_boxplot_ci_error(
    input_directory: str,
):
    """Generate boxplot of CI error values.
    Boxplots for each of the forecasts for a list of given windows.

    Uses the final recorded 'actual' intensity from the merged summary data as the true 'actual' value.
    """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    summaries = load_summaries(input_directory)
    merged_df = pd.merge(*summaries, left_index=True, right_index=True, how="outer")
    merged_df = format_dataframe(merged_df)

    # Get the final (rightmost, assuming we have -24.0 as the rightmost) non-NaN value in each row
    merged_df["intensity.actual.final"] = (
        merged_df["intensity.actual"].ffill(axis=1).iloc[:, -1]
    )

    dates = get_dates(merged_df, HOURS_OF_DATA * 2)

    dff = merged_df.loc[dates][["intensity.forecast", "intensity.actual.final"]].copy()

    # Percentage error
    dfferr = 100.0 * (
        dff["intensity.forecast"].sub(dff["intensity.actual.final"], axis=0)
    ).div(dff["intensity.actual.final"], axis=0)

    # only pre-timepoint forecasts
    dfferr = dfferr[[c for c in dfferr.columns if float(c) >= 0.0]]

    fig, ax = plt.subplots(1, 1)
    dfferr.loc[dates].T.boxplot(rot=90, sym="r.")
    ax.set_title("Percentage forecast error from final recorded actual intensity")
    ax.set_ylabel("forecast % error")
    ax.grid("on", linestyle="--", alpha=0.33)

    return fig


def generate_boxplot_ci_error_for_days(input_directory: str):
    """Generate boxplot summaries for entire days.
    Combine all forecasts for each day; don't worry about the number of hours before the window they came from.
    """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    days = 7

    summaries = load_summaries(input_directory)
    merged_df = pd.merge(*summaries, left_index=True, right_index=True, how="outer")
    merged_df = format_dataframe(merged_df)

    # Get the final (rightmost, assuming we have -24.0 as the rightmost) non-NaN value in each row
    merged_df["intensity.actual.final"] = (
        merged_df["intensity.actual"].ffill(axis=1).iloc[:, -1]
    )

    # Get the earliest time from the day a week ago
    now = datetime.utcnow().astimezone(timezone.utc)
    dt = now - timedelta(days=days)
    dt = datetime(dt.year, dt.month, dt.day, 0, 0, 0).astimezone(timezone.utc)

    dff = merged_df.loc[dt:now][["intensity.forecast", "intensity.actual.final"]].copy()

    # Percentage err
    dfferr = 100.0 * (
        dff["intensity.forecast"].sub(dff["intensity.actual.final"], axis=0)
    ).div(dff["intensity.actual.final"], axis=0)
    # only pre-timepoint forecasts
    dfferr = dfferr[[c for c in dfferr.columns if float(c) >= 0.0]]

    # All days from then to now
    dff = dfferr.loc[dt:now].copy()
    dff.index = dff.index.date

    forecast_cols = dff.columns

    # Add a helper column to count occurrences of each label
    dff["count_per_day"] = dff.groupby(dff.index).cumcount()

    # pivot into a multiindex
    result = dff.pivot_table(
        index=dff.index,
        columns="count_per_day",
        values=list(forecast_cols),
        aggfunc="first",
    )

    # flatten
    result.columns = [f"{level1}_{level2+1}" for level1, level2 in result.columns]

    fig, ax = plt.subplots(1, 1)
    result.T.boxplot(sym="r.")
    ax.set_title(f"Percentage error from last {days} days' forecasts")
    ax.set_ylabel("forecast % error")
    ax.grid("on", linestyle="--", alpha=0.33)

    return fig


def create_graph_images(
    input_directory: str, output_directory: str = None, *args, **kwargs
) -> None:
    """Create graphs from summaries, and save.

    Args:
        input_directory (str): Directory containing summaries
        output_directory (str): Directory to save figures
    """

    fig = generate_plot_ci_lines(input_directory)
    save_figure(fig, output_directory or input_directory, "ci_lines.png")

    fig = generate_boxplot_ci(input_directory)
    save_figure(fig, output_directory or input_directory, "ci_boxplot.png")

    fig = generate_boxplot_ci_error(input_directory)
    save_figure(fig, output_directory or input_directory, "ci_error_boxplot.png")

    fig = generate_boxplot_ci_error_for_days(input_directory)
    save_figure(fig, output_directory or input_directory, "ci_error_boxplot_days.png")
