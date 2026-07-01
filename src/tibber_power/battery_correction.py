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
    """Switches between profiles at a specific wall-clock datetime.

    Before the switchover timestamp the ``before`` profile is used;
    from that moment onward the ``after`` profile is used.
    """

    def __init__(self, switchover: datetime, before: BatteryProfile, after: BatteryProfile):
        """
        Args:
            switchover: The datetime at which to switch from ``before`` to ``after``.
            before: Profile used for timestamps strictly before ``switchover``.
            after:  Profile used for timestamps at or after ``switchover``.
        """
        self.switchover = switchover
        self.before = before
        self.after = after

    def get_correction_watts(self, timestamp: datetime) -> float:
        profile = self.after if timestamp >= self.switchover else self.before
        return profile.get_correction_watts(timestamp)


def get_default_profile() -> BatteryProfile:
    """Get the default battery correction profile.

    - Before 2026-05-21 14:00: 50 W at night (21:00–09:00), 200 W during the day.
    - From  2026-05-21 14:00 to 2026-07-01 09:00: hourly schedule with varying dispatch levels.
    - From  2026-07-01 09:00: hourly schedule with 100/200/300 W dispatch levels.
    """
    before = SimpleTimeProfile(night_watts=50.0, day_watts=200.0)
    after = HourlyProfile([
        (0,  6,  200.0),
        (6,  9,  100.0),
        (9,  12, 200.0),
        (12, 15, 100.0),
        (15, 21,   0.0),
        (21, 24, 200.0),
    ])
    stage_2026_05_21 = ScheduledProfile(
        switchover=datetime(2026, 5, 21, 14, 0, 0),
        before=before,
        after=after,
    )
    stage_2026_07_01 = HourlyProfile([
        (0,  8,  100.0),
        (8,  9,  200.0),
        (9,  12, 300.0),
        (12, 13, 200.0),
        (13, 24, 100.0),
    ])
    return ScheduledProfile(
        switchover=datetime(2026, 7, 1, 9, 0, 0),
        before=stage_2026_05_21,
        after=stage_2026_07_01,
    )


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
