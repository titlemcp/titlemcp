from __future__ import annotations

from titlemcp_platform_countyfusion.client import CountyFusionClient, CountyFusionProtocolError
from titlemcp_platform_countyfusion.config import CountyFusionSiteConfig
from titlemcp_platform_countyfusion.connector import CountyFusionRecorderConnector
from titlemcp_platform_countyfusion.index import CountyFusionIndex


def build_recorder_source_connector(
    config: CountyFusionSiteConfig,
) -> CountyFusionRecorderConnector:
    """A source connector for one CountyFusion county."""
    return CountyFusionRecorderConnector(config)


__all__ = [
    "CountyFusionClient",
    "CountyFusionIndex",
    "CountyFusionProtocolError",
    "CountyFusionRecorderConnector",
    "CountyFusionSiteConfig",
    "build_recorder_source_connector",
]
