from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.recorder import InstrumentKind


class FidlarAvaSiteConfig(BaseModel):
    """One county on Fidlar AVA.

    ``app_url`` is the county's AvaWeb app, the page a visitor searches from
    (``https://ava.example.test/XXExample/AvaWeb/``). The app names the web API
    it talks to, so the API's address is read from it rather than configured.
    Document types are the county's own: one writes ``MORTGAGE RELEASE``,
    another ``CANC`` for the same thing, and ``document_type_kinds`` corrects
    the shared classifier by type where a county's wording misleads it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    county: str
    state: str = Field(min_length=2, max_length=2)
    name: str
    app_url: str
    owner: str | None = None
    priority: int = 220
    #: The least time between two requests to the county's site.
    min_interval_seconds: float = Field(default=1.1, ge=0)
    document_type_kinds: dict[str, InstrumentKind] = Field(default_factory=dict)

    @field_validator("state")
    @classmethod
    def _upper_state(cls, value: str) -> str:
        return value.upper()

    @field_validator("app_url")
    @classmethod
    def _app_directory(cls, value: str) -> str:
        # The app's files are read relative to it, so it ends in a slash.
        return value.rstrip("/") + "/"

    @field_validator("document_type_kinds")
    @classmethod
    def _normalized_types(cls, value: dict[str, InstrumentKind]) -> dict[str, InstrumentKind]:
        return {" ".join(key.upper().split()): kind for key, kind in value.items()}

    @property
    def scope(self) -> JurisdictionScope:
        return JurisdictionScope(country="US", state=self.state, county=self.county)
