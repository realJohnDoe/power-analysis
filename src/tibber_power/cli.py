import asyncio
from pathlib import Path
from typing import Optional

import typer
from pydantic import SecretStr

from tibber_power.api import TibberAPI
from tibber_power.config import TibberConfig
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
    token: Optional[str] = typer.Option(
        None,
        "--token",
        "-t",
        help="Tibber access token (or set TIBBER_ACCESS_TOKEN env var)",
    ),
) -> None:
    """Stream real-time data from Tibber Pulse via WebSocket."""
    # Load config
    try:
        config = TibberConfig()
    except Exception:
        config = None

    # Get token from CLI, env var, or prompt
    if token:
        access_token = SecretStr(token)
    elif config:
        access_token = config.access_token
    else:
        access_token = SecretStr(typer.prompt("Enter your Tibber access token", hide_input=True))

    # Get output path from CLI, env var, or default
    output_path = get_output_path(config, output) if config else (output or Path.home() / "Desktop" / "tibber_pulse_stream.csv")

    # Get home ID if not provided
    if not home_id:
        typer.echo("Fetching homes...")
        api = TibberAPI(access_token)
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
        access_token=access_token,
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


if __name__ == "__main__":
    app()
