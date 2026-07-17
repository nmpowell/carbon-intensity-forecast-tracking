"""HTTP client behaviour: timeout wiring and one retry on transient failure."""

from typing import Any

import pytest
import requests

from cift.client import CarbonIntensityClient
from tests.conftest import utc


class FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self.payload


class FlakySession:
    def __init__(self, failures: int, payload: dict[str, Any]):
        self.failures = failures
        self.payload = payload
        self.calls: list[str] = []

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.calls.append(url)
        if len(self.calls) <= self.failures:
            raise requests.ConnectionError("transient blip")
        return FakeResponse(self.payload)


class TestFetchRetry:
    def test_fetch_retries_once_on_a_transient_error(self) -> None:
        session = FlakySession(failures=1, payload={"data": ["ok"]})
        client = CarbonIntensityClient(session=session, retry_delay_seconds=0)

        payload = client.fetch("national_fw48h", utc("2023-03-22T11:31Z"))

        assert payload == {"data": ["ok"]}
        assert len(session.calls) == 2
        assert session.calls[0].endswith("/intensity/2023-03-22T11:31Z/fw48h")

    def test_fetch_raises_after_the_retry_also_fails(self) -> None:
        session = FlakySession(failures=2, payload={})
        client = CarbonIntensityClient(session=session, retry_delay_seconds=0)

        with pytest.raises(requests.ConnectionError, match="transient blip"):
            client.fetch("national_fw48h", utc("2023-03-22T11:31Z"))

        assert len(session.calls) == 2
