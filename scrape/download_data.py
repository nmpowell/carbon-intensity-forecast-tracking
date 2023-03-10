"""
Download historic data from the UK National Grid ESO API.

There's no point downloading historic data for forecast assessment, as it's all the same!

Example usage:
    python download_historic_data.py --output_directory data -n 10
    python download_historic_data.py --output_directory "data" --now
    python download_historic_data.py --output_directory "data" -n 1 --start_date "2023-03-09T20:01Z" --end_date "2024-03-09T20:01Z"
    
    Where:
        -n 10 means download 10 half-hourly files (i.e. 5 hours of data)
    
    Maybe:
        --start_date 2018-05-10T23:30Z --end_date 2018-05-11T23:30Z
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import requests
from dateutil import parser

log = logging.getLogger(__name__)


TIME_DELTA = timedelta(minutes=30)

BASE_URL = "https://api.carbonintensity.org.uk"
TEMPLATE_48HR_FORWARD_URL = BASE_URL + "/regional/intensity/{}/fw48h"

DATETIME_FMT_STR = "%Y-%m-%dT%H:%MZ"
EARLIEST_DATE_STR = "2018-05-10T23:30Z"


def check_create_directory(directory: str = ""):
    """Recursively create a specified directory tree."""
    ndir = os.path.realpath(os.path.expanduser(os.path.normpath(directory)))
    if not os.path.exists(ndir):
        os.makedirs(ndir, exist_ok=True)
    return ndir


def download_json_to_file(url: str, filepath: str):
    """Download a JSON file from the given URL and save it to the given filepath."""
    response = requests.get(url)
    if response.status_code == 200 and "application/json" in response.headers.get(
        "content-type", ""
    ):
        # Still get a 200 even if the response JSON is empty (e.g. far in the future)
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise e
        if data:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=4)
    else:
        raise Exception(f"Failed to download {url}")
    return response.json()


# round a timezone-aware datetime object down to the nearest multiple of TIME_DELTA
def round_down_datetime(dt, delta: timedelta = TIME_DELTA):
    return dt - (dt - datetime.min.replace(tzinfo=timezone.utc)) % delta


def get_datetimes(start: str, end: str):
    """Given strings, return start and end datetime objects, rounded down to the nearest half hour."""

    # For niceness, use dateutil on these well-defined strings to preserve the timezone
    start_dt = parser.parse(start)
    try:
        end_dt = parser.parse(end)
    except TypeError:
        end_dt = None
        pass

    end_dt = end_dt or max(start_dt, datetime.utcnow().replace(tzinfo=timezone.utc))
    return round_down_datetime(start_dt), round_down_datetime(end_dt)


def run(
    output_directory: str = "data",
    start_date: str = EARLIEST_DATE_STR,
    end_date: str = None,
    num_files: int = 0,
    now: bool = False,
    *args,
    **kwargs,
):

    output_directory = check_create_directory(output_directory)

    if now:
        # override some inputs
        start_date = (
            datetime.utcnow().replace(tzinfo=timezone.utc).strftime(DATETIME_FMT_STR)
        )
        num_files = 1
        end_date = start_date

    inspect_datetime, end_datetime = get_datetimes(start_date, end_date)

    file_count = 0

    while inspect_datetime <= end_datetime and file_count < num_files:
        inspect_datetime_str = inspect_datetime.strftime(DATETIME_FMT_STR)
        log.info("Getting data for %s ...", inspect_datetime_str)

        url = TEMPLATE_48HR_FORWARD_URL.format(inspect_datetime_str)
        filepath = os.path.join(
            output_directory, f"{inspect_datetime_str}.json".replace(":", "")
        )

        # advance for next iteration
        inspect_datetime += TIME_DELTA
        file_count += 1

        if os.path.exists(filepath):
            # Ensure we won't overwrite files as the API doesn't seem to save old forecasts
            log.info("File already exists; skipping: %s", filepath)
            continue

        if not download_json_to_file(url, filepath):
            log.warning("No data for this date; stopping.")
            break

        print(f"Downloaded: {inspect_datetime_str}")

    log.info("Success!")
