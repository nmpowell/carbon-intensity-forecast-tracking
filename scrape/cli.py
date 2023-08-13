import argparse
import logging
from importlib import import_module

from pythonjsonlogger import jsonlogger

from scrape.api import DATETIME_FMT_STR
from scrape.api import EARLIEST_DATE_STR
from scrape.api import TEMPLATE_URLS

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


def get_parser():
    parser = argparse.ArgumentParser(description="Choose function and get arguments.")

    parser_common = argparse.ArgumentParser(add_help=False)
    parser_common.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser_common.add_argument(
        "--output_directory",
        "-o",
        default=None,
        help="Path to output directory",
        type=str,
    )
    parser_common.add_argument(
        "--endpoint",
        choices=TEMPLATE_URLS.keys(),
        default="regional_fw48h",
        type=str,
        help="Endpoint to use. Options: {}".format(TEMPLATE_URLS.keys()),
    )

    # positional argument for choosing the pipeline function to be called
    subparsers = parser.add_subparsers(dest="func")
    parser_download = subparsers.add_parser(
        "download",
        aliases=["download_regional"],
        help="Download JSON file(s) from the API.",
        parents=[parser_common],
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
        default=EARLIEST_DATE_STR,
        type=str,
        help="Start date in format {}".format(DATETIME_FMT_STR),
    )
    parser_download.add_argument(
        "--end_date",
        default=None,
        type=str,
        help="End date in format {}".format(DATETIME_FMT_STR),
    )
    parser_download.add_argument(
        "--unique_names", action="store_true", help="Use a unique name for each file."
    )

    parser_wrangle = subparsers.add_parser(
        "wrangle",
        help="Save .CSV files from .json files.",
        parents=[parser_common],
    )

    parser_wrangle.add_argument(
        "--input_directory",
        "-i",
        default="data",
        help="Path to input directory containing JSON files",
        type=str,
    )
    parser_wrangle.add_argument(
        "--delete_json",
        action="store_true",
        help="Delete source JSON files once CSV is saved.",
    )
    parser_wrangle.add_argument(
        "--delete_old_files",
        action="store_true",
        help="Delete CSV files once summarised.",
    )

    parser_summary = subparsers.add_parser(
        "summary",
        help="Generate a summary of CSV files.",
        parents=[parser_common],
    )

    parser_summary.add_argument(
        "--input_directory",
        "-i",
        default="data",
        help="Path to input directory containing CSV files",
        type=str,
    )
    parser_summary.add_argument(
        "--start_date",
        default=EARLIEST_DATE_STR,
        type=str,
        help="Start date in format {}".format(DATETIME_FMT_STR),
    )
    parser_summary.add_argument(
        "--end_date",
        default=None,
        type=str,
        help="End date in format {}".format(DATETIME_FMT_STR),
    )

    parser_graph = subparsers.add_parser(
        "graph",
        help="Generate graph images from summary CSV files.",
        parents=[parser_common],
    )

    parser_graph.add_argument(
        "--input_directory",
        "-i",
        default="data",
        help="Path to input directory containing summary CSV files",
        type=str,
    )

    return parser


def main() -> None:
    args = get_parser().parse_args()
    configure_logger(args.debug)

    if args.debug:
        log.debug("Debug mode enabled")

    if fn := PIPELINE_FUNCTIONS.get(args.func):
        module = import_module("scrape." + args.func)
        function = getattr(module, fn)
        function(**vars(args))
    else:
        get_parser().print_help()


if __name__ == "__main__":
    main()

# End
