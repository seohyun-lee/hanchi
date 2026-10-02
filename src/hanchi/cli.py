"""Command-line entry point (`hanchi`).

Subcommands: ``eval`` (M4). analyze, rank, repl, expand and dict follow in M5.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from hanchi import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hanchi",
        description="Korean query understanding: per-word role & weight from context.",
    )
    parser.add_argument("--version", action="version", version=f"hanchi {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("eval", help="evaluate ranking / role cases", add_help=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "eval":
        from hanchi.evaluation import main as eval_main

        return eval_main(args[1:])
    parser = build_parser()
    parser.parse_args(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
