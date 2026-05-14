"""Title operations MCP platform."""

from title_mcp._version import __version__
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings

__all__ = ["TitleMCPPlatform", "TitleMCPSettings", "__version__"]
