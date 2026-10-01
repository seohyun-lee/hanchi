"""YAML configuration loading and layering.

Configuration is layered: package defaults, then user plugins, then overrides. Later
layers win; mappings merge recursively, everything else (lists, scalars) is replaced.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


def deep_merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def load_package_yaml(package: str, name: str) -> dict[str, Any]:
    text = resources.files(package).joinpath(name).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def layered(package: str, name: str, extra_dirs: Iterable[str | Path] = ()) -> dict[str, Any]:
    """Package default ``name`` merged with ``<dir>/name`` for each existing extra dir."""
    config = load_package_yaml(package, name)
    for d in extra_dirs:
        path = Path(d) / name
        if path.is_file():
            config = deep_merge(config, load_yaml(path))
    return config
