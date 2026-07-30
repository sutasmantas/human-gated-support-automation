from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="SUPPORT_",
        extra="ignore",
    )

    data_dir: Path = PROJECT_ROOT / "data" / "runtime"
    automation_provider: Literal["local", "openai-compatible"] = "local"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    approval_arr_threshold: int = 25_000
    notification_webhook_url: str = ""

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "support.sqlite3"
