"""
Add the retrieved log context to a calibration sheet so you can label against the
exact evidence the judge saw -- not from memory.

`calibration.py export` writes question + claim + judge_label, but not the context
those claims should be judged against. Retrieval is deterministic (cosine search
over fixed embeddings), so calling /api/retrieve now reproduces exactly what the
judge was given at eval time, as long as the corpus and vectorizer haven't changed
since the run.

This reads a sheet, appends a `context` column (right after `claim`), and keeps
every existing column -- including any human_label you already filled in.

Usage (stack must be up):
    python -m eval.label_context sheet.csv                 # -> sheet.with_context.csv
    python -m eval.label_context sheet.csv out.csv --k 5
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import httpx

BASE_URL = os.getenv("LOGSENSE_BASE_URL", "http://localhost:8000")


def _fetch_context(question: str, k: int) -> str:
    resp = httpx.post(
        f"{BASE_URL}/api/retrieve",
        json={"query": question, "top_k": k},
        timeout=30,
    )
    resp.raise_for_status()
    chunks = resp.json().get("chunks", [])
    return "\n".join(c["text"] for c in chunks) if chunks else "(no logs retrieved)"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") \
        else in_path.with_suffix(".with_context.csv")
    k = int(sys.argv[sys.argv.index("--k") + 1]) if "--k" in sys.argv else 5

    rows = list(csv.DictReader(in_path.open()))
    if not rows:
        print("Empty sheet.", file=sys.stderr)
        return 1

    # One retrieval per distinct question, reused across that question's claims.
    cache: dict[str, str] = {}
    for row in rows:
        q = row["question"]
        if q not in cache:
            cache[q] = _fetch_context(q, k)
        row["context"] = cache[q]

    # Keep original column order; insert `context` right after `claim`.
    fields = [f for f in rows[0].keys() if f != "context"]
    if "claim" in fields:
        fields.insert(fields.index("claim") + 1, "context")
    else:
        fields.append("context")

    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"Wrote {out_path} with a `context` column ({len(cache)} distinct questions).\n"
        "Your existing human_label values are preserved. Re-check the rows where\n"
        "judge said 'supported' but you said 'unsupported' now that you can see the\n"
        "context, then score it:\n"
        f"  python -m eval.calibration score {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
