"""Data sources. Network access goes through :func:`fetch` so tests can replace it."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

Fetch = Callable[[str, Mapping[str, str]], bytes]


class MissingKeyError(RuntimeError):
    """An API key environment variable is not set."""


def require_key(env: str, purpose: str) -> str:
    value = os.environ.get(env, "").strip()
    if not value:
        raise MissingKeyError(
            f"{purpose} needs an API key: set the environment variable {env}.\n"
            f"Get a key from the data provider and run e.g. `export {env}=...`."
        )
    return value


def http_fetch(timeout: float, retries: int, user_agent: str) -> Fetch:
    def fetch(url: str, params: Mapping[str, str]) -> bytes:
        full = url + "?" + urllib.parse.urlencode(params, safe="%")
        req = urllib.request.Request(full, headers={"User-Agent": user_agent})
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return bytes(resp.read())
            except OSError:
                if attempt == retries:
                    raise
                time.sleep(1 + attempt)
        raise AssertionError("unreachable")

    return fetch


def dig(data: Any, path: Sequence[str]) -> Any:
    node = data
    for key in path:
        if isinstance(node, Mapping) and key in node:
            node = node[key]
        else:
            return None
    return node


def first(data: Any, paths: Sequence[Sequence[str]]) -> Any:
    for p in paths:
        found = dig(data, p)
        if found is not None:
            return found
    return None


def load_json(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))
