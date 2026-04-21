import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import typer
from pydantic import SecretStr

from tibber_power.api import TibberAPI
from tibber_power.config import TibberConfig
from tibber_power.websocket import PulseCollector

app = typer.Typer(help="Tibber power consumption data downloader")

Resolution = str  # Literal["HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"]


@app.command()
def download(
    output: Path = typer.Option(
        Path.home() / "Desktop" / "tibber_consumption.csv",
        "--output",
        "-o",
        help="Output CSV file path",
    ),
    resolution: str = typer.Option(
        "HOURLY",
        "--resolution",
        "-r",
        help="Data resolution: HOURLY, DAILY, WEEKLY, MONTHLY, YEARLY",
    ),
    last: int = typer.Option(
        24,
        "--last",
        "-n",
        help="Number of data points to fetch",
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
        help="Tibber access token",
    ),
) -> None:
    """
    Download power consumption data from Tibber API and save to CSV.
    """
    # Get token from env var, CLI, or prompt
    access_token: SecretStr | None = None
    try:
        config = TibberConfig()
        access_token = config.access_token
    except Exception:
        pass

    if token:
        access_token = SecretStr(token)

    if not access_token:
        access_token = SecretStr(typer.prompt("Enter your Tibber access token", hide_input=True))

    # Initialize API client
    api = TibberAPI(access_token)

    # Get home ID if not provided
    if not home_id:
        typer.echo("Fetching homes...")
        homes = api.get_homes()
        if not homes:
            typer.echo("Error: No homes found for this account.", err=True)
            raise typer.Exit(1)
        home_id = homes[0]["id"]
        address = homes[0]["address"]
        typer.echo(f"Using home: {address['address1']}, {address['city']}")

    # Fetch consumption data
    typer.echo(f"Fetching {resolution.lower()} consumption data (last {last} periods)...")
    try:
        data = api.get_consumption(home_id, resolution=resolution, last=last)
    except Exception as e:
        typer.echo(f"Error fetching data: {e}", err=True)
        raise typer.Exit(1)

    if not data:
        typer.echo("No consumption data returned.", err=True)
        raise typer.Exit(1)

    # Filter out nodes with null consumption (common with Pulse data)
    valid_data = [node for node in data if node.get("consumption") is not None]

    if not valid_data:
        typer.echo(
            f"API returned {len(data)} records but all have null consumption values. "
            "This is common with Pulse data - the billed consumption data may not be available yet. "
            "Try DAILY resolution or check back later.",
            err=True,
        )
        raise typer.Exit(1)

    if len(valid_data) < len(data):
        typer.echo(f"Note: Filtered out {len(data) - len(valid_data)} records with null consumption values")

    # Convert to DataFrame
    df = pd.DataFrame(valid_data)

    # Rename columns for clarity
    df = df.rename(
        columns={
            "from": "period_start",
            "to": "period_end",
            "consumption": "consumption_kwh",
            "consumptionUnit": "unit",
            "unitPrice": "unit_price",
            "unitPriceVAT": "unit_price_vat",
            "cost": "total_cost",
        }
    )

    # Add metadata columns
    df["exported_at"] = datetime.now().isoformat()
    df["resolution"] = resolution

    # Ensure output directory exists
    output.parent.mkdir(parents=True, exist_ok=True)

    # Save to CSV
    df.to_csv(output, index=False)
    typer.echo(f"Saved {len(df)} records to: {output}")


@app.command()
def list_homes(
    token: Optional[str] = typer.Option(
        None,
        "--token",
        "-t",
        help="Tibber access token",
    ),
) -> None:
    """List all homes associated with your Tibber account."""
    # Get token from env var, CLI, or prompt
    access_token: SecretStr | None = None
    try:
        config = TibberConfig()
        access_token = config.access_token
    except Exception:
        pass

    if token:
        access_token = SecretStr(token)

    if not access_token:
        access_token = SecretStr(typer.prompt("Enter your Tibber access token", hide_input=True))

    api = TibberAPI(access_token)
    homes = api.get_homes()

    if not homes:
        typer.echo("No homes found.")
        return

    typer.echo(f"Found {len(homes)} home(s):")
    for home in homes:
        addr = home["address"]
        typer.echo(f"  - ID: {home['id']}")
        typer.echo(f"    Address: {addr['address1']}, {addr['city']}")


@app.command()
def live(
    output: Path = typer.Option(
        Path.home() / "Desktop" / "tibber_live.csv",
        "--output",
        "-o",
        help="Output CSV file path",
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
        help="Tibber access token",
    ),
) -> None:
    """Get real-time live measurement data from Tibber Pulse."""
    # Get token from env var, CLI, or prompt
    access_token: SecretStr | None = None
    try:
        config = TibberConfig()
        access_token = config.access_token
    except Exception:
        pass

    if token:
        access_token = SecretStr(token)

    if not access_token:
        access_token = SecretStr(typer.prompt("Enter your Tibber access token", hide_input=True))

    # Initialize API client
    api = TibberAPI(access_token)

    # Get home ID if not provided
    if not home_id:
        typer.echo("Fetching homes...")
        homes = api.get_homes()
        if not homes:
            typer.echo("Error: No homes found for this account.", err=True)
            raise typer.Exit(1)
        home_id = homes[0]["id"]
        address = homes[0]["address"]
        typer.echo(f"Using home: {address['address1']}, {address['city']}")

    # Fetch live measurement data
    typer.echo("Fetching live measurement from Pulse...")
    try:
        data = api.get_live_measurement(home_id)
    except Exception as e:
        typer.echo(f"Error fetching live data: {e}", err=True)
        raise typer.Exit(1)

    # Convert to DataFrame (single row)
    df = pd.DataFrame([data])

    # Add metadata columns
    df["exported_at"] = datetime.now().isoformat()
    df["home_id"] = home_id

    # Ensure output directory exists
    output.parent.mkdir(parents=True, exist_ok=True)

    # Save to CSV
    df.to_csv(output, index=False)
    typer.echo(f"Saved live measurement to: {output}")
    typer.echo(f"Current power: {data.get('power', 'N/A')} W")
    typer.echo(f"Accumulated consumption today: {data.get('accumulatedConsumption', 'N/A')} kWh")


@app.command()
def stream(
    output: Path = typer.Option(
        Path.home() / "Desktop" / "tibber_pulse_stream.csv",
        "--output",
        "-o",
        help="Output CSV file path",
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
        help="Tibber access token",
    ),
) -> None:
    """Stream real-time data from Tibber Pulse via WebSocket."""
    # Get token from env var, CLI, or prompt
    access_token: SecretStr | None = None
    try:
        config = TibberConfig()
        access_token = config.access_token
    except Exception:
        pass

    if token:
        access_token = SecretStr(token)

    if not access_token:
        access_token = SecretStr(typer.prompt("Enter your Tibber access token", hide_input=True))

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
    typer.echo(f"Data will be saved to: {output}")

    collector = PulseCollector(
        access_token=access_token,
        home_id=home_id,
        output_file=output,
        on_reading=lambda r: typer.echo(
            f"[{r.timestamp}] Consumption: {r.accumulated_consumption}kWh, Production: {r.accumulated_production}kWh"
        ),
    )

    try:
        asyncio.run(collector.run(duration_seconds=duration))
    except KeyboardInterrupt:
        typer.echo("\nStream stopped by user")
    finally:
        typer.echo(f"Data saved to: {output}")


if __name__ == "__main__":
    app()
