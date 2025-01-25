#!/usr/bin/env python3
"""Example script demonstrating database creation and population."""

import logging
from pathlib import Path
from typing import Tuple

from carbon_intensity_scraper.db import CarbonIntensityDB

# Set up logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def process_directory(
    db: CarbonIntensityDB, directory: Path, endpoint: str
) -> Tuple[int, int]:
    """Process all JSON files in a directory.

    Args:
        db: Database instance
        directory: Directory containing JSON files
        endpoint: API endpoint name

    Returns:
        Tuple of (total forecasts stored, total actuals stored)
    """
    total_forecasts = 0
    total_actuals = 0

    # Process each JSON file in the directory
    for json_file in sorted(directory.glob("*.json")):
        try:
            forecasts, actuals = db.store_snapshot(json_file, endpoint)
            total_forecasts += forecasts
            total_actuals += actuals
            log.info(
                f"Processed {json_file.name}: {forecasts} forecasts, "
                f"{actuals} actuals"
            )
        except Exception as e:
            log.error(f"Error processing {json_file}: {e}")

    return total_forecasts, total_actuals


def main() -> None:
    """Create database and populate with all available data."""
    # Create database in the data directory
    db_path = Path("data/carbon_intensity.db")

    with CarbonIntensityDB(db_path) as db:
        # Process forward-looking forecasts (fw48h)
        fw48h_dir = Path("data/national_fw48h")
        log.info(f"\nProcessing forward-looking forecasts from {fw48h_dir}")
        fw48h_forecasts, fw48h_actuals = process_directory(
            db, fw48h_dir, "national_fw48h"
        )
        log.info(
            f"Total fw48h data stored: {fw48h_forecasts} forecasts, "
            f"{fw48h_actuals} actuals"
        )

        # Process past 24h data (pt24h)
        pt24h_dir = Path("data/national_pt24h")
        log.info(f"\nProcessing past 24h data from {pt24h_dir}")
        pt24h_forecasts, pt24h_actuals = process_directory(
            db, pt24h_dir, "national_pt24h"
        )
        log.info(
            f"Total pt24h data stored: {pt24h_forecasts} forecasts, "
            f"{pt24h_actuals} actuals"
        )

        total_forecasts = fw48h_forecasts + pt24h_forecasts
        total_actuals = fw48h_actuals + pt24h_actuals
        log.info(
            f"\nGrand total: {total_forecasts} forecasts, " f"{total_actuals} actuals"
        )

        # Query some recent data to verify storage
        log.info("\nVerifying data storage with a sample query:")
        results = db.get_forecast_vs_actual("2023-10-20T00:00Z", "2023-10-20T01:00Z")
        for row in results:
            log.info(
                f"Time window: {row['time_from']} - {row['time_to']}\n"
                f"Forecast: {row['forecast_value']} gCO2/kWh\n"
                f"Actual: {row['actual_value']} gCO2/kWh\n"
                f"Intensity: {row['intensity']}\n"
                f"Forecast made at: {row['forecast_made_at']}\n"
            )


if __name__ == "__main__":
    main()
