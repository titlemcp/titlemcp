from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(
        os.pathsep
    )
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "title_mcp.mcp.server"],
        cwd=str(ROOT),
        env=env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("TOOLS:")
            for tool in tools.tools:
                print(f"- {tool.name}")

            result = await session.call_tool(
                "request_municipal_lien_search",
                {
                    "file_number": "2025-123",
                    "state": "FL",
                    "county": "Pinellas",
                    "municipality": "St. Petersburg",
                    "parcel_id": "12-34-56-7890",
                },
            )

            print("RESULT:")
            print(result)


if __name__ == "__main__":
    asyncio.run(main())
