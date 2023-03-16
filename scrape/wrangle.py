# TODO: use jsonschema to validate the structure

"""
Functions to extract data from JSON files and save in separate .CSV files.

One .CSV file for each of the regions.
"""


import json
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


# Load JSON to a dict
def load_json_file(filepath: str) -> dict:
    with open(filepath) as f:
        return json.load(f)


def get_forecast_data_from_json_file(filepath: str) -> dict:
    return load_json_file(filepath).get("data")


def datetime_from_filepath(filepath: str) -> str:
    name, _ = os.path.splitext(os.path.basename(filepath))
    dt = datetime.strptime(name, DATETIME_FMT_STR.replace(":", "")).replace(
        tzinfo=timezone.utc
    )
    # datetime_str = datetime.strftime(dt, DATETIME_FMT_STR)
    return dt


def calculate_time_difference(datetime_str: str, dt2: datetime) -> str:
    """Calculate the time difference between two datetimes, the first represented as a string.
    Returns the timedelta.
    """
    dt = datetime.strptime(datetime_str, DATETIME_FMT_STR).replace(tzinfo=timezone.utc)
    return dt - dt2


# Read CSVs and collate into a forecast summary
def summary(
    input_directory: str, summary_directory: str = "", summary_name: str = "summary.csv"
) -> None:
    """Read CSVs from input_directory. Collate forecasts per-region and per-fuel."""

    # The idea is to learn about new future datetimes from each CSV and add them to a list.
    # To normalise datetimes, I calculate the difference between the "now" datetime, from the filepath, and each forecasted datetime (the "from" column in each CSV).

    summary_directory = check_create_directory(summary_directory)

    # get existing summary, or start from scratch
    summary_fp = os.path.join(summary_directory, summary_name)
    if os.path.exists(summary_fp):
        summary = pd.read_csv(summary_fp, header=[0, 1, 2], index_col=0)
    else:
        summary = pd.DataFrame()

    forecast_files = get_data_files(input_directory, extension=".csv")
    for fp in forecast_files:

        # The datetime of the filepath is the approximate time the forecast was made
        fp_dt = round_down_datetime(datetime_from_filepath(fp))

        df = pd.read_csv(fp)
        # For each date in the "from" column, get the time difference from the forecast time
        # Forecasts give positive time differences; past times give negative
        # This is recorded in hours.
        df["time_difference"] = df["from"].apply(
            lambda forecast_dt: calculate_time_difference(
                forecast_dt, fp_dt
            ).total_seconds()
            / 3600
        )

        # Convert a couple of columns to strings, otherwise we struggle to convert to the correct dtypes when loading from CSV.
        df[["time_difference", "regions.regionid"]] = df[
            ["time_difference", "regions.regionid"]
        ].astype(str)

        # The pivot creates a Pandas MultiIndex, the result of which is _almost_ small enough to load into Excel (but not quite).
        # Only practical if you can load it correctly from .CSV, which you can do as above for the summary_df.
        df_p = df.pivot(
            index="from",
            columns=["regions.regionid", "time_difference"],
            values=[
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
        )

        # .update is reasonably fast and overwrites NaNs as we want. Columns will be identical.
        # It doesn't appear to require identical indices, but it requires the index of df1 to be exhaustive i.e. includes all the indices in df2 (a superset); df2 must be a subset of df1, or values will be lost from df2.
        union_index = summary.index.union(df_p.index)
        if summary.empty:
            summary = df_p.reindex(union_index)
        else:
            summary = summary.reindex(union_index)
            summary.update(df_p)

    summary.to_csv(summary_fp)

    # # Get one dataframe per region
    # region_groups = df.groupby("regions.regionid")
    # for df_rg in [region_groups.get_group(g) for g in region_groups.groups]:
    #     df_rg.pivot(
    #         index="from",
    #         columns="time_difference",
    #         values=[
    #             "regions.intensity.forecast",
    #             "biomass",
    #             "coal",
    #             "gas",
    #             "hydro",
    #             "imports",
    #             "nuclear",
    #             "other",
    #             "solar",
    #             "wind",
    #         ],
    #     )

    # # We will fill the "from" row at the "time_difference" column

    # # df = df.set_index("time_difference")

    # region_groups = df.groupby("regions.regionid")
    # dfs = [region_groups.get_group(g) for g in region_groups.groups]


# Below commented code used to construct some summary CSVs; will be removed.

# def get_one_region_intensity_forecasts(data: dict, region_id: int = 1) -> dict:
#     # we know the region_id is the n-1th in the list
#     return {
#         e.get("from"): e.get("regions")[region_id - 1].get("intensity").get("forecast")
#         for e in data
#     }


def get_national_intensity_forecasts(
    data: dict,
) -> dict:
    return dict(
        pd.json_normalize(data)[
            ["from", "intensity.forecast", "intensity.actual"]
        ].iloc[0]
    )


# def files_to_dataframe(input_directory: str, region_id: int = 0) -> pd.DataFrame:
#     # list files in the directory
#     files = os.listdir(input_directory)
#     subset = []
#     for filepath in files:
#         data = get_forecast_data_from_json_file(os.path.join(input_directory, filepath))
#         results = get_one_region_intensity_forecasts(data, region_id)
#         results["filename"] = os.path.basename(filepath)
#         subset.append(results)
#     df = pd.DataFrame(subset)
#     # sort columns alphabetically
#     df = df.reindex(sorted(df.columns), axis=1)
#     # use "filename" as the index
#     df.set_index("filename", inplace=True)
#     # sort the index alphabetically
#     df.sort_index(inplace=True)
#     return df


def files_to_dataframe_national(input_directory: str) -> pd.DataFrame:
    # list files in the directory
    files = os.listdir(input_directory)
    subset = []
    for filepath in files:
        data = get_forecast_data_from_json_file(os.path.join(input_directory, filepath))
        results = get_national_intensity_forecasts(data)
        results["filename"] = os.path.basename(filepath)
        subset.append(results)
    df = pd.DataFrame(subset)
    # sort columns alphabetically
    df = df.reindex(sorted(df.columns), axis=1)
    # use "filename" as the index
    df.set_index("filename", inplace=True)
    # sort the index alphabetically
    df.sort_index(inplace=True)
    return df


def _regional_json_to_csv(data) -> pd.DataFrame:
    df = pd.json_normalize(
        data,
        record_path=["regions", "generationmix"],
        meta=["from", ["regions", "regionid"], ["regions", "intensity", "forecast"]],
    )
    return df.pivot(
        index=["from", "regions.regionid", "regions.intensity.forecast"],
        columns="fuel",
        values="perc",
    )


def _national_generation_json_to_csv(data) -> pd.DataFrame:
    df = pd.json_normalize(data, record_path=["generationmix"], meta=["from"])
    return df.pivot(index="from", columns="fuel", values="perc")


# Select wrangling function based upon the endpoint (thus, the JSON format)
WRANGLE_SELECT = {
    "national_generation_pt24h": _national_generation_json_to_csv,
    "regional_pt24h": _regional_json_to_csv,
    "regional_fw48h": _regional_json_to_csv,
}


def run_wrangle(
    input_directory: str = "data",
    output_directory: str = None,
    delete_json: bool = False,
    endpoint: str = "",
    *args,
    **kwargs,
):
    """Wrangle data from JSON to CSVs.

    Args:
        input_directory (str, optional): _description_. Defaults to "data".
        output_directory (str, optional): _description_. Defaults to None (same as input).
        delete_json (bool, optional): _description_. Defaults to False.
        endpoint (str, optional): _description_. Must be a valid endpoint from WRANGLE_SELECT.

    Raises:
        ValueError: _description_

    Returns:
        _type_: _description_
    """
    log.info(f"JSON files in {input_directory} will be converted to CSV...")
    if delete_json:
        log.warning("JSON files will be deleted after conversion to CSV.")

    # We don't need to get the output directory from each file if we have input_directory
    output_directory = check_create_directory(
        output_directory or os.path.normpath(input_directory)
    )

    for fp in get_data_files(input_directory, ".json"):
        csv_fp = os.path.join(
            output_directory,
            os.path.basename(fp.replace(".json", ".csv")),
        )
        if os.path.isfile(csv_fp):
            log.info("CSV file already exists: %s", csv_fp)
            continue

        _wrangle_json_to_csv(fp, csv_fp, endpoint, output_directory)

        # delete the json file if we have a csv
        if os.path.isfile(csv_fp) and delete_json:
            os.remove(fp)
            log.debug("Deleted JSON file: %s", fp)


def _wrangle_json_to_csv(
    filepath: str, csv_fp: str, endpoint: str, output_directory: str = None
) -> str:
    """Wrangle a single JSON file to a CSV file.

    Args:
        filepath (str): Input JSON file path.
        output_directory (str, optional): _description_. Defaults to None.
    """

    # Load the JSON file, normalise, and return a pandas DataFrame
    data = get_forecast_data_from_json_file(filepath)

    df = WRANGLE_SELECT.get(endpoint)(data)

    df.to_csv(csv_fp)
    log.info("Wrote CSV file: %s", csv_fp)
    return
