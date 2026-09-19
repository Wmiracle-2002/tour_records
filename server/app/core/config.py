from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Footmarks API"
    database_url: str = "sqlite:///./data/footmarks.db"
    token_secret: str | None = None
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    cos_bucket: str | None = "footmark-1489262329"
    cos_region: str = "ap-hongkong"
    cos_domain: str = "https://footmark-1489262329.cos.ap-hongkong.myqcloud.com"
    cos_secret_id: str | None = None
    cos_secret_key: str | None = None
    cos_session_token: str | None = None
    cos_url_expire_seconds: int = 3600
    amap_web_key: str | None = None
    amap_base_url: str = "https://restapi.amap.com"
    amap_timeout_seconds: float = 10.0
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=1, ge=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FOOTMARKS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
