"""HTTP adapter for the NESO Carbon Intensity API."""

import time
from datetime import datetime
from typing import Any
from typing import Protocol
from typing import cast

import requests

from cift.api import DATETIME_FMT_STR
from cift.api import TEMPLATE_URLS


class Client(Protocol):
    """What ingestion needs from an API client; tests substitute a fixture-backed fake."""

    def fetch(self, endpoint: str, at: datetime) -> dict[str, Any]: ...


class Session(Protocol):
    """The slice of requests.Session the client uses; tests substitute a fake."""

    def get(self, url: str, timeout: float) -> Any: ...


class CarbonIntensityClient:
    """Fetch one endpoint's JSON for the window containing `at`, with one retry."""

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        session: Session | None = None,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.session: Session = (
            session if session is not None else cast(Session, requests.Session())
        )
        self.retry_delay_seconds = retry_delay_seconds

    def fetch(self, endpoint: str, at: datetime) -> dict[str, Any]:
        url = TEMPLATE_URLS[endpoint].format(at.strftime(DATETIME_FMT_STR))
        for attempt in (1, 2):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
                return payload
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(self.retry_delay_seconds)
        raise AssertionError("unreachable")
