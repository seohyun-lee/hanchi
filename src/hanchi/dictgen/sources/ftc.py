"""Fair Trade Commission franchise brand list (data.go.kr 15125467)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from hanchi.dictgen.sources import Fetch, first, load_json


@dataclass(frozen=True)
class Brand:
    raw_name: str
    brand_id: str
    category_large: str
    category_mid: str
    year: str
    company: str


def _items(data: Any, cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = first(data, [cfg["items_path"], *cfg.get("alt_items_paths", [])])
    if items is None:
        return []
    if isinstance(items, dict):  # a single item is sometimes not wrapped in a list
        return [items]
    return [x for x in items if isinstance(x, dict)]


def collect(
    cfg: Mapping[str, Any], key: str, fetch: Fetch, year: str | None = None
) -> Iterator[Brand]:
    p = cfg["params"]
    f = cfg["fields"]
    size = int(cfg["page_size"])
    for page in range(1, int(cfg["max_pages"]) + 1):
        params = {
            p["key"]: key,
            p["page"]: str(page),
            p["page_size"]: str(size),
            p["format"]: str(p["format_value"]),
        }
        if year:
            params[p["year"]] = year
        data = load_json(fetch(str(cfg["url"]), params))
        items = _items(data, cfg)
        for it in items:
            name = str(it.get(f["name"], "") or "").strip()
            if not name:
                continue
            yield Brand(
                raw_name=name,
                brand_id=str(it.get(f["id"], "") or ""),
                category_large=str(it.get(f["category_large"], "") or ""),
                category_mid=str(it.get(f["category_mid"], "") or ""),
                year=str(it.get(f["year"], "") or ""),
                company=str(it.get(f["company"], "") or ""),
            )
        total = first(data, [cfg["total_path"], *cfg.get("alt_total_paths", [])])
        if not items or len(items) < size or (total is not None and page * size >= int(total)):
            return
