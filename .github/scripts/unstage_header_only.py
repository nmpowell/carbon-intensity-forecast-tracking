"""Drop staged SQLite files whose only change is the header counters.

Opening a database read-write bumps SQLite's file change counter (header bytes
24-27) and version-valid-for number (bytes 92-95). That rewrites the file
without touching a single row, and committing it re-adds the whole partition as
a fresh blob. cift.store._open avoids those writes; this is the backstop that
keeps a regression from silently re-inflating the repository.
"""

import subprocess
import sys

# Header fields SQLite rewrites on any write transaction, data unchanged: the
# file change counter, the version-valid-for number, and the version of the
# library that did the writing. Every byte outside them is schema or data, so a
# file differing only here is byte-for-byte the same database.
_WRITE_METADATA_BYTES = (
    frozenset(range(24, 28))  # file change counter
    | frozenset(range(92, 96))  # version-valid-for number
    | frozenset(range(96, 100))  # SQLITE_VERSION_NUMBER of the last writer
)


def _git(*args: str) -> bytes:
    return subprocess.run(("git", *args), check=True, stdout=subprocess.PIPE).stdout


def _header_only(path: str) -> bool:
    head, staged = _git("show", f"HEAD:{path}"), _git("show", f":{path}")
    if len(head) != len(staged):
        return False
    return all(
        index in _WRITE_METADATA_BYTES
        for index, (before, after) in enumerate(zip(head, staged, strict=True))
        if before != after
    )


def main() -> int:
    listed = _git(
        "diff", "--cached", "--name-only", "--diff-filter=M", "-z", "--", "*.sqlite"
    )
    paths = [name for name in listed.decode().split("\0") if name]
    dropped = [path for path in paths if _header_only(path)]
    for path in dropped:
        _git("restore", "--source=HEAD", "--staged", "--worktree", "--", path)
        print(f"unstaged (header-only change): {path}")
    print(f"{len(dropped)}/{len(paths)} staged .sqlite files were header-only churn")
    return 0


if __name__ == "__main__":
    sys.exit(main())
