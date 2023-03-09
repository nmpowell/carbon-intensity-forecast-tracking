# Python3

"""
Download historic data from the UK National Grid ESO API.

NB There's no point downloading historic data for forecast assessment, as it's all the same!

Example usage:
    python download_historic_data.py --output_directory ./data -n 10
    
    Where:
        -n 10 means download 10 half-hourly files (i.e. 5 hours of data)
    
    Maybe:
        --start_date 2018-05-10T23:30Z --end_date 2018-05-11T23:30Z
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import requests
from dateutil import parser

BASE_URL = "https://api.carbonintensity.org.uk"
TEMPLATE_48HR_FORWARD_URL = (
    "https://api.carbonintensity.org.uk/regional/intensity/{}/fw48h"
)

DATETIME_STRFMT = "%Y-%m-%dT%H:%MZ"
EARLIEST_DATE_STR = "2018-05-10T23:30Z"

TIME_DELTA = timedelta(minutes=30)


def check_create_directory(directory: str = ""):
    """Recursively create a specified directory tree."""
    ndir = os.path.realpath(os.path.expanduser(os.path.normpath(directory)))
    if not os.path.exists(ndir):
        os.makedirs(ndir, exist_ok=True)
    return ndir


def download_json_to_file(url: str, filepath: str):
    """Download a JSON file from the given URL and save it to the given filepath."""
    response = requests.get(url)
    if response.status_code == 200:
        with open(filepath, "w") as f:
            f.write(response.text)
    else:
        raise Exception(f"Failed to download {url}")


def get_json_from_url(url: str):
    """Download JSON from the given URL and return it as a dict."""
    response = requests.get(url)
    if response.status_code == 200 and "application/json" in response.headers.get(
        "content-type", ""
    ):
        try:
            return response.json()
        except json.JSONDecodeError as e:
            raise e
    else:
        raise Exception(f"Failed to download {url}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output_directory",
        "-o",
        default=".",
        help="Path to output directory",
        type=str,
    )
    parser.add_argument(
        "--num_files",
        "-n",
        default=0,
        type=int,
        help="Number of files. All if 0 or not specified.",
    )
    parser.add_argument(
        "--start_date",
        default=EARLIEST_DATE_STR,
        type=str,
        help="Start date in format {}".format(DATETIME_STRFMT),
    )
    return parser.parse_args()


def main(
    output_directory: str = "data",
    start_date: str = EARLIEST_DATE_STR,
    num_files: int = 0,
):

    output_directory = check_create_directory(output_directory)

    # For niceness, use dateutil on these well-defined strings to preserve the timezone
    inspect_datetime = parser.parse(start_date)
    file_count = 0

    max = datetime.utcnow().replace(tzinfo=timezone.utc)

    while inspect_datetime <= max and file_count <= num_files:
        inspect_datetime_str = inspect_datetime.strftime(DATETIME_STRFMT)
        print(f"Getting data for {inspect_datetime_str} ...")

        url = TEMPLATE_48HR_FORWARD_URL.format(inspect_datetime_str)
        filepath = os.path.join(output_directory, f"{inspect_datetime_str}.json")
        download_json_to_file(url, filepath)

        # advance for next iteration
        inspect_datetime += TIME_DELTA
        file_count += 1


if __name__ == "__main__":
    args = parse_args()
    main(**vars(args))
