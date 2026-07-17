"""Build the window-by-lead analysis frames the charts and README tables consume."""

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Iterable

import numpy as np
import pandas as pd
import scipy.stats as st
from scipy.optimize import curve_fit

from cift.store import Store

FINAL_ACTUAL = ("intensity.actual.final", "")

HOURS_OF_DATA = 24

EXPECTED_WINDOWS = {
    "national_fw48h": 96,
    "national_pt24h": 48,
    "regional_fw48h": 96,
    "regional_pt24h": 48,
    "national_generation_pt24h": 48,
}


def national_matrix(store: Store) -> pd.DataFrame:
    """The legacy summary shape, read from partitions plus unmerged inboxes."""
    return matrix_from_rows(store.national_rows())


def matrix_from_rows(
    rows: list[tuple[int, int, int | None, int | None]],
) -> pd.DataFrame:
    """One row per window, MultiIndex columns of ('intensity.forecast'|
    'intensity.actual') by lead-time hours, descending, plus the final actual."""
    df = pd.DataFrame(
        rows, columns=["window_utc", "capture_utc", "forecast", "actual"]
    ).drop_duplicates(subset=["window_utc", "capture_utc"], keep="first")
    df["lead"] = (df["window_utc"] - df["capture_utc"]) / 3600.0

    matrix = df.pivot(index="window_utc", columns="lead", values=["forecast", "actual"])
    matrix.columns = matrix.columns.set_levels(
        [
            "intensity.actual" if v == "actual" else "intensity.forecast"
            for v in matrix.columns.levels[0]
        ],
        level=0,
    )
    matrix = matrix.reindex(sorted(matrix.columns, reverse=True), axis=1)
    matrix.index = pd.to_datetime(matrix.index, unit="s")
    matrix[FINAL_ACTUAL] = matrix["intensity.actual"].ffill(axis=1).iloc[:, -1]
    return matrix


def error_frames(matrix: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Forecast error and percentage error against the final actual, for
    pre-window leads only (post-hoc "forecasts" are not predictions)."""
    final = matrix[FINAL_ACTUAL]
    forecasts = matrix["intensity.forecast"]
    errors = forecasts.sub(final, axis=0)
    percentage = 100.0 * errors.div(final, axis=0)
    forward_leads = [column for column in errors.columns if column >= 0.0]
    return errors[forward_leads], percentage[forward_leads]


def get_dates(
    df: pd.DataFrame,
    start_date: datetime | None = None,
    num_timepoints: int | None = None,
    num_hours: float | None = None,
    num_days: int | None = None,
    incomplete_hours_offset: int = 72,
    random_n: int = 0,
) -> list[datetime]:
    """Get the dates to plot.
    By default the most recent available complete data is used. Note that "complete"
    data includes 'actual' figures, which are only complete 24 hours after a given
    timepoint.
    Note also that we forecast 48 hours into the future, so the most recent timepoint
    with complete data is 72 hours earlier than the latest timepoint in the data.

    If start date isn't specified, we return the latest complete num_timepoints timepoints,
    based on the number of hours or days requested.

    Args:
        df (pd.DataFrame): dataframe with datetime index
        num_timepoints (int): number of plots to generate
        num_days (int): number of complete days' data to return. Optional. If set, overrides
            num_timepoints.
        incomplete_hours_offset (int): assume this many hours prior to the final timepoint in
            the data have incomplete 'actual' data. Defaults to 72.
        random_n (int): if > 0, return a sorted random sample of this size. Default is 0.

    Returns:
        list: list of datetimes
    """

    # Want to show N hours of data. The most recent timepoint for which all data is available
    # should be the latest - 24 hours.
    # The first timepoint will be now - 24 hours - N hours.

    if num_days:
        num_hours = num_days * 24
    if num_hours:
        num_timepoints = int(num_hours * 2)
    if not num_timepoints:
        num_timepoints = HOURS_OF_DATA * 2

    if start_date:
        return [d for d in df.index if d >= start_date][:num_timepoints]

    # The last timepoint with complete data
    latest_tp = df.index[-1] - timedelta(hours=incomplete_hours_offset)

    # The earliest timepoint to return
    if num_days:
        dt_earliest = latest_tp - timedelta(days=num_days)
    else:
        # The number of hours' data to show
        hours_prior = num_timepoints / 2
        dt_earliest = latest_tp - timedelta(hours=hours_prior)

    if dt_earliest > df.index[-1]:
        raise ValueError("Not enough data to generate plots")

    # pick datetimes
    dates = [d for d in df.index if d >= dt_earliest and d <= latest_tp][
        :num_timepoints
    ]
    if random_n > 0:
        return sorted(np.random.choice(dates, size=random_n, replace=False))
    return dates


def daily_stats(matrix: pd.DataFrame, days: int) -> pd.DataFrame:
    """Per-day absolute error and absolute percentage error statistics over the
    legacy completed-data window (see get_dates), so historical output reproduces."""
    errors, percentage = error_frames(matrix.loc[get_dates(matrix, num_days=days)])

    def per_day(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
        stacked = frame.abs().stack().dropna()
        by_day = stacked.groupby(stacked.index.get_level_values(0).date)
        rows = {}
        for day, values in by_day:
            mean, sem = float(values.mean()), float(st.sem(values))
            lo, hi = st.t.interval(0.95, len(values) - 1, loc=mean, scale=sem)
            rows[str(day)] = {
                "forecast_count": len(values),
                f"{prefix}_mean": round(mean, 2),
                f"{prefix}_sem": round(sem, 2),
                f"{prefix}_ci95_lo": round(float(lo), 2),
                f"{prefix}_ci95_hi": round(float(hi), 2),
            }
        return pd.DataFrame.from_dict(rows, orient="index")

    absolute = per_day(errors, "abs_err")
    percent = per_day(percentage, "pc_err").drop(columns=["forecast_count"])
    return absolute.join(percent, how="inner")


def _fit_distributions(data: np.ndarray) -> dict[str, tuple[object, tuple[float, ...]]]:
    """Fit t, Normal and Laplace to the error histogram, as the legacy analysis did."""
    edges = np.arange(data.min() - 0.5, data.max() + 1.5, 1.0)
    hist, bin_edges = np.histogram(data, bins=edges, density=True)
    centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    mu, sigma = float(data.mean()), float(data.std())

    fitted: dict[str, tuple[object, tuple[float, ...]]] = {}
    for name, distribution, initial in (
        # a t initial guess above ~30 dof is numerically indistinguishable from
        # normal and makes curve_fit crawl
        ("Student's t probability", st.t, (min(len(data) - 1, 30), mu, sigma)),
        ("Normal probability", st.norm, (mu, sigma)),
        ("Laplace probability", st.laplace, (mu, sigma)),
    ):
        parameters, _ = curve_fit(
            lambda x, *p, d=distribution: d.pdf(x, *p),
            centers,
            hist,
            p0=initial,
            maxfev=20000,
        )
        fitted[name] = (distribution, tuple(parameters))
    return fitted


def error_probabilities(errors: Iterable[float], magnitudes: list[int]) -> pd.DataFrame:
    """P(|error| >= magnitude) under each fitted distribution — the README table."""
    data = np.asarray(list(errors), dtype=float)
    data = data[np.isfinite(data)]
    fitted = _fit_distributions(data)

    table = {}
    for name, (distribution, parameters) in fitted.items():
        table[name] = [
            float(
                1
                - distribution.cdf(abs(value), *parameters)  # type: ignore[attr-defined]
                + distribution.cdf(-abs(value), *parameters)  # type: ignore[attr-defined]
            )
            for value in magnitudes
        ]
    frame = pd.DataFrame(table, index=pd.Index(magnitudes, name="error value"))
    return frame


@dataclass(frozen=True)
class HealthReport:
    """Expected-versus-observed horizon check; alerting is the fix for silent decay."""

    alerts: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return not self.alerts


def horizon_health(
    store: Store, now: datetime, lookback_hours: int = 26
) -> HealthReport:
    """Alert when snapshots observe far fewer windows than the endpoint should return:
    under 50% in any single capture alerts immediately; under 90% for six consecutive
    captures alerts as sustained; a full-horizon capture resets the streak."""
    cutoff = int(now.timestamp()) - lookback_hours * 3600
    by_endpoint: dict[str, list[tuple[int, int]]] = {}
    for slot, endpoint, first_utc, last_utc in store.capture_records():
        if slot >= cutoff:
            observed = (last_utc - first_utc) // 1800 + 1
            by_endpoint.setdefault(endpoint, []).append((slot, observed))

    alerts = []
    for endpoint, records in sorted(by_endpoint.items()):
        expected = EXPECTED_WINDOWS[endpoint]
        streak = 0
        for slot, observed in sorted(records):
            ratio = observed / expected
            when = datetime.fromtimestamp(slot, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%MZ"
            )
            if ratio < 0.5:
                alerts.append(
                    f"{endpoint} at {when} observed only {observed}/{expected} windows"
                )
            if ratio < 0.9:
                streak += 1
                if streak == 6:
                    alerts.append(
                        f"{endpoint} sustained truncation: six consecutive short"
                        f" captures ending {when}"
                    )
            else:
                streak = 0
    return HealthReport(alerts=tuple(alerts))
