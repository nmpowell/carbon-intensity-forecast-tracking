# TODO: use jsonschema to validate the structure

"""
Functions to extract data from JSON files and save in separate .CSV files.

One .CSV file for each of the regions.
"""

import json
import os

import pandas as pd

from scrape.files import json_data_filepath


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
