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


def calculate_percentile_curves(df: pd.DataFrame, percentiles: list[int] = [20, 40, 60, 80]) -> dict[int, pd.Series]:
    """Calculate percentile curves for net production across time of day.

    Args:
        df: DataFrame with timestamp and net_energy_kwh columns
        percentiles: List of percentiles to calculate (e.g., [20, 40, 60, 80])

    Returns:
        Dictionary mapping percentile to Series of values by time bin
    """
    # Extract time components
    df = df.copy()
    df["date"] = df["timestamp"].dt.date
    df["time_bin"] = df["timestamp"].dt.hour * 4 + df["timestamp"].dt.minute // 15

    # Get the energy column (corrected if available)
    energy_col = "net_energy_kwh_corrected" if "net_energy_kwh_corrected" in df.columns else "net_energy_kwh"

    # Pivot to get time bins as columns, dates as rows
    pivot = df.pivot_table(
        index="date",
        columns="time_bin",
        values=energy_col,
        aggfunc="max"  # Use max energy in each time bin per day
    )

    curves = {}
    # Clip values below zero before calculating percentiles
    clipped_pivot = pivot.clip(lower=0)
    for p in percentiles:
        curve = pd.Series(
            np.nanpercentile(clipped_pivot.values, p, axis=0),
            index=clipped_pivot.columns,
            name=f"p{p}"
        )
        curves[p] = curve

    return curves


def create_2d_histogram(
    csv_path: Path,
    output_path: Path | None,
    min_power: float | None,
    max_power: float | None,
    bin_size: float,
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
        min_power: Minimum energy value for y-axis
        max_power: Maximum energy value for y-axis (auto-detected if None)
        bin_size: Size of each energy bin in kWh
        time_bins_per_day: Number of time bins per day

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

    # Create bins with 0 as a boundary: ..., [-0.2,-0.1), [-0.1,0), [0,0.1), [0.1,0.2), ...
    # Calculate how many bins needed below and above 0
    bins_below_zero = int(np.ceil(-min_power / bin_size)) if min_power < 0 else 0
    bins_above_zero = int(np.ceil(max_power / bin_size)) if max_power > 0 else 0

    # Create edges: negative bins (descending), then 0, then positive bins
    negative_edges = np.arange(-bins_below_zero, 0) * bin_size if bins_below_zero > 0 else np.array([])
    positive_edges = np.arange(0, bins_above_zero + 1) * bin_size if bins_above_zero > 0 else np.array([0.0])

    power_bin_edges = np.concatenate([negative_edges, positive_edges])
    power_bins = len(power_bin_edges) - 1
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
    # X-axis labels at hour boundaries (edges), including 24:00 at the end
    bins_per_hour = 60 // minutes_per_bin
    time_label_positions = list(range(0, time_bins_per_day + 1, bins_per_hour))
    time_labels_hourly = [f"{h:02d}:00" for h in range(25)]  # 00:00 to 24:00

    # Create the heatmap with Plotly
    # Calculate cell centers so bin edges align with tick labels
    # For x: cells span [i, i+1], so center is at i + 0.5
    # For y: cells span [edge, edge+bin_size], so center is at edge + bin_size/2
    power_bin_centers = power_bin_edges[:-1] + bin_size / 2

    fig = go.Figure(data=go.Heatmap(
        z=histogram,
        x=[i + 0.5 for i in range(time_bins_per_day)],
        y=power_bin_centers,
        colorscale="Cividis",
        colorbar=dict(
            title=dict(
                text="Days Exceeding<br>Threshold",
                side="right",
            ),
        ),
        hovertemplate=(
            "Time: %{customdata[0]}<br>" +
            "Energy: %{customdata[1]:.2f} kWh<br>" +
            "Days exceeding: %{z}<br>" +
            "<extra></extra>"
        ),
        # customdata: [time_label, lower_edge] for each (y_bin, x_bin) cell
        customdata=[[[time_labels_all[x], power_bin_edges[y]] for x in range(time_bins_per_day)] for y in range(power_bins)],
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
            tickmode="array",
            tickvals=power_bin_edges,
            ticktext=[f"{edge:.2f}" for edge in power_bin_edges],
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
    # Add battery dispatch percentile curves
    percentile_colors = {20: "rgba(255, 0, 0, 0.7)", 40: "rgba(255, 165, 0, 0.7)",
                         60: "rgba(0, 255, 0, 0.7)", 80: "rgba(0, 0, 255, 0.7)"}
    percentile_labels = {20: "20th percentile", 40: "40th percentile",
                         60: "60th percentile", 80: "80th percentile"}

    curves = calculate_percentile_curves(df, percentiles=[20, 40, 60, 80])
    x_positions = [i + 0.5 for i in range(time_bins_per_day)]

    for p, curve in curves.items():
        # Ensure curve has values for all time bins
        curve_values = [curve.get(i, np.nan) for i in range(time_bins_per_day)]

        fig.add_trace(go.Scatter(
            x=x_positions,
            y=curve_values,
            mode="lines",
            name=percentile_labels[p],
            line=dict(color=percentile_colors[p], width=2),
            hovertemplate=(
                f"{percentile_labels[p]}<br>" +
                "Time: %{customdata}<br>" +
                "Energy: %{y:.2f} kWh<br>" +
                "<extra></extra>"
            ),
            customdata=time_labels_all,
        ))

    # Update layout to show legend at bottom left to avoid color scale overlap
    fig.update_layout(
        legend=dict(
            title=dict(text="Dispatch Curves"),
            x=0.01,
            y=0.01,
            xanchor="left",
            yanchor="bottom",
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="gray",
            borderwidth=1,
        ),
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
