from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ERASURE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/erasure.db"
    master_key: str = ""
    password_hash: str = ""
    session_secret: str = ""
    base_url: str = "http://127.0.0.1:8787"
    live_submissions: bool = False
    demo_mode: bool = False
    desktop_mode: bool = False
    desktop_root: str = ''
    desktop_data_dir: str = ''
    google_client_id: str = ""
    google_client_secret: str = ""
    jev_enabled: bool = False
    typesafe_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="TYPESAFE_API_KEY")
    templates_dir: Path = Path("templates")
    static_dir: Path = Path("static")
    catalog_dir: Path = Path("catalog")
    worker_poll_seconds: float = 2.0
    session_hours: int = 12

    @model_validator(mode='after')
    def isolated_demo_database(self):
        if self.demo_mode and not (
            self.database_url.startswith('sqlite:///') and self.database_url.endswith('/demo.db')
        ):
            raise ValueError('Demo requires its own SQLite demo.db; never enable it on the live database')
        return self

    @property
    def configured(self) -> bool:
        return bool(self.master_key and self.password_hash and self.session_secret)


@lru_cache
def get_settings() -> Settings:
    isolated = any(os.environ.get(key) == 'true' for key in ('ERASURE_DEMO_MODE', 'ERASURE_DESKTOP_MODE'))
    return Settings(_env_file=None) if isolated else Settings()
