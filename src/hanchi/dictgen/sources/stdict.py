"""Standard Korean Language Dictionary lookups (CC BY-SA 2.0 KR) with a local cache.

Only a yes/no answer ("is this a common headword?") leaves this module. Responses are
cached under the user's cache directory with source and license recorded; nothing from
the dictionary is written to plugin files, reports or the repository.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from hanchi.dictgen.sources import Fetch, dig, first, load_json

CACHE_MARKER = "hanchi-stdict-cache"
SOURCE = "표준국어대사전 (국립국어원), https://stdict.korean.go.kr"
LICENSE = "CC BY-SA 2.0 KR"


class StdictChecker:
    def __init__(
        self, cfg: Mapping[str, Any], key: str, fetch: Fetch, cache_dir: str | Path | None = None
    ) -> None:
        self.cfg = cfg
        self.key = key
        self.fetch = fetch
        self.cache = Path(cache_dir or str(cfg["cache_dir"])).expanduser()
        self.hold_pos = set(cfg.get("hold_pos", []))

    def _cache_path(self, word: str) -> Path:
        return self.cache / (hashlib.sha256(word.encode("utf-8")).hexdigest()[:24] + ".json")

    def lookup(self, word: str) -> Any:
        path = self._cache_path(word)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        p = self.cfg["params"]
        params = {p["key"]: self.key, p["query"]: word, p["format"]: str(p["format_value"])}
        raw = self.fetch(str(self.cfg["url"]), params)
        try:
            response = load_json(raw) if raw.strip() else {}
        except ValueError:
            response = {}
        self.cache.mkdir(parents=True, exist_ok=True)
        record = {
            "marker": CACHE_MARKER,
            "source": SOURCE,
            "license": LICENSE,
            "notice": "Local cache only. Do not commit or redistribute.",
            "fetched": date.today().isoformat(),
            "query": word,
            "response": response,
        }
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return response

    def is_common_word(self, word: str) -> bool:
        """True if ``word`` is a headword with a held part of speech (e.g. a common noun)."""
        items = dig(self.lookup(word), self.cfg["items_path"]) or []
        if isinstance(items, dict):
            items = [items]
        target = word.replace(" ", "")
        for it in items:
            if not isinstance(it, Mapping):
                continue
            headword = str(it.get(self.cfg["word_field"], "")).replace("-", "").replace("^", "")
            if headword.replace(" ", "") != target:
                continue
            pos = first(it, self.cfg["pos_paths"])
            if isinstance(pos, list):
                pos = pos[0] if pos else ""
            if not self.hold_pos or str(pos) in self.hold_pos:
                return True
        return False
