import asyncio
from pathlib import Path
from typing import Optional

import typer

from tibber_power.api import TibberAPI
from tibber_power.config import TibberConfig
from tibber_power.plotting import create_2d_histogram
from tibber_power.websocket import PulseCollector

app = typer.Typer(help="Tibber Pulse data streaming tool")


def get_output_path(config: TibberConfig, cli_output: Optional[Path]) -> Path:
    """Get output path from CLI option, env var, or default."""
    if cli_output:
        return cli_output
    return config.output_csv_path


@app.command()
def stream(
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output CSV file path (or set TIBBER_OUTPUT_CSV_PATH env var)",
    ),
    duration: Optional[int] = typer.Option(
        None,
        "--duration",
        "-d",
        help="Duration to stream in seconds (if not set, streams until interrupted)",
    ),
    home_id: Optional[str] = typer.Option(
        None,
        "--home-id",
        "-h",
        help="Home ID (auto-detected if not specified)",
    ),
) -> None:
    """Stream real-time data from Tibber Pulse via WebSocket."""
    # Load config
    config = TibberConfig()

    # Validate token is set
    if config.access_token is None:
        typer.echo(
            "Error: TIBBER_ACCESS_TOKEN not set.\n"
            "Create a .env file with TIBBER_ACCESS_TOKEN=your-token or set the environment variable.",
            err=True,
        )
        raise typer.Exit(1)

    # Get output path from CLI, env var, or default
    output_path = get_output_path(config, output)

    # Get home ID if not provided
    if not home_id:
        typer.echo("Fetching homes...")
        api = TibberAPI(config.access_token)
        homes = api.get_homes()
        if not homes:
            typer.echo("Error: No homes found for this account.", err=True)
            raise typer.Exit(1)
        home_id = homes[0]["id"]
        address = homes[0]["address"]
        typer.echo(f"Using home: {address['address1']}, {address['city']}")

    # Start streaming
    typer.echo(f"Starting Pulse stream...")
    typer.echo(f"Data will be saved to: {output_path}")

    collector = PulseCollector(
        access_token=config.access_token,
        home_id=home_id,
        output_file=output_path,
        on_reading=lambda r: typer.echo(
            f"[{r.timestamp}] Consumption: {r.accumulated_consumption}kWh, Production: {r.accumulated_production}kWh"
        ),
    )

    try:
        asyncio.run(collector.run(duration_seconds=duration))
    except KeyboardInterrupt:
        typer.echo("\nStream stopped by user")
    finally:
        typer.echo(f"Data saved to: {output_path}")


@app.command()
def deduplicate(
    input_path: Path = typer.Argument(
        ...,
        help="Input CSV file to deduplicate",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output CSV file path (default: overwrites input file)",
    ),
) -> None:
    """Remove duplicate rows from a CSV file based on timestamp."""
    import pandas as pd

    typer.echo(f"Reading {input_path}...")
    df = pd.read_csv(input_path)

    initial_count = len(df)
    typer.echo(f"Initial rows: {initial_count}")

    # Remove duplicates based on timestamp column
    if "timestamp" in df.columns:
        df = df.drop_duplicates(subset=["timestamp"], keep="first")
    else:
        # Fallback: drop duplicates based on all columns
        df = df.drop_duplicates(keep="first")

    final_count = len(df)
    removed = initial_count - final_count

    # Save result
    output_path = output or input_path
    df.to_csv(output_path, index=False)

    typer.echo(f"Removed {removed} duplicate rows")
    typer.echo(f"Final rows: {final_count}")
    typer.echo(f"Saved to: {output_path}")


@app.command()
def plot(
    input_path: Path = typer.Argument(
        ...,
        help="Input CSV file or directory containing CSV files to analyze",
        exists=True,
        dir_okay=True,
        readable=True,
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output HTML file path (e.g., plot.html). Opens in browser if not set.",
    ),
    min_power: float = typer.Option(
        -1.0,
        "--min-power",
        help="Minimum power for Y-axis in kW (default: -1.0)",
    ),
    max_power: float = typer.Option(
        None,
        "--max-power",
        "-m",
        help="Maximum power for Y-axis (auto-detected if not set)",
    ),
    power_bins: int = typer.Option(
        50,
        "--power-bins",
        "-b",
        help="Number of power bins for the histogram",
    ),
) -> None:
    """Generate a 2D histogram plot from CSV data.

    Accepts a single CSV file or a directory of CSV files (e.g., multiple months).
    Creates a heatmap showing power consumption patterns:
    - X-axis: Time of day (24 hours in 15-minute bins)
    - Y-axis: Net power consumption (kW)
    - Color: Number of days where power exceeded threshold at that time
    """
    try:
        create_2d_histogram(
            csv_path=input_path,
            output_path=output,
            min_power=min_power,
            max_power=max_power,
            power_bins=power_bins,
        )
        if output:
            typer.echo(f"Plot saved to: {output}")
        else:
            typer.echo("Plot displayed.")
    except Exception as e:
        typer.echo(f"Error generating plot: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
