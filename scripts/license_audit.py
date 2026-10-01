"""Print the license metadata of hanchi's runtime dependency closure.

Usage: .venv/bin/python scripts/license_audit.py [extra ...]
Fails (exit 1) if a package declares a GPL/AGPL/LGPL or non-commercial license.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError, distribution

FORBIDDEN = re.compile(
    r"\b(A?GPL|LGPL|GNU (Affero |Lesser )?General Public|NC\b|NonCommercial)", re.I
)


def _name(req: str) -> str:
    return re.split(r"[\s;<>=!~\[(]", req, maxsplit=1)[0].lower()


def closure(root: str, extras: set[str]) -> list[str]:
    seen: list[str] = []
    stack = [(root, extras)]
    while stack:
        name, wanted = stack.pop()
        if name in seen:
            continue
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            continue
        seen.append(name)
        for req in dist.requires or []:
            marker = req.split(";", 1)[1] if ";" in req else ""
            extra = re.search(r"extra\s*==\s*['\"]([^'\"]+)", marker)
            if extra and extra.group(1) not in wanted:
                continue
            stack.append((_name(req), set()))
    return seen


def license_of(name: str) -> str:
    meta = distribution(name).metadata
    expr = meta.get("License-Expression")
    if expr:
        return expr
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License")
    ]
    if classifiers:
        return " / ".join(classifiers)
    return (meta.get("License") or "UNKNOWN").splitlines()[0]


def main() -> int:
    bad = 0
    for name in closure("hanchi", set(sys.argv[1:])):
        lic = license_of(name)
        flag = "!!" if FORBIDDEN.search(lic) else "  "
        bad += flag == "!!"
        print(f"{flag} {name:<24} {distribution(name).version:<12} {lic}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
