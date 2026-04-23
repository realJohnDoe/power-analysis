"""Plotting utilities for Tibber Pulse data analysis."""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def compute_power_from_accumulated(df: pd.DataFrame) -> pd.DataFrame:
    """Compute instantaneous power (kW) from accumulated consumption/production.

    Power is calculated as the difference in accumulated energy divided by time difference.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Calculate time differences in hours
    df["time_diff_hours"] = df["timestamp"].diff().dt.total_seconds() / 3600

    # Calculate power from consumption and production
    df["consumption_power"] = df["accumulated_consumption"].diff() / df["time_diff_hours"]
    df["production_power"] = df["accumulated_production"].diff() / df["time_diff_hours"]

    # Net power = consumption - production (positive = consuming from grid)
    df["net_power"] = df["consumption_power"] - df["production_power"]

    # Remove rows with invalid calculations (first row, or where time_diff is 0)
    df = df[df["time_diff_hours"] > 0].copy()

    return df


def create_2d_histogram(
    csv_path: Path,
    output_path: Path | None = None,
    max_power: float | None = None,
    power_bins: int = 50,
) -> Path:
    """Create an interactive 2D histogram of power consumption patterns using Plotly.

    The histogram shows:
    - X-axis: Time of day in 15-minute bins (96 bins for 24 hours)
    - Y-axis: Net power consumption (kW)
    - Color: Number of days where that power level was exceeded at that time

    Args:
        csv_path: Path to the CSV file with Tibber data
        output_path: Where to save the plot (HTML file). Opens in browser if not set.
        max_power: Maximum power value for y-axis (auto-detected if None)
        power_bins: Number of bins for the power axis

    Returns:
        Path to the saved plot
    """
    # Load and process data
    df = pd.read_csv(csv_path)

    if len(df) < 2:
        raise ValueError("Need at least 2 data points to compute power")

    # Compute power values
    df = compute_power_from_accumulated(df)

    # Extract time components
    df["hour"] = df["timestamp"].dt.hour
    df["minute"] = df["timestamp"].dt.minute
    df["date"] = df["timestamp"].dt.date

    # Create time-of-day bins (15-minute intervals = 96 bins)
    df["time_bin"] = df["hour"] * 4 + df["minute"] // 15

    # Get unique days for counting
    unique_days = df["date"].nunique()

    # Determine power range
    if max_power is None:
        max_power = df["net_power"].quantile(0.99)  # Use 99th percentile to exclude outliers
    min_power = max(-5, df["net_power"].min())  # Cap at -5 kW for visual clarity

    # Create bins
    power_bin_edges = np.linspace(min_power, max_power, power_bins + 1)
    power_bin_centers = (power_bin_edges[:-1] + power_bin_edges[1:]) / 2

    # Initialize 2D histogram: count of days where power exceeded threshold
    histogram = np.zeros((power_bins, 96))

    # Group by date and time bin to get max power for each (day, time_bin) combination
    daily_max_power = df.groupby(["date", "time_bin"])["net_power"].max().reset_index()

    # For each time bin and power threshold, count days exceeding that power
    for time_idx in range(96):
        time_data = daily_max_power[daily_max_power["time_bin"] == time_idx]

        if len(time_data) == 0:
            continue

        for power_idx in range(power_bins):
            threshold = power_bin_edges[power_idx + 1]
            # Count days where max power at this time exceeded the threshold
            days_exceeding = (time_data["net_power"] > threshold).sum()
            histogram[power_idx, time_idx] = days_exceeding

    # Create time labels for x-axis (every 2 hours)
    time_labels = [f"{h:02d}:00" for h in range(0, 24)]
    time_label_positions = list(range(0, 96, 4))

    # Create the heatmap with Plotly
    fig = go.Figure(data=go.Heatmap(
        z=histogram,
        x=list(range(96)),
        y=power_bin_centers,
        colorscale="YlOrRd",
        colorbar=dict(
            title=dict(
                text="Days Exceeding<br>Threshold",
                side="right",
            ),
        ),
        hovertemplate=(
            "Time: %{customdata}<br>" +
            "Power: %{y:.2f} kW<br>" +
            "Days exceeding: %{z}<br>" +
            "<extra></extra>"
        ),
        customdata=[[time_labels[i // 4] if i % 4 == 0 else "" for i in range(96)] for _ in range(power_bins)],
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
            ticktext=time_labels,
            tickangle=-45,
            showgrid=True,
            gridcolor="rgba(128,128,128,0.2)",
        ),
        yaxis=dict(
            title="Net Power (kW)",
            showgrid=True,
            gridcolor="rgba(128,128,128,0.2)",
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        width=1200,
        height=700,
        margin=dict(l=80, r=150, t=100, b=80),
    )

    # Add annotation
    fig.add_annotation(
        text="Color intensity shows how many days power exceeded threshold at that time",
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
