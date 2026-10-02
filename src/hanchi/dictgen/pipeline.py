"""collect → clean → diff → judge → write → report."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from hanchi.config import deep_merge, load_package_yaml, load_yaml
from hanchi.dictgen.names import clean
from hanchi.dictgen.sources import Fetch, http_fetch, require_key
from hanchi.dictgen.sources import ftc as ftc_source
from hanchi.dictgen.sources.stdict import StdictChecker

APPROVED = "approved"
HELD = "held"
REVIEW = "review"
EXISTING = "existing"

ENTITY_FILE = "entities/{source}_brands.tsv"
REVIEW_FILE = "review/{source}_review.tsv"
HELD_FILE = "review/{source}_held.tsv"
STATE_FILE = ".dictgen/state.json"
REPORT_FILE = "reports/dictgen-{day}.md"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = load_package_yaml("hanchi.dictgen.data", "dictgen.yaml")
    return deep_merge(cfg, load_yaml(path)) if path else cfg


@dataclass
class Candidate:
    name: str
    key: str
    source: str
    source_id: str = ""
    category: str = ""
    aliases: list[str] = field(default_factory=list)
    decision: str = ""
    reason: str = ""


@dataclass
class Result:
    source: str
    candidates: list[Candidate]
    removed: list[str]
    files: dict[str, Path]
    report: Path
    stats: dict[str, Any]

    def count(self, decision: str) -> int:
        return sum(c.decision == decision for c in self.candidates)


def _read_tsv_keys(paths: Iterable[Path], key: Callable[[str], str]) -> set[str]:
    keys: set[str] = set()
    for p in paths:
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                keys.add(key(line.split("\t")[0].lstrip("-")))
    return keys


def collect_ftc(cfg: Mapping[str, Any], fetch: Fetch, key: Callable[[str], str]) -> list[Candidate]:
    api_key = require_key(cfg["ftc"]["key_env"], "the FTC brand collector")
    out: dict[str, Candidate] = {}
    for b in ftc_source.collect(cfg["ftc"], api_key, fetch):
        cn = clean(b.raw_name)
        k = key(cn.name)
        if not k:
            continue
        category = " > ".join(x for x in (b.category_large, b.category_mid) if x)
        if k in out:
            for a in cn.aliases:
                if a not in out[k].aliases:
                    out[k].aliases.append(a)
            continue
        out[k] = Candidate(cn.name, k, "ftc", b.brand_id, category, cn.aliases)
    return list(out.values())


def judge(
    candidates: Sequence[Candidate],
    existing: set[str],
    cfg: Mapping[str, Any],
    stdict: StdictChecker | None,
) -> None:
    rules = cfg["judge"]
    min_len = int(rules["min_name_length"])
    auto = set(rules["auto_approve_sources"])
    for c in candidates:
        if c.key in existing:
            c.decision, c.reason = EXISTING, "already in the plugin"
        elif len(c.key) < min_len:
            c.decision, c.reason = REVIEW, f"name shorter than {min_len}"
        elif stdict is not None and stdict.is_common_word(c.name):
            c.decision, c.reason = HELD, "common dictionary headword"
        elif c.source in auto:
            c.decision, c.reason = APPROVED, f"registered source ({c.source})"
        else:
            c.decision, c.reason = REVIEW, "needs review"


def name_stats(
    names: Sequence[str], tokenize: Callable[[str], list[str]], cfg: Mapping[str, Any]
) -> dict[str, Any]:
    """End-token distribution (category-word candidates) and token IDF over names."""
    s = cfg["stats"]
    ends: Counter[str] = Counter()
    df: Counter[str] = Counter()
    for n in names:
        toks = tokenize(n)
        if len(toks) > 1:
            ends[toks[-1]] += 1
        df.update(set(toks))
    total = max(1, len(names))
    idf = {t: round(math.log(total / c), 4) for t, c in df.items()}
    top = [
        (t, c)
        for t, c in ends.most_common(int(s["top_end_tokens"]))
        if c >= int(s["min_end_token_count"])
    ]
    return {"names": len(names), "end_tokens": top, "idf": idf}


def _write_tsv(path: Path, header: str, rows: Iterable[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def write_outputs(
    out: Path,
    source: str,
    candidates: Sequence[Candidate],
    key: Callable[[str], str],
    stats: Mapping[str, Any] | None,
    write_idf: bool,
) -> dict[str, Path]:
    files: dict[str, Path] = {}
    entity_path = out / ENTITY_FILE.format(source=source)
    previous: dict[str, str] = {}
    if entity_path.is_file():
        for line in entity_path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                previous[key(line.split("\t")[0])] = line
    rows = dict(previous)
    for c in candidates:
        if c.decision != APPROVED:
            continue
        rows[c.key] = f"{c.name}\t{c.name}\tbrand\t{source}\t1.0"
        for a in c.aliases:
            rows.setdefault(key(a), f"{a}\t{c.name}\tbrand\t{source}\t1.0")
    files["entities"] = _write_tsv(
        entity_path,
        "# name\tcanonical\ttype\tsource\tscore   (generated by hanchi dictgen)",
        [rows[k] for k in sorted(rows)],
    )
    review = [c for c in candidates if c.decision == REVIEW]
    files["review"] = _write_tsv(
        out / REVIEW_FILE.format(source=source),
        "# name\tkey\tsource_id\tcategory\taliases\treason   (move approved rows to entities/)",
        [
            f"{c.name}\t{c.key}\t{c.source_id}\t{c.category}\t{'|'.join(c.aliases)}\t{c.reason}"
            for c in review
        ],
    )
    held = [c for c in candidates if c.decision == HELD]
    files["held"] = _write_tsv(
        out / HELD_FILE.format(source=source),
        "# name\tsource_id\tcategory\treason",
        [f"{c.name}\t{c.source_id}\t{c.category}\t{c.reason}" for c in held],
    )
    if write_idf and stats:
        files["idf"] = _write_tsv(
            out / "idf.tsv",
            "# token\tidf   (generated by hanchi dictgen from collected names)",
            [f"{t}\t{v}" for t, v in sorted(stats["idf"].items())],
        )
    return files


def _load_state(out: Path) -> dict[str, Any]:
    p = out / STATE_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _save_state(out: Path, state: Mapping[str, Any]) -> None:
    p = out / STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def write_report(out: Path, res: Result, since: str | None, stdict_used: bool) -> Path:
    day = date.today().strftime("%Y%m%d")
    path = out / REPORT_FILE.format(day=day)
    lines = [
        f"# dictgen report — {res.source} — {date.today().isoformat()}",
        "",
        f"- collected: {len(res.candidates)}",
        f"- approved (written to entities): {res.count(APPROVED)}",
        f"- review queue: {res.count(REVIEW)}",
        f"- held (common dictionary words): {res.count(HELD)}"
        + ("" if stdict_used else " — dictionary check skipped"),
        f"- already in the plugin: {res.count(EXISTING)}",
    ]
    if since:
        lines.append(f"- not seen since the last run ({since}): {len(res.removed)}")
    lines += ["", "## Newly approved", ""]
    lines += [
        f"- {c.name}"
        + (f" ({', '.join(c.aliases)})" if c.aliases else "")
        + (f" — {c.category}" if c.category else "")
        for c in res.candidates
        if c.decision == APPROVED
    ] or ["(none)"]
    lines += ["", "## Review queue", ""]
    lines += [f"- {c.name} — {c.reason}" for c in res.candidates if c.decision == REVIEW] or [
        "(none)"
    ]
    lines += ["", "## Held", ""]
    lines += [f"- {c.name}" for c in res.candidates if c.decision == HELD] or ["(none)"]
    if res.removed:
        lines += ["", "## No longer listed (kept in entities; remove manually if needed)", ""]
        lines += [f"- {n}" for n in res.removed]
    ends = res.stats.get("end_tokens", [])
    if ends:
        lines += ["", "## Category-word candidates (most frequent last tokens)", ""]
        lines += [f"- {t}: {c}" for t, c in ends]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(
    sources: Sequence[str],
    out: str | Path,
    analyzer: Any,
    *,
    config: str | Path | None = None,
    check_stdict: bool = True,
    since_last: bool = False,
    write_idf: bool = False,
    fetch: Fetch | None = None,
    stdict_cache: str | Path | None = None,
) -> list[Result]:
    cfg = load_config(config)
    http = cfg["http"]
    fetch = fetch or http_fetch(
        float(http["timeout_seconds"]), int(http["retries"]), str(http["user_agent"])
    )
    out = Path(out)
    key: Callable[[str], str] = analyzer._key
    stdict = None
    if check_stdict:
        stdict_key = require_key(
            cfg["stdict"]["key_env"], "the dictionary check (or pass --no-stdict)"
        )
        stdict = StdictChecker(cfg["stdict"], stdict_key, fetch, stdict_cache)

    def tokenize(name: str) -> list[str]:
        return [m.form for m in analyzer.pack.backend.tokenize(analyzer.pack.normalize(name).text)]

    state = _load_state(out)
    results = []
    for source in sources:
        if source != "ftc":
            raise ValueError(f"unknown or unavailable source: {source!r} (available: ftc)")
        candidates = collect_ftc(cfg, fetch, key)
        existing = set(analyzer.resources.entities) | _read_tsv_keys(
            (out / "entities").glob("*.tsv") if (out / "entities").is_dir() else [], key
        )
        prev_approved = _read_tsv_keys([out / ENTITY_FILE.format(source=source)], key)
        existing -= prev_approved  # re-judge our own previous output
        judge(candidates, existing, cfg, stdict)
        for c in candidates:
            if c.decision == APPROVED and c.key in prev_approved:
                c.decision, c.reason = EXISTING, "approved in an earlier run"
        stats = name_stats([c.name for c in candidates], tokenize, cfg)
        seen_before = set(state.get(source, {}).get("keys", []))
        current = {c.key for c in candidates}
        names = {c.key: c.name for c in candidates}
        removed = (
            sorted(state.get(source, {}).get("names", {}).get(k, k) for k in seen_before - current)
            if since_last
            else []
        )
        files = write_outputs(out, source, candidates, key, stats, write_idf)
        res = Result(source, candidates, removed, files, out, stats)
        res.report = write_report(
            out, res, state.get(source, {}).get("date") if since_last else None, stdict is not None
        )
        state[source] = {"date": date.today().isoformat(), "keys": sorted(current), "names": names}
        results.append(res)
    _save_state(out, state)
    return results
