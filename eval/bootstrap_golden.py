"""
Helper for building the golden set against the REAL corpus -- not a generator.

The golden set is the actual work, and it has to reference real log_entries.id
values or the retrieval metrics are meaningless. This tool does not invent
questions or mappings. It gives you the three things you need to label by hand:

  stats             corpus overview: how many logs, by service and level, and the
                    recurring message shapes with example ids. Tells you which of
                    the seed questions your data can actually support.

  search "<text>"   every log whose message matches, with its id. This is how you
                    fill relevant_chunk_ids: search the phrase, read the hits,
                    copy the ids that genuinely answer the question.

  autofill          for every answerable question that carries a `match` rule,
                    resolve relevant_chunk_ids from the live corpus by lexical
                    match and write golden_set.filled.jsonl for you to review.

  validate          checks golden/golden_set.jsonl against the live corpus:
                    flags REPLACE_WITH_REAL_CHUNK_ID placeholders and any
                    relevant_chunk_ids that do not exist, and prints the category
                    composition next to the README's target mix.

Why this is not circular: the `match` rules are hand-authored substrings of the
real log wording, and every autofilled mapping is meant to be read and verified
before use -- the ids never come from the same embedding model the system under
test uses. See eval/README.md.

Usage (stack must be up and a pipeline run must have completed):
    python -m eval.bootstrap_golden stats
    python -m eval.bootstrap_golden search "authentication failed"
    python -m eval.bootstrap_golden search "memory" --level ERROR
    python -m eval.bootstrap_golden autofill        # -> golden/golden_set.filled.jsonl
    python -m eval.bootstrap_golden validate
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import httpx

BASE_URL = os.getenv("LOGSENSE_BASE_URL", "http://localhost:8000")
GOLDEN_PATH = Path(__file__).parent / "golden" / "golden_set.jsonl"

# The composition the README argues makes the numbers informative. Keys match the
# `category` slugs used in golden_set.jsonl (unanswerable is by the answerable flag).
TARGET_MIX = {
    "single_chunk_lookup": 0.25,
    "multi_hop": 0.25,
    "aggregation": 0.15,
    "temporal": 0.10,
    "pipeline_introspection": 0.10,
    "unanswerable": 0.15,
}


def _fetch_all_logs(page_size: int = 500) -> list[dict]:
    """Pull the whole corpus via the paginated list endpoint."""
    logs: list[dict] = []
    page = 1
    with httpx.Client(timeout=30) as client:
        while True:
            resp = client.get(
                f"{BASE_URL}/api/v1/logs",
                params={"page": page, "page_size": page_size},
            )
            resp.raise_for_status()
            body = resp.json()
            logs.extend(body["items"])
            if not body.get("has_next"):
                break
            page += 1
    return logs


def cmd_stats() -> int:
    logs = _fetch_all_logs()
    if not logs:
        print("No logs found. Ingest sample logs and run the pipeline first.", file=sys.stderr)
        return 1

    by_service = Counter(l["service"] for l in logs)
    by_level = Counter(l["level"] for l in logs)
    n_embedded_hint = sum(1 for l in logs if l.get("cluster_id") is not None)

    print(f"Corpus: {len(logs)} logs")
    print(f"  clustered (pipeline has run): {n_embedded_hint}")
    print("\nBy service:")
    for svc, n in by_service.most_common():
        print(f"  {n:5d}  {svc}")
    print("\nBy level:")
    for lvl, n in by_level.most_common():
        print(f"  {n:5d}  {lvl}")

    # Group by exact message to surface recurring shapes with example ids.
    by_message: dict[str, list[int]] = {}
    for l in logs:
        by_message.setdefault(l["message"], []).append(l["id"])
    print(f"\nRecurring message shapes ({len(by_message)} distinct), top 25 by count:")
    for msg, ids in sorted(by_message.items(), key=lambda kv: -len(kv[1]))[:25]:
        preview = msg if len(msg) <= 90 else msg[:87] + "..."
        print(f"  x{len(ids):<4d} e.g. id={ids[0]:<7d} {preview}")
    return 0


def cmd_search(term: str, level: str | None = None, service: str | None = None) -> int:
    logs = _fetch_all_logs()
    term_l = term.lower()
    hits = [
        l for l in logs
        if term_l in l["message"].lower()
        and (level is None or l["level"] == level.upper())
        and (service is None or l["service"] == service.lower())
    ]
    if not hits:
        print(f"No logs matched {term!r}"
              f"{' level=' + level if level else ''}{' service=' + service if service else ''}.")
        return 0
    print(f"{len(hits)} match(es) for {term!r}"
          f"{' level=' + level if level else ''}{' service=' + service if service else ''}:\n")
    for l in hits:
        print(f'  id={l["id"]:<7d} {l["timestamp"]}  {l["level"]:<5s} {l["service"]:<18s} {l["message"]}')
    print(f'\nrelevant_chunk_ids candidates: {json.dumps([str(l["id"]) for l in hits])}')
    return 0


def _log_matches(log: dict, match: dict) -> bool:
    """Does a log line satisfy a golden question's hand-authored `match` rule?

    `contains`: message must include at least one of these substrings (OR).
    `all`:      message must include every one of these substrings (AND).
    `level` / `service`: exact filters. An empty `contains` with no other keys
    matches everything (used for whole-corpus aggregation ground truth).
    """
    msg = log["message"].lower()
    contains = match.get("contains") or []
    if contains and not any(c.lower() in msg for c in contains):
        return False
    if match.get("all") and not all(c.lower() in msg for c in match["all"]):
        return False
    if match.get("level") and log["level"] != match["level"].upper():
        return False
    if match.get("service") and log["service"] != match["service"].lower():
        return False
    return True


def cmd_autofill(out_path: Path) -> int:
    logs = _fetch_all_logs()
    if not logs:
        print("No logs found. Ingest sample logs and run the pipeline first.", file=sys.stderr)
        return 1

    filled = no_match = passthrough = 0
    out_lines: list[str] = []
    # Re-emit the file line-by-line so // comments and blank lines are preserved.
    for line in GOLDEN_PATH.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            out_lines.append(line)
            continue
        row = json.loads(s)
        match = row.get("match")
        if row.get("answerable", True) and match is not None:
            ids = [str(l["id"]) for l in logs if _log_matches(l, match)]
            if ids:
                row["relevant_chunk_ids"] = ids
                filled += 1
            else:
                no_match += 1  # leave the placeholder so validate/run_eval still flag it
        else:
            passthrough += 1
        out_lines.append(json.dumps(row))

    out_path.write_text("\n".join(out_lines) + "\n")
    print(
        f"Wrote {out_path}\n"
        f"  autofilled from match rules : {filled}\n"
        f"  match rule found nothing    : {no_match} (left as placeholder)\n"
        f"  passed through unchanged    : {passthrough} (unanswerable / hand-only)\n\n"
        "Next: read the filled relevant_chunk_ids, spot-check a few against the log\n"
        "lines they point to, then replace the golden set:\n"
        f"  mv {out_path} {GOLDEN_PATH}"
    )
    return 0


def _load_golden() -> list[dict]:
    rows = []
    with GOLDEN_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("//"):
                rows.append(json.loads(line))
    return rows


def cmd_validate() -> int:
    rows = _load_golden()
    logs = _fetch_all_logs()
    existing_ids = {str(l["id"]) for l in logs}

    placeholders, missing = [], []
    for r in rows:
        ids = r.get("relevant_chunk_ids", [])
        if any("REPLACE_WITH_REAL_CHUNK_ID" in str(i) for i in ids):
            placeholders.append(r["id"])
            continue
        for i in ids:
            if str(i) not in existing_ids:
                missing.append((r["id"], i))

    answerable = sum(1 for r in rows if r.get("answerable", True))
    print(f"Golden set: {len(rows)} questions ({answerable} answerable, {len(rows) - answerable} unanswerable)")
    print(f"Corpus for validation: {len(existing_ids)} log ids\n")

    if placeholders:
        print(f"[!] {len(placeholders)} still have placeholder chunk ids: {', '.join(placeholders)}")
    if missing:
        print(f"[!] {len(missing)} reference ids not in the corpus:")
        for qid, i in missing:
            print(f"      {qid} -> {i}")
    if not placeholders and not missing:
        print("[ok] every relevant_chunk_id resolves to a real log entry.")

    # Composition vs README target.
    cats = Counter(
        "unanswerable" if not r.get("answerable", True) else (r.get("category") or "uncategorised")
        for r in rows
    )
    print("\nComposition (share of set):")
    for cat, n in cats.most_common():
        print(f"  {n:3d}  {n / len(rows) * 100:4.0f}%  {cat}")
    print("\nREADME target mix, for reference:")
    for cat, share in TARGET_MIX.items():
        print(f"        {share * 100:4.0f}%  {cat}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "stats":
        return cmd_stats()
    if cmd == "search":
        if len(sys.argv) < 3:
            print("usage: python -m eval.bootstrap_golden search \"<text>\" [--level L] [--service S]", file=sys.stderr)
            return 1
        term = sys.argv[2]
        args = sys.argv[3:]
        level = args[args.index("--level") + 1] if "--level" in args else None
        service = args[args.index("--service") + 1] if "--service" in args else None
        return cmd_search(term, level=level, service=service)
    if cmd == "autofill":
        out = Path(sys.argv[2]) if len(sys.argv) > 2 else GOLDEN_PATH.parent / "golden_set.filled.jsonl"
        return cmd_autofill(out)
    if cmd == "validate":
        return cmd_validate()
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
