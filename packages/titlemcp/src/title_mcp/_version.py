from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("titlemcp")
except PackageNotFoundError:
    # Run from a source tree that was never installed, so there is no metadata
    # to read. The real version is the release tag, applied at build time.
    __version__ = "0+unknown"
