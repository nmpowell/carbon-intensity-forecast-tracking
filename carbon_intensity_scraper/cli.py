import logging
from importlib import import_module
from typing import Optional

import click
from pythonjsonlogger import jsonlogger

from scrape.api import DATETIME_FMT_STR, EARLIEST_DATE_STR, TEMPLATE_URLS

log = logging.getLogger(__name__)

PIPELINE_FUNCTIONS = {
    "download": "run_download",
    "wrangle": "run_wrangle",
    "summary": "run_summary",
    "graph": "create_graph_images",
}


def configure_logger(debug: bool = False) -> None:
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    logging.basicConfig(
        handlers=[handler], level=logging.DEBUG if debug else logging.INFO
    )


# Common options as function decorators
def common_options(f) -> click.Command:
    f = click.option("--debug/--no-debug", default=False, help="Enable debug logging")(
        f
    )
    f = click.option(
        "--output-directory", "-o", default=None, help="Path to output directory"
    )(f)
    f = click.option(
        "--endpoint",
        type=click.Choice(list(TEMPLATE_URLS.keys())),
        default="regional_fw48h",
        help="Endpoint to use",
    )(f)
    return f


@click.group()
def cli() -> None:
    """Carbon Intensity Forecast Tracking CLI"""
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
    endpoint: str,  # type: ignore
    now: bool,
    num_files: int,
    start_date: str,
    end_date: Optional[str],
    unique_names: bool,
):
    """Download JSON file(s) from the API."""
    configure_logger(debug)
    if debug:
        log.debug("Debug mode enabled")

    module = import_module("scrape.download")
    function = getattr(module, PIPELINE_FUNCTIONS["download"])
    function(
        debug=debug,
        output_directory=output_directory,
        endpoint=endpoint,
        now=now,
        num_files=num_files,
        start_date=start_date,
        end_date=end_date,
        unique_names=unique_names,
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
    endpoint: str,  # type: ignore
    input_directory: str,
    delete_json: bool,
):
    """Save .CSV files from .json files."""
    configure_logger(debug)
    if debug:
        log.debug("Debug mode enabled")

    module = import_module("scrape.wrangle")
    function = getattr(module, PIPELINE_FUNCTIONS["wrangle"])
    function(
        debug=debug,
        output_directory=output_directory,
        endpoint=endpoint,
        input_directory=input_directory,
        delete_json=delete_json,
    )


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
    endpoint: str,  # type: ignore
    input_directory: str,
    start_date: str,
    end_date: Optional[str],
    delete_old_files: bool,
):
    """Generate a summary of CSV files."""
    configure_logger(debug)
    if debug:
        log.debug("Debug mode enabled")

    module = import_module("scrape.summary")
    function = getattr(module, PIPELINE_FUNCTIONS["summary"])
    function(
        debug=debug,
        output_directory=output_directory,
        endpoint=endpoint,
        input_directory=input_directory,
        start_date=start_date,
        end_date=end_date,
        delete_old_files=delete_old_files,
    )


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
    endpoint: str,  # type: ignore
    input_directory: str,
):
    """Generate graph images from summary CSV files."""
    configure_logger(debug)
    if debug:
        log.debug("Debug mode enabled")

    module = import_module("scrape.graph")
    function = getattr(module, PIPELINE_FUNCTIONS["graph"])
    function(
        debug=debug,
        output_directory=output_directory,
        endpoint=endpoint,
        input_directory=input_directory,
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
