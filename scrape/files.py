import logging
import os
import shutil

log = logging.getLogger(__name__)


def data_filepath(
    output_directory: str, datetime_str: str, extension: str = ".json"
) -> str:
    """Given a datetime string, return a filename."""
    return os.path.join(output_directory, datetime_str.replace(":", "") + extension)


def get_csv_path(output_directory: str, filepath: str) -> str:
    """Given a JSON filepath, return the CSV filepath."""
    return os.path.join(
        output_directory,
        os.path.basename(filepath.replace(".json", ".csv")),
    )


def move_to_subdirectory(filepath: str, subdirectory_name: str = "_archive") -> None:
    target_directory = os.path.join(os.path.dirname(filepath), subdirectory_name)
    _ = check_create_directory(target_directory)
    # provide the full target path to force overwriting
    shutil.move(filepath, os.path.join(target_directory, os.path.basename(filepath)))


def check_create_directory(directory: str = ""):
    """Recursively create a specified directory tree."""
    ndir = os.path.realpath(os.path.expanduser(os.path.normpath(directory)))
    if not os.path.exists(ndir):
        os.makedirs(ndir, exist_ok=True)
    return ndir


def get_data_files(directory: str, extension: str = ".json", filter: str = "") -> list:
    """Get a list of complete filepaths to data files in the given directory."""
    try:
        return [
            os.path.join(directory, fn)
            for fn in os.listdir(directory)
            if fn.lower().endswith(extension.lower()) and filter.lower() in fn.lower()
        ]
    except FileNotFoundError:
        log.error("Directory %s does not exist", directory)
        return []
