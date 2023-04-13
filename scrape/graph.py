# Show some graphs

import logging
import os
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
    num_plots: int,
    hours_offset: int = 72,
    start_date: datetime = None,
    start_days_offset: int = None,
    random_n: int = 0,
) -> list:
    """Get the dates to plot.
    By default the most recent available complete data is used. Note that "complete"
    data includes 'actual' figures, which are only complete 24 hours after a given
    timepoint.
    Note also that we forecast 48 hours into the future, so the most recent timepoint
    with complete data is 72 hours earlier than the latest timepoint in the data.

    Args:
        df (pd.DataFrame): dataframe with datetime index
        num_plots (int): number of plots to generate
        hours_offset (int): assume this many hours prior to the final timepoint in
            the data have incomplete 'actual' data. Defaults to 72.
        random_n (int): if > 0, return a sorted random sample of this size. Default is 0.

    Returns:
        list: list of datetimes
    """

    # Want to show N hours of data. The most recent timepoint for which all data is available
    # should be the latest - 24 hours.
    # The first timepoint will be now - 24 hours - N hours.

    if not num_plots:
        num_plots = int(HOURS_OF_DATA * 2)

    if start_date:
        return [d for d in df.index if d >= start_date][:num_plots]

    # The last timepoint with complete data
    latest_tp = df.index[-1] - timedelta(hours=hours_offset)

    # if start_days_offset:
    #     hours_prior = start_days_offset * 24
    # else:
    # The number of hours' data to show
    hours_prior = num_plots / 2

    # The earliest timepoint to return
    dt_pastpoint = latest_tp - timedelta(hours=hours_prior)

    if dt_pastpoint > df.index[-1]:
        raise ValueError("Not enough data to generate plots")

    # pick datetimes
    dates = [d for d in df.index if d >= dt_pastpoint][:num_plots]
    if random_n > 0:
        return sorted(np.random.choice(dates, size=random_n, replace=False))
    return dates


def get_dates_days(
    df: pd.DataFrame,
    num_days: int = 7,
    hours_offset: int = 72,
) -> list:
    """Get all dates within a given number of days from the last date with complete data.

    Args:
        df (pd.DataFrame): Summary dataframe with datetime index.
        num_days (int): The number of complete days' data to include. Defaults to 7.
        hours_offset (int, optional): assume this many hours prior to the final timepoint in
            the data have incomplete data. Defaults to 72.

    Returns:
        list: All timepoints to include.
    """

    # The last timepoint with complete data
    latest_tp = df.index[-1] - timedelta(hours=hours_offset)

    # The earliest timepoint to return
    dt_pastpoint = latest_tp - timedelta(days=num_days)

    # floor to the start of that day
    dt_pastpoint = dt_pastpoint.floor("D").astimezone(timezone.utc)

    if dt_pastpoint > df.index[-1]:
        raise ValueError("Not enough data to generate plots")

    # pick datetimes
    return [d for d in df.index if d >= dt_pastpoint and d <= latest_tp]


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
    hours_of_data: int = HOURS_OF_DATA,
    random_n: int = 0,
):
    """Generate plots from summaries."""

    dates = get_dates(df, hours_of_data * 2, random_n=random_n)

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
        fct = df["intensity.forecast"].loc[dt].plot(**plot_defs)

        # Actual
        if dt == dates[-1]:
            plot_defs["label"] = "actual"
        plot_defs["c"] = next(colours)
        act = df["intensity.actual"].loc[dt].plot(**plot_defs)

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
    ax.set_ylabel("carbon intensity, $gCO_2/kWh$")
    ax.set_title(f"{_ftime(dates[0])} - {_ftime(dates[-1])} UTC")
    fig.suptitle(
        f"Published national CI forecast values, {len(dates)} half-hour windows"
    )

    return fig


def generate_boxplot_ci(
    df: pd.DataFrame,
    hours_of_data: int = HOURS_OF_DATA,
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

    dates = get_dates(df, hours_of_data * 2)

    # reformat x-axis for display
    dff = df["intensity.forecast"].loc[dates]
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
        linewidth=0.5,
        label="actual",
    )

    ax.set_title(f"{_ftime(dates[0])} - {_ftime(dates[-1])} UTC")
    ax.set_ylabel("carbon intensity, $gCO_2/kWh$")
    ax.grid("on", linestyle="--", alpha=0.33)
    ax.legend()
    fig.suptitle(
        f"National carbon intensity forecast ranges, {len(dates)} half-hour windows"
    )
    # add_colourmap(ax, 2023)

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
    hours_of_data: int = HOURS_OF_DATA,
):
    """Generate boxplot of CI error values.
    Boxplots for each of the forecasts for a list of given windows.

    Uses the final recorded 'actual' intensity from the merged summary data as the true 'actual' value.
    """

    plt.rcParams["figure.figsize"] = [12, 6]
    plt.rcParams["figure.dpi"] = DPI

    dates = get_dates(df, hours_of_data * 2)
    df = df.loc[dates].copy()

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
    df = df.loc[get_dates_days(df, days)].copy()

    _, df_pc_err = _error_and_percentage_error(df)

    result = _aggregate_per_day(df_pc_err)

    fig, ax = plt.subplots(1, 1)
    _ = result.T.boxplot(sym="r.")
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
        df = df.loc[get_dates_days(df, days)].copy()

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


def _aggregate_per_day(df: pd.DataFrame) -> pd.DataFrame:
    """..."""
    df_err = df.copy()

    # Only pre-timepoint forecasts
    df_err = df_err[[c for c in df_err.columns if float(c) >= 0.0]]

    # Replace all index values by their date (day)
    df_err.index = df_err.index.date
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


def _get_stats_per_day(df: pd.DataFrame) -> pd.DataFrame:
    """Generate summary statistics for each day.
    Note that we should take the mean absolute error, as errors can be +/-.
    """
    result = _aggregate_per_day(df)

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

    # # splitting each ci column:
    # ci_95 = pd.DataFrame(
    #     stats["confidence_95"].to_list(),
    #     columns=["ci_95_lo", "ci_95_hi"],
    #     index=stats.index,
    # )
    # ci_99 = pd.DataFrame(
    #     stats["confidence_99"].to_list(),
    #     columns=["ci_99_lo", "ci_99_hi"],
    #     index=stats.index,
    # )
    # stats = pd.concat([stats, ci_95, ci_99], axis=1)

    return stats


def generate_stats_dataframes(
    df: pd.DataFrame, days: int = 7
) -> (pd.DataFrame, pd.DataFrame):
    # Get the earliest time from a given number of days ago
    df = df.loc[get_dates_days(df, days)]

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


def create_graph_images(
    input_directory: str,
    output_directory: str = "charts",
    hours_of_data: int = HOURS_OF_DATA,
    filter: str = "national",
    days: int = 7,
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

    fig = generate_plot_ci_lines(summaries_merged_df, hours_of_data)
    save_figure(fig, output_directory, filter + "_ci_lines.png")

    fig = generate_boxplot_ci(summaries_merged_df, hours_of_data)
    save_figure(fig, output_directory, filter + "_ci_boxplot.png")

    fig = generate_boxplot_ci_error(summaries_merged_df, hours_of_data)
    save_figure(fig, output_directory, filter + "_ci_error_boxplot.png")

    fig = generate_boxplot_ci_error_for_days(summaries_merged_df, days)
    save_figure(fig, output_directory, filter + "_ci_error_boxplot_days.png")

    fig = generate_boxplot_ci_error_per_hour(summaries_merged_df, days)
    save_figure(fig, output_directory, filter + "_ci_error_boxplot_per_hour.png")

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
