from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_mode: Literal["local", "deployed"] = "local"
    app_access_code: str | None = None
    database_url: str = "sqlite+pysqlite:///./ai_calendar.db"
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_api_key: str | None = None
    llm_model: str = "glm-5.2"
    llm_timeout_seconds: float = 120
    llm_max_output_tokens: int = 4096
    default_timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def require_deployed_access_code(self) -> "Settings":
        if self.app_mode == "deployed" and not (self.app_access_code or "").strip():
            raise ValueError("APP_ACCESS_CODE is required in deployed mode")
        return self

    @property
    def bind_host(self) -> str:
        return "127.0.0.1" if self.app_mode == "local" else "0.0.0.0"
