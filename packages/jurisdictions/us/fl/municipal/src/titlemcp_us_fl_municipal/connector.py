from __future__ import annotations

from datetime import date

from title_mcp.adapters.base import JurisdictionScope
from title_mcp.domain.models import Jurisdiction, WorkflowKind
from title_mcp.sources import (
    SourceDescriptor,
    SourceKind,
    SourceQuery,
    SourceResult,
    municipal_directory_result,
)
from titlemcp_us_fl_municipal.directory import (
    COVERAGE,
    FloridaDirectory,
    is_unincorporated,
    load_directory,
)


class FloridaMunicipalDirectory:
    """Who issues each Florida lien letter, and where permits and code cases are.

    Each entry was read from the government's own pages: its lien search page,
    fee schedule and request form, its permit and code case search, and its
    utility billing. The answer for a city carries the city's entry and its
    county's.
    """

    source_id = "us-fl-municipal-directory"
    descriptor = SourceDescriptor(
        source_id=source_id,
        name="Florida municipal lien directory",
        kind=SourceKind.MUNICIPAL,
        jurisdiction_scope=JurisdictionScope(country="US", state="FL"),
        priority=200,
        requires_auth=False,
        supports_workflow_kinds=[WorkflowKind.MUNICIPAL_LIEN_SEARCH],
    )

    def __init__(
        self, *, directory: FloridaDirectory | None = None, today: date | None = None
    ) -> None:
        self._directory = directory or load_directory()
        self._today = today

    def supports(self, jurisdiction: Jurisdiction, kind: object | None = None) -> bool:
        kind_matches = kind is None or kind == self.descriptor.kind
        return kind_matches and self.descriptor.jurisdiction_scope.matches(jurisdiction)

    async def query(self, query: SourceQuery) -> SourceResult:
        return await self.find_offices(query.jurisdiction)

    async def find_offices(self, jurisdiction: Jurisdiction) -> SourceResult:
        if is_unincorporated(jurisdiction.municipality):
            jurisdiction = jurisdiction.model_copy(update={"municipality": None})
        municipality = (
            self._directory.municipality(jurisdiction.municipality, jurisdiction.county)
            if jurisdiction.municipality
            else None
        )
        county = self._directory.county(jurisdiction.county)
        if county is None and municipality is not None:
            county = self._directory.county(municipality.county)
        return municipal_directory_result(
            descriptor=self.descriptor,
            jurisdiction=jurisdiction,
            municipality=municipality,
            county=county,
            coverage=COVERAGE,
            today=self._today,
        )
