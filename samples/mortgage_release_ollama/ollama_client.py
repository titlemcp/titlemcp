from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGGER = logging.getLogger("samples.mortgage_release_ollama.client")
RELEASE_TOOL_NAME = "mortgage_release_search"


def shared_helpers():
    from samples._shared.ollama_mcp import configure_logging, run_tool_trigger_sample

    return configure_logging, run_tool_trigger_sample


def default_prompt(
    *,
    county: str,
    instrument: str,
    paid_off_on: str,
    summarize_with_ollama: bool,
) -> str:
    prompt = (
        f"We paid off a mortgage at closing on {paid_off_on}. The commitment lists it as "
        f"instrument {instrument}, recorded in {county} County, Ohio. Has the lender recorded "
        "the release yet?"
    )
    if summarize_with_ollama:
        return f"{prompt} After checking, tell me in a sentence what the record shows."
    return prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask Ollama whether a paid-off mortgage was released, and log the tool use."
    )
    parser.add_argument("--model", default="qwen3:8b", help="Ollama model name")
    parser.add_argument("--county", default="Cuyahoga", help="Ohio county the mortgage is in")
    parser.add_argument(
        "--instrument",
        default="202001150101",
        help="The mortgage's instrument number, as the commitment lists it",
    )
    parser.add_argument("--paid-off-on", default="2026-05-01", help="Payoff date, YYYY-MM-DD")
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
        "--summarize-with-ollama",
        action="store_true",
        help="Ask Ollama for a final summary after the release search result",
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
        default=90.0,
        help="Seconds to wait for the MCP tool before failing visibly",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging, run_tool_trigger_sample = shared_helpers()
    configure_logging(args.log_level)
    prompt = args.prompt or default_prompt(
        county=args.county,
        instrument=args.instrument,
        paid_off_on=args.paid_off_on,
        summarize_with_ollama=args.summarize_with_ollama,
    )
    LOGGER.info("Prompt: %s", prompt)
    final_text = asyncio.run(
        run_tool_trigger_sample(
            tool_name=RELEASE_TOOL_NAME,
            prompt=prompt,
            model=args.model,
            log_level=args.log_level,
            max_tool_rounds=args.max_tool_rounds,
            num_predict=args.num_predict,
            think=args.think,
            stop_after_tool=not args.summarize_with_ollama,
            logger=LOGGER,
            tool_timeout_seconds=args.tool_timeout,
        )
    )
    print(final_text)


if __name__ == "__main__":
    main()
