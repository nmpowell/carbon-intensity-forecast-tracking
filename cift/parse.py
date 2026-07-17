"""Turn raw API payloads into storage-ready observation rows. Pure: no I/O, no clock."""

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any

ENDPOINTS = (
    "national_fw48h",
    "national_pt24h",
    "regional_fw48h",
    "regional_pt24h",
    "national_generation_pt24h",
)

FUELS = (
    "biomass",
    "coal",
    "gas",
    "hydro",
    "imports",
    "nuclear",
    "other",
    "solar",
    "wind",
)

HALF_HOUR_SECONDS = 1800


def to_epoch(timestamp: str) -> int:
    """Convert an API timestamp like '2023-03-22T11:30Z' to unix seconds."""
    dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def floor_to_slot(dt: datetime) -> int:
    """Round a datetime down to its half-hour capture slot, as unix seconds."""
    epoch = int(dt.timestamp())
    return epoch - epoch % HALF_HOUR_SECONDS


@dataclass(frozen=True)
class Snapshot:
    """One endpoint's parsed response at one capture slot."""

    endpoint: str
    capture_utc: int
    observed_utc: int | None
    window_first_utc: int
    window_last_utc: int
    national: tuple[tuple[int, int, int | None, int | None], ...]
    regional: tuple[tuple[int | None, ...], ...]
    generation: tuple[tuple[int | None, ...], ...]
    # Migration provenance; live ingestion always uses the defaults.
    source: str = "live"
    gaps: tuple[tuple[int, int], ...] = ()  # (window_utc, region_id 0 = all)


class MalformedSnapshotError(Exception):
    """The response can't be trusted by reconstruction, so none of it is stored."""


def _fuel_tenths(endpoint: str, generationmix: list[dict[str, Any]]) -> tuple[int, ...]:
    names = [entry["fuel"] for entry in generationmix]
    if len(names) != len(FUELS) or set(names) != set(FUELS):
        raise MalformedSnapshotError(
            f"{endpoint}: expected exactly the fuel set {sorted(FUELS)}, got {sorted(names)}"
        )
    percs = {entry["fuel"]: entry["perc"] for entry in generationmix}
    tenths = []
    for fuel in FUELS:
        scaled = percs[fuel] * 10
        if abs(scaled - round(scaled)) > 1e-9:
            raise MalformedSnapshotError(
                f"{endpoint}: {fuel} percentage {percs[fuel]} has more than one decimal"
            )
        tenths.append(round(scaled))
    return tuple(tenths)


def _validate_horizon(endpoint: str, window_epochs: list[int]) -> None:
    if not window_epochs:
        raise MalformedSnapshotError(f"{endpoint}: no windows in response")
    for previous, current in zip(window_epochs, window_epochs[1:], strict=False):
        if current - previous != HALF_HOUR_SECONDS:
            raise MalformedSnapshotError(
                f"{endpoint}: windows are not contiguous half-hours"
                f" ({previous} -> {current})"
            )


def _validate_regions(endpoint: str, window: dict[str, Any]) -> None:
    region_ids = [region["regionid"] for region in window["regions"]]
    if len(region_ids) != 18 or set(region_ids) != set(range(1, 19)):
        raise MalformedSnapshotError(
            f"{endpoint}: expected 18 regions with unique ids 1-18, got {len(region_ids)}"
        )


def _validate_horizon_side(
    endpoint: str, window_epochs: list[int], capture_utc: int
) -> None:
    """fw48h horizons start at the capture slot; pt24h horizons end before it.

    This disjointness is what lets the fact tables omit an endpoint column: the
    same (window, capture) key can never be observed by both endpoint families.
    """
    if endpoint.endswith("fw48h"):
        if window_epochs[0] < capture_utc:
            raise MalformedSnapshotError(
                f"{endpoint}: forward horizon starts before its capture slot"
            )
    elif window_epochs[-1] >= capture_utc:
        raise MalformedSnapshotError(
            f"{endpoint}: past horizon reaches into its own capture slot"
        )


def parse_snapshot(
    endpoint: str, payload: dict[str, Any], capture_utc: int, observed_utc: int | None
) -> Snapshot:
    """Parse one endpoint payload into rows keyed by window and capture slot.

    Raises MalformedSnapshotError unless the response satisfies the completeness
    invariant: a contiguous half-hour horizon, all 18 regions, all 9 fuels, and
    one-decimal fuel percentages (what reconstruction relies on — see ADR-001).
    """
    windows = payload["data"]
    window_epochs = [to_epoch(w["from"]) for w in windows]
    _validate_horizon(endpoint, window_epochs)
    _validate_horizon_side(endpoint, window_epochs, capture_utc)
    national: list[tuple[int, int, int | None, int | None]] = []
    regional: list[tuple[int | None, ...]] = []
    generation: list[tuple[int | None, ...]] = []

    for window in windows:
        window_utc = to_epoch(window["from"])
        if endpoint == "national_generation_pt24h":
            generation.append(
                (
                    window_utc,
                    capture_utc,
                    *_fuel_tenths(endpoint, window["generationmix"]),
                )
            )
        elif endpoint.startswith("national"):
            intensity = window["intensity"]
            national.append(
                (
                    window_utc,
                    capture_utc,
                    intensity["forecast"],
                    intensity.get("actual"),
                )
            )
        else:
            _validate_regions(endpoint, window)
            for region in window["regions"]:
                regional.append(
                    (
                        window_utc,
                        region["regionid"],
                        capture_utc,
                        region["intensity"]["forecast"],
                        *_fuel_tenths(endpoint, region["generationmix"]),
                    )
                )

    window_epochs = [to_epoch(w["from"]) for w in windows]
    return Snapshot(
        endpoint=endpoint,
        capture_utc=capture_utc,
        observed_utc=observed_utc,
        window_first_utc=min(window_epochs),
        window_last_utc=max(window_epochs),
        national=tuple(national),
        regional=tuple(regional),
        generation=tuple(generation),
    )
