from __future__ import annotations

from titlemcp_platform_publicsearch.client import (
    PublicSearchClient,
    PublicSearchProtocolError,
    PublicSearchQuery,
    PublicSearchResult,
)
from titlemcp_platform_publicsearch.config import PublicSearchSiteConfig
from titlemcp_platform_publicsearch.connector import PublicSearchRecorderConnector
from titlemcp_platform_publicsearch.index import PublicSearchIndex


def build_recorder_source_connector(
    config: PublicSearchSiteConfig,
) -> PublicSearchRecorderConnector:
    """A source connector for one PublicSearch county."""
    return PublicSearchRecorderConnector(config)


__all__ = [
    "PublicSearchClient",
    "PublicSearchIndex",
    "PublicSearchProtocolError",
    "PublicSearchQuery",
    "PublicSearchRecorderConnector",
    "PublicSearchResult",
    "PublicSearchSiteConfig",
    "build_recorder_source_connector",
]
