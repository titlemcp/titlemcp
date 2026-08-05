from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGGER = logging.getLogger("samples.lake_auditor_ollama.client")
LAKE_TOOL_NAME = "lake_county_auditor_search"


def local_src_paths(root: Path) -> list[Path]:
    # The Lake auditor tool ships in the shared iasWorld platform package plus
    # the multi-county titlemcp-us-oh-auditor package.
    return [
        root / "packages" / "titlemcp" / "src",
        root / "packages" / "platforms" / "iasworld" / "src",
        root / "packages" / "jurisdictions" / "us" / "oh" / "auditor" / "src",
    ]


def lake_server_params(root: Path, log_level: str) -> Any:
    from samples._shared.ollama_mcp import core_server_params

    return core_server_params(
        root,
        log_level,
        extra_python_paths=local_src_paths(root)[1:],
    )


def default_prompt(
    *,
    scenario: str,
    parcel_id: str,
    address: str,
    owner_name: str,
    summarize_with_ollama: bool,
) -> str:
    if scenario == "address":
        prompt = (
            "I'm reviewing a Lake County, Ohio property. Can you look up the "
            f"county auditor record for {address} and return the assessment record?"
        )
    elif scenario == "owner":
        prompt = (
            "I'm checking Lake County, Ohio auditor records for an owner. "
            f"Can you search for {owner_name} and return any property assessment "
            "records you find?"
        )
    else:
        prompt = (
            "I'm reviewing a Lake County, Ohio property. Can you look up the "
            f"county auditor record for parcel {parcel_id} and return the assessment "
            "record?"
        )

    if summarize_with_ollama:
        return (
            f"{prompt} After you find it, give me a short plain-English summary "
            "of the canonical assessment record too."
        )
    return prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ask Ollama a natural Lake County auditor question and log whether "
            "it chooses the MCP tool."
        )
    )
    parser.add_argument("--model", default="qwen3:8b", help="Ollama model name")
    parser.add_argument(
        "--scenario",
        choices=["parcel", "address", "owner"],
        default="parcel",
        help="Natural prompt scenario to generate when --prompt is not supplied",
    )
    parser.add_argument(
        "--parcel-id",
        default="00A0000000002",
        help="Lake County parcel ID for the parcel scenario",
    )
    parser.add_argument(
        "--address",
        default="100 EXAMPLE ST",
        help="Lake County property address for the address scenario",
    )
    parser.add_argument(
        "--owner-name",
        default="DOE JANE A",
        help="Owner name for the owner scenario",
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
        help="Ask Ollama for a final narrative summary after the canonical tool result",
    )
    parser.add_argument(
        "--stop-after-tool",
        action="store_true",
        help="Deprecated: this is now the default unless --summarize-with-ollama is used",
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=3,
        help="Maximum model/tool iterations before failing",
    )
    return parser.parse_args()


def shared_helpers():
    from samples._shared.ollama_mcp import configure_logging, run_tool_trigger_sample

    return configure_logging, run_tool_trigger_sample


def main() -> None:
    args = parse_args()
    configure_logging, run_tool_trigger_sample = shared_helpers()
    configure_logging(args.log_level)
    prompt = args.prompt or default_prompt(
        scenario=args.scenario,
        parcel_id=args.parcel_id,
        address=args.address,
        owner_name=args.owner_name,
        summarize_with_ollama=args.summarize_with_ollama,
    )
    LOGGER.info("Scenario: %s", args.scenario)
    LOGGER.info("Prompt: %s", prompt)
    final_text = asyncio.run(
        run_tool_trigger_sample(
            tool_name=LAKE_TOOL_NAME,
            prompt=prompt,
            model=args.model,
            log_level=args.log_level,
            max_tool_rounds=args.max_tool_rounds,
            num_predict=args.num_predict,
            think=args.think,
            stop_after_tool=args.stop_after_tool or not args.summarize_with_ollama,
            logger=LOGGER,
            server_params_factory=lake_server_params,
        )
    )
    print(final_text)


if __name__ == "__main__":
    main()
