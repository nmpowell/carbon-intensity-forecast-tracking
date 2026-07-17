"""Splice generated content into README sections bounded by explicit markers."""


def splice(text: str, name: str, replacement: str) -> str:
    """Replace the content between <!-- cift:name:start --> and its end marker.

    Raises rather than guessing when a marker is absent — the legacy
    heading-based splicer silently prepended to the top of the file.
    """
    start = f"<!-- cift:{name}:start -->"
    end = f"<!-- cift:{name}:end -->"
    if start not in text or end not in text:
        raise ValueError(
            f"README markers for 'cift:{name}' not found; refusing to write"
        )
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{start}\n{replacement}\n{end}{tail}"
