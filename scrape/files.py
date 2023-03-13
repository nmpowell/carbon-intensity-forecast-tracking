import logging
import os

log = logging.getLogger(__name__)


def data_filepath(
    output_directory: str, datetime_str: str, extension: str = ".json"
) -> str:
    """Given a datetime string, return a filename."""
    return os.path.join(output_directory, datetime_str.replace(":", "") + extension)


def check_create_directory(directory: str = ""):
    """Recursively create a specified directory tree."""
    ndir = os.path.realpath(os.path.expanduser(os.path.normpath(directory)))
    if not os.path.exists(ndir):
        os.makedirs(ndir, exist_ok=True)
    return ndir


def get_json_files(directory: str) -> list:
    """Get a list of complete filepaths to JSON files in the given directory."""
    return [
        os.path.join(directory, fn)
        for fn in os.listdir(directory)
        if fn.lower().endswith(".json")
    ]
