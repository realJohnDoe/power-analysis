from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import typer

from pydantic import SecretStr

from tibber_power.api import TibberAPI
from tibber_power.config import TibberConfig

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
        168,
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

    # Convert to DataFrame
    df = pd.DataFrame(data)

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


if __name__ == "__main__":
    app()
