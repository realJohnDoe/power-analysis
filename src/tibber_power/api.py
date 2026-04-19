from typing import Any

import requests
from pydantic import SecretStr

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

        response = requests.post(
            TIBBER_API_URL,
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def get_homes(self) -> list[dict[str, Any]]:
        """Get list of homes associated with the account."""
        result = self._query(HOMES_QUERY)
        return result["data"]["viewer"]["homes"]

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
        nodes = result["data"]["viewer"]["home"]["consumption"]["nodes"]
        return nodes
