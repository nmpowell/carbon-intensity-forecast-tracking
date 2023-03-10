import logging
import os

log = logging.getLogger(__name__)


def json_data_filepath(output_directory: str, datetime_str: str) -> str:
    """Given a datetime string, return a filename."""
    return os.path.join(output_directory, datetime_str.replace(":", "") + ".json")


def check_create_directory(directory: str = ""):
    """Recursively create a specified directory tree."""
    ndir = os.path.realpath(os.path.expanduser(os.path.normpath(directory)))
    if not os.path.exists(ndir):
        os.makedirs(ndir, exist_ok=True)
    return ndir
