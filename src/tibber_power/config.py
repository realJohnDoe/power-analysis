from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TibberConfig(BaseSettings):
    """Configuration for Tibber API access.
    
    Reads from environment variables (TIBBER_* prefix) and .env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="TIBBER_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    access_token: SecretStr
    output_csv_path: Path = Path.home() / "Desktop" / "tibber_pulse_stream.csv"

    def get_token(self) -> str:
        """Get the decrypted access token."""
        return self.access_token.get_secret_value()
