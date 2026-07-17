# Show some graphs

import logging
import os
from collections import defaultdict
from datetime import datetime
from itertools import cycle

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as st

from cift.analysis import HOURS_OF_DATA  # noqa: F401  (re-exported for legacy callers)
from cift.analysis import get_dates  # noqa: F401
from cift.colourmap import add_colourmap
from cift.investigation import distribution_parameters

log = logging.getLogger(__name__)

# TODO:
# check the merge of summaries doesn't require a known order
# How complete is the data?

DPI = 125

PLOT_DT_FORMAT = "%Y %b %-d %H:%M"


def save_figure(fig, output_directory, filename):
    fig.savefig(os.path.join(output_directory, filename), bbox_inches="tight", dpi=DPI)


# TODO: need another header row for regional data


def _ftime(dt):
    """Format datetimes for graphs."""
    return datetime.strftime(dt, PLOT_DT_FORMAT)


def fancy_xaxis_dateformats(df: pd.DataFrame) -> None:
    """Formats the input dataframe index for plotting.
    For each day, the first hour is shown as a full date, and the rest are shown as hours only.
    A fancier version of df.index = df.index.strftime(PLOT_DT_FORMAT)
    """

    def _special_fmt(dt):
        # if it's the 1st of the month, print %Y-%m-%d %H:%M
        if dt.day == 1:
            return _ftime(dt)
        if dt.hour == 0 and dt.minute == 0:
            return datetime.strftime(dt, "%b %-d %H:%M")
        return datetime.strftime(dt, "%H:%M")

    for ix, dt in enumerate(df.index):
        if ix == 0:
            df.rename(index={dt: _ftime(dt)}, inplace=True)
            continue
        df.rename(index={dt: _special_fmt(dt)}, inplace=True)


def confidence_interval(data, level=0.99, decimals=2):
    # Pandas would remove NaNs for us but not NumPy!
    data = data[~np.isnan(data)]
    if len(data) < 2:
        return (np.nan, np.nan)
    m = np.mean(data)
    sem = st.sem(data)
    dof = int(len(data) - 1)
    result = st.t.interval(confidence=level, df=dof, loc=m, scale=sem)
    return tuple([np.round(i, decimals=decimals) for i in result])


def confidence_95(data):
    return confidence_interval(data, 0.95, 2)


def confidence_99(data):
    return confidence_interval(data, 0.99, 2)


def generate_plot_ci_lines(
    df: pd.DataFrame,
    dates: list,
    separate_subplots: bool = False,
):
    """Generate plots from summaries."""

    height = 1 + 2 * len(dates) if separate_subplots else 6
    plt.rcParams["figure.figsize"] = [12, height]
    plt.rcParams["figure.dpi"] = DPI

    if separate_subplots:
        fig, axes = plt.subplots(
            len(dates), 1, sharex=True, sharey="col", constrained_layout=True
        )
        axes = np.ravel(axes)
    else:
        fig, ax = plt.subplots(1, 1)

    # Don't start opacity from 0
    alphas = (
        iter([1] * len(dates))
        if (separate_subplots or len(dates) == 1)
        else iter(np.linspace(0.1, 1, len(dates)))
    )
    colours = cycle(["tab:blue", "tab:orange"])

    for ix, dt in enumerate(dates):
        if separate_subplots:
            ax = axes[ix]

        alpha = next(alphas)

        # set label to empty string unless it is the last iteration
        plot_defs = {"ax": ax, "linewidth": 1, "alpha": alpha, "label": ""}

        # Forecast
        if dt == dates[-1]:
            plot_defs["label"] = "forecast"
        plot_defs["c"] = next(colours)
        df["intensity.forecast"].loc[dt].plot(**plot_defs)

        # Actual
        if dt == dates[-1]:
            plot_defs["label"] = "actual"
        plot_defs["c"] = next(colours)
        df["intensity.actual"].loc[dt].plot(**plot_defs)

        ax.set(xlabel=None)

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
    if len(dates) > 1:
        ax.set_title(f"{_ftime(dates[0])} - {_ftime(dates[-1])} UTC")
    else:
        ax.set_title(f"{_ftime(dates[0])} UTC")
    fig.supylabel("carbon intensity, $gCO_2/kWh$")
    fig.supxlabel("hours before forecasted window")
    fig.suptitle(
        f"Published national CI forecast values, {len(dates)} half-hour windows"
    )

    return fig


def generate_boxplot_ci(
    df: pd.DataFrame,
    dates: list,
    colourmap: bool = False,
    boundaries=None,
):
    """Generate boxplot of CI values.
    Boxplots for all of the forecasts for a list of given windows

    Also overlay the actual values.
    """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    # We don't get "actual" intensity from the fw48h endpoint
    # Use only forecasts for measuring prediction quality
    df = df.drop("intensity.actual", level=0, axis=1)

    # reformat x-axis for display
    dff = df["intensity.forecast"].copy()
    fancy_xaxis_dateformats(dff)

    fig, ax = plt.subplots(1, 1)
    _ = dff.T.boxplot(rot=90, sym="r.", ax=ax)

    # Boxplots have weird positioning so we can't plot a line directly over them using the same axes; instead use this hackery.
    x_locs = ax.get_xticks()
    ax.plot(
        x_locs,
        df["intensity.actual.final"].loc[dates],
        "tab:orange",
        linestyle="-",
        linewidth=1.0,
        label="actual",
    )

    ax.set_title(f"{_ftime(dates[0])} - {_ftime(dates[-1])} UTC")
    ax.set_ylabel("carbon intensity, $gCO_2/kWh$")
    ax.grid("on", linestyle="--", alpha=0.33)
    ax.legend()
    fig.suptitle(
        f"National carbon intensity forecast ranges, {len(dates)} half-hour windows"
    )
    if colourmap:
        add_colourmap(ax, dates[0].year, boundaries=boundaries)
    return fig


def _error_and_percentage_error(df: pd.DataFrame) -> (pd.DataFrame, pd.DataFrame):
    dff = df[["intensity.forecast", "intensity.actual.final"]]

    # Error
    df_err = dff["intensity.forecast"].sub(dff["intensity.actual.final"], axis=0)

    # Percentage error
    df_pc_err = 100.0 * df_err.div(dff["intensity.actual.final"], axis=0)

    # Only pre-timepoint forecasts (exclude post-hoc)
    df_err = df_err[[c for c in df_err.columns if float(c) >= 0.0]]
    df_pc_err = df_pc_err[[c for c in df_pc_err.columns if float(c) >= 0.0]]

    return df_err, df_pc_err


def generate_boxplot_ci_error(
    df: pd.DataFrame,
    dates: list,
):
    """Generate boxplot of CI error values.
    Boxplots for each of the forecasts for a list of given windows.

    Uses the final recorded 'actual' intensity from the merged summary data as the true 'actual' value.
    """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    _, df_pc_err = _error_and_percentage_error(df)

    # reformat x-axis for display
    df = df_pc_err.loc[dates]
    fancy_xaxis_dateformats(df)

    fig, ax = plt.subplots(1, 1)
    _ = df.T.boxplot(rot=90, sym="r.")
    ax.set_title(f"{_ftime(dates[0])} - {_ftime(dates[-1])} UTC")
    ax.set_ylabel("forecast % error")
    ax.grid("on", linestyle="--", alpha=0.33)
    ax.hlines(
        0.0,
        ax.get_xlim()[0],
        ax.get_xlim()[-1],
        color="k",
        linestyle="--",
        linewidth=0.5,
    )

    fig.suptitle(f"Percentage national forecast error, {len(dates)} half-hour windows")

    return fig


def _aggregate_per(df: pd.DataFrame, aggregate_by: str = "date") -> pd.DataFrame:
    """Aggregate a datagrame by date groupings (year, month, day)"""

    def index_by_dates(df: pd.DataFrame, aggregate_by: str):
        if aggregate_by == "date" or aggregate_by == "day":
            return df.index.date
        elif aggregate_by == "month":
            return df.index.month
        elif aggregate_by == "year":
            return df.index.year
        else:
            raise ValueError("aggregate_by must be one of 'date', 'month', 'year'")

    df_err = df.copy()

    # Replace all index values by their date (day) or aggregation grouping
    df_err.index = index_by_dates(df_err, aggregate_by)
    forecast_cols = df_err.columns

    # Add a helper column to count occurrences of each label
    df_err[f"count_per_{aggregate_by}"] = df_err.groupby(df_err.index).cumcount()

    # pivot into a multiindex
    result = df_err.pivot_table(
        index=df_err.index,
        columns=f"count_per_{aggregate_by}",
        values=list(forecast_cols),
        aggfunc="first",
    )

    # flatten
    result.columns = [f"{level1}_{level2+1}" for level1, level2 in result.columns]
    return result


def generate_boxplot_ci_error_for_days(
    df: pd.DataFrame,
    days: int = 7,
):
    """Generate boxplot summaries for entire days.
    Combine all forecasts for each day; don't worry about the number of hours before the window they came from.
    """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    # Get the earliest time from a given number of days ago
    # All days from then to now
    df = df.loc[get_dates(df, num_days=days)].copy()

    _, df_pc_err = _error_and_percentage_error(df)

    result = _aggregate_per(df_pc_err, "date")

    fig, ax = plt.subplots(1, 1)
    _ = result.T.boxplot(
        sym="r.",
        rot=90,
    )
    ax.set_title(f"Percentage forecast error, all time windows, past {days+1} days")
    ax.set_ylabel("forecast % error")
    ax.grid("on", linestyle="--", alpha=0.33)
    ax.hlines(
        0.0,
        ax.get_xlim()[0],
        ax.get_xlim()[-1],
        color="k",
        linestyle="--",
        linewidth=0.5,
    )

    return fig


def generate_boxplot_ci_error_per_hour(
    df: pd.DataFrame,
    days: int = 7,
):
    """Generate boxplots of the percentage forecast error per hour prior to the window,
    using data from the past days.

    Args:
        input_directory (str): Directory containing summary CSVs.
        days (int, optional): Number of past days' data to include. Defaults to None, for all available data.
    """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    if days:
        # Get the earliest time from a given number of days ago
        df = df.loc[get_dates(df, num_days=days)].copy()

    _, df_pc_err = _error_and_percentage_error(df)

    dates = df_pc_err.index

    fig, ax = plt.subplots(1, 1)
    _ = df_pc_err.boxplot(rot=90, sym="r.")
    ax.set_title(f"{_ftime(dates[0])} - {_ftime(dates[-1])} UTC")
    ax.set_ylabel("forecast % error")
    ax.grid("on", linestyle="--", alpha=0.33)
    ax.hlines(
        0.0,
        ax.get_xlim()[0],
        ax.get_xlim()[-1],
        color="k",
        linestyle="--",
        linewidth=0.5,
    )

    fig.suptitle("Percentage forecast error per half-hour before forecasted window")

    return fig


def generate_ci_error_relationship(
    df: pd.DataFrame,
):
    """Generate a scatter plot of CI error versus actual recorded intensity.

    Includes all data.

    Returns the figure and Pearson's r."""

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    df_err, _ = _error_and_percentage_error(df)

    # Need to re-add the actual intensity column
    x_col_name = "intensity.actual.final"

    df_actual = df[[x_col_name]]
    cols = df_actual.columns
    df_actual.columns = cols.droplevel(1)
    data = pd.concat([df_actual, df_err], axis=1)

    marker_properties_raw_data = {
        "color": "tab:blue",
        "marker": "o",
        "s": 0.5,  # size
    }

    # Set up means
    data_dict = defaultdict(list)

    # Gather all the data from the other columns for each key
    for _ix, row in data.iterrows():
        key = row[x_col_name]
        data_dict[key].append(row[1:].mean())

    # Calculate the overall mean for each key
    mean_dict = {key: np.mean(values) for key, values in data_dict.items()}

    # Plot both raw data and means

    fig, ax = plt.subplots()
    for column in data.columns[1:]:
        ax.scatter(data[x_col_name], data[column], **marker_properties_raw_data)

    ax.scatter(
        list(mean_dict.keys()), list(mean_dict.values()), color="tab:red", label="mean"
    )

    ax.hlines(
        0.0,
        ax.get_xlim()[0],
        ax.get_xlim()[-1],
        color="k",
        linestyle="--",
        linewidth=0.5,
    )
    ax.set_title("Forecast error compared with the final actual intensity")
    ax.legend()
    ax.set_xlabel("final actual intensity")
    ax.set_ylabel("forecast errors")

    melted = data.melt(id_vars=[x_col_name], value_name="error").dropna(
        subset=["error"]
    )
    pearson_r = melted[x_col_name].corr(melted["error"])
    ax.text(
        10.0,
        0.95,
        f"$r={pearson_r.round(3)}$",
        horizontalalignment="left",
        verticalalignment="top",
        # This transform uses x:data and y:axes
        transform=ax.get_xaxis_transform(),
    )

    return fig, pearson_r


def _get_colour_iter():
    return iter(("tab:orange", "tab:green", "tab:purple"))


def generate_distribution_plots(
    data,
    x_label: str,
    hist_label: str,
    n_bins: int = 0,
    density: bool = True,
    x_min: int = -100,
    x_max: int = 100,
    lookup_extreme_values: list | None = None,
):
    """ """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    if not n_bins:
        # Because the errors are integers, the histogram here can be ugly, with random gaps.
        # Using this helpful answer to fix that: https://stackoverflow.com/a/30121210/3329384
        # Where 1 is the smallest difference in the data
        left_of_first_bin = data.min() - 1.0 / 2
        right_of_last_bin = data.max() + 1.0 / 2
        n_bins = len(np.arange(left_of_first_bin, right_of_last_bin + 1, 1)) - 1

    x, distn_results, cdf_results, df_extreme_prob = distribution_parameters(
        data,
        n_bins,
        density,
        lookup_extreme_values or [],
    )

    fig, axes = plt.subplots(1, 2)
    ax = axes[0]
    ax.hist(data, bins=n_bins, density=density, alpha=0.6, label=hist_label)

    colours = _get_colour_iter()
    for k, v in distn_results.items():
        ax.plot(x, v, label=k, lw=2, c=next(colours))

    ax.legend()
    ax.set_title("frequency distribution")
    ax.grid("on", linestyle="--", alpha=0.33)
    ax.set_xlim(x_min, x_max)
    ylims = ax.get_ylim()
    ax.vlines(
        0.0,
        ylims[0],
        ylims[-1],
        color="k",
        linestyle="--",
        linewidth=0.5,
    )

    # Plot the CDFs to read off probabilities of extreme values
    ax = axes[1]

    # reset iter
    colours = _get_colour_iter()
    for k, v in cdf_results.items():
        ax.plot(x, v, label=k + " CDF", lw=2, c=next(colours))

    ax.set_title("cumulative probability")
    ax.legend()
    ax.grid("on", linestyle="--", alpha=0.33)
    ax.set_xlim(x_min, x_max)
    fig.supxlabel(x_label)

    return fig, df_extreme_prob
