import json
import os
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest

# Chart tests must never open a display; conftest runs before any test module
# imports pyplot, so the backend choice lands in time.
os.environ.setdefault("MPLBACKEND", "Agg")

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def utc(spec: str) -> datetime:
    """Parse '2023-03-22T11:33Z' into an aware datetime."""
    return datetime.strptime(spec, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


class FixtureClient:
    """Test double for CarbonIntensityClient: serves canned payloads, records requests."""

    def __init__(self, payloads: dict[str, Any]):
        self.payloads = payloads
        self.requests: list[tuple[str, datetime]] = []

    def fetch(self, endpoint: str, at: datetime) -> dict[str, Any]:
        self.requests.append((endpoint, at))
        return self.payloads[endpoint]


def national_payload(*windows: tuple[str, int | None, int | None]) -> dict[str, Any]:
    """Build a national intensity payload: windows are ('from', forecast, actual)."""
    return {
        "data": [
            {
                "from": start,
                "intensity": {"forecast": forecast, "actual": actual, "index": "low"},
            }
            for start, forecast, actual in windows
        ]
    }


def _mix(perc_by_fuel: dict[str, float] | None = None) -> list[dict[str, Any]]:
    fuels = [
        "biomass",
        "coal",
        "gas",
        "hydro",
        "imports",
        "nuclear",
        "other",
        "solar",
        "wind",
    ]
    percs = perc_by_fuel or {}
    return [{"fuel": fuel, "perc": percs.get(fuel, 0.0)} for fuel in fuels]


ALL_REGION_IDS = tuple(range(1, 19))


def regional_payload(
    *windows: tuple[str, int],
    region_ids: tuple[int, ...] = ALL_REGION_IDS,
    mix: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build a regional payload: windows are ('from', forecast) applied to every region."""
    return {
        "data": [
            {
                "from": start,
                "regions": [
                    {
                        "regionid": region_id,
                        "intensity": {"forecast": forecast, "index": "low"},
                        "generationmix": _mix(mix),
                    }
                    for region_id in region_ids
                ],
            }
            for start, forecast in windows
        ]
    }


def generation_payload(
    *windows: str, mix: dict[str, float] | None = None
) -> dict[str, Any]:
    return {"data": [{"from": start, "generationmix": _mix(mix)} for start in windows]}


@pytest.fixture
def five_endpoint_payloads() -> dict[str, Any]:
    """Realistic shapes for one 11:30 capture: fw48h fixtures start at the slot,
    pt24h payloads lie strictly before it (the disjointness parse enforces)."""
    past = ["2023-03-22T10:00Z", "2023-03-22T10:30Z", "2023-03-22T11:00Z"]
    return {
        "national_fw48h": load_fixture("national/2023-03-22T1131Z.json"),
        "national_pt24h": national_payload(*[(window, 41, 43) for window in past]),
        "regional_fw48h": load_fixture("regional/2023-03-22T1131Z.json"),
        "regional_pt24h": regional_payload(*[(window, 50) for window in past]),
        "national_generation_pt24h": generation_payload(*past),
    }
