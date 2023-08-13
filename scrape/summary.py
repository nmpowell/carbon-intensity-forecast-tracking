# TODO: use jsonschema to validate the structure

"""
Functions to extract data from JSON files and save in separate .CSV files.

One .CSV file for each of the regions.
"""

import logging
import os
from datetime import datetime
from datetime import timezone

import pandas as pd

from scrape.api import DATETIME_FMT_STR
from scrape.api import EARLIEST_DATE_STR
from scrape.download import round_down_datetime
from scrape.files import check_create_directory
from scrape.files import get_data_files
from scrape.files import move_to_subdirectory

log = logging.getLogger(__name__)


SUMMARY_FORMATS = {
    "national": {
        "columns": ["time_difference"],
        "values": ["intensity.forecast", "intensity.actual"],
        "header_rows": [0, 1],
    },
    "regional": {
        "columns": ["regions.regionid", "time_difference"],
        "values": [
            "regions.intensity.forecast",
            "biomass",
            "coal",
            "gas",
            "hydro",
            "imports",
            "nuclear",
            "other",
            "solar",
            "wind",
        ],
        "header_rows": [0, 1, 2],
    },
}


def datetime_from_filepath(filepath: str) -> str:
    name, _ = os.path.splitext(os.path.basename(filepath))
    dt = datetime.strptime(name, DATETIME_FMT_STR.replace(":", "")).replace(
        tzinfo=timezone.utc
    )
    return dt


def _calculate_time_difference(datetime_str: str, dt2: datetime) -> str:
    """Calculate the time difference between two datetimes, the first represented as a string.
    Returns the timedelta.
    """
    dt = datetime.strptime(datetime_str, DATETIME_FMT_STR).replace(tzinfo=timezone.utc)
    return dt - dt2


def get_hours_between(datetime_str: str, dt2: datetime) -> float:
    """Calculate the time difference between two datetimes, the first represented as a string.
    Returns the timedelta in hours.
    """
    return _calculate_time_difference(datetime_str, dt2).total_seconds() / 3600


def _update_summary_dataframe(summary: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Add the new data to the summary dataframe, combine indices, and return the updated summary."""

    # .update is reasonably fast and overwrites NaNs as we want. Columns will be identical.
    # It doesn't appear to require identical indices, but it requires the index of df1 to be exhaustive i.e. includes all the indices in df2 (a superset); df2 must be a subset of df1, or values will be lost from df2.
    # Don't want to overwrite and accidentally lose data.

    union_index = summary.index.union(df.index)
    if summary.empty:
        summary = df.reindex(union_index)
    else:
        summary = summary.reindex(union_index)
        summary.update(df)
    return summary


def get_summary_filepath(directory: str, name: str) -> str:
    """Get the filepath for the summary file."""
    summary_directory = check_create_directory(os.path.normpath(directory))

    # get existing summary, or start from scratch
    summary_name = "summary_{}.csv".format(name)
    return os.path.join(summary_directory, summary_name)


def load_summary(filepath: str, format: str) -> pd.DataFrame:
    if os.path.exists(filepath):
        summary = pd.read_csv(
            filepath,
            header=SUMMARY_FORMATS[format].get("header_rows"),
            index_col=0,
        )
        log.info("Read existing summary file: {}".format(filepath))
    else:
        summary = pd.DataFrame()
    return summary


# Read CSVs and collate into a forecast summary
def run_summary(
    input_directory: str,
    output_directory: str = None,
    endpoint: str = "regional_fw48h",
    start_date: str = EARLIEST_DATE_STR,
    end_date: str = None,
    num_files: int = 0,
    delete_old_files: bool = False,
    *args,
    **kwargs,
) -> None:
    """Read CSVs from input_directory. Collate forecasts per-region and per-fuel.

    endpoint: str, national or regional

    Learn about new future datetimes from each CSV and add them to a universal list in the summary.
    To normalise datetimes, calculate the difference between the "now" datetime, from the filepath, and each forecasted/past datetime (the "from" column in each CSV).

    delete_old_files (bool, optional): Delete CSV files (rather than archiving) once they have been added to summary. Defaults to False.
    """

    if delete_old_files:
        log.warning("CSV files will be deleted after being added to the summary.")

    abbreviated_endpoint = endpoint.split("_")[0]

    summary_fp = get_summary_filepath(output_directory, endpoint)
    summary = load_summary(summary_fp, abbreviated_endpoint)

    group_column_names = SUMMARY_FORMATS[abbreviated_endpoint].get("columns")
    value_column_names = SUMMARY_FORMATS[abbreviated_endpoint].get("values")

    # file selection range
    start_dt = datetime.strptime(start_date, DATETIME_FMT_STR).replace(
        tzinfo=timezone.utc
    )
    end_dt = (
        datetime.now(timezone.utc)
        if end_date is None
        else datetime.strptime(end_date, DATETIME_FMT_STR).replace(tzinfo=timezone.utc)
    )

    file_count = 0
    forecast_files = get_data_files(input_directory, extension=".csv")
    for fp in forecast_files:
        # The datetime of the filepath is the approximate time the forecast was made
        fp_dt = round_down_datetime(datetime_from_filepath(fp))

        if fp_dt < start_dt or fp_dt > end_dt:
            continue

        df = pd.read_csv(fp)
        # For each date in the "from" column, get the time difference from the forecast time
        # Forecasts give positive time differences; past times give negative
        # This is returned in hours
        df["time_difference"] = df["from"].apply(
            lambda forecast_dt: get_hours_between(forecast_dt, fp_dt)
        )
        # Format as a string with a leading 0 for visual sorting. Use .zfill(5) to ensure the leading 0 is always present even with a '-'.
        df["time_difference"] = df["time_difference"].apply(lambda x: str(x).zfill(5))

        # Convert a couple of columns to strings, otherwise we struggle to convert to the correct dtypes when loading from CSV.
        for col in group_column_names:
            try:
                df[col] = df[col].astype(str)
            except KeyError as e:
                log.error(f"KeyError: {e} in {fp}")
                continue

        # The pivot creates a Pandas MultiIndex, the result of which is _almost_ small enough to load into Excel (but not quite).
        # Only practical if you can load it correctly from .CSV, which you can do as above for the summary_df.
        df_p = df.pivot(
            index="from",
            columns=group_column_names,
            values=value_column_names,
        )

        summary = _update_summary_dataframe(summary, df_p)

        # TODO: do this with a limit on the number of files to load, instead.
        # Archive the CSV to speed up future runs
        if "_archive" not in fp and not delete_old_files:
            move_to_subdirectory(fp, "_archive")

        file_count += 1
        if num_files and file_count >= num_files:
            break

    summary.to_csv(summary_fp)

    if os.path.isfile(summary_fp) and delete_old_files:
        log.info("Deleting old files which were added to the summary")
        # Delete old files
        for fp in forecast_files:
            if "summary" not in fp:
                os.remove(fp)
                log.debug("Deleted CSV file: %s", fp)


# Pandas function
def get_rows_on_date(dataframe, target_dt):
    """
    Get all rows of a pandas DataFrame whose datetimes are on a specific date.
    """
    # Convert target_datetime to a date
    target_date = target_dt.date()

    filtered_df = dataframe.copy()

    # Extract the date part of the datetime values in the specified date_column
    filtered_df.index = filtered_df.index.date

    # Filter rows where the date_column values match the target_date
    return filtered_df[filtered_df.index == target_date]
