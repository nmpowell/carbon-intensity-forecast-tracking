"""No tracked source may import the deleted legacy package."""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def tracked_sources() -> list[Path]:
    files = [p for p in REPO.glob("cift/**/*.py")] + [
        p for p in REPO.glob("tests/**/*.py")
    ]
    files += list(REPO.glob("*.py")) + list(REPO.glob("*.ipynb"))
    return [p for p in files if "venv" not in p.parts]


class TestNoLegacyImports:
    def test_no_tracked_source_imports_the_scrape_package(self) -> None:
        offenders = []
        for path in tracked_sources():
            text = path.read_text(errors="ignore")
            if path.suffix == ".ipynb":
                text = "".join(
                    line
                    for cell in json.loads(text).get("cells", [])
                    for line in cell.get("source", [])
                )
            needles = ("from " + "scrape", "import " + "scrape")
            if any(needle in text for needle in needles):
                offenders.append(str(path.relative_to(REPO)))
        assert offenders == []
