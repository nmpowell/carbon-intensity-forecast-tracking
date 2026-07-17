"""Fetch all endpoints for the current half-hour and record them as one inbox database."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from cift.client import Client
from cift.parse import ENDPOINTS
from cift.parse import floor_to_slot
from cift.parse import parse_snapshot
from cift.store import Store


def run_ingest(db_root: Path, now: datetime, client: Client) -> Path:
    """Snapshot every endpoint at `now`'s half-hour slot into a single inbox file.

    The API returns the window *before* an exact half-hour boundary, so the
    query time is the slot plus one minute (see README: Dates and times).
    """
    slot_utc = floor_to_slot(now)
    store = Store(db_root)
    existing = store.inbox_path(slot_utc)
    if existing.exists():
        return existing

    query_at = datetime.fromtimestamp(slot_utc, tz=timezone.utc) + timedelta(minutes=1)
    observed_utc = int(now.timestamp())

    snapshots = [
        parse_snapshot(
            endpoint, client.fetch(endpoint, query_at), slot_utc, observed_utc
        )
        for endpoint in ENDPOINTS
    ]
    return store.write_inbox(snapshots)
