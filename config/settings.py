"""Shared settings policy; application-specific fields belong to their owning context."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Base policy for typed environment configuration, with no application fields."""

    model_config = SettingsConfigDict(
        env_prefix="EW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )
