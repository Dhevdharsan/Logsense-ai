"""
Run the full evaluation over the golden set and write results.

Usage:
    python -m eval.run_eval --k 5
    python -m eval.run_eval --k 5 --retrieval-only     # no judge calls, no API cost
    python -m eval.run_eval --k 5 --limit 10           # quick smoke run
    python -m eval.run_eval --k 5 --tag baseline       # label the run

Outputs two files under eval/results/:
    <tag>_<timestamp>.json  -- full per-question detail, for diffing runs
    <tag>_<timestamp>.md    -- the summary table you paste into your README
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from eval import adapters
from eval.retrieval_metrics import score_retrieval, summarise_retrieval

GOLDEN_PATH = Path(__file__).parent / "golden" / "golden_set.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"


def load_golden(path: Path = GOLDEN_PATH) -> list[dict]:
    rows = []
    with path.open() as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Malformed JSON on line {line_no} of {path}: {e}") from e

    placeholder = [r["id"] for r in rows if "REPLACE_WITH_REAL_CHUNK_ID" in r.get("relevant_chunk_ids", [])]
    if placeholder:
        print(
            f"WARNING: {len(placeholder)} golden entries still contain placeholder chunk IDs "
            f"({', '.join(placeholder[:5])}{'...' if len(placeholder) > 5 else ''}). "
            "Retrieval metrics for these will be meaningless until you fill in real IDs.",
            file=sys.stderr,
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5, help="cutoff for retrieval metrics")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    parser.add_argument("--tag", type=str, default="run", help="label for this run")
    parser.add_argument("--retrieval-only", action="store_true", help="skip all judge calls")
    parser.add_argument("--skip-health-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_health_check and not adapters.health_check():
        print(
            f"LogSense does not look reachable at {adapters.LOGSENSE_BASE_URL}. "
            "Start the stack (docker compose up) or pass --skip-health-check.",
            file=sys.stderr,
        )
        return 1

    golden = load_golden()
    if args.limit:
        golden = golden[: args.limit]

    if not args.retrieval_only:
        from eval.judge import JUDGE_MODEL, JUDGE_PROVIDER, judge_generation

    retrieval_scores = []
    generation_records = []
    latencies: list[float] = []

    for i, row in enumerate(golden, start=1):
        qid, question = row["id"], row["question"]
        print(f"[{i}/{len(golden)}] {qid}", file=sys.stderr)

        started = time.perf_counter()
        try:
            if args.retrieval_only:
                retrieved_ids = adapters.retrieve(question, k=args.k)
                rag = None
            else:
                rag = adapters.answer(question, k=args.k)
                retrieved_ids = rag.context_ids
        except Exception as e:
            print(f"  pipeline error on {qid}: {e}", file=sys.stderr)
            continue
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(rag.latency_ms if (rag and rag.latency_ms) else elapsed_ms)

        retrieval_scores.append(
            score_retrieval(qid, retrieved_ids, row.get("relevant_chunk_ids", []), k=args.k)
        )

        if args.retrieval_only or rag is None:
            continue

        try:
            verdict = judge_generation(qid, question, rag.answer, rag.context_chunks)
        except Exception as e:
            print(f"  judge error on {qid}: {e}", file=sys.stderr)
            continue

        generation_records.append(
            {
                "question_id": qid,
                "question": question,
                "answerable": row.get("answerable", True),
                "category": row.get("category"),
                "answer": rag.answer,
                "verdict": asdict(verdict),
            }
        )

    # ---------------- aggregate ----------------
    retrieval_summary = summarise_retrieval(retrieval_scores, k=args.k)

    gen_summary: dict = {}
    if generation_records:
        answerable = [r for r in generation_records if r["answerable"]]
        unanswerable = [r for r in generation_records if not r["answerable"]]

        faith = [
            r["verdict"]["faithfulness"]
            for r in answerable
            if r["verdict"]["faithfulness"] is not None
        ]
        rel = [
            r["verdict"]["relevance"]
            for r in answerable
            if r["verdict"]["relevance"] is not None
        ]
        halluc = [
            (r["verdict"]["n_contradicted"] + r["verdict"]["n_unsupported"]) > 0
            for r in answerable
        ]

        gen_summary = {
            "judge_provider": JUDGE_PROVIDER,
            "judge_model": JUDGE_MODEL,
            "n_answerable": len(answerable),
            "n_unanswerable": len(unanswerable),
            "faithfulness_mean": statistics.mean(faith) if faith else None,
            "answer_relevance_mean": statistics.mean(rel) if rel else None,
            "hallucination_rate": (sum(halluc) / len(halluc)) if halluc else None,
            "abstention_rate_on_unanswerable": (
                sum(1 for r in unanswerable if r["verdict"]["is_abstention"]) / len(unanswerable)
                if unanswerable
                else None
            ),
            "false_abstention_rate_on_answerable": (
                sum(1 for r in answerable if r["verdict"]["is_abstention"]) / len(answerable)
                if answerable
                else None
            ),
        }

    latency_summary = {
        "p50_ms": statistics.median(latencies) if latencies else None,
        "p95_ms": (
            sorted(latencies)[int(0.95 * len(latencies)) - 1] if len(latencies) >= 20 else None
        ),
        "n": len(latencies),
    }

    # ---------------- write ----------------
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = RESULTS_DIR / f"{args.tag}_{stamp}"

    payload = {
        "run": {
            "tag": args.tag,
            "timestamp_utc": stamp,
            "k": args.k,
            "n_questions": len(golden),
            "retrieval_only": args.retrieval_only,
        },
        "retrieval": retrieval_summary.as_dict(),
        "generation": gen_summary,
        "latency": latency_summary,
        "per_question_retrieval": [asdict(s) for s in retrieval_scores],
        "per_question_generation": generation_records,
    }
    base.with_suffix(".json").write_text(json.dumps(payload, indent=2))
    base.with_suffix(".md").write_text(render_markdown(payload))

    print(f"\nWrote {base.with_suffix('.json')} and {base.with_suffix('.md')}", file=sys.stderr)
    print(render_markdown(payload))
    return 0


def _fmt(value, pct: bool = False, places: int = 3) -> str:
    if value is None:
        return "n/a"
    if pct:
        return f"{value * 100:.1f}%"
    return f"{value:.{places}f}"


def render_markdown(payload: dict) -> str:
    r, g, lat, run = (
        payload["retrieval"],
        payload["generation"],
        payload["latency"],
        payload["run"],
    )
    k = run["k"]

    lines = [
        f"## LogSense RAG evaluation - `{run['tag']}`",
        "",
        f"Run {run['timestamp_utc']} | k={k} | {run['n_questions']} golden questions",
        "",
        "### Retrieval (deterministic, no LLM involved)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Recall@{k} | {_fmt(r.get(f'recall@{k}'), pct=True)} |",
        f"| Precision@{k} | {_fmt(r.get(f'precision@{k}'), pct=True)} |",
        f"| Hit rate@{k} | {_fmt(r.get(f'hit_rate@{k}'), pct=True)} |",
        f"| MRR | {_fmt(r.get('mrr'))} |",
        f"| nDCG@{k} | {_fmt(r.get(f'ndcg@{k}'))} |",
        f"| Questions scored | {r.get('n_questions_scored')} |",
        "",
    ]

    if g:
        lines += [
            f"### Generation (LLM-as-judge: `{g.get('judge_model')}` via {g.get('judge_provider')})",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Faithfulness (supported claims / total claims) | {_fmt(g.get('faithfulness_mean'), pct=True)} |",
            f"| Hallucination rate (answers with >=1 ungrounded claim) | {_fmt(g.get('hallucination_rate'), pct=True)} |",
            f"| Answer relevance (0-2) | {_fmt(g.get('answer_relevance_mean'), places=2)} |",
            f"| Correct abstention on unanswerable questions | {_fmt(g.get('abstention_rate_on_unanswerable'), pct=True)} |",
            f"| False abstention on answerable questions | {_fmt(g.get('false_abstention_rate_on_answerable'), pct=True)} |",
            "",
        ]

    lines += [
        "### Latency",
        "",
        f"p50 {_fmt(lat.get('p50_ms'), places=0)} ms | p95 {_fmt(lat.get('p95_ms'), places=0)} ms | n={lat.get('n')}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
