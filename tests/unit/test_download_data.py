from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from scrape import download_data as dd


class TestDownloadData:
    def test_get_number_of_time_points(self):
        start = "2023-01-01T00:00Z"
        end = "2023-01-01T01:00Z"
        expected = 2
        result = dd.get_number_of_time_points(start, end)
        assert result == expected

    def test_round_down_datetime(self):
        dt = datetime(2022, 1, 1, 0, 15, tzinfo=timezone.utc)
        expected = datetime(2022, 1, 1, 0, 0, tzinfo=timezone.utc)
        result = dd.round_down_datetime(dt)
        assert result == expected

    def test_get_datetimes(self):
        start = "2023-01-01T13:31Z"
        end = "2023-01-01T14:29Z"
        expected_start = datetime(2023, 1, 1, 13, 30, tzinfo=timezone.utc)
        expected_end = datetime(2023, 1, 1, 14, 0, tzinfo=timezone.utc)
        result_start, result_end = dd.get_datetimes(start, end)
        assert result_start == expected_start
        assert result_end == expected_end
