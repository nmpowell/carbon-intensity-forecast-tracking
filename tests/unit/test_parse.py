"""Parsing and the completeness invariant: reject anything reconstruction can't trust."""

import pytest

from cift.parse import MalformedSnapshotError
from cift.parse import floor_to_slot
from cift.parse import parse_snapshot
from tests.conftest import generation_payload
from tests.conftest import load_fixture
from tests.conftest import national_payload
from tests.conftest import regional_payload
from tests.conftest import utc

SLOT = floor_to_slot(utc("2023-03-22T11:31Z"))


AFTER_FIXTURE_WINDOWS = floor_to_slot(utc("2023-03-22T13:01Z"))


class TestParseSnapshot:
    def test_parses_every_endpoint_fixture_into_rows(self) -> None:
        national = parse_snapshot(
            "national_fw48h", load_fixture("national/2023-03-22T1131Z.json"), SLOT, SLOT
        )
        regional = parse_snapshot(
            "regional_fw48h", load_fixture("regional/2023-03-22T1131Z.json"), SLOT, SLOT
        )
        generation = parse_snapshot(
            "national_generation_pt24h",
            load_fixture("generationmix/2023-03-23T1131Z.json"),
            AFTER_FIXTURE_WINDOWS,
            AFTER_FIXTURE_WINDOWS,
        )

        assert national.national[0] == (SLOT, SLOT, 41, 43)
        assert len(regional.regional) == 3 * 18
        assert regional.regional[0][:4] == (SLOT, 1, SLOT, 0)
        assert len(generation.generation) == 3

    def test_null_actuals_stay_null_and_fuels_store_as_tenths(self) -> None:
        national = parse_snapshot(
            "national_fw48h",
            national_payload(("2023-03-22T11:30Z", 41, None)),
            SLOT,
            SLOT,
        )
        regional = parse_snapshot(
            "regional_fw48h",
            regional_payload(
                ("2023-03-22T11:30Z", 50), mix={"wind": 34.5, "gas": 65.5}
            ),
            SLOT,
            SLOT,
        )

        assert national.national[0] == (SLOT, SLOT, 41, None)
        gas, wind = regional.regional[0][6], regional.regional[0][12]
        assert (gas, wind) == (655, 345)

    def test_a_noncontiguous_horizon_rejects_the_endpoint(self) -> None:
        payload = national_payload(
            ("2023-03-22T11:30Z", 41, None),
            ("2023-03-22T13:00Z", 42, None),  # 12:00 and 12:30 missing
        )

        with pytest.raises(MalformedSnapshotError, match="contiguous"):
            parse_snapshot("national_fw48h", payload, SLOT, SLOT)

    def test_a_missing_region_rejects_the_endpoint(self) -> None:
        payload = regional_payload(
            ("2023-03-22T11:30Z", 50), region_ids=tuple(range(1, 18))
        )

        with pytest.raises(MalformedSnapshotError, match="18 regions"):
            parse_snapshot("regional_fw48h", payload, SLOT, SLOT)

    def test_a_missing_fuel_rejects_the_endpoint(self) -> None:
        payload = generation_payload("2023-03-22T11:00Z")
        del payload["data"][0]["generationmix"][3]

        with pytest.raises(MalformedSnapshotError, match="fuel"):
            parse_snapshot("national_generation_pt24h", payload, SLOT, SLOT)

    def test_a_second_decimal_in_a_fuel_percentage_rejects_the_endpoint(self) -> None:
        payload = generation_payload("2023-03-22T11:00Z", mix={"wind": 12.34})

        with pytest.raises(MalformedSnapshotError, match="one decimal"):
            parse_snapshot("national_generation_pt24h", payload, SLOT, SLOT)

    def test_an_empty_response_rejects_the_endpoint(self) -> None:
        with pytest.raises(MalformedSnapshotError, match="no windows"):
            parse_snapshot("national_fw48h", {"data": []}, SLOT, SLOT)

    def test_a_contiguous_short_horizon_is_accepted_with_true_coverage(self) -> None:
        payload = national_payload(("2023-03-22T11:30Z", 41, None))

        snapshot = parse_snapshot("national_fw48h", payload, SLOT, SLOT)

        assert (snapshot.window_first_utc, snapshot.window_last_utc) == (SLOT, SLOT)

    def test_a_duplicate_region_rejects_the_endpoint(self) -> None:
        payload = regional_payload(("2023-03-22T11:30Z", 50))
        payload["data"][0]["regions"].append(dict(payload["data"][0]["regions"][0]))

        with pytest.raises(MalformedSnapshotError, match="unique ids"):
            parse_snapshot("regional_fw48h", payload, SLOT, SLOT)

    def test_a_duplicate_fuel_rejects_the_endpoint(self) -> None:
        payload = generation_payload("2023-03-22T11:00Z", mix={"wind": 50.0})
        payload["data"][0]["generationmix"].append({"fuel": "wind", "perc": 10.0})

        with pytest.raises(MalformedSnapshotError, match="exactly the fuel set"):
            parse_snapshot("national_generation_pt24h", payload, SLOT, SLOT)

    def test_a_forward_horizon_starting_before_its_capture_rejects(self) -> None:
        payload = national_payload(("2023-03-22T11:00Z", 41, None))

        with pytest.raises(MalformedSnapshotError, match="before its capture slot"):
            parse_snapshot("national_fw48h", payload, SLOT, SLOT)

    def test_a_past_horizon_reaching_its_capture_slot_rejects(self) -> None:
        payload = national_payload(("2023-03-22T11:30Z", 41, 43))

        with pytest.raises(
            MalformedSnapshotError, match="reaches into its own capture"
        ):
            parse_snapshot("national_pt24h", payload, SLOT, SLOT)
