from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg.conninfo import make_conninfo
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HorizonShip API"
    database_url: str | None = None
    azure_pg_host: str | None = None
    azure_pg_name: str = ""
    azure_pg_user: str | None = None
    azure_pg_password: str | None = None
    azure_pg_port: int = 5432
    azure_pg_sslmode: str = "require"
    database_pool_min_size: int = Field(default=1, ge=1, le=10)
    database_pool_max_size: int = Field(default=5, ge=1, le=20)
    database_connect_timeout_seconds: float = Field(default=10, ge=1, le=60)
    azure_openai_endpoint: str = ""
    azure_openai_key: str | None = Field(default=None, repr=False)
    azure_openai_deployment: str = "gpt-5.4"
    azure_embed_deployment: str = "text-embedding-3-small"
    azure_api_version: str = "2025-03-01-preview"
    embedding_model_alias: str = "horizonship-embedding"
    chat_provider: Literal["azure_openai", "horizondb"] = "azure_openai"
    embedding_provider: Literal["azure_openai", "horizondb"] = "azure_openai"
    chat_model_alias: str = Field(default="horizonship-chat", min_length=1)
    model_timeout_seconds: int = Field(default=45, ge=1, le=100)
    search_timezone: str = "Asia/Seoul"
    capture_query_plan: bool = False
    embedding_batch_size: int = Field(default=20, ge=1, le=100)
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("search_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("SEARCH_TIMEZONE must be an IANA timezone") from exc
        return value

    @property
    def database_conninfo(self) -> str | None:
        if self.database_url:
            return self.database_url
        if not all((self.azure_pg_host, self.azure_pg_user, self.azure_pg_password)):
            return None
        return make_conninfo(
            host=self.azure_pg_host,
            dbname=self.azure_pg_name,
            user=self.azure_pg_user,
            password=self.azure_pg_password,
            port=self.azure_pg_port,
            sslmode=self.azure_pg_sslmode,
        )

    def validate_live_configuration(self) -> None:
        missing: list[str] = []
        if not self.database_conninfo:
            missing.append("DATABASE_URL or Azure PostgreSQL connection settings")
        if not self.azure_openai_endpoint:
            missing.append("AZURE_OPENAI_ENDPOINT")
        if missing:
            raise ValueError(
                "Live HorizonShip configuration is required: " + ", ".join(missing)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
