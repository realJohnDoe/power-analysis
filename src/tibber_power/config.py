from pydantic import SecretStr
from pydantic_settings import BaseSettings


class TibberConfig(BaseSettings):
    """Configuration for Tibber API access."""

    model_config = SettingsConfigDict(env_prefix="TIBBER_")

    access_token: SecretStr

    def get_token(self) -> str:
        """Get the decrypted access token."""
        return self.access_token.get_secret_value()
