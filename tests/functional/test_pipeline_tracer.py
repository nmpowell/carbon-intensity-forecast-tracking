"""Walking-skeleton tests: the whole ingest → inbox → compact → read path, minimally."""

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import requests

from cift.ingest import run_ingest
from cift.store import Store
from tests.conftest import FixtureClient
from tests.conftest import utc


class TestIngestCompactRoundTrip:
    def test_ingest_then_compact_round_trips_one_snapshot_end_to_end(
        self, tmp_path: Path, five_endpoint_payloads: dict[str, Any]
    ) -> None:
        now = utc("2023-03-22T11:33Z")
        client = FixtureClient(five_endpoint_payloads)

        run_ingest(db_root=tmp_path, now=now, client=client)

        store = Store(tmp_path)
        store.compact(now=now + timedelta(days=2))
        window = utc("2023-03-22T11:30Z")
        trajectory = store.national_trajectory(window)

        assert trajectory == [(utc("2023-03-22T11:30Z"), 41, 43)]
        assert not list((tmp_path / "inbox").iterdir())

    def test_ingest_requests_the_current_half_hour_plus_one_minute(
        self, tmp_path: Path, five_endpoint_payloads: dict[str, Any]
    ) -> None:
        client = FixtureClient(five_endpoint_payloads)

        run_ingest(db_root=tmp_path, now=utc("2023-03-22T11:33Z"), client=client)

        assert len(client.requests) == 5
        assert {at for _, at in client.requests} == {utc("2023-03-22T11:31Z")}


class FailingClient:
    def fetch(self, endpoint: str, at: object) -> dict[str, Any]:
        raise requests.ConnectionError("api unreachable")


class TestIngestGuards:
    def test_a_rerun_in_the_same_slot_exits_successfully_without_writing(
        self, tmp_path: Path, five_endpoint_payloads: dict[str, Any]
    ) -> None:
        first = run_ingest(
            db_root=tmp_path,
            now=utc("2023-03-22T11:33Z"),
            client=FixtureClient(five_endpoint_payloads),
        )
        original = first.read_bytes()
        rerun_client = FixtureClient(five_endpoint_payloads)

        second = run_ingest(
            db_root=tmp_path, now=utc("2023-03-22T11:52Z"), client=rerun_client
        )

        assert second == first
        assert rerun_client.requests == []
        assert first.read_bytes() == original

    def test_an_api_error_leaves_no_inbox_file_at_all(self, tmp_path: Path) -> None:
        with pytest.raises(requests.ConnectionError):
            run_ingest(
                db_root=tmp_path, now=utc("2023-03-22T11:33Z"), client=FailingClient()
            )

        assert (
            not list((tmp_path / "inbox").glob("*"))
            or not (tmp_path / "inbox").exists()
        )

    def test_observed_utc_records_the_real_fetch_time_not_the_slot(
        self, tmp_path: Path, five_endpoint_payloads: dict[str, Any]
    ) -> None:
        now = utc("2023-03-22T11:33Z")

        inbox = run_ingest(
            db_root=tmp_path, now=now, client=FixtureClient(five_endpoint_payloads)
        )

        connection = sqlite3.connect(inbox)
        observed = {
            value
            for (value,) in connection.execute("SELECT observed_utc FROM captures")
        }
        connection.close()
        assert observed == {int(now.timestamp())}
