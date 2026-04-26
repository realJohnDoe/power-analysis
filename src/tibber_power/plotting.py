"""Plotting utilities for Tibber Pulse data analysis."""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from tibber_power.battery_correction import apply_correction, get_default_profile
from tibber_power.resample import resample_power


def compute_power_from_accumulated(df: pd.DataFrame, time_bins_per_day: int) -> pd.DataFrame:
    """Compute energy per interval from accumulated consumption/production.

    Uses resampling with midnight anchor points to handle daily resets properly.

    Args:
        df: DataFrame with timestamp, accumulated_consumption, accumulated_production
        time_bins_per_day: Number of time bins per day (default 96 = 15-minute intervals)

    Returns:
        DataFrame with net_energy_kwh per interval
    """
    # Calculate interval minutes from bins per day (1440 minutes / bins)
    interval_minutes = 1440 // time_bins_per_day

    # Rename columns to match resample module expectations
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Map Tibber column names to resample module names
    if "accumulated_consumption" in df.columns:
        df["cum_consumption"] = df["accumulated_consumption"]
    if "accumulated_production" in df.columns:
        df["cum_production"] = df["accumulated_production"]

    # Use resampling with calculated interval (interpolates across gaps)
    resampled = resample_power(df, interval_minutes=interval_minutes)

    # Use energy consumed in interval (kWh) instead of power (kW)
    # net_production_kwh is already the energy per interval
    resampled["net_energy_kwh"] = resampled["net_production_kwh"]

    # For compatibility with existing code, map interval_start to timestamp
    resampled["timestamp"] = resampled["interval_start"]

    return resampled


def load_csv_data(csv_path: Path) -> pd.DataFrame:
    """Load CSV data from a file or directory of CSV files.

    Args:
        csv_path: Path to a CSV file or directory containing CSV files

    Returns:
        Combined DataFrame with all data
    """
    csv_path = Path(csv_path)

    if csv_path.is_file():
        if csv_path.suffix.lower() != ".csv":
            raise ValueError(f"File must be a CSV: {csv_path}")
        return pd.read_csv(csv_path)

    elif csv_path.is_dir():
        csv_files = list(csv_path.glob("*.csv"))
        if not csv_files:
            raise ValueError(f"No CSV files found in directory: {csv_path}")

        print(f"Found {len(csv_files)} CSV file(s) in {csv_path}")
        dfs = []
        for f in sorted(csv_files):
            print(f"  Loading: {f.name}")
            dfs.append(pd.read_csv(f))
        return pd.concat(dfs, ignore_index=True)

    else:
        raise ValueError(f"Path does not exist: {csv_path}")


def create_2d_histogram(
    csv_path: Path,
    output_path: Path | None,
    min_power: float | None,
    max_power: float | None,
    power_bins: int,
    time_bins_per_day: int,
) -> Path:
    """Create an interactive 2D histogram of power consumption patterns using Plotly.

    The histogram shows:
    - X-axis: Time of day in regular bins (default 96 bins = 15-minute intervals for 24 hours)
    - Y-axis: Net energy consumption (kWh)
    - Color: Number of days where energy level was exceeded at that time

    Args:
        csv_path: Path to a CSV file or directory containing CSV files with Tibber data
        output_path: Where to save the plot (HTML file). Opens in browser if not set.
        min_power: Minimum energy value for y-axis (default: 1.0 kWh)
        max_power: Maximum energy value for y-axis (auto-detected if None)
        power_bins: Number of bins for the energy axis
        time_bins_per_day: Number of time bins per day (default 96 = 15-minute intervals)

    Returns:
        Path to the saved plot
    """
    # Load data from file or directory
    df = load_csv_data(csv_path)

    if len(df) < 2:
        raise ValueError("Need at least 2 data points to compute power")

    # Compute energy from accumulated data with specified time resolution
    df = compute_power_from_accumulated(df, time_bins_per_day=time_bins_per_day)

    # Apply battery correction
    df = apply_correction(df, profile=get_default_profile())

    # Extract time components
    df["hour"] = df["timestamp"].dt.hour
    df["minute"] = df["timestamp"].dt.minute
    df["date"] = df["timestamp"].dt.date

    # Create time-of-day bins based on specified resolution
    minutes_per_bin = 1440 // time_bins_per_day
    df["time_bin"] = df["hour"] * (60 // minutes_per_bin) + df["minute"] // minutes_per_bin

    # Get unique days for counting
    unique_days = df["date"].nunique()

    # Determine energy range (use corrected net energy if available)
    energy_col = "net_energy_kwh_corrected" if "net_energy_kwh_corrected" in df.columns else "net_energy_kwh"
    if max_power is None:
        max_power = df[energy_col].quantile(0.99)  # Use 99th percentile to exclude outliers
    if min_power is None:
        min_power = max(-1, df[energy_col].min())  # Cap at -1 kWh for visual clarity

    # Create bins
    power_bin_edges = np.linspace(min_power, max_power, power_bins + 1)
    power_bin_centers = (power_bin_edges[:-1] + power_bin_edges[1:]) / 2

    # Initialize 2D histogram: count of days where energy exceeded threshold
    histogram = np.zeros((power_bins, time_bins_per_day))

    # Group by date and time bin to get max energy for each (day, time_bin) combination
    daily_max_energy = df.groupby(["date", "time_bin"])[energy_col].max().reset_index()

    # For each time bin and energy threshold, count days exceeding that energy
    for time_idx in range(time_bins_per_day):
        time_data = daily_max_energy[daily_max_energy["time_bin"] == time_idx]

        if len(time_data) == 0:
            continue

        for power_idx in range(power_bins):
            threshold = power_bin_edges[power_idx + 1]
            # Count days where max power at this time exceeded the threshold
            days_exceeding = (time_data[energy_col] > threshold).sum()
            histogram[power_idx, time_idx] = days_exceeding

    # Create time labels for all bins
    time_labels_all = []
    for h in range(24):
        for m in range(0, 60, minutes_per_bin):
            time_labels_all.append(f"{h:02d}:{m:02d}")
    # X-axis shows every hour (4 bins per hour at 15min resolution)
    bins_per_hour = 60 // minutes_per_bin
    time_label_positions = list(range(0, time_bins_per_day, bins_per_hour))
    time_labels_hourly = [time_labels_all[i] for i in time_label_positions]  # For x-axis ticks (every hour)

    # Create the heatmap with Plotly
    fig = go.Figure(data=go.Heatmap(
        z=histogram,
        x=list(range(96)),
        y=power_bin_centers,
        colorscale="Cividis",
        colorbar=dict(
            title=dict(
                text="Days Exceeding<br>Threshold",
                side="right",
            ),
        ),
        hovertemplate=(
            "Time: %{customdata}<br>" +
            "Energy: %{y:.2f} kWh<br>" +
            "Days exceeding: %{z}<br>" +
            "<extra></extra>"
        ),
        customdata=[time_labels_all for _ in range(power_bins)],
    ))

    # Update layout
    fig.update_layout(
        title=dict(
            text=(
                f"Power Consumption Patterns - Days Exceeding Power Threshold<br>"
                f"<sub>Data: {csv_path.name} ({unique_days} days)</sub>"
            ),
            x=0.5,
            xanchor="center",
        ),
        xaxis=dict(
            title="Time of Day",
            tickmode="array",
            tickvals=time_label_positions,
            ticktext=time_labels_hourly,
            tickangle=-45,
            showgrid=True,
            gridcolor="rgba(128,128,128,0.2)",
        ),
        yaxis=dict(
            title="Net Energy (kWh)",
            showgrid=True,
            gridcolor="rgba(128,128,128,0.2)",
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        width=1200,
        height=700,
        margin=dict(l=80, r=150, t=100, b=80),
        hovermode="closest",
    )

    # Add annotation
    fig.add_annotation(
        text="Color intensity shows how many days energy exceeded threshold at that time",
        xref="paper",
        yref="paper",
        x=0.01,
        y=0.99,
        showarrow=False,
        font=dict(size=10),
        bgcolor="rgba(255,255,255,0.8)",
        bordercolor="gray",
        borderwidth=1,
        borderpad=4,
        align="left",
    )

    # Save or open in browser
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.write_html(output_path, include_plotlyjs="cdn")
        print(f"Plot saved to: {output_path}")
        return output_path
    else:
        fig.show()
        return None
