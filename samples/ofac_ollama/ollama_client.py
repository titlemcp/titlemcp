from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGGER = logging.getLogger("samples.ofac_ollama.client")
OFAC_TOOL_NAME = "ofac_screen_parties"


def shared_helpers():
    from samples._shared.ollama_mcp import configure_logging, run_tool_trigger_sample

    return configure_logging, run_tool_trigger_sample


def default_prompt(*, buyer: str, seller: str, lender: str, summarize_with_ollama: bool) -> str:
    prompt = (
        "Before we close this file, run the sanctions check on everyone involved: the buyer "
        f"{buyer}, the seller {seller}, and the lender {lender}. Return the structured result."
    )
    if summarize_with_ollama:
        return f"{prompt} Then tell me briefly whether anyone needs a closer look."
    return prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask Ollama a natural closing-file sanctions question and log OFAC tool use."
    )
    parser.add_argument("--model", default="qwen3:8b", help="Ollama model name")
    parser.add_argument("--buyer", default="Mary Johnson", help="Buyer's name")
    parser.add_argument("--seller", default="Example Holdings LLC", help="Seller's name")
    parser.add_argument("--lender", default="Example Mortgage LLC", help="Lender's name")
    parser.add_argument("--prompt", default=None, help="Override the default prompt")
    parser.add_argument("--log-level", default="INFO", help="Python log level")
    parser.add_argument("--num-predict", type=int, default=512, help="Max tokens per round")
    parser.add_argument("--think", action="store_true", help="Allow Ollama thinking mode")
    parser.add_argument(
        "--summarize-with-ollama",
        action="store_true",
        help="Ask Ollama for a final narrative summary after the screening result",
    )
    parser.add_argument("--max-tool-rounds", type=int, default=3, help="Model/tool iterations")
    parser.add_argument(
        "--tool-timeout",
        type=float,
        default=180.0,
        help="Seconds to wait for the tool (the first run downloads OFAC's lists)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging, run_tool_trigger_sample = shared_helpers()
    configure_logging(args.log_level)
    prompt = args.prompt or default_prompt(
        buyer=args.buyer,
        seller=args.seller,
        lender=args.lender,
        summarize_with_ollama=args.summarize_with_ollama,
    )
    LOGGER.info("Prompt: %s", prompt)
    final_text = asyncio.run(
        run_tool_trigger_sample(
            tool_name=OFAC_TOOL_NAME,
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
