from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from title_mcp.client.ollama_bridge import run_ollama_prompt


async def main() -> None:
    prompt = (
        "Use your tools to create a municipal lien search workflow for file 2025-123 "
        "in Pinellas County, Florida. Summarize the workflow status and next actions."
    )
    print(await run_ollama_prompt(prompt))


if __name__ == "__main__":
    asyncio.run(main())
