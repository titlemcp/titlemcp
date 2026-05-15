from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGGER = logging.getLogger("samples.hoa_serpapi_ollama.client")
HOA_TOOL_NAME = "hoa_contact_search"


def shared_helpers():
    from samples._shared.ollama_mcp import configure_logging, run_tool_trigger_sample

    return configure_logging, run_tool_trigger_sample


def default_prompt(
    *,
    hoa_name: str,
    state: str | None,
    max_results: int,
    extract_with_ollama: bool,
) -> str:
    location = f" in {state}" if state else ""
    prompt = (
        "I need contact details for an HOA. Find contact information for "
        f"{hoa_name}{location}. Return up to {max_results} candidate results."
    )
    if extract_with_ollama:
        prompt += (
            " After the tool returns, read records[0].first_result_page.text and"
            " extract the HOA's structured contact information as JSON with these"
            " keys: hoa_name, management_company, mailing_address, phone_numbers,"
            " email_addresses, website, source_url. Use null for fields you cannot"
            " confirm from the page text."
        )
    return prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ask Ollama a natural HOA contact lookup question and log whether it "
            "chooses the SerpAPI-backed MCP tool."
        )
    )
    parser.add_argument("--model", default="qwen3:8b", help="Ollama model name")
    parser.add_argument(
        "--hoa-name",
        default="Tartan Fields Homeowners Association",
        help="HOA or homeowners association name for the prompt",
    )
    parser.add_argument(
        "--state",
        default="Ohio",
        help="Optional state name or abbreviation to bias the search",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum candidate search results to ask the tool to return",
    )
    parser.add_argument("--prompt", default=None, help="Override the default prompt")
    parser.add_argument("--log-level", default="INFO", help="Python log level")
    parser.add_argument(
        "--num-predict",
        type=int,
        default=512,
        help="Maximum Ollama response tokens per chat round",
    )
    parser.add_argument(
        "--think",
        action="store_true",
        help="Allow Ollama thinking mode for models that support it",
    )
    parser.add_argument(
        "--extract-with-ollama",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Send the tool result back to Ollama so it extracts structured HOA "
            "contacts from records[0].first_result_page.text"
        ),
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=3,
        help="Maximum model/tool iterations before failing",
    )
    parser.add_argument(
        "--tool-timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for the MCP HOA tool before failing visibly",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging, run_tool_trigger_sample = shared_helpers()
    configure_logging(args.log_level)
    state = args.state or None
    prompt = args.prompt or default_prompt(
        hoa_name=args.hoa_name,
        state=state,
        max_results=args.max_results,
        extract_with_ollama=args.extract_with_ollama,
    )
    LOGGER.info("HOA name: %s", args.hoa_name)
    LOGGER.info("State: %s", state or "<none>")
    LOGGER.info("Prompt: %s", prompt)
    final_text = asyncio.run(
        run_tool_trigger_sample(
            tool_name=HOA_TOOL_NAME,
            prompt=prompt,
            model=args.model,
            log_level=args.log_level,
            max_tool_rounds=args.max_tool_rounds,
            num_predict=args.num_predict,
            think=args.think,
            stop_after_tool=not args.extract_with_ollama,
            logger=LOGGER,
            tool_timeout_seconds=args.tool_timeout,
        )
    )
    print(final_text)


if __name__ == "__main__":
    main()
