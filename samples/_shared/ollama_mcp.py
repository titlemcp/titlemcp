from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_pythonpath(root: Path, extra_paths: list[Path] | None = None) -> str:
    local_paths = [str(root / "packages" / "titlemcp" / "src")]
    local_paths.extend(str(path) for path in extra_paths or [])
    current = os.environ.get("PYTHONPATH")
    if current:
        local_paths.append(current)
    return os.pathsep.join(local_paths)


def core_server_params(
    root: Path,
    log_level: str,
    *,
    extra_python_paths: list[Path] | None = None,
) -> Any:
    from mcp import StdioServerParameters

    env = dict(os.environ)
    env["PYTHONPATH"] = build_pythonpath(root, extra_python_paths)
    env["TITLE_MCP_LOG_LEVEL"] = log_level.upper()
    env["TITLE_MCP_LOG_JSON"] = "false"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "title_mcp.mcp.server"],
        cwd=str(root),
        env=env,
    )


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
    structured_content = getattr(result, "structuredContent", None)
    if structured_content:
        return json.dumps(structured_content, default=str)

    parts = []
    for item in getattr(result, "content", []):
        parts.append(item.text if hasattr(item, "text") else str(item))
    return "\n".join(parts)


def summarize_source_result(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text[:300].replace("\n", " ")

    if not isinstance(payload, dict):
        return text[:300].replace("\n", " ")

    status = payload.get("status")
    records = payload.get("records")
    record_count = len(records) if isinstance(records, list) else 0
    warnings = payload.get("warnings") or []
    parts = [f"status={status!r}", f"records={record_count}", f"warnings={len(warnings)}"]

    first_record = records[0] if isinstance(records, list) and records else None
    if isinstance(first_record, dict):
        for key in ("schema_name", "record_type", "result_count"):
            if first_record.get(key) is not None:
                parts.append(f"{key}={first_record[key]!r}")
        if isinstance(first_record.get("query"), dict):
            query = first_record["query"]
            for key in ("hoa_name", "state", "address", "business_name", "last_name"):
                if query.get(key):
                    parts.append(f"{key}={query[key]!r}")
        if isinstance(first_record.get("search"), dict):
            search_query = first_record["search"].get("query")
            if isinstance(search_query, dict) and search_query.get("address"):
                parts.append(f"address={search_query['address']!r}")
        if isinstance(first_record.get("best_match"), dict):
            best_match = first_record["best_match"]
            if best_match.get("name"):
                parts.append(f"best_match={best_match['name']!r}")
        for key in ("email_addresses", "phone_numbers", "addresses", "websites"):
            values = first_record.get(key)
            if isinstance(values, list):
                parts.append(f"{key}={len(values)}")
        if isinstance(first_record.get("summary"), dict):
            summary = first_record["summary"]
            if summary.get("title_officer_review_required") is not None:
                parts.append(
                    "title_officer_review_required="
                    f"{summary['title_officer_review_required']!r}"
                )
    return ", ".join(parts)


async def run_tool_trigger_sample(
    *,
    tool_name: str,
    prompt: str,
    model: str,
    log_level: str,
    max_tool_rounds: int,
    num_predict: int,
    think: bool,
    stop_after_tool: bool,
    logger: logging.Logger,
    tool_timeout_seconds: float | None = None,
    server_params_factory: Callable[[Path, str], Any] | None = None,
) -> str:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from ollama import chat

    root = repo_root()
    params = (
        server_params_factory(root, log_level)
        if server_params_factory
        else core_server_params(root, log_level)
    )
    logger.info("Repo root: %s", root)
    logger.info("Starting MCP server command: %s %s", params.command, " ".join(params.args))
    logger.info("Using Ollama model: %s", model)
    logger.info("Ollama options: think=%s, num_predict=%s", think, num_predict)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            logger.info("Initializing MCP session")
            await session.initialize()

            tools_response = await session.list_tools()
            tool_names = [tool.name for tool in tools_response.tools]
            logger.info("MCP tools discovered: %s", ", ".join(tool_names))

            target_tools = [tool for tool in tools_response.tools if tool.name == tool_name]
            if not target_tools:
                raise RuntimeError(f"MCP server did not expose {tool_name!r}")

            ollama_tools = [mcp_tool_to_ollama_tool(target_tools[0])]
            messages: list[dict[str, Any] | Any] = [{"role": "user", "content": prompt}]
            logger.info("Sending prompt to Ollama")

            saw_tool_call = False
            for round_number in range(1, max_tool_rounds + 1):
                logger.info("Ollama chat round %s", round_number)
                response = chat(
                    model=model,
                    messages=messages,
                    tools=ollama_tools,
                    think=think,
                    options={"num_predict": num_predict},
                )
                message = response.message
                messages.append(message)

                tool_calls = message.tool_calls or []
                if not tool_calls:
                    if not saw_tool_call:
                        raise RuntimeError(
                            f"Ollama returned a final answer without calling {tool_name!r}. "
                            "Try a tool-capable model or a stricter prompt."
                        )
                    logger.info("Ollama returned final text response")
                    return message.content or ""

                for tool_call in tool_calls:
                    requested_tool = tool_call.function.name
                    arguments = tool_call.function.arguments or {}
                    logger.info("Ollama requested tool: %s", requested_tool)
                    logger.info("Tool arguments: %s", json.dumps(arguments, sort_keys=True))

                    if requested_tool != tool_name:
                        raise RuntimeError(f"Ollama requested unexpected tool {requested_tool!r}")

                    saw_tool_call = True
                    if tool_timeout_seconds:
                        logger.info(
                            "Waiting for MCP tool result with %.1fs timeout",
                            tool_timeout_seconds,
                        )
                        try:
                            result = await asyncio.wait_for(
                                session.call_tool(requested_tool, arguments),
                                timeout=tool_timeout_seconds,
                            )
                        except TimeoutError as exc:
                            raise TimeoutError(
                                f"MCP tool {requested_tool!r} did not return within "
                                f"{tool_timeout_seconds:.1f} seconds."
                            ) from exc
                    else:
                        logger.info("Waiting for MCP tool result")
                        result = await session.call_tool(requested_tool, arguments)
                    result_text = tool_result_to_text(result)
                    logger.info("MCP tool returned %s characters", len(result_text))
                    logger.info("MCP result summary: %s", summarize_source_result(result_text))
                    if stop_after_tool:
                        logger.info("Stopping after MCP tool result")
                        return result_text
                    messages.append(
                        {
                            "role": "tool",
                            "name": requested_tool,
                            "content": result_text,
                        }
                    )

            raise RuntimeError(f"Ollama did not finish after {max_tool_rounds} tool rounds")
