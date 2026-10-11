from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.recorder import InstrumentKind


class CountyFusionSiteConfig(BaseModel):
    """One county on CountyFusion.

    Counties share hosts: ``countyfusion8.kofiletech.us`` serves several, and
    ``county_key`` (``WayneOH``) picks the county. Document types are the
    county's own: Ashland writes ``RELEASE MORTGAGE`` where Wayne writes
    ``MORTGAGE RELEASE``, and Wayne's plain ``RELEASE`` releases a lease.
    ``document_type_kinds`` corrects the shared classifier by type
    description where a county's wording misleads it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str
    county: str
    state: str = Field(min_length=2, max_length=2)
    name: str
    host: str
    county_key: str
    owner: str | None = None
    priority: int = 220
    #: The least time between two requests to the county's site.
    min_interval_seconds: float = Field(default=1.1, ge=0)
    document_type_kinds: dict[str, InstrumentKind] = Field(default_factory=dict)

    @field_validator("state")
    @classmethod
    def _upper_state(cls, value: str) -> str:
        return value.upper()

    @field_validator("host")
    @classmethod
    def _bare_host(cls, value: str) -> str:
        return value.removeprefix("https://").removeprefix("http://").strip("/")

    @property
    def base_url(self) -> str:
        return f"https://{self.host}/countyweb"

    @property
    def scope(self) -> JurisdictionScope:
        return JurisdictionScope(country="US", state=self.state, county=self.county)
