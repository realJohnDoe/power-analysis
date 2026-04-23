"""Plotting utilities for Tibber Pulse data analysis."""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm


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
    """Create a 2D histogram of power consumption patterns.
    
    The histogram shows:
    - X-axis: Time of day in 15-minute bins (96 bins for 24 hours)
    - Y-axis: Net power consumption (kW)
    - Color: Number of days where that power level was exceeded at that time
    
    Args:
        csv_path: Path to the CSV file with Tibber data
        output_path: Where to save the plot (optional, displays if not set)
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
    time_bins = np.arange(97)  # 0 to 96 (15-minute bins)
    power_bin_edges = np.linspace(min_power, max_power, power_bins + 1)
    
    # Initialize 2D histogram: count of days where power exceeded threshold
    # For each time bin and power threshold, count days
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
    
    # Create the plot
    fig, ax = plt.subplots(figsize=(14, 8))
    
    # Create time labels for x-axis (every 2 hours)
    time_labels = [f"{h:02d}:00" for h in range(0, 24, 2)]
    time_label_positions = [h * 4 for h in range(0, 24, 2)]
    
    # Plot the 2D histogram
    im = ax.imshow(
        histogram,
        aspect="auto",
        origin="lower",
        extent=[0, 96, min_power, max_power],
        cmap="YlOrRd",
        interpolation="nearest",
    )
    
    # Set labels and title
    ax.set_xlabel("Time of Day", fontsize=12)
    ax.set_ylabel("Net Power (kW)", fontsize=12)
    ax.set_title(
        f"Power Consumption Patterns - Days Exceeding Power Threshold\n"
        f"Data: {csv_path.name} ({unique_days} days)",
        fontsize=14,
    )
    
    # Set x-axis ticks
    ax.set_xticks(time_label_positions)
    ax.set_xticklabels(time_labels, rotation=45, ha="right")
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax, label="Days Exceeding Threshold")
    
    # Add grid for readability
    ax.grid(True, alpha=0.3, linestyle="--")
    
    # Add annotation
    ax.text(
        0.02, 0.98,
        "Color = days where power exceeded threshold at that time",
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
    )
    
    plt.tight_layout()
    
    # Save or display
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Plot saved to: {output_path}")
        plt.close()
        return output_path
    else:
        plt.show()
        return None
