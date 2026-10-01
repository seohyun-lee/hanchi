"""Command-line entry point (`hanchi`).

Subcommands (analyze, rank, eval, repl, expand, dict) are added in later milestones.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from hanchi import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hanchi",
        description="Korean query understanding: per-word role & weight from context.",
    )
    parser.add_argument("--version", action="version", version=f"hanchi {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
