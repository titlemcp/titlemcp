import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def secret_value(value: SecretStr | str | None) -> str | None:
    """The plain text of a credential setting, for the one call that sends it."""
    if isinstance(value, SecretStr):
        return value.get_secret_value() or None
    return value or None


class TitleMCPSettings(BaseSettings):
    """Runtime settings for the title operations MCP platform.

    Every credential is a ``SecretStr``: printing, logging or dumping the settings
    shows ``**********`` in its place. Read one with ``secret_value()`` at the call
    that needs it, and nowhere else.
    """

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
    postgres_dsn: SecretStr | None = None

    mcp_transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    mcp_public_url: str | None = None
    inspector_url: str | None = None
    inspector_backend_url: str | None = None
    mcp_dns_rebinding_protection: bool = True
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    mcp_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("mcp_allowed_hosts", "mcp_allowed_origins", mode="before")
    @classmethod
    def parse_security_list(cls, value: Any) -> Any:
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                return [item.strip() for item in stripped.split(",") if item.strip()]
            return decoded
        return value

    ollama_model: str = "qwen3"
    ollama_server_command: str = "python"

    pacer_username: str | None = None
    pacer_password: SecretStr | None = None
    pacer_client_code: str | None = None
    pacer_qa_mode: bool = False
    pacer_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)

    ofac_cache_dir: str = "~/.cache/titlemcp/ofac"
    ofac_max_age_hours: float = Field(default=24.0, ge=0.0, le=720.0)
    ofac_timeout_seconds: float = Field(default=120.0, ge=5.0, le=600.0)

    smart_proxy: SecretStr | None = None
    regrid_proxy_port_start: int = Field(default=10001, ge=1, le=65535)
    regrid_proxy_port_end: int = Field(default=10999, ge=1, le=65535)
    regrid_max_retries: int = Field(default=5, ge=0, le=20)
    regrid_backoff_factor: float = Field(default=0.5, ge=0.0, le=30.0)
    regrid_cookie_refresh_threshold: int = Field(default=25, ge=1, le=1000)
    regrid_max_proxy_attempts: int = Field(default=10, ge=1, le=1000)
    regrid_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    regrid_cookie_timeout_seconds: float = Field(default=5.0, ge=1.0, le=120.0)

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5"
    anthropic_timeout_seconds: float = Field(default=300.0, ge=1.0, le=1800.0)

    serpapi_api_key: SecretStr | None = None
    serpapi_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)

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
