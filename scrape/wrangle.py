# TODO: use jsonschema to validate the structure

"""
Functions to extract data from JSON files and save in separate .CSV files.

One .CSV file for each of the regions.
"""


import json
import logging
import os

import pandas as pd

from scrape.files import check_create_directory
from scrape.files import get_csv_path
from scrape.files import get_data_files

log = logging.getLogger(__name__)


# Load JSON to a dict
def load_json_file(filepath: str) -> dict:
    with open(filepath) as f:
        return json.load(f)


def get_forecast_data_from_json_file(filepath: str) -> dict:
    return load_json_file(filepath).get("data")


def _regional_json_to_csv(data) -> pd.DataFrame:
    df = pd.json_normalize(
        data,
        record_path=["regions", "generationmix"],
        meta=["from", ["regions", "regionid"], ["regions", "intensity", "forecast"]],
    )
    # This raises FutureWarning: In a future version, the Index constructor will not infer numeric dtypes when passed object-dtype sequences (matching Series behavior)
    return df.pivot(
        index=["from", "regions.regionid", "regions.intensity.forecast"],
        columns="fuel",
        values="perc",
    )


def _national_generation_json_to_csv(data) -> pd.DataFrame:
    df = pd.json_normalize(data, record_path=["generationmix"], meta=["from"])
    return df.pivot(index="from", columns="fuel", values="perc")


def _national_json_to_csv(data) -> pd.DataFrame:
    df = pd.json_normalize(data)
    return df.set_index("from").drop(columns=["to", "intensity.index"])


# Select wrangling function based upon the endpoint (thus, the JSON format)
WRANGLE_SELECT = {
    "national_fw48h": _national_json_to_csv,
    "national_pt24h": _national_json_to_csv,
    "national_generation_pt24h": _national_generation_json_to_csv,
    "regional_pt24h": _regional_json_to_csv,
    "regional_fw48h": _regional_json_to_csv,
}


def _wrangle_json_to_csv(
    filepath: str, csv_fp: str, endpoint: str, output_directory: str = None
) -> str:
    """Wrangle a single JSON file to a CSV file.

    Args:
        filepath (str): Input JSON file path.
        output_directory (str, optional): _description_. Defaults to None.
    """

    # Load the JSON file, normalise, and return a pandas DataFrame
    try:
        data = get_forecast_data_from_json_file(filepath)
    except json.decoder.JSONDecodeError as e:
        log.error("File skipped; JSONDecodeError: %s", e)
        return

    df = WRANGLE_SELECT.get(endpoint)(data)

    df.to_csv(csv_fp)
    # Print for commit message
    print(f"Wrote CSV file: {csv_fp}")
    return


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

    for fp in get_data_files(input_directory, extension=".json"):
        csv_fp = get_csv_path(output_directory, fp)
        if not os.path.isfile(csv_fp):
            _wrangle_json_to_csv(fp, csv_fp, endpoint, output_directory)
        else:
            log.debug("CSV file already exists: %s", csv_fp)

        # delete the json file if we have a csv
        if os.path.isfile(csv_fp) and delete_json:
            os.remove(fp)
            log.debug("Deleted JSON file: %s", fp)
