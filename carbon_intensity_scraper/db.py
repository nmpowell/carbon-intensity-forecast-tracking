"""
SQLite database operations for carbon intensity data.

This module provides functionality to store and retrieve carbon intensity data
from a SQLite database, with proper normalization and efficient querying.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Type

log = logging.getLogger(__name__)

# SQL statements for creating tables
CREATE_TABLES_SQL = """
-- Store unique time windows
CREATE TABLE IF NOT EXISTS time_windows (
    id INTEGER PRIMARY KEY,
    time_from DATETIME NOT NULL,
    time_to DATETIME NOT NULL,
    UNIQUE(time_from, time_to)
);

-- Store unique intensity indices
CREATE TABLE IF NOT EXISTS intensity_indices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- Store API snapshot times
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    captured_at DATETIME NOT NULL,
    endpoint TEXT NOT NULL,
    UNIQUE(captured_at, endpoint)
);

-- Store forecast values
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL,
    time_window_id INTEGER NOT NULL,
    forecast_value INTEGER NOT NULL,
    intensity_index_id INTEGER NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES snapshots(id),
    FOREIGN KEY(time_window_id) REFERENCES time_windows(id),
    FOREIGN KEY(intensity_index_id) REFERENCES intensity_indices(id),
    UNIQUE(snapshot_id, time_window_id)
);

-- Store actual values (only for pt24h)
CREATE TABLE IF NOT EXISTS actuals (
    id INTEGER PRIMARY KEY,
    time_window_id INTEGER NOT NULL,
    actual_value INTEGER,
    last_updated DATETIME NOT NULL,
    FOREIGN KEY(time_window_id) REFERENCES time_windows(id),
    UNIQUE(time_window_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_time_windows_from ON time_windows(time_from);
CREATE INDEX IF NOT EXISTS idx_time_windows_to ON time_windows(time_to);
CREATE INDEX IF NOT EXISTS idx_forecasts_snapshot ON forecasts(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_forecasts_time_window ON forecasts(time_window_id);
CREATE INDEX IF NOT EXISTS idx_actuals_time_window ON actuals(time_window_id);
"""

class CarbonIntensityDB:
    """Handle SQLite database operations for carbon intensity data."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        """Initialize database connection and create tables if needed.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        
        # Enable foreign key constraints
        self.conn.execute("PRAGMA foreign_keys = ON")
        
        # Create tables if they don't exist
        with self.conn:
            self.conn.executescript(CREATE_TABLES_SQL)
            
        # Pre-populate intensity indices if needed
        self._ensure_intensity_indices()

    def _ensure_intensity_indices(self) -> None:
        """Ensure all intensity index values exist in the database."""
        indices = ["very low", "low", "moderate", "high", "very high"]
        with self.conn:
            for index in indices:
                self.conn.execute(
                    "INSERT OR IGNORE INTO intensity_indices (name) VALUES (?)",
                    (index,)
                )

    def get_or_create_time_window(self, time_from: str, time_to: str) -> int:
        """Get or create a time window and return its ID.
        
        Args:
            time_from: Start time in ISO format
            time_to: End time in ISO format
            
        Returns:
            ID of the time window
        """
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO time_windows (time_from, time_to)
                VALUES (?, ?)
                """,
                (time_from, time_to)
            )
            
            if cursor.rowcount == 0:
                cursor = self.conn.execute(
                    "SELECT id FROM time_windows WHERE time_from = ? AND time_to = ?",
                    (time_from, time_to)
                )
            
            return cursor.fetchone()[0]

    def get_intensity_index_id(self, index_name: str) -> int:
        """Get the ID for an intensity index.
        
        Args:
            index_name: Name of the intensity index
            
        Returns:
            ID of the intensity index
            
        Raises:
            ValueError: If index_name is not valid
        """
        cursor = self.conn.execute(
            "SELECT id FROM intensity_indices WHERE name = ?",
            (index_name,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Invalid intensity index: {index_name}")
        return row[0]

    def store_snapshot(
        self,
        json_path: Union[str, Path],
        endpoint: str
    ) -> Tuple[int, int]:
        """Store a JSON snapshot in the database.
        
        Args:
            json_path: Path to JSON file
            endpoint: API endpoint name
            
        Returns:
            Tuple of (number of forecasts stored, number of actuals stored)
            
        Raises:
            FileNotFoundError: If JSON file doesn't exist
            json.JSONDecodeError: If JSON is invalid
            sqlite3.Error: If database operation fails
        """
        json_path = Path(json_path)
        if not json_path.exists():
            raise FileNotFoundError(f"JSON file not found: {json_path}")
            
        # Extract capture time from filename
        captured_at = json_path.stem  # e.g., "2025-01-25T1431Z"
        
        # Read and parse JSON
        with open(json_path) as f:
            data = json.load(f)
            
        forecasts_stored = 0
        actuals_stored = 0
        
        with self.conn:
            # Store snapshot
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO snapshots (captured_at, endpoint)
                VALUES (?, ?)
                """,
                (captured_at, endpoint)
            )
            
            if cursor.rowcount == 0:
                cursor = self.conn.execute(
                    "SELECT id FROM snapshots WHERE captured_at = ? AND endpoint = ?",
                    (captured_at, endpoint)
                )
            
            snapshot_id = cursor.fetchone()[0]
            
            # Process each time window
            for entry in data["data"]:
                time_window_id = self.get_or_create_time_window(
                    entry["from"],
                    entry["to"]
                )
                
                # Store forecast
                intensity_index_id = self.get_intensity_index_id(
                    entry["intensity"]["index"]
                )
                
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO forecasts
                    (snapshot_id, time_window_id, forecast_value, intensity_index_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        time_window_id,
                        entry["intensity"]["forecast"],
                        intensity_index_id
                    )
                )
                forecasts_stored += 1
                
                # Store actual if present
                if entry["intensity"]["actual"] is not None:
                    self.conn.execute(
                        """
                        INSERT OR REPLACE INTO actuals
                        (time_window_id, actual_value, last_updated)
                        VALUES (?, ?, ?)
                        """,
                        (
                            time_window_id,
                            entry["intensity"]["actual"],
                            captured_at
                        )
                    )
                    actuals_stored += 1
                    
        return forecasts_stored, actuals_stored

    def get_forecast_vs_actual(
        self,
        time_from: str,
        time_to: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get forecast vs actual values for a time period.
        
        Args:
            time_from: Start time in ISO format
            time_to: Optional end time in ISO format
            
        Returns:
            List of dicts containing forecast and actual values
        """
        query = """
        SELECT 
            tw.time_from,
            tw.time_to,
            f.forecast_value,
            a.actual_value,
            ii.name as intensity,
            s.captured_at as forecast_made_at
        FROM time_windows tw
        JOIN forecasts f ON f.time_window_id = tw.id
        JOIN snapshots s ON f.snapshot_id = s.id
        JOIN intensity_indices ii ON f.intensity_index_id = ii.id
        LEFT JOIN actuals a ON a.time_window_id = tw.id
        WHERE tw.time_from >= ?
        """
        params = [time_from]
        
        if time_to:
            query += " AND tw.time_to <= ?"
            params.append(time_to)
            
        query += " ORDER BY tw.time_from, s.captured_at"
        
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_forecast_history(
        self,
        time_from: str,
        time_to: str
    ) -> List[Dict[str, Any]]:
        """Get all forecasts made for a specific time window.
        
        Args:
            time_from: Start time in ISO format
            time_to: End time in ISO format
            
        Returns:
            List of dicts containing forecast history
        """
        cursor = self.conn.execute(
            """
            SELECT 
                s.captured_at as forecast_made_at,
                f.forecast_value,
                ii.name as intensity,
                a.actual_value
            FROM time_windows tw
            JOIN forecasts f ON f.time_window_id = tw.id
            JOIN snapshots s ON f.snapshot_id = s.id
            JOIN intensity_indices ii ON f.intensity_index_id = ii.id
            LEFT JOIN actuals a ON a.time_window_id = tw.id
            WHERE tw.time_from = ? AND tw.time_to = ?
            ORDER BY s.captured_at
            """,
            (time_from, time_to)
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self) -> 'CarbonIntensityDB':
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any]
    ) -> None:
        """Close the database connection when exiting context manager.
        
        Args:
            exc_type: The type of the exception that was raised
            exc_val: The instance of the exception that was raised
            exc_tb: The traceback of the exception that was raised
        """
        self.close()
