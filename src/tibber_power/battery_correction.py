"""Battery power correction based on time of day profiles."""

from datetime import datetime
from typing import Protocol


class BatteryProfile(Protocol):
    """Protocol for battery correction profiles."""

    def get_correction_watts(self, timestamp: datetime) -> float:
        """Get the correction in watts for a given timestamp."""
        ...


class SimpleTimeProfile:
    """Simple time-of-day battery correction profile.

    Correction values based on hour of day:
    - 21:00 to 09:00 (night): add 50W
    - 09:00 to 21:00 (day): add 200W
    """

    def __init__(self, night_watts: float = 50.0, day_watts: float = 200.0):
        self.night_watts = night_watts
        self.day_watts = day_watts

    def get_correction_watts(self, timestamp: datetime) -> float:
        hour = timestamp.hour
        if hour >= 21 or hour < 9:
            return self.night_watts
        return self.day_watts


class HourlyProfile:
    """Arbitrary piecewise-constant correction profile defined by hour-of-day segments.

    Each segment is (start_hour, end_hour, watts) where start_hour is inclusive
    and end_hour is exclusive.  Segments may wrap past midnight (end_hour > 24 is
    not needed — just use two segments).  The first matching segment wins.
    """

    def __init__(self, segments: list[tuple[int, int, float]]):
        """
        Args:
            segments: List of (start_hour, end_hour, watts).
                      Hours are 0–24; end_hour is exclusive.
                      Example: [(0, 6, 200), (6, 9, 100), ..., (21, 24, 200)]
        """
        self.segments = segments

    def get_correction_watts(self, timestamp: datetime) -> float:
        hour = timestamp.hour
        for start, end, watts in self.segments:
            if start <= hour < end:
                return watts
        return 0.0


class ScheduledProfile:
    """Switches between profiles at specific wall-clock datetimes.

    Given a list of (start_time, profile) entries, the profile used for a
    timestamp is the one with the latest start_time that is <= timestamp.
    """

    def __init__(self, schedule: list[tuple[datetime, BatteryProfile]]):
        """
        Args:
            schedule: List of (start_time, profile) tuples, in any order.
                      The profile with the latest start_time <= timestamp is used,
                      so entries effectively apply until the next later start_time.
        """
        self.schedule = sorted(schedule, key=lambda entry: entry[0])

    def get_correction_watts(self, timestamp: datetime) -> float:
        active_profile = self.schedule[0][1]
        for start_time, profile in self.schedule:
            if start_time > timestamp:
                break
            active_profile = profile
        return active_profile.get_correction_watts(timestamp)


def get_default_profile() -> BatteryProfile:
    """Get the default battery correction profile.

    - Before 2026-05-21 14:00: 50 W at night (21:00–09:00), 200 W during the day.
    - From  2026-05-21 14:00 to 2026-07-01 09:00: hourly schedule with varying dispatch levels.
    - From  2026-07-01 09:00: hourly schedule with 100/200/300 W dispatch levels.
    """
    return ScheduledProfile([
        (datetime.min, SimpleTimeProfile(night_watts=50.0, day_watts=200.0)),
        (datetime(2026, 5, 21, 14, 0, 0), HourlyProfile([
            (0,  6,  200.0),
            (6,  9,  100.0),
            (9,  12, 200.0),
            (12, 15, 100.0),
            (15, 21,   0.0),
            (21, 24, 200.0),
        ])),
        (datetime(2026, 7, 1, 9, 0, 0), HourlyProfile([
            (0,  8,  100.0),
            (8,  9,  200.0),
            (9,  12, 300.0),
            (12, 13, 200.0),
            (13, 24, 100.0),
        ])),
    ])


def apply_correction(df, timestamp_col: str = "timestamp", profile: BatteryProfile | None = None):
    """Apply battery correction to a DataFrame.

    Args:
        df: DataFrame with timestamp column
        timestamp_col: Name of the timestamp column
        profile: Battery profile to use (default: SimpleTimeProfile)

    Returns:
        DataFrame with added 'battery_correction_w' and 'net_power_corrected' columns
    """
    if profile is None:
        profile = get_default_profile()

    # Calculate correction for each row
    df["battery_correction_w"] = df[timestamp_col].apply(
        lambda ts: profile.get_correction_watts(ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts)))
    )

    # Apply correction to net_power if it exists (convert kW to W, add correction, convert back)
    if "net_power" in df.columns:
        df["net_power_corrected"] = df["net_power"] + (df["battery_correction_w"] / 1000.0)

    return df
