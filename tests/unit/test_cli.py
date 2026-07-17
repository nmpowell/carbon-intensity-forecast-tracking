"""CLI dispatch: the new commands thread arguments through to their functions."""

from pathlib import Path
from unittest import mock

import pytest

import cift.ingest
import cift.store
from cift import cli


class TestNewCommandDispatch:
    def test_ingest_dispatches_with_a_real_client_and_clock(self) -> None:
        with mock.patch.object(cift.ingest, "run_ingest") as run:
            cli.main(["ingest", "--db_root", "data/db"])

        _, kwargs = run.call_args
        assert kwargs["db_root"] == Path("data/db")
        assert kwargs["now"].tzinfo is not None
        assert hasattr(kwargs["client"], "fetch")

    def test_compact_dispatches_and_prints_the_report(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = cift.store.CompactReport(
            merged_inboxes=3, remaining_inboxes=1, quarantined=("snap_x.sqlite",)
        )
        with mock.patch.object(cift.store.Store, "compact", return_value=report):
            cli.main(["compact", "--db_root", "data/db", "--max_inboxes", "500"])

        printed = capsys.readouterr().out
        assert "merged=3" in printed
        assert "remaining=1" in printed
        assert "quarantined=snap_x.sqlite" in printed
