from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from ollama import chat

from title_mcp.settings import get_settings


def mcp_tool_to_ollama_tool(tool: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


def tool_result_to_text(result: Any) -> str:
    if result.structuredContent:
        return json.dumps(result.structuredContent)

    parts = []
    for item in result.content:
        if hasattr(item, "text"):
            parts.append(item.text)
        else:
            parts.append(str(item))
    return "\n".join(parts)


def default_server_params() -> StdioServerParameters:
    project_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    src_path = str(project_root / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "title_mcp.mcp.server"],
        cwd=str(project_root),
        env=env,
    )


async def run_ollama_prompt(prompt: str, *, model: str | None = None) -> str:
    settings = get_settings()
    model = model or settings.ollama_model

    async with stdio_client(default_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            ollama_tools = [mcp_tool_to_ollama_tool(tool) for tool in tools_response.tools]

            messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

            while True:
                response = chat(model=model, messages=messages, tools=ollama_tools)
                message = response.message
                messages.append(message)

                if not message.tool_calls:
                    return message.content or ""

                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    arguments = tool_call.function.arguments or {}
                    result = await session.call_tool(tool_name, arguments)
                    messages.append(
                        {
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result_to_text(result),
                        }
                    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an Ollama prompt against the title MCP server."
    )
    parser.add_argument("prompt", nargs="*", help="Prompt text")
    parser.add_argument("--model", default=None, help="Ollama model name")
    args = parser.parse_args()
    prompt = " ".join(args.prompt).strip() or (
        "Use your tools to create a municipal lien search workflow for file 2025-123 in "
        "Pinellas County, Florida, then summarize the next actions."
    )
    print(asyncio.run(run_ollama_prompt(prompt, model=args.model)))


if __name__ == "__main__":
    main()
