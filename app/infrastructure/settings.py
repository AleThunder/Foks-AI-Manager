from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load runtime configuration from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    foks_base_url: str = Field(default="https://my.foks.biz", alias="FOKS_BASE_URL")
    foks_username: str = Field(default="", alias="FOKS_USERNAME")
    foks_password: str = Field(default="", alias="FOKS_PASSWORD")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_timeout_seconds: float = Field(default=60.0, alias="OPENAI_TIMEOUT_SECONDS")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    app_log_dir: str = Field(default="logs", alias="APP_LOG_DIR")
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_user: str = Field(default="postgres", alias="DB_USER")
    db_password: str = Field(default="postgres", alias="DB_PASSWORD")
    db_name: str = Field(default="foks_app", alias="DB_NAME")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    @property
    def sqlalchemy_database_url(self) -> str:
        """Build the SQLAlchemy connection URL for the configured PostgreSQL server."""
        username = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return f"postgresql+psycopg://{username}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object so the application reads env only once."""
    return Settings()
