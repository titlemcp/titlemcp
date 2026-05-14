from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from title_mcp.mcp.server import main


if __name__ == "__main__":
    main()
