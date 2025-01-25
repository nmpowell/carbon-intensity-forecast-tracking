"""
Download historic data from the UK National Grid ESO API.

This module provides functionality to download carbon intensity data from the National Grid ESO API
using Click for command line interface handling.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import click
import requests
from dateutil import parser

from scrape.api import DATETIME_FMT_STR, EARLIEST_DATE_STR, TEMPLATE_URLS
from scrape.files import check_create_directory, data_filepath, get_csv_path

log = logging.getLogger(__name__)

TIME_DELTA = timedelta(minutes=30)


def round_down_datetime(dt: datetime, delta: timedelta = TIME_DELTA) -> datetime:
    """Round a timezone-aware datetime object down to the nearest multiple of TIME_DELTA."""
    return dt - (dt - datetime.min.replace(tzinfo=timezone.utc)) % delta


def get_datetimes(start: str, end: Optional[str] = None) -> tuple[datetime, datetime]:
    """Convert start and end date strings to datetime objects, rounded to nearest half hour.

    Args:
        start: Start date string in DATETIME_FMT_STR format
        end: Optional end date string in DATETIME_FMT_STR format

    Returns:
        Tuple of (start_datetime, end_datetime)
    """
    start_dt = parser.parse(start)
    try:
        end_dt = parser.parse(end) if end else None
    except TypeError:
        end_dt = None

    end_dt = end_dt or max(start_dt, datetime.now(tz=timezone.utc))
    return round_down_datetime(start_dt), round_down_datetime(end_dt)


def download_json_to_file(url: str, filepath: str) -> Optional[Dict[str, Any]]:
    """Download JSON from URL and save to filepath.

    Args:
        url: URL to download from
        filepath: Path to save JSON file to

    Returns:
        Downloaded JSON data as dict if successful, None otherwise

    Raises:
        requests.exceptions.RequestException: If download fails
        json.JSONDecodeError: If response is not valid JSON
    """
    response = requests.get(url)
    if response.status_code == 200 and "application/json" in response.headers.get(
        "content-type", ""
    ):
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            log.error("Failed to decode JSON from %s: %s", url, e)
            raise

        if data:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=4)
            return data

        log.warning("Empty JSON response from %s", url)
        return None

    raise requests.exceptions.RequestException(
        f"Failed to download {url}: {response.status_code}"
    )


@click.command()
@click.option(
    "--output-directory",
    "-o",
    default="data",
    help="Directory to save downloaded files",
    type=click.Path(),
)
@click.option(
    "--endpoint",
    type=click.Choice(list(TEMPLATE_URLS.keys())),
    default="regional_fw48h",
    help="API endpoint to use",
)
@click.option(
    "--start-date",
    default=EARLIEST_DATE_STR,
    help=f"Start date in format {DATETIME_FMT_STR}",
)
@click.option(
    "--end-date",
    default=None,
    help=f"End date in format {DATETIME_FMT_STR}",
)
@click.option(
    "--num-files",
    "-n",
    default=0,
    help="Maximum number of files to download (0 for unlimited)",
    type=int,
)
@click.option(
    "--now",
    is_flag=True,
    help="Download only current data",
)
@click.option(
    "--unique-names",
    is_flag=True,
    help="Use unique filenames including capture timestamp",
)
@click.option(
    "--debug/--no-debug",
    default=False,
    help="Enable debug logging",
)
def download(
    output_directory: str,
    endpoint: str,
    start_date: str,
    end_date: Optional[str],
    num_files: int,
    now: bool,
    unique_names: bool,
    debug: bool,
) -> None:
    """Download carbon intensity data from the National Grid ESO API.

    This command downloads JSON files containing carbon intensity data for the specified
    time period and endpoint. Files are saved to the output directory with names based
    on their timestamps.

    Examples:
        Download current data only:
        $ python -m carbon_intensity_scraper.download --now

        Download 10 half-hourly files:
        $ python -m carbon_intensity_scraper.download -n 10

        Download data for specific date range:
        $ python -m carbon_intensity_scraper.download --start-date 2023-03-09T20:01Z --end-date 2024-03-09T20:01Z
    """
    # Configure logging
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=log_level)

    if debug:
        log.debug("Debug mode enabled")

    log.info("Using endpoint: %s", endpoint)

    # Set up output directory
    output_directory = check_create_directory(os.path.join(output_directory, endpoint))

    # Get current time for unique filenames
    capture_dt = datetime.now(tz=timezone.utc).strftime(DATETIME_FMT_STR)

    # Handle --now flag
    if now:
        start_date = capture_dt
        num_files = 1
        end_date = start_date

    # Get datetime objects for start/end
    inspect_datetime, end_datetime = get_datetimes(start_date, end_date)

    # Add 1 minute so returned forecast starts with current half hour at index 0
    inspect_datetime += timedelta(minutes=1)
    end_datetime += timedelta(minutes=1)

    file_count = 0
    success_count = 0

    while inspect_datetime <= end_datetime and (
        file_count < num_files if num_files > 0 else True
    ):
        inspect_datetime_str = inspect_datetime.strftime(DATETIME_FMT_STR)
        log.info("Getting data for %s", inspect_datetime_str)

        url = TEMPLATE_URLS[endpoint].format(inspect_datetime_str)

        filename = (
            f"{capture_dt}_{inspect_datetime_str}"
            if unique_names
            else inspect_datetime_str
        )
        filepath = data_filepath(output_directory, filename)

        # Advance for next iteration
        inspect_datetime += TIME_DELTA
        file_count += 1

        # Skip if file exists
        if os.path.exists(filepath) or os.path.exists(
            get_csv_path(output_directory, filepath)
        ):
            log.debug("File already exists; skipping: %s", filepath)
            continue

        try:
            if download_json_to_file(url, filepath):
                success_count += 1
                # Print for commit message
                print(f"Downloaded: {filepath} at {datetime.now(tz=timezone.utc)}")
            else:
                log.warning("No data available for %s", inspect_datetime_str)
                break
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            log.error("Failed to download data: %s", e)
            continue

    log.info(
        "Download complete. Successfully downloaded %d/%d files",
        success_count,
        file_count,
    )


if __name__ == "__main__":
    download()
