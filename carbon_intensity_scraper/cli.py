"""
Carbon Intensity Forecast Tracking CLI.

This module provides a Click-based command line interface for downloading and analyzing
carbon intensity data from the National Grid ESO API.
"""

import logging
from typing import Any, Callable, Optional, TypeVar, cast

import click
from pythonjsonlogger import jsonlogger

from carbon_intensity_scraper.download import download as download_command
from scrape.api import DATETIME_FMT_STR, EARLIEST_DATE_STR, TEMPLATE_URLS

log = logging.getLogger(__name__)


def configure_logger(debug: bool = False) -> None:
    """Configure JSON logging with appropriate log level.
    
    Args:
        debug: If True, set log level to DEBUG, otherwise INFO
    """
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    logging.basicConfig(
        handlers=[handler], level=logging.DEBUG if debug else logging.INFO
    )


def common_options(command: Callable[..., Any]) -> Callable[..., Any]:
    """Add common CLI options to a command.
    
    Args:
        command: Click command function to decorate
        
    Returns:
        Decorated command with common options added
    """
    decorators = [
        click.option("--debug/--no-debug", default=False, help="Enable debug logging"),
        click.option(
            "--output-directory", "-o", default=None, help="Path to output directory"
        ),
        click.option(
            "--endpoint",
            type=click.Choice(list(TEMPLATE_URLS.keys())),
            default="regional_fw48h",
            help="Endpoint to use",
        ),
    ]
    
    # Apply decorators in reverse order
    for decorator in reversed(decorators):
        command = decorator(command)
    
    return command


@click.group()
def cli() -> None:
    """Carbon Intensity Forecast Tracking CLI."""
    pass


@cli.command()
@common_options
@click.option("--now", is_flag=True, help="Download current data and nothing else")
@click.option(
    "--num-files",
    "-n",
    default=0,
    type=int,
    help="Max number of files. All if 0 or not specified",
)
@click.option(
    "--start-date",
    default=EARLIEST_DATE_STR,
    help=f"Start date in format {DATETIME_FMT_STR}",
)
@click.option("--end-date", default=None, help=f"End date in format {DATETIME_FMT_STR}")
@click.option("--unique-names", is_flag=True, help="Use a unique name for each file")
def download(
    debug: bool,
    output_directory: Optional[str],
    endpoint: str,
    now: bool,
    num_files: int,
    start_date: str,
    end_date: Optional[str],
    unique_names: bool,
) -> None:
    """Download JSON file(s) from the API.
    
    This command downloads carbon intensity data files from the National Grid ESO API
    for the specified time period and endpoint. Files are saved to the output directory
    with names based on their timestamps.

    Examples:
        Download current data only:
        $ carbon-intensity-scraper download --now

        Download 10 half-hourly files:
        $ carbon-intensity-scraper download -n 10

        Download data for specific date range:
        $ carbon-intensity-scraper download --start-date 2023-03-09T20:01Z --end-date 2024-03-09T20:01Z
    """
    configure_logger(debug)
    if debug:
        log.debug("Debug mode enabled")

    # Use the Click command from carbon_intensity_scraper.download
    download_command(
        output_directory=output_directory or "data",
        endpoint=endpoint,
        start_date=start_date,
        end_date=end_date,
        num_files=num_files,
        now=now,
        unique_names=unique_names,
        debug=debug,
    )


@cli.command()
@common_options
@click.option(
    "--input-directory",
    "-i",
    default="data",
    help="Path to input directory containing JSON files",
)
@click.option(
    "--delete-json", is_flag=True, help="Delete source JSON files once CSV is saved"
)
def wrangle(
    debug: bool,
    output_directory: Optional[str],
    endpoint: str,
    input_directory: str,
    delete_json: bool,
) -> None:
    """Save .CSV files from .json files."""
    configure_logger(debug)
    if debug:
        log.debug("Debug mode enabled")

    # TODO: Update to use carbon_intensity_scraper.wrangle
    raise NotImplementedError("Wrangle command not yet implemented")


@cli.command()
@common_options
@click.option(
    "--input-directory",
    "-i",
    default="data",
    help="Path to input directory containing CSV files",
)
@click.option(
    "--start-date",
    default=EARLIEST_DATE_STR,
    help=f"Start date in format {DATETIME_FMT_STR}",
)
@click.option("--end-date", default=None, help=f"End date in format {DATETIME_FMT_STR}")
@click.option(
    "--delete-old-files", is_flag=True, help="Delete CSV files once summarised"
)
def summary(
    debug: bool,
    output_directory: Optional[str],
    endpoint: str,
    input_directory: str,
    start_date: str,
    end_date: Optional[str],
    delete_old_files: bool,
) -> None:
    """Generate a summary of CSV files."""
    configure_logger(debug)
    if debug:
        log.debug("Debug mode enabled")

    # TODO: Update to use carbon_intensity_scraper.summary
    raise NotImplementedError("Summary command not yet implemented")


@cli.command()
@common_options
@click.option(
    "--input-directory",
    "-i",
    default="data",
    help="Path to input directory containing summary CSV files",
)
def graph(
    debug: bool,
    output_directory: Optional[str],
    endpoint: str,
    input_directory: str,
) -> None:
    """Generate graph images from summary CSV files."""
    configure_logger(debug)
    if debug:
        log.debug("Debug mode enabled")

    # TODO: Update to use carbon_intensity_scraper.graph
    raise NotImplementedError("Graph command not yet implemented")


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
