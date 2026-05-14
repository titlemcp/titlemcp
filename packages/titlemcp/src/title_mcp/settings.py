from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TitleMCPSettings(BaseSettings):
    """Runtime settings for the title operations MCP platform."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TITLE_MCP_",
        extra="ignore",
    )

    app_name: str = "Title Operations MCP"
    environment: str = "local"
    log_level: str = "INFO"
    log_json: bool = True

    state_backend: Literal["memory", "postgres"] = "memory"
    postgres_dsn: str | None = None

    mcp_transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000

    ollama_model: str = "qwen3"
    ollama_server_command: str = "python"

    pacer_username: str | None = None
    pacer_password: str | None = None
    pacer_client_code: str | None = None
    pacer_qa_mode: bool = False
    pacer_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)

    smart_proxy: str | None = None
    regrid_proxy_port_start: int = Field(default=10001, ge=1, le=65535)
    regrid_proxy_port_end: int = Field(default=10999, ge=1, le=65535)
    regrid_max_retries: int = Field(default=5, ge=0, le=20)
    regrid_backoff_factor: float = Field(default=0.5, ge=0.0, le=30.0)
    regrid_cookie_refresh_threshold: int = Field(default=25, ge=1, le=1000)
    regrid_max_proxy_attempts: int = Field(default=10, ge=1, le=1000)
    regrid_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    regrid_cookie_timeout_seconds: float = Field(default=5.0, ge=1.0, le=120.0)

    background_worker_concurrency: int = Field(default=4, ge=1, le=64)
    default_human_review_required: bool = True
    jurisdiction_config_path: str | None = None
    load_entry_point_capabilities: bool = True
    load_entry_point_adapters: bool = True
    load_entry_point_sources: bool = True
    load_entry_point_vendors: bool = True
    load_entry_point_toolsets: bool = True
    load_entry_point_plugins: bool = False

    aws_region: str | None = None
    textract_s3_bucket: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> TitleMCPSettings:
    return TitleMCPSettings()
