"""WebSocket client for Tibber Pulse real-time streaming."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
from gql import Client, gql
from gql.transport.websockets import WebsocketsTransport
from pydantic import SecretStr

TIBBER_GQL_URL = "https://api.tibber.com/v1-beta/gql"

WEBSOCKET_URL_QUERY = """
{
  viewer {
    websocketSubscriptionUrl
  }
}
"""


def get_monthly_csv_path(base_path: Path) -> Path:
    """Generate a monthly CSV path based on current date.
    
    If base_path is /data/tibber_pulse.csv, returns /data/tibber_pulse_2024-01.csv
    """
    now = datetime.now()
    month_str = now.strftime("%Y-%m")
    
    # Insert month before the extension
    if base_path.suffix:
        stem = base_path.stem
        suffix = base_path.suffix
        return base_path.parent / f"{stem}_{month_str}{suffix}"
    else:
        return base_path.parent / f"{base_path.name}_{month_str}.csv"


def make_subscription(home_id: str):
    """Create subscription query with embedded home_id (required by Tibber API)."""
    return gql(f"""
    subscription {{
      liveMeasurement(homeId: "{home_id}") {{
        timestamp
        accumulatedConsumption
        accumulatedProduction
      }}
    }}
    """)


@dataclass
class PulseReading:
    """A single Pulse measurement reading."""

    timestamp: str
    accumulated_consumption: float | None = None
    accumulated_production: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PulseReading":
        return cls(
            timestamp=data.get("timestamp", ""),
            accumulated_consumption=data.get("accumulatedConsumption"),
            accumulated_production=data.get("accumulatedProduction"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "accumulated_consumption": self.accumulated_consumption,
            "accumulated_production": self.accumulated_production,
        }


class PulseCollector:
    """Collects Pulse data via WebSocket and saves to monthly CSV files."""

    def __init__(
        self,
        access_token: SecretStr,
        home_id: str,
        output_file: Path,
        on_reading: Callable[[PulseReading], None] | None = None,
    ):
        self.access_token = access_token
        self.home_id = home_id
        self.base_output_path = Path(output_file)
        self.on_reading = on_reading
        self.readings: list[PulseReading] = []
        self._stop_event = asyncio.Event()
        self._current_month: str = datetime.now().strftime("%Y-%m")
        self._last_data_received: datetime | None = None
        self._reconnect_delay: float = 1.0  # Start with 1 second, exponential backoff

    @property
    def output_file(self) -> Path:
        """Get the current month's output file path."""
        current_month = datetime.now().strftime("%Y-%m")
        if current_month != self._current_month:
            # Month has changed, start new file
            self._current_month = current_month
            self.readings = []  # Start fresh for new month
        return get_monthly_csv_path(self.base_output_path)

    async def _watchdog(self):
        """Monitor connection health and trigger reconnect if no data for 10 minutes."""
        timeout_seconds = 600  # 10 minutes
        
        while not self._stop_event.is_set():
            await asyncio.sleep(60)  # Check every minute
            
            if self._stop_event.is_set():
                break
                
            if self._last_data_received is not None:
                elapsed = (datetime.now() - self._last_data_received).total_seconds()
                if elapsed > timeout_seconds:
                    print(f"\n⚠️  No data received for {elapsed:.0f}s - connection may be stale")
                    print("Triggering reconnect...")
                    # Signal that we need to reconnect
                    self._reconnect_event.set()
                    break

    async def run(self, duration_seconds: float | None = None):
        """Start collecting data with automatic reconnect logic."""
        token = self.access_token.get_secret_value()
        
        # Start duration timer if specified
        if duration_seconds:
            asyncio.create_task(self._stop_after(duration_seconds))

        print(f"Connecting to Pulse stream for home {self.home_id}...")
        print(f"Saving data to: {self.output_file}")
        
        # Reconnect loop
        max_reconnect_delay = 300  # Max 5 minutes between reconnects
        reconnect_attempts = 0
        
        while not self._stop_event.is_set():
            try:
                await self._connect_and_stream(token, duration_seconds)
                
                # If we get here without exception, it was a clean stop
                if not self._stop_event.is_set():
                    print("Stream ended unexpectedly, reconnecting...")
                else:
                    break
                    
            except Exception as e:
                if self._stop_event.is_set():
                    break
                print(f"\nConnection error: {e}")
                
            # Exponential backoff for reconnect
            reconnect_attempts += 1
            delay = min(self._reconnect_delay * (2 ** (reconnect_attempts - 1)), max_reconnect_delay)
            # Add jitter to avoid thundering herd
            delay = delay * (0.5 + 0.5 * (asyncio.get_event_loop().time() % 1))
            
            print(f"Reconnecting in {delay:.1f}s (attempt {reconnect_attempts})...")
            await asyncio.sleep(delay)
        
        self._save()
        print(f"Saved {len(self.readings)} readings to {self.output_file}")

    async def _connect_and_stream(self, token: str, duration_seconds: float | None = None):
        """Establish connection and stream data."""
        # Step 1: Fetch dynamic WebSocket URL via HTTP
        print("\nFetching WebSocket URL...")
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "tibber-power-cli/0.1.0",
            "Content-Type": "application/json",
        }
        response = requests.post(
            TIBBER_GQL_URL,
            headers=headers,
            json={"query": WEBSOCKET_URL_QUERY},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            raise Exception(f"API error: {data['errors']}")
        
        ws_url = data["data"]["viewer"]["websocketSubscriptionUrl"]
        print(f"WebSocket URL: {ws_url}")
        
        # Step 2: Create WebSocket transport
        transport = WebsocketsTransport(
            url=ws_url,
            init_payload={"token": token},
            headers={"User-Agent": "tibber-power-cli/0.1.0"},
            ping_interval=60,
            pong_timeout=None,
        )

        # Create client
        client = Client(transport=transport, fetch_schema_from_transport=False)
        
        # Create reconnect event for this connection
        self._reconnect_event = asyncio.Event()

        # Start watchdog
        watchdog_task = asyncio.create_task(self._watchdog())

        try:
            # Subscribe and process results
            subscription = make_subscription(self.home_id)
            
            async with client as session:
                print("Connected! Waiting for data (updates every 1-2 minutes)...")
                
                async for result in session.subscribe(subscription):
                    # Check if reconnect was triggered
                    if self._reconnect_event.is_set():
                        print("Reconnect triggered by watchdog")
                        break
                        
                    if self._stop_event.is_set():
                        break

                    data = result.get("liveMeasurement")
                    if data:
                        reading = PulseReading.from_dict(data)
                        self.readings.append(reading)
                        self._save()
                        self._last_data_received = datetime.now()
                        self._reconnect_delay = 1.0  # Reset backoff on successful data
                        
                        if self.on_reading:
                            self.on_reading(reading)

        except KeyboardInterrupt:
            print("\nStopping collector...")
            self._stop_event.set()
        except Exception as e:
            print(f"Stream error: {e}")
            raise
        finally:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
            self._save()

    def _save(self):
        """Save readings to CSV, appending if file exists."""
        if not self.readings:
            return
        
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([r.to_dict() for r in self.readings])
        
        # Append if file exists, otherwise create new
        if self.output_file.exists():
            df.to_csv(self.output_file, index=False, mode='a', header=False)
        else:
            df.to_csv(self.output_file, index=False)
        
        # Clear readings after saving to prevent duplicates on reconnect
        self.readings = []

    async def _stop_after(self, seconds: float):
        """Stop collection after specified duration."""
        await asyncio.sleep(seconds)
        print(f"\nReached duration limit ({seconds}s), stopping...")
        self._stop_event.set()

    def stop(self):
        """Signal the collector to stop."""
        self._stop_event.set()
