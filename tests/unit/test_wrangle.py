import pandas as pd
import pytest

from scrape.wrangle import _national_json_to_csv


def test_national_json_to_csv():
    # Sample JSON data representing the national structure
    sample_data = [
        {
            "from": "2021-01-01T00:00Z",
            "to": "2021-01-01T01:00Z",
            "intensity": {"forecast": 100, "index": "low"},
            "generationmix": [
                {"fuel": "gas", "perc": 50},
                {"fuel": "wind", "perc": 50},
            ],
        },
        {
            "from": "2021-01-01T01:00Z",
            "to": "2021-01-01T02:00Z",
            "intensity": {"forecast": 200, "index": "moderate"},
            "generationmix": [
                {"fuel": "gas", "perc": 40},
                {"fuel": "wind", "perc": 60},
            ],
        },
    ]

    # Call the function being tested with the sample data
    result = _national_json_to_csv(sample_data)

    # Expected output DataFrame
    expected_output = pd.DataFrame(
        {
            "from": ["2021-01-01T00:00Z", "2021-01-01T01:00Z"],
            "intensity.forecast": [100, 200],
            "intensity.index": ["low", "moderate"],
        }
    ).set_index("from")

    # Check if the resulting DataFrame is equal to the expected output
    pd.testing.assert_frame_equal(result, expected_output)
