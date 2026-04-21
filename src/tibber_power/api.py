from typing import Any

import requests
from pydantic import SecretStr

# Debug logging for API responses
DEBUG = False

def log_response(context: str, data: Any) -> None:
    """Log API response for debugging."""
    if DEBUG:
        print(f"[DEBUG] {context}:")
        print(f"  {data}")

TIBBER_API_URL = "https://api.tibber.com/v1-beta/gql"

HOMES_QUERY = """
query {
  viewer {
    homes {
      id
      address {
        address1
        city
      }
    }
  }
}
"""

CONSUMPTION_QUERY = """
query Consumption($homeId: ID!, $resolution: EnergyResolution!, $last: Int) {
  viewer {
    home(id: $homeId) {
      consumption(resolution: $resolution, last: $last) {
        nodes {
          from
          to
          cost
          unitPrice
          unitPriceVAT
          consumption
          consumptionUnit
        }
      }
    }
  }
}
"""

LIVE_MEASUREMENT_QUERY = """
query LiveMeasurement($homeId: ID!) {
  viewer {
    home(id: $homeId) {
      liveMeasurement {
        timestamp
        accumulatedConsumption
        accumulatedProduction
      }
    }
  }
}
"""


class TibberAPI:
    """Client for the Tibber GraphQL API."""

    def __init__(self, access_token: SecretStr):
        self.headers = {
            "Authorization": f"Bearer {access_token.get_secret_value()}",
            "Content-Type": "application/json",
        }

    def _query(self, query: str, variables: dict | None = None) -> dict[str, Any]:
        """Execute a GraphQL query."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        log_response("Request payload", payload)

        response = requests.post(
            TIBBER_API_URL,
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        log_response("Response data", data)

        # Check for GraphQL errors
        if "errors" in data:
            error_msgs = [e.get("message", str(e)) for e in data["errors"]]
            raise Exception(f"API errors: {', '.join(error_msgs)}")

        return data

    def get_homes(self) -> list[dict[str, Any]]:
        """Get list of homes associated with the account."""
        result = self._query(HOMES_QUERY)
        viewer = result.get("data", {}).get("viewer")
        if viewer is None:
            raise Exception(f"No viewer data in response: {result}")
        homes = viewer.get("homes")
        if homes is None:
            raise Exception(f"No homes data in response: {result}")
        return homes

    def get_consumption(
        self,
        home_id: str,
        resolution: str = "HOURLY",
        last: int = 24,
    ) -> list[dict[str, Any]]:
        """
        Get consumption data for a home.

        Args:
            home_id: The home ID
            resolution: EnergyResolution (HOURLY, DAILY, WEEKLY, MONTHLY, YEARLY)
            last: Number of periods to fetch
        """
        variables = {
            "homeId": home_id,
            "resolution": resolution,
            "last": last,
        }
        result = self._query(CONSUMPTION_QUERY, variables)
        home = result.get("data", {}).get("viewer", {}).get("home")
        if home is None:
            raise Exception(f"No home data in response: {result}")

        consumption = home.get("consumption")
        if consumption is None:
            raise Exception(
                f"No consumption data available for home {home_id}. "
                "This home may not have a smart meter or the data is not yet available."
            )

        nodes = consumption.get("nodes", [])
        return nodes

    def get_live_measurement(self, home_id: str) -> dict[str, Any]:
        """
        Get real-time measurement data from Tibber Pulse.

        Args:
            home_id: The home ID
        """
        variables = {"homeId": home_id}
        result = self._query(LIVE_MEASUREMENT_QUERY, variables)
        home = result.get("data", {}).get("viewer", {}).get("home")
        if home is None:
            raise Exception(f"No home data in response: {result}")

        measurement = home.get("liveMeasurement")
        if measurement is None:
            raise Exception(
                f"No live measurement data available for home {home_id}. "
                "Make sure you have a Tibber Pulse connected."
            )

        return measurement
