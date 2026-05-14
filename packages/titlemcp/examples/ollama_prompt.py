from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def main() -> None:
    from title_mcp.client.ollama_bridge import run_ollama_prompt

    prompt = " ".join(sys.argv[1:]).strip() or (
        "Use your tools to create a municipal lien search workflow for file 2025-123 "
        "in Pinellas County, Florida. Summarize the workflow status and next actions."
    )
    print(await run_ollama_prompt(prompt))


if __name__ == "__main__":
    asyncio.run(main())
