import argparse
import logging

from pythonjsonlogger import jsonlogger

from scrape import download_data

log = logging.getLogger(__name__)


PIPELINE_FUNCTIONS = {"download": download_data}


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

    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    # positional argument for choosing the function to be called
    subparsers = parser.add_subparsers(dest="func")
    subparsers.add_parser(
        "download", help="Download JSON files.", parents=[common_parser]
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
        parser.print_help()


if __name__ == "__main__":
    main()

# End
