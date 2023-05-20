# Show some graphs

import logging
import os
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from itertools import cycle

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as st

from scrape.colourmap import add_colourmap
from scrape.files import get_data_files
from scrape.investigation import distribution_parameters

log = logging.getLogger(__name__)

# TODO:
# check the merge of summaries doesn't require a known order
# How complete is the data?

DPI = 250

HOURS_OF_DATA = 24

NOW = datetime.now(tz=timezone.utc)

PLOT_DT_FORMAT = "%Y %b %-d %H:%M"


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


# TODO: need another header row for regional data
def load_summaries(directory: str, filter: str = "") -> list:
    files = get_data_files(directory, extension=".csv", filter=filter)
    return [pd.read_csv(f, index_col=0, header=[0, 1]) for f in files]


def load_merge_summaries(
    directory: str, filter: str = "summary_national"
) -> pd.DataFrame:
    summaries = load_summaries(directory, filter=filter)
    merged_df = pd.merge(*summaries, left_index=True, right_index=True, how="outer")
    return format_dataframe(merged_df)


def _load_forward_summary(directory: str) -> pd.DataFrame:
    files = get_data_files(directory, extension=".csv", filter="summary_national_fw48h")
    return pd.read_csv(files[0], index_col=0, header=[0, 1])


def _load_past_summary(directory: str) -> pd.DataFrame:
    files = get_data_files(directory, extension=".csv", filter="summary_national_pt24h")
    return pd.read_csv(files[0], index_col=0, header=[0, 1])


def get_merged_summaries_with_final_actual_intensities(
    directory: str, filter: str = "national"
) -> pd.DataFrame:
    merged_df = load_merge_summaries(directory, filter="summary_" + filter)

    # Get the final (rightmost, assuming we have -24.0 as the rightmost) non-NaN value in each row
    merged_df["intensity.actual.final"] = (
        merged_df["intensity.actual"].ffill(axis=1).iloc[:, -1]
    )
    return merged_df


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


def get_dates(
    df: pd.DataFrame,
    start_date: datetime = None,
    num_timepoints: int = None,
    num_hours: float = None,
    num_days: int = None,
    incomplete_hours_offset: int = 72,
    random_n: int = 0,
) -> list:
    """Get the dates to plot.
    By default the most recent available complete data is used. Note that "complete"
    data includes 'actual' figures, which are only complete 24 hours after a given
    timepoint.
    Note also that we forecast 48 hours into the future, so the most recent timepoint
    with complete data is 72 hours earlier than the latest timepoint in the data.

    If start date isn't specified, we return the latest complete num_timepoints timepoints,
    based on the number of hours or days requested.

    Args:
        df (pd.DataFrame): dataframe with datetime index
        num_timepoints (int): number of plots to generate
        num_days (int): number of complete days' data to return. Optional. If set, overrides
            num_timepoints.
        incomplete_hours_offset (int): assume this many hours prior to the final timepoint in
            the data have incomplete 'actual' data. Defaults to 72.
        random_n (int): if > 0, return a sorted random sample of this size. Default is 0.

    Returns:
        list: list of datetimes
    """

    # Want to show N hours of data. The most recent timepoint for which all data is available
    # should be the latest - 24 hours.
    # The first timepoint will be now - 24 hours - N hours.

    if num_days:
        num_hours = num_days * 24
    if num_hours:
        num_timepoints = int(num_hours * 2)
    if not num_timepoints:
        num_timepoints = HOURS_OF_DATA * 2

    if start_date:
        return [d for d in df.index if d >= start_date][:num_timepoints]

    # The last timepoint with complete data
    latest_tp = df.index[-1] - timedelta(hours=incomplete_hours_offset)

    # The earliest timepoint to return
    if num_days:
        dt_earliest = latest_tp - timedelta(days=num_days)
    else:
        # The number of hours' data to show
        hours_prior = num_timepoints / 2
        dt_earliest = latest_tp - timedelta(hours=hours_prior)

    if dt_earliest > df.index[-1]:
        raise ValueError("Not enough data to generate plots")

    # pick datetimes
    dates = [d for d in df.index if d >= dt_earliest and d <= latest_tp][
        :num_timepoints
    ]
    if random_n > 0:
        return sorted(np.random.choice(dates, size=random_n, replace=False))
    return dates


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
        fct = df["intensity.forecast"].loc[dt].plot(**plot_defs)

        # Actual
        if dt == dates[-1]:
            plot_defs["label"] = "actual"
        plot_defs["c"] = next(colours)
        act = df["intensity.actual"].loc[dt].plot(**plot_defs)

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


def generate_plots_ci_lines_with_boxplots(
    df: pd.DataFrame,
    dates: list,
):
    """Generate plots from summaries."""

    height = 1 + 2 * len(dates)
    plt.rcParams["figure.figsize"] = [12, height]
    plt.rcParams["figure.dpi"] = DPI

    width_cols = 6
    fig, axes = plt.subplots(
        len(dates),
        2,
        sharex="col",
        sharey=True,
        constrained_layout=True,
        gridspec_kw={"width_ratios": [width_cols - 1, 1]},
    )
    # axes = np.ravel(axes)

    colours = cycle(["tab:blue", "tab:orange"])

    ylims = (0, 0)
    for ix, ax in enumerate(fig.axes):
        dt = dates[ix // 2]

        if ix % 2 == 0:
            # Line plot in left column
            # for ix, dt in enumerate(dates):
            #     ax = axes[ix]

            # all but the last column if we have a boxplot
            # ax = fig.add_subplot(gs[ix, :-1])

            # set label to empty string unless it is the last iteration
            plot_defs = {"ax": ax, "linewidth": 1, "alpha": 1.0, "label": ""}

            # Forecast
            if ix == 0:
                plot_defs["label"] = "forecast"
            plot_defs["c"] = next(colours)
            fct = df["intensity.forecast"].loc[dt].plot(**plot_defs)

            # Actual
            if ix == 0:
                plot_defs["label"] = "actual"
            plot_defs["c"] = next(colours)
            act = df["intensity.actual"].loc[dt].plot(**plot_defs)

            ax.text(
                0.0,
                0.95,
                _ftime(dt) + " UTC ",
                horizontalalignment="right",
                verticalalignment="top",
                # This transform uses x:data and y: axes
                transform=ax.get_xaxis_transform(),
            )

            if ix == 0:
                ax.legend()
                ymin, ymax = ax.get_ylim()
            else:
                if ax.get_ylim()[0] < ymin:
                    ymin = ax.get_ylim()[0]
                if ax.get_ylim()[1] > ymax:
                    ymax = ax.get_ylim()[1]

            continue

        # Boxplot in right column
        bxp = pd.DataFrame(df[["intensity.forecast"]].loc[dt]).boxplot(
            rot=90, sym="r.", ax=ax
        )
        ax.xaxis.set_ticklabels([])

    # plt.gca().invert_xaxis()
    for ix, ax in enumerate(fig.axes):
        ax.set(xlabel=None)
        ax.grid("on", linestyle="--", alpha=0.33)
        if ix % 2 != 0:
            continue
        ax.vlines(
            0.0,
            ymin,
            ymax,
            color="k",
            linestyle="--",
            linewidth=0.5,
        )

    # select the last line-plot axis
    fig.axes[-2].invert_xaxis()
    fig.axes[-2].set_xlabel("hours before forecasted window")
    fig.axes[-1].set_xlabel("forecast range")

    # if len(dates) > 1:
    #     fig.axes[0].set_title(f"{_ftime(dates[0])} - {_ftime(dates[-1])} UTC")
    # else:
    #     fig.axes[0].set_title(f"{_ftime(dates[0])} UTC")
    fig.supylabel("carbon intensity, $gCO_2/kWh$")
    # fig.supxlabel("hours before forecasted window")
    fig.suptitle(
        f"Published national CI forecast values, {len(dates)} half-hour windows"
    )

    return fig


def generate_boxplot_ci(
    df: pd.DataFrame,
    dates: list,
    colourmap: bool = False,
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
        add_colourmap(ax, dates[0].year)
    return fig


# def generate_boxplot_ci_future(
#     input_directory: str, hours_of_data: int = HOURS_OF_DATA
# ):
#     """Generate boxplot of future CI forecasts. This data will be less complete than the past data."""

#     plt.rcParams["figure.figsize"] = [12, 6]
#     plt.rcParams["figure.dpi"] = DPI

#     df = _load_forward_summary(input_directory)


def _error_and_percentage_error(df: pd.DataFrame) -> (pd.DataFrame, pd.DataFrame):
    dff = df[["intensity.forecast", "intensity.actual.final"]]

    # Error
    df_err = dff["intensity.forecast"].sub(dff["intensity.actual.final"], axis=0)

    # Percentage error
    df_pc_err = 100.0 * df_err.div(dff["intensity.actual.final"], axis=0)

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

    # only pre-timepoint forecasts
    df_pc_err = df_pc_err[[c for c in df_pc_err.columns if float(c) >= 0.0]]

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

    # only pre-timepoint forecasts
    dfferr = df_pc_err[[c for c in df_pc_err.columns if float(c) >= 0.0]]

    dates = dfferr.index

    fig, ax = plt.subplots(1, 1)
    _ = dfferr.boxplot(rot=90, sym="r.")
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


# def generate_text_boxes(df: pd.DataFrame, hours_of_data: int = 24):
#     """ """
#     plt.rcParams["figure.figsize"] = [9, 3]
#     plt.rcParams["figure.dpi"] = DPI

#     fig, axs = plt.subplots(nrows=1, ncols=3, squeeze=0)
#     for ax in axs.reshape(-1):
#         ax.text(2, 6, r'an equation: $E=mc^2$', fontsize=15)


def _aggregate_per(df: pd.DataFrame, aggregate_by: str = "date") -> pd.DataFrame:
    """..."""

    def group_by_dates(df: pd.DataFrame, aggregate_by: str):
        if aggregate_by == "date" or aggregate_by == "day":
            return df.index.date
        elif aggregate_by == "month":
            return df.index.month
        elif aggregate_by == "year":
            return df.index.year
        else:
            raise ValueError(f"aggregate_by must be one of 'date', 'month', 'year'")

    df_err = df.copy()

    # Only pre-timepoint forecasts
    df_err = df_err[[c for c in df_err.columns if float(c) >= 0.0]]

    # Replace all index values by their date (day)
    df_err.index = group_by_dates(df_err, aggregate_by)
    forecast_cols = df_err.columns

    # Add a helper column to count occurrences of each label
    df_err["count_per_day"] = df_err.groupby(df_err.index).cumcount()

    # pivot into a multiindex
    result = df_err.pivot_table(
        index=df_err.index,
        columns="count_per_day",
        values=list(forecast_cols),
        aggfunc="first",
    )

    # flatten
    result.columns = [f"{level1}_{level2+1}" for level1, level2 in result.columns]
    return result


def _get_stats_per_day(df: pd.DataFrame, split_ci: bool = False) -> pd.DataFrame:
    """Generate summary statistics for each day.
    Note that we should take the mean absolute error, as errors can be +/-.
    """
    result = _aggregate_per(df, "date")

    # Get the absolute error values
    result = result.abs()

    stats = result.T.agg(
        ["count", "mean", "std", "sem", confidence_95, confidence_99], axis=0
    ).T

    stats_rounded = stats[["mean", "std", "sem"]].astype("float").round(2)
    stats = pd.concat(
        [stats[["count"]], stats_rounded, stats[["confidence_95", "confidence_99"]]],
        axis=1,
    ).astype(str)

    stats = stats.rename(
        columns={
            "confidence_95": "95% confidence interval",
            "confidence_99": "99% confidence interval",
        }
    )

    if not split_ci:
        return stats

    # splitting each ci column:
    ci_95 = pd.DataFrame(
        stats["confidence_95"].to_list(),
        columns=["ci_95_lo", "ci_95_hi"],
        index=stats.index,
    )
    ci_99 = pd.DataFrame(
        stats["confidence_99"].to_list(),
        columns=["ci_99_lo", "ci_99_hi"],
        index=stats.index,
    )
    return pd.concat([stats, ci_95, ci_99], axis=1)


def generate_stats_dataframes(
    df: pd.DataFrame, days: int = 7
) -> (pd.DataFrame, pd.DataFrame):
    # Get the earliest time from a given number of days ago
    df = df.loc[get_dates(df, num_days=days)]

    df_err, df_pc_err = _error_and_percentage_error(df)

    stats = _get_stats_per_day(df_err)
    stats_pc = _get_stats_per_day(df_pc_err)

    # Drop some columns to clean up.
    # Standard deviation on these absolute errors is not that helpful.
    stats_corr = stats.drop(columns=["std", "99% confidence interval"])
    stats_pc_corr = stats_pc.drop(columns=["count", "std", "99% confidence interval"])

    # label indices (but this is the title)
    # stats_corr.index.name = "error, gCO_2/kWh"
    # stats_pc_corr.index.name = "error, %"
    return stats_corr, stats_pc_corr


def generate_combined_stats_dataframe(df: pd.DataFrame, days: int = 7) -> pd.DataFrame:
    stats_corr, stats_pc_corr = generate_stats_dataframes(df, days)
    # group into a dict so we can concat into a multi-level dataframe
    d = {
        "forecast": stats_corr["count"],
        "absolute error, gCO2/kWh": stats_corr.drop(columns=["count"]),
        "percentage absolute error": stats_pc_corr,
    }
    combined = pd.concat(d.values(), axis=1, keys=d.keys())
    combined.index = combined.index.astype("str")
    return combined


def generate_markdown_table(df: pd.DataFrame, days: int = 7) -> (str, str):
    stats_corr, stats_pc_corr = generate_stats_dataframes(df, days)
    return stats_corr.to_markdown(), stats_pc_corr.to_markdown()


def replace_markdown_section(
    filepath: str, section: str, text: str, pad_before="\n\n", pad_after="\n\n"
) -> None:
    """Replace a section in a markdown file with new text.

    Args:
        filepath (str): Path to markdown file
        section (str): Section header to replace
        text (str): Text to replace section with
    """
    with open(filepath, "r") as f:
        lines = f.readlines()

    # Find the start and end of the section
    start = 0
    end = start
    for i, line in enumerate(lines):
        if line.startswith(section):
            start = i
            end = i
            continue
        if line.startswith("#") and start > 0:
            end = i
            break

    # Replace the section
    before = lines[:start]
    after = lines[end:]

    new_section = section + pad_before + text + pad_after

    result = before + [new_section] + after

    with open(filepath, "w") as f:
        f.writelines(result)


def update_stats_history(
    input_directory: str, df: pd.DataFrame, name: str = "national"
) -> None:
    """Create or update an existing CSV with statistics."""

    filename = "stats_history_{}.csv".format(name)
    filepath = os.path.join(input_directory, filename)
    if os.path.exists(filepath):
        df_stats = pd.read_csv(filepath, header=[0, 1], index_col=0)
        log.info("Read existing history file: {}".format(filepath))
    else:
        df_stats = pd.DataFrame()

    union_index = df_stats.index.union(df.index)
    if df_stats.empty:
        df_stats = df.reindex(union_index)
    else:
        df_stats = df_stats.reindex(union_index)
        # Overwrite any existing stats
        df_stats.update(df, overwrite=True)

    df_stats.to_csv(filepath, index=True)
    log.info("Saved stats history to: {}".format(filepath))


def generate_ci_error_relationship(
    df: pd.DataFrame,
):
    """Generate a scatter plot of CI error versus actual recorded intensity.

    Includes all data.

    Returns the figure and Pearson's r."""

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    df_err, _ = _error_and_percentage_error(df)

    # only pre-timepoint forecasts
    df_err = df_err[[c for c in df_err.columns if float(c) >= 0.0]]

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
    for ix, row in data.iterrows():
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

    pearson_r = data[x_col_name].corr(data[column])
    return fig, pearson_r


def _get_colour_iter():
    return iter(("tab:orange", "tab:green", "tab:purple"))


def generate_distribution_plots(
    data,
    x_label: str,
    hist_label: str,
    n_bins: int = 100,
    density: bool = True,
    x_min: int = -100,
    x_max: int = 100,
    lookup_extreme_values: list = [],
):
    """ """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    x, distn_results, cdf_results, df_extreme_prob = distribution_parameters(
        data,
        n_bins,
        density,
        lookup_extreme_values,
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


def create_graph_images(
    input_directory: str,
    output_directory: str = "charts",
    hours_of_data: int = HOURS_OF_DATA,
    filter: str = "national",
    days: int = 7,
    start_date: datetime = None,
    random_n: int = 0,
    *args,
    **kwargs,
) -> None:
    """Create graphs from summaries, and save.

    Args:
        input_directory (str): Directory containing summaries
        output_directory (str): Directory to save figures
    """

    output_directory = output_directory or input_directory

    summaries_merged_df = get_merged_summaries_with_final_actual_intensities(
        input_directory, filter=filter.split("_")[0]
    )
    dates = get_dates(
        summaries_merged_df,
        num_hours=hours_of_data,
        start_date=start_date,
        random_n=random_n,
    )
    df = summaries_merged_df.loc[dates].copy()

    fig = generate_plot_ci_lines(df, dates=dates)
    save_figure(fig, output_directory, filter + "_ci_lines.png")

    fig = generate_boxplot_ci(df, dates=dates, colourmap=True)
    save_figure(fig, output_directory, filter + "_ci_boxplot.png")

    fig = generate_boxplot_ci_error(df, dates=dates)
    save_figure(fig, output_directory, filter + "_ci_error_boxplot.png")

    # Boxplots summarising days at a time
    # dates = get_dates(
    #     summaries_merged_df,
    #     num_hours=24 * days,
    #     start_date=start_date,
    # )

    fig = generate_boxplot_ci_error_for_days(summaries_merged_df, days)
    save_figure(fig, output_directory, filter + "_ci_error_boxplot_days.png")

    fig = generate_boxplot_ci_error_per_hour(summaries_merged_df, days)
    save_figure(fig, output_directory, filter + "_ci_error_boxplot_per_hour.png")

    fig, pearson_r = generate_ci_error_relationship(summaries_merged_df)
    save_figure(fig, output_directory, filter + "_ci_vs_error_scatter_relationship.png")

    # fig = generate_text_boxes(summaries_merged_df, hours_of_data)
    # save_figure(fig, output_directory, "text_boxes.png")

    # TODO: avoid all this repetition
    md_stats, md_stats_pc = generate_markdown_table(summaries_merged_df, days=days)
    readme_filepath = os.path.join(os.path.abspath("."), "README.md")
    replace_markdown_section(readme_filepath, "#### Absolute error, gCO2/kWh", md_stats)
    replace_markdown_section(
        readme_filepath, "#### Absolute percentage error", md_stats_pc
    )

    # Save stats to a single combined CSV
    stats_combined_df = generate_combined_stats_dataframe(
        summaries_merged_df, days=days
    )
    update_stats_history(output_directory, stats_combined_df, name=filter)
