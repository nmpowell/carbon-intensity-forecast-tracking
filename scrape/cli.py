import argparse
import logging

from pythonjsonlogger import jsonlogger

from scrape import download_data
from scrape.urls import TEMPLATE_URLS

log = logging.getLogger(__name__)


PIPELINE_FUNCTIONS = {
    "download": download_data.run,
    # "wrangle": wrangle.run,
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


def get_parser():
    parser = argparse.ArgumentParser(description="Choose function and get arguments.")

    parser_common = argparse.ArgumentParser(add_help=False)
    parser_common.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    # positional argument for choosing the pipeline function to be called
    subparsers = parser.add_subparsers(dest="func")
    parser_download = subparsers.add_parser(
        "download", help="Download JSON file(s) from the API.", parents=[parser_common]
    )

    parser_download.add_argument(
        "--output_directory",
        "-o",
        default="data",
        help="Path to output directory",
        type=str,
    )
    parser_download.add_argument(
        "--endpoint",
        choices=TEMPLATE_URLS.keys(),
        default="regional_forward",
        type=str,
        help="Endpoint to use. Options: {}".format(TEMPLATE_URLS.keys()),
    )
    parser_download.add_argument(
        "--now", action="store_true", help="Download current data and nothing else."
    )
    parser_download.add_argument(
        "--num_files",
        "-n",
        default=0,
        type=int,
        help="Max number of files. All if 0 or not specified.",
    )
    parser_download.add_argument(
        "--start_date",
        default=download_data.EARLIEST_DATE_STR,
        type=str,
        help="Start date in format {}".format(download_data.DATETIME_FMT_STR),
    )
    parser_download.add_argument(
        "--end_date",
        default=None,
        type=str,
        help="End date in format {}".format(download_data.DATETIME_FMT_STR),
    )
    return parser


def main() -> None:
    args = get_parser().parse_args()
    configure_logger(args.debug)

    if args.debug:
        log.debug("Debug mode enabled")

    if fn := PIPELINE_FUNCTIONS.get(args.func):
        fn(**vars(args))
    else:
        get_parser().print_help()


if __name__ == "__main__":
    main()

# End
