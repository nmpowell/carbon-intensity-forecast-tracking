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

Note: This module requires the following type stubs:
    pip install types-requests types-python-dateutil
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, Union, cast

import requests  # type: ignore
from dateutil import parser  # type: ignore

from scrape.api import DATETIME_FMT_STR, EARLIEST_DATE_STR, TEMPLATE_URLS
from scrape.files import check_create_directory, data_filepath, get_csv_path

log = logging.getLogger(__name__)


TIME_DELTA: timedelta = timedelta(minutes=30)


def download_json_to_file(url: str, filepath: str) -> Dict[str, Any]:
    """Download a JSON file from the given URL and save it to the given filepath.
    
    Args:
        url: The URL to download the JSON from
        filepath: The path to save the downloaded JSON to
        
    Returns:
        The downloaded JSON data as a dictionary
        
    Raises:
        Exception: If the download fails or the response is not valid JSON
        json.JSONDecodeError: If the response cannot be parsed as JSON
    """
    response: requests.Response = requests.get(url)
    if response.status_code == 200 and "application/json" in response.headers.get(
        "content-type", ""
    ):
        # Still get a 200 even if the response JSON is empty (e.g. far in the future)
        try:
            data: Dict[str, Any] = response.json()
        except json.JSONDecodeError as e:
            raise e
        if data:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=4)
            return data
    raise Exception(f"Failed to download {url}")


def get_number_of_time_points(start: str, end: str) -> int:
    """Given strings, return the number of TIME_DELTA time points between them.
    
    Args:
        start: Start datetime string in ISO format
        end: End datetime string in ISO format
        
    Returns:
        Number of TIME_DELTA intervals between start and end
    """
    start_dt, end_dt = get_datetimes(start, end)
    return int((end_dt - start_dt) / TIME_DELTA)


def round_down_datetime(dt: datetime, delta: timedelta = TIME_DELTA) -> datetime:
    """Round a timezone-aware datetime object down to the nearest multiple of delta.
    
    Args:
        dt: The datetime to round down
        delta: The time interval to round to (default: TIME_DELTA)
        
    Returns:
        The rounded datetime
    """
    return dt - (dt - datetime.min.replace(tzinfo=timezone.utc)) % delta


def get_datetimes(start: str, end: Optional[str]) -> Tuple[datetime, datetime]:
    """Given strings, return start and end datetime objects, rounded down to the nearest half hour.
    
    Args:
        start: Start datetime string in ISO format
        end: End datetime string in ISO format, or None to use current time
        
    Returns:
        Tuple of (start_datetime, end_datetime)
    """
    # For niceness, use dateutil on these well-defined strings to preserve the timezone
    start_dt: datetime = parser.parse(start)
    try:
        end_dt: Optional[datetime] = parser.parse(end) if end else None
    except TypeError:
        end_dt = None

    end_dt = end_dt or max(start_dt, datetime.now(tz=timezone.utc))
    return round_down_datetime(start_dt), round_down_datetime(end_dt)


def run_download(
    output_directory: str = "data",
    endpoint: str = "regional_fw48h",
    start_date: str = EARLIEST_DATE_STR,
    end_date: Optional[str] = None,
    num_files: int = 0,
    now: bool = False,
    unique_names: bool = False,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Download data from the API and save to JSON files.
    
    Args:
        output_directory: Directory to save files to
        endpoint: API endpoint to use
        start_date: Start date in ISO format
        end_date: End date in ISO format, or None to use current time
        num_files: Number of files to download (0 for unlimited)
        now: If True, only download current data
        unique_names: If True, use unique filenames including capture time
        args: Additional positional arguments (ignored)
        kwargs: Additional keyword arguments (ignored)
    """
    log.info(f"Using endpoint: {endpoint}")

    output_directory = check_create_directory(os.path.join(output_directory, endpoint))

    capture_dt: str = datetime.now(tz=timezone.utc).strftime(DATETIME_FMT_STR)

    if now:
        # override some inputs
        start_date = capture_dt
        num_files = 1
        end_date = start_date

    inspect_datetime, end_datetime = get_datetimes(start_date, end_date)

    # Add 1 minute so the returned forecast starts with the current half hour at index 0.
    inspect_datetime += timedelta(minutes=1)
    end_datetime += timedelta(minutes=1)

    file_count: int = 0

    while (
        inspect_datetime <= end_datetime and file_count < num_files
        if num_files > 0
        else True
    ):
        inspect_datetime_str: str = inspect_datetime.strftime(DATETIME_FMT_STR)
        log.info("Getting data for %s ...", inspect_datetime_str)

        # Get the URL template and ensure it exists
        template_url: Optional[str] = TEMPLATE_URLS.get(endpoint)
        if template_url is None:
            raise ValueError(f"Unknown endpoint: {endpoint}")

        # Now we know template_url is a string, we can safely call format
        url: str = template_url.format(inspect_datetime_str)

        filename: str = (
            capture_dt + "_" + inspect_datetime_str
            if unique_names
            else inspect_datetime_str
        )
        filepath: str = data_filepath(output_directory, filename)

        # advance for next iteration
        inspect_datetime += TIME_DELTA
        file_count += 1

        if any(
            [
                os.path.exists(filepath),
                os.path.exists(get_csv_path(output_directory, filepath)),
            ]
        ):
            # Ensure we won't overwrite files as the API doesn't seem to save old forecasts
            log.debug("File already exists; skipping: %s", filepath)
            continue

        try:
            download_json_to_file(url, filepath)
            # Print for commit message
            print(f"Downloaded: {filepath} at {datetime.now(tz=timezone.utc)}")
        except Exception as e:
            log.warning("Failed to download data: %s", e)
            break

    log.info("Success!")


# End
