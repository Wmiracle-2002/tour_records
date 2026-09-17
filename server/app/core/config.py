from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Footmarks API"
    database_url: str = "sqlite:///./data/footmarks.db"
    token_secret: str | None = None
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FOOTMARKS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
