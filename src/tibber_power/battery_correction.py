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
        """Initialize profile with correction values.

        Args:
            night_watts: Watts to add during night hours (21:00-09:00)
            day_watts: Watts to add during day hours (09:00-21:00)
        """
        self.night_watts = night_watts
        self.day_watts = day_watts

    def get_correction_watts(self, timestamp: datetime) -> float:
        """Get correction based on hour of day.

        Args:
            timestamp: The timestamp to check

        Returns:
            Correction in watts to add to measured consumption
        """
        hour = timestamp.hour

        # Night: 21:00 to 09:00 (inclusive of 21, exclusive of 9 when rolling over)
        if hour >= 21 or hour < 9:
            return self.night_watts
        # Day: 09:00 to 21:00
        else:
            return self.day_watts


def get_default_profile() -> BatteryProfile:
    """Get the default battery correction profile."""
    return SimpleTimeProfile(night_watts=50.0, day_watts=200.0)


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
