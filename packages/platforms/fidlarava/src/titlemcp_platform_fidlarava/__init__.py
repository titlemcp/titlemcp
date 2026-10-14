from __future__ import annotations

from titlemcp_platform_fidlarava.client import (
    FidlarAvaCaptchaRequired,
    FidlarAvaClient,
    FidlarAvaProtocolError,
)
from titlemcp_platform_fidlarava.config import FidlarAvaSiteConfig
from titlemcp_platform_fidlarava.connector import FidlarAvaRecorderConnector
from titlemcp_platform_fidlarava.index import FidlarAvaIndex


def build_recorder_source_connector(
    config: FidlarAvaSiteConfig,
) -> FidlarAvaRecorderConnector:
    """A source connector for one Fidlar AVA county."""
    return FidlarAvaRecorderConnector(config)


__all__ = [
    "FidlarAvaCaptchaRequired",
    "FidlarAvaClient",
    "FidlarAvaIndex",
    "FidlarAvaProtocolError",
    "FidlarAvaRecorderConnector",
    "FidlarAvaSiteConfig",
    "build_recorder_source_connector",
]
