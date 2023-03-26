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
from scrape.download_data import round_down_datetime
from scrape.files import check_create_directory
from scrape.files import get_data_files

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


def calculate_time_difference(datetime_str: str, dt2: datetime) -> str:
    """Calculate the time difference between two datetimes, the first represented as a string.
    Returns the timedelta.
    """
    dt = datetime.strptime(datetime_str, DATETIME_FMT_STR).replace(tzinfo=timezone.utc)
    return dt - dt2


def _update_summary_dataframe(summary: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Add the new data to the summary dataframe, combine indices, and return the updated summary."""

    # .update is reasonably fast and overwrites NaNs as we want. Columns will be identical.
    # It doesn't appear to require identical indices, but it requires the index of df1 to be exhaustive i.e. includes all the indices in df2 (a superset); df2 must be a subset of df1, or values will be lost from df2.

    union_index = summary.index.union(df.index)
    if summary.empty:
        summary = df.reindex(union_index)
    else:
        summary = summary.reindex(union_index)
        summary.update(df)
    return summary


# Read CSVs and collate into a forecast summary
def run(
    input_directory: str,
    output_directory: str = None,
    endpoint: "str" = "regional_fw48h",
    summary_name: str = None,
    *args,
    **kwargs,
) -> None:
    """Read CSVs from input_directory. Collate forecasts per-region and per-fuel.

    endpoint: str, national or regional

    Learn about new future datetimes from each CSV and add them to a universal list in the summary.
    To normalise datetimes, calculate the difference between the "now" datetime, from the filepath, and each forecasted/past datetime (the "from" column in each CSV).
    """

    abbreviated_endpoint = endpoint.split("_")[0]

    summary_directory = check_create_directory(
        output_directory or os.path.normpath(input_directory)
    )

    # get existing summary, or start from scratch
    summary_name = summary_name or "summary_{}.csv".format(endpoint)
    summary_fp = os.path.join(summary_directory, summary_name)
    if os.path.exists(summary_fp):
        summary = pd.read_csv(
            summary_fp,
            header=SUMMARY_FORMATS[abbreviated_endpoint].get("header_rows"),
            index_col=0,
        )
        log.info("Read existing summary file: {}".format(summary_fp))
    else:
        summary = pd.DataFrame()

    group_column_names = SUMMARY_FORMATS[abbreviated_endpoint].get("columns")
    value_column_names = SUMMARY_FORMATS[abbreviated_endpoint].get("values")

    forecast_files = get_data_files(input_directory, extension=".csv")
    for fp in forecast_files:

        # The datetime of the filepath is the approximate time the forecast was made
        fp_dt = round_down_datetime(datetime_from_filepath(fp))

        df = pd.read_csv(fp)
        # For each date in the "from" column, get the time difference from the forecast time
        # Forecasts give positive time differences; past times give negative
        # This is returned in hours
        df["time_difference"] = df["from"].apply(
            lambda forecast_dt: calculate_time_difference(
                forecast_dt, fp_dt
            ).total_seconds()
            / 3600
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

    summary.to_csv(summary_fp)
