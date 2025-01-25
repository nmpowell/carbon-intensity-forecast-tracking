"""Example usage of the CarbonIntensityDB class."""

import logging
from pathlib import Path
from typing import Any, Dict, List

from carbon_intensity_scraper.db import CarbonIntensityDB

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def print_results(results: List[Dict[str, Any]], title: str) -> None:
    """Print query results in a formatted way.

    Args:
        results: List of result dictionaries
        title: Title to display above results
    """
    print(f"\n{title}")
    print("-" * len(title))

    for row in results:
        # Format the row based on what fields are present
        if "forecast_made_at" in row:
            print(
                f"Made at {row['forecast_made_at']}: "
                f"forecast={row['forecast_value']}, "
                f"intensity={row['intensity']}"
            )
        else:
            print(
                f"{row['time_from']}: "
                f"forecast={row['forecast_value']}, "
                f"actual={row['actual_value']}, "
                f"intensity={row['intensity']}"
            )


def main() -> None:
    """Run the database example."""
    # Initialize database in the data directory
    db_path = Path("data/carbon_intensity.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Initializing database at %s", db_path)

    with CarbonIntensityDB(db_path) as db:
        # Store data from JSON files
        fw48h_file = Path("data/national_fw48h/2025-01-25T1431Z.json")
        pt24h_file = Path("data/national_pt24h/2025-01-25T1431Z.json")

        # Store forward forecast
        log.info("Storing forward forecast data from %s", fw48h_file)
        forecasts, actuals = db.store_snapshot(fw48h_file, "national_fw48h")
        log.info("Stored %d forecasts and %d actuals", forecasts, actuals)

        # Store past data
        log.info("Storing past data from %s", pt24h_file)
        forecasts, actuals = db.store_snapshot(pt24h_file, "national_pt24h")
        log.info("Stored %d forecasts and %d actuals", forecasts, actuals)

        # Example 1: Get forecast vs actual for a specific time range
        results = db.get_forecast_vs_actual("2025-01-24T14:30Z", "2025-01-24T15:30Z")
        print_results(results, "Forecast vs Actual (1 hour window)")

        # Example 2: Get forecast history for a specific time window
        history = db.get_forecast_history("2025-01-25T14:30Z", "2025-01-25T15:00Z")
        print_results(history, "Forecast History (single time window)")

        # Example 3: Get all forecasts for a longer time period
        results = db.get_forecast_vs_actual(
            "2025-01-24T14:30Z",  # Start of pt24h data
            "2025-01-27T14:30Z",  # End of fw48h data
        )

        # Print some statistics
        total = len(results)
        with_actual = sum(1 for r in results if r["actual_value"] is not None)
        print("\nStatistics")
        print("-" * 10)
        print(f"Total time windows: {total}")
        print(f"Windows with actual values: {with_actual}")
        print(f"Windows with only forecasts: {total - with_actual}")


if __name__ == "__main__":
    main()
