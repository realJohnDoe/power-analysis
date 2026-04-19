from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TibberConfig(BaseSettings):
    """Configuration for Tibber API access."""

    model_config = SettingsConfigDict(
        env_prefix="TIBBER_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    access_token: SecretStr

    def get_token(self) -> str:
        """Get the decrypted access token."""
        return self.access_token.get_secret_value()
