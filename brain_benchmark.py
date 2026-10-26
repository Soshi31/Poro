#!/usr/bin/python3
"""Măsoară pe Pi latența locală, tokens/s efectiv și RAM maxim al llama-server."""

import argparse
import json
from pathlib import Path

import config
from brain.llm import LocalLLM


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", default="Tell me in one short sentence who Poro is.")
    parser.add_argument("--tokens", type=int, default=32)
    parser.add_argument("--model", type=Path, help="GGUF de comparat fără schimbarea configurației implicite")
    args = parser.parse_args(argv)
    if args.tokens < 1:
        parser.error("--tokens trebuie să fie pozitiv")
    if args.model is not None:
        config.LLM_MODEL_PATH = args.model.resolve()
    with LocalLLM() as llm:
        answer = llm.generate([{"role": "system", "content": "Reply concisely in English as Poro from the Freljord."},
                               {"role": "user", "content": args.prompt}], max_tokens=args.tokens)
        print(json.dumps({"answer": answer, "metrics": llm.last_metrics},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
