"""
Judge calibration: does the LLM judge agree with a human?

This is the part almost every portfolio RAG project skips, and it is the part
that separates "I ran some evals" from "I built an evaluation system". An
uncalibrated judge is an unvalidated instrument: your 91% faithfulness number
means nothing if you have never checked whether the judge's notion of
"supported" matches yours.

Workflow:
  1. Run the full eval:            python -m eval.run_eval --tag baseline
  2. Export a labelling sheet:     python -m eval.calibration export <results.json>
  3. Hand-label 30-50 claims in the exported CSV (column: human_label)
  4. Score agreement:              python -m eval.calibration score labels.csv

Interpreting Cohen's kappa (Landis & Koch convention):
    < 0.20   poor        -- your judge is close to noise, fix the prompt
    0.21-0.40 fair
    0.41-0.60 moderate   -- usable with caveats, report it honestly
    0.61-0.80 substantial -- this is the target
    > 0.80   almost perfect

If kappa is low, the usual causes in order of likelihood: the rubric is
ambiguous about "unsupported" vs "contradicted"; the judge is using world
knowledge instead of the context; or your context chunks are truncated so the
judge cannot see the evidence the generator saw.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

LABELS = ("supported", "contradicted", "unsupported")


def cohens_kappa(a: list[str], b: list[str]) -> float:
    """Agreement between two raters, corrected for chance agreement."""
    if len(a) != len(b):
        raise ValueError("rater label lists must be the same length")
    n = len(a)
    if n == 0:
        raise ValueError("no labels to score")

    observed = sum(1 for x, y in zip(a, b) if x == y) / n

    count_a, count_b = Counter(a), Counter(b)
    expected = sum(
        (count_a[label] / n) * (count_b[label] / n)
        for label in set(a) | set(b)
    )

    if expected == 1.0:
        # Both raters used a single identical label for everything.
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def gwets_ac1(a: list[str], b: list[str]) -> float:
    """Gwet's AC1 -- an agreement coefficient that does not collapse when one label
    dominates. Cohen's kappa punishes high prevalence so hard that 92% agreement can
    score ~0 (the 'kappa paradox'); AC1 estimates chance agreement differently and
    stays meaningful, which is what you want when faithfulness is genuinely high and
    almost every sampled claim is 'supported'."""
    n = len(a)
    if n == 0:
        raise ValueError("no labels to score")
    cats = set(a) | set(b)
    q = len(cats)
    if q < 2:
        return 1.0  # only one label in play: perfect agreement by construction
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    # chance agreement = mean over categories of pi_k*(1-pi_k), normalised by (q-1)
    pe = sum(
        (p := (ca[k] + cb[k]) / (2 * n)) * (1 - p) for k in cats
    ) / (q - 1)
    if pe == 1.0:
        return 0.0
    return (observed - pe) / (1 - pe)


def pabak(a: list[str], b: list[str]) -> float:
    """Prevalence-Adjusted Bias-Adjusted Kappa: (po - 1/q) / (1 - 1/q). A simple,
    prevalence-robust sanity check to report next to Cohen's kappa and AC1."""
    n = len(a)
    if n == 0:
        raise ValueError("no labels to score")
    q = len(set(a) | set(b))
    if q < 2:
        return 1.0
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    return (observed - 1 / q) / (1 - 1 / q)


def interpret(kappa: float) -> str:
    if kappa < 0.20:
        return "poor"
    if kappa < 0.41:
        return "fair"
    if kappa < 0.61:
        return "moderate"
    if kappa < 0.81:
        return "substantial"
    return "almost perfect"


def export_sheet(results_path: Path, out_path: Path, n: int = 40, seed: int = 0) -> None:
    """Pull a random sample of claim verdicts into a CSV for hand-labelling.

    Random, not cherry-picked: if you only label the claims you already suspect,
    your kappa is meaningless.
    """
    payload = json.loads(results_path.read_text())
    rows = []
    for record in payload.get("per_question_generation", []):
        for verdict in record["verdict"].get("claim_verdicts", []):
            rows.append(
                {
                    "question_id": record["question_id"],
                    "question": record["question"],
                    "claim": verdict["claim"],
                    "judge_label": verdict["label"],
                    "judge_evidence": verdict.get("evidence") or "",
                    "human_label": "",
                }
            )

    if not rows:
        print("No claim verdicts found. Did you run with --retrieval-only?", file=sys.stderr)
        return

    random.Random(seed).shuffle(rows)
    sample = rows[:n]

    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(sample[0].keys()))
        writer.writeheader()
        writer.writerows(sample)

    print(
        f"Wrote {len(sample)} rows to {out_path}.\n"
        f"Fill in 'human_label' with one of: {', '.join(LABELS)}.\n"
        "Label against the context only, using the same rule you gave the judge.\n"
        "Tip: hide the judge_label column while you label, or you will anchor to it.",
    )


def score_sheet(labels_path: Path) -> None:
    judge, human = [], []
    skipped = 0
    with labels_path.open() as f:
        for row in csv.DictReader(f):
            h = (row.get("human_label") or "").strip().lower()
            j = (row.get("judge_label") or "").strip().lower()
            if h not in LABELS or j not in LABELS:
                skipped += 1
                continue
            human.append(h)
            judge.append(j)

    if not human:
        print("No usable labelled rows found.", file=sys.stderr)
        return

    kappa = cohens_kappa(judge, human)
    ac1 = gwets_ac1(judge, human)
    pab = pabak(judge, human)
    raw = sum(1 for x, y in zip(judge, human) if x == y) / len(human)

    # How lopsided are the labels? Cohen's kappa is unreliable when one dominates.
    human_dist = Counter(human)
    top_label, top_n = human_dist.most_common(1)[0]
    top_share = top_n / len(human)

    print(f"Labelled claims scored : {len(human)} (skipped {skipped} unlabelled)")
    print(f"Raw agreement          : {raw * 100:.1f}%")
    print(f"Cohen's kappa          : {kappa:.3f} ({interpret(kappa)})")
    print(f"Gwet's AC1             : {ac1:.3f} ({interpret(ac1)})")
    print(f"PABAK                  : {pab:.3f} ({interpret(pab)})")
    print()

    if top_share >= 0.80 and raw >= 0.80 and kappa < 0.41:
        print(
            f"NOTE: {top_share * 100:.0f}% of labels are '{top_label}', so Cohen's kappa is "
            "unreliable here\n(the 'kappa paradox': high agreement, near-zero kappa). With this "
            "much\nimbalance, report Gwet's AC1 and raw agreement instead. A low kappa\n"
            "does NOT mean the judge is bad -- it means the sample is one-sided.\n"
            "To calibrate the judge's ability to catch UNFAITHFUL claims, build a\n"
            "targeted sheet over the claims it marked 'unsupported'/'contradicted'.\n"
        )

    # Confusion detail: which direction does the judge drift?
    confusion: Counter = Counter(zip(judge, human))
    disagreements = {k: v for k, v in confusion.items() if k[0] != k[1]}
    if disagreements:
        print("Most common disagreements (judge -> human):")
        for (j, h), count in sorted(disagreements.items(), key=lambda x: -x[1])[:5]:
            print(f"  judge said {j:14s} human said {h:14s}  x{count}")
        print()
        print(
            "If the judge over-uses 'supported', it is probably importing world "
            "knowledge about how logs behave. Tighten that instruction in the rubric."
        )


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    command = sys.argv[1]
    if command == "export":
        results = Path(sys.argv[2])
        out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("calibration_sheet.csv")
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 40
        export_sheet(results, out, n=n)
        return 0

    if command == "score":
        score_sheet(Path(sys.argv[2]))
        return 0

    print(f"Unknown command: {command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
