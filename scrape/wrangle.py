# TODO: use jsonschema to validate the structure

"""
Functions to extract data from JSON files and save in separate .CSV files.

One .CSV file for each of the regions.
"""

import json
import logging
import os

import pandas as pd

from scrape.files import json_data_filepath

log = logging.getLogger(__name__)


# Load JSON to a dict
def load_json_file(filepath: str) -> dict:
    with open(filepath) as f:
        return json.load(f)


def get_forecast_data_from_json_file(filepath: str) -> dict:
    return load_json_file(filepath).get("data")


def get_one_region_intensity_forecasts(data: dict, region_id: int = 1) -> dict:
    # we know the region_id is the n-1th in the list
    return {
        e.get("from"): e.get("regions")[region_id - 1].get("intensity").get("forecast")
        for e in data
    }


def get_national_intensity_forecasts(
    data: dict,
) -> dict:
    return dict(
        pd.json_normalize(data)[
            ["from", "intensity.forecast", "intensity.actual"]
        ].iloc[0]
    )


def files_to_dataframe(input_directory: str, region_id: int = 0) -> pd.DataFrame:
    # list files in the directory
    files = os.listdir(input_directory)
    subset = []
    for filepath in files:
        data = get_forecast_data_from_json_file(os.path.join(input_directory, filepath))
        results = get_one_region_intensity_forecasts(data, region_id)
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


# Load the JSON file, normalise, and return a pandas DataFrame
# def load_normalise(filepath: str) -> pd.DataFrame:
# with open(filepath) as f:
#     data = json.load(f)
# df = pd.json_normalize(data)

#     df = load_json(filepath)
#     df = normalise(df)
#     return df


for i in range(20):
    try:
        files_to_dataframe("data_forecasts", region_id=i).to_csv(
            f"_test_region_{i}.csv"
        )
    except:
        print(f"No {i} file!")

files_to_dataframe_national("data_national_fixed").to_csv(f"_test_national.csv")


# Given a JSON filepath, load and return a pandas DataFrame
def load_json(filepath: str) -> pd.DataFrame:
    return pd.read_json(filepath, orient="records", lines=True)


def run(*args, **kwargs):
    """Wrangle data from JSON files into CSV files."""
    pass


def get_json_files(directory: str) -> list:
    """Get a list of complete filepaths to JSON files in the given directory."""
    return [
        os.path.join(directory, fn)
        for fn in os.listdir(directory)
        if fn.lower().endswith(".json")
    ]


# Process JSON files which are saved in the format <datetime>.<regionid>.json
# The output CSVs are also per-region and per-datetime.
def run_wrangle_regional(
    input_directory: str = "data",
    output_directory: str = None,
    delete_json: bool = False,
    *args,
    **kwargs,
):
    """Wrangle data from JSON files into CSV files."""

    for fp in get_json_files(input_directory):
        csv_fp = _wrangle_regional_json_to_csv(fp, output_directory)
        log.info("Wrote CSV file: %", csv_fp)

        # delete the json file if we have a csv
        if os.path.isfile(csv_fp) and delete_json:
            os.remove(fp)
            log.debug("Deleted JSON file: %s", fp)


def _wrangle_regional_json_to_csv(filepath: str, output_directory: str):
    """Wrangle a single JSON file into a (more compact) CSV file.
    JSON as downloaded from e.g. /regional/intensity/<datetime>/fw48h/regionid/<regionid>
    """
    print(f"Loading {filepath}")
    # Load the JSON file, normalise, and return a pandas DataFrame
    data = get_forecast_data_from_json_file(filepath)

    # check the regionid matches that of the file
    if data.get("regionid") != int(os.path.basename(filepath).split(".")[1]):
        raise ValueError("Region ID does not match filename")

    df = pd.json_normalize(
        data,
        record_path=["data", "generationmix"],
        meta=[["data", "from"], ["data", "intensity", "forecast"]],
    )
    df = df.pivot(
        index=["data.from", "data.intensity.forecast"], columns="fuel", values="perc"
    )

    output_fp = os.path.join(
        output_directory or os.path.dirname(filepath),
        os.path.basename(filepath.replace(".json", ".csv")),
    )
    df.to_csv(output_fp)
    return output_fp


# This is from the regional data for one region, from e.g. https://api.carbonintensity.org.uk/regional/intensity/2023-03-11T23:31Z/fw48h/regionid/18
# data = get_forecast_data_from_json_file(fp)
# generationmix_df = pd.json_normalize(
#     data,
#     record_path=["data", "generationmix"],
#     meta=[["data", "from"], ["data", "intensity", "forecast"]],
# )
# result = generationmix_df.pivot(
#     index=["data.from", "data.intensity.forecast"], columns="fuel", values="perc"
# )
