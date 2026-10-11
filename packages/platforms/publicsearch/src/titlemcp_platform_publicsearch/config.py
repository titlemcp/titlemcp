from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.recorder import InstrumentKind


class PublicSearchSiteConfig(BaseModel):
    """One county's PublicSearch site.

    The protocol is the same in every county. What differs is the address and
    the county's own document types: Cuyahoga writes ``RELS - RELEASE
    SATISFACTION`` and Stark writes ``MORTGAGE RELEASE``. The shared classifier
    reads both; ``document_type_kinds`` corrects it by type code where a
    county's wording misleads it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    county: str
    state: str = Field(min_length=2, max_length=2)
    name: str
    base_url: str
    owner: str | None = None
    priority: int = 220
    #: The least time between two searches of the county's site.
    min_interval_seconds: float = Field(default=0.5, ge=0)
    document_type_kinds: dict[str, InstrumentKind] = Field(default_factory=dict)

    @field_validator("state")
    @classmethod
    def _upper_state(cls, value: str) -> str:
        return value.upper()

    @field_validator("base_url")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def scope(self) -> JurisdictionScope:
        return JurisdictionScope(country="US", state=self.state, county=self.county)
