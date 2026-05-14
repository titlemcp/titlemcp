from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGGER = logging.getLogger("samples.pacer_ollama.client")
PACER_TOOL_NAME = "pacer_bankruptcy_search"


def shared_helpers():
    from samples._shared.ollama_mcp import configure_logging, run_tool_trigger_sample

    return configure_logging, run_tool_trigger_sample


def default_prompt(
    *,
    scenario: str,
    first_name: str | None,
    last_name: str,
    business_name: str,
    summarize_with_ollama: bool,
) -> str:
    if scenario == "business":
        prompt = (
            "Can you check bankruptcy records for the business "
            f"{business_name} and return the structured PACER result?"
        )
    else:
        name = " ".join(part for part in [first_name, last_name] if part)
        prompt = (
            "Can you check bankruptcy records for "
            f"{name} and return the structured PACER result?"
        )

    if summarize_with_ollama:
        return f"{prompt} After the lookup, give me a short summary too."
    return prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask Ollama a natural bankruptcy-search question and log PACER tool use."
    )
    parser.add_argument("--model", default="qwen3:8b", help="Ollama model name")
    parser.add_argument(
        "--scenario",
        choices=["person", "business"],
        default="person",
        help="Natural prompt scenario to generate when --prompt is not supplied",
    )
    parser.add_argument("--first-name", default="John", help="First name for person searches")
    parser.add_argument("--last-name", default="Smith", help="Last name for person searches")
    parser.add_argument(
        "--business-name",
        default="Example Holdings LLC",
        help="Business name for entity searches",
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
        "--summarize-with-ollama",
        action="store_true",
        help="Ask Ollama for a final narrative summary after the PACER result",
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
        help="Seconds to wait for the MCP PACER tool before failing visibly",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging, run_tool_trigger_sample = shared_helpers()
    configure_logging(args.log_level)
    prompt = args.prompt or default_prompt(
        scenario=args.scenario,
        first_name=args.first_name,
        last_name=args.last_name,
        business_name=args.business_name,
        summarize_with_ollama=args.summarize_with_ollama,
    )
    LOGGER.info("Scenario: %s", args.scenario)
    LOGGER.info("Prompt: %s", prompt)
    final_text = asyncio.run(
        run_tool_trigger_sample(
            tool_name=PACER_TOOL_NAME,
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
