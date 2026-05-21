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


_EXPECTED_COLS = ["timestamp", "accumulated_consumption", "accumulated_production"]


def _read_csv_file(path: Path) -> pd.DataFrame:
    """Read a single CSV file, recovering gracefully from a missing header row.

    If the file was created by a month-rollover bug the header row may be absent,
    so the first data row ends up as the column names.  We detect this by checking
    whether all expected columns are present and, if not, re-read with explicit
    column names (treating whatever is on line 1 as data, not a header).
    """
    df = pd.read_csv(path)
    if not all(col in df.columns for col in _EXPECTED_COLS):
        # Header is missing — the first row was already parsed as column names.
        # Re-read with explicit names so that row is kept as data.
        df = pd.read_csv(path, header=None, names=_EXPECTED_COLS)
    return df


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
        return _read_csv_file(csv_path)

    elif csv_path.is_dir():
        csv_files = list(csv_path.glob("*.csv"))
        if not csv_files:
            raise ValueError(f"No CSV files found in directory: {csv_path}")

        print(f"Found {len(csv_files)} CSV file(s) in {csv_path}")
        dfs = []
        for f in sorted(csv_files):
            print(f"  Loading: {f.name}")
            dfs.append(_read_csv_file(f))
        return pd.concat(dfs, ignore_index=True)

    else:
        raise ValueError(f"Path does not exist: {csv_path}")


def calculate_percentile_curves(
    df: pd.DataFrame,
    time_bins_per_day: int,
    target_areas: list[float],
    power_bin_edges: np.ndarray,
) -> tuple[dict[float, pd.Series], dict[float, float]]:
    """Calculate percentile curves for fixed areas under curve.

    Values are snapped to power_bin_edges before the AUC is computed, so the
    binary search converges to the right percentile for the binned curve and the
    returned curves already sit on the histogram's y-grid.

    Args:
        df: DataFrame with timestamp and net_energy_kwh columns
        time_bins_per_day: Number of time bins per day (for calculating interval hours)
        target_areas: List of target AUC values in kWh (e.g., [1, 2, 3, 4, 5])
        power_bin_edges: Histogram bin edges used to snap curve values

    Returns:
        Tuple of (dictionary mapping target area to Series of values by time bin,
                  dictionary mapping target area to the percentile found)
    """
    df = df.copy()
    df["date"] = df["timestamp"].dt.date
    minutes_per_bin = 1440 // time_bins_per_day
    df["time_bin"] = (df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute) // minutes_per_bin

    energy_col = "net_energy_kwh_corrected" if "net_energy_kwh_corrected" in df.columns else "net_energy_kwh"
    df[energy_col] = df[energy_col].astype(float)

    pivot = df.pivot_table(
        index="date",
        columns="time_bin",
        values=energy_col,
        aggfunc="max"
    )

    interval_hours = 24 / time_bins_per_day
    clipped_pivot = pivot.clip(lower=0)

    def snap(values: np.ndarray) -> np.ndarray:
        """Snap each value down to the lower edge of its histogram bin."""
        idx = np.searchsorted(power_bin_edges, values, side='right') - 1
        idx = np.clip(idx, 0, len(power_bin_edges) - 2)
        return power_bin_edges[idx]

    def auc_for_percentile(p: float) -> float:
        raw = np.nanpercentile(clipped_pivot.values, p, axis=0)
        return float(np.nansum(snap(raw)) * interval_hours)

    max_auc = auc_for_percentile(100)

    curves = {}
    percentiles_found = {}

    for target in target_areas:
        if target > max_auc:
            continue
        # Binary search for percentile whose snapped AUC equals target
        lo, hi = 0.0, 100.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if auc_for_percentile(mid) < target:
                lo = mid
            else:
                hi = mid
        p = (lo + hi) / 2
        curve = pd.Series(
            snap(np.nanpercentile(clipped_pivot.values, p, axis=0)),
            index=clipped_pivot.columns,
            name=f"auc_{target}",
        )
        curves[target] = curve
        percentiles_found[target] = p

    return curves, percentiles_found


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
    # Convert the per-row watt correction to kWh for the interval and add to net energy.
    # battery_correction_w is positive → battery is discharging → adds to net consumption.
    interval_hours = (1440 / time_bins_per_day) / 60
    df["net_energy_kwh_corrected"] = (
        df["net_energy_kwh"] + df["battery_correction_w"] / 1000 * interval_hours
    )

    # Extract time components
    df["hour"] = df["timestamp"].dt.hour
    df["minute"] = df["timestamp"].dt.minute
    df["date"] = df["timestamp"].dt.date

    # Create time-of-day bins based on specified resolution
    minutes_per_bin = 1440 // time_bins_per_day
    df["time_bin"] = (df["hour"] * 60 + df["minute"]) // minutes_per_bin

    # Get unique days for counting
    unique_days = df["date"].nunique()

    # Determine energy range (use corrected net energy if available)
    energy_col = "net_energy_kwh_corrected" if "net_energy_kwh_corrected" in df.columns else "net_energy_kwh"
    df[energy_col] = df[energy_col].astype(float)
    if max_power is None:
        max_power = df[energy_col].quantile(0.99)  # Use 99th percentile to exclude outliers
    if min_power is None:
        min_power = max(-1, df[energy_col].min())  # Cap at -1 kWh for visual clarity

    def make_bin_edges(lo: float, hi: float) -> np.ndarray:
        """Build bin edges with 0 as a boundary, aligned to bin_size."""
        n_below = int(np.ceil(-lo / bin_size)) if lo < 0 else 0
        n_above = int(np.ceil(hi / bin_size)) if hi > 0 else 0
        neg = np.arange(-n_below, 0) * bin_size if n_below > 0 else np.array([])
        pos = np.arange(0, n_above + 1) * bin_size if n_above > 0 else np.array([0.0])
        return np.concatenate([neg, pos])

    # Provisional bin edges (based on data range only) — needed by the curves
    # so AUC snapping uses a consistent grid.
    power_bin_edges = make_bin_edges(min_power, max_power)

    # Compute percentile curves now so we can extend max_power to cover their peak.
    curves, percentiles_found = calculate_percentile_curves(
        df, time_bins_per_day, target_areas=[1, 2, 3, 4, 5], power_bin_edges=power_bin_edges
    )
    if curves:
        curves_max = max(float(curve.max()) for curve in curves.values())
        if curves_max > max_power:
            max_power = np.ceil(curves_max / bin_size) * bin_size
            # Recompute edges and re-run curves with the extended grid so the
            # snapping and AUC are consistent with the final histogram range.
            power_bin_edges = make_bin_edges(min_power, max_power)
            curves, percentiles_found = calculate_percentile_curves(
                df, time_bins_per_day, target_areas=[1, 2, 3, 4, 5], power_bin_edges=power_bin_edges
            )

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

    # Create time labels for all bins (one per bin, based on bin width)
    time_labels_all = []
    for i in range(time_bins_per_day):
        total_minutes = i * minutes_per_bin
        time_labels_all.append(f"{total_minutes // 60:02d}:{total_minutes % 60:02d}")
    # End label is the start of the next bin (or 24:00 for the last bin)
    time_labels_end = []
    for i in range(time_bins_per_day):
        total_minutes = (i + 1) * minutes_per_bin
        time_labels_end.append("24:00" if total_minutes >= 1440 else f"{total_minutes // 60:02d}:{total_minutes % 60:02d}")
    # X-axis labels: at every bin edge when bins are wider than an hour,
    # otherwise only at hour boundaries
    if minutes_per_bin >= 60:
        # One tick per bin edge
        time_label_positions = list(range(time_bins_per_day + 1))
        time_labels_hourly = [
            f"{(i * minutes_per_bin) // 60:02d}:{(i * minutes_per_bin) % 60:02d}"
            for i in range(time_bins_per_day + 1)
        ]
    else:
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
            "Time: %{customdata[0]} - %{customdata[1]}<br>" +
            "Energy: %{customdata[2]:.2f} kWh<br>" +
            "Days exceeding: %{z}<br>" +
            "<extra></extra>"
        ),
        # customdata: [start_time, end_time, lower_edge] for each (y_bin, x_bin) cell
        customdata=[[[time_labels_all[x], time_labels_end[x], power_bin_edges[y]] for x in range(time_bins_per_day)] for y in range(power_bins)],
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
    # Add dispatch curves for fixed AUC targets
    auc_colors = {
        1: "rgba(0, 0, 255, 0.7)",
        2: "rgba(0, 180, 180, 0.7)",
        3: "rgba(0, 200, 0, 0.7)",
        4: "rgba(255, 165, 0, 0.7)",
        5: "rgba(255, 0, 0, 0.7)",
    }

    # Create time interval labels for hover (start - end time)
    time_interval_labels = [
        f"{time_labels_all[i]} - {time_labels_end[i]}" for i in range(time_bins_per_day)
    ]

    # Use bin edges for x positions to align step function with bins
    x_edges = list(range(time_bins_per_day + 1))

    for target, curve in curves.items():
        p = percentiles_found[target]
        color = auc_colors.get(target, "rgba(128, 128, 128, 0.7)")
        curve_values = [curve.get(i, np.nan) for i in range(time_bins_per_day)]
        step_x = x_edges
        step_y = curve_values + [curve_values[-1] if curve_values else np.nan]

        fig.add_trace(go.Scatter(
            x=step_x,
            y=step_y,
            mode="lines",
            name=f"{target} kWh (p={p:.0f}%)",
            line=dict(color=color, width=2, shape="hv"),
            hovertemplate=(
                f"{target} kWh curve (p={p:.1f}%)<br>" +
                "Time: %{customdata}<br>" +
                "Energy: %{y:.2f} kWh<br>" +
                "<extra></extra>"
            ),
            customdata=time_interval_labels + [time_interval_labels[-1]] if time_interval_labels else [],
        ))

    # Update layout to show legend at bottom left to avoid color scale overlap
    fig.update_layout(
        legend=dict(
            title=dict(text="Dispatch Curves (AUC target)"),
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
