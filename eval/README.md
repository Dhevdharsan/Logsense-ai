# LogSense RAG Evaluation Harness

Measures whether the retrieval layer finds the right log chunks, and whether the
generator's answers are actually grounded in what it retrieved.

Two independent layers, deliberately kept separate:

| Layer | Method | Depends on an LLM? |
|---|---|---|
| Retrieval | Recall@k, Precision@k, Hit rate@k, MRR, nDCG@k against a golden set | No, fully deterministic |
| Generation | Claim-level faithfulness, hallucination rate, answer relevance, abstention behaviour | Yes, LLM-as-judge |

Keeping them separate matters because it localises failure. A low faithfulness
score with high recall means the generator is inventing things despite having
the right context, which is a prompting or model problem. Low recall with high
faithfulness means retrieval is starving the generator, which is a chunking or
embedding problem. A single blended "RAG score" tells you neither.

---

## Wired into LogSense

`adapters.py` is already pointed at the LogSense RAG endpoints that ship in this
repo, so there is nothing to edit to run it:

- `POST /api/retrieve` -> top-k `log_entries.id` values (retrieval metrics, no LLM)
- `POST /api/query` with `include_context=true` -> answer plus the exact log
  lines the generator saw (faithfulness / abstention metrics)

Both live in `backend/app/routers/query.py` and retrieve by cosine similarity over
the TF-IDF `log_entries.embedding` column.

**Prerequisite that is easy to miss:** those embeddings and the query-time
vectorizer are produced by the analysis pipeline, not at ingest. Retrieval returns
a `503` until a pipeline run has happened. So the order is always:

```bash
docker compose up -d                                   # postgres, redis, backend
python scripts/generate_sample_logs.py --count 300     # ingest a corpus
curl -X POST http://localhost:8000/api/v1/analyze/run  # embed + cluster (writes embeddings, saves vectorizer)
```

Then build the golden set against that live corpus (`bootstrap_golden.py` below)
before trusting any retrieval number.

---

## Quick start

```bash
pip install httpx

# 0. Bring the stack up and run the pipeline once (see "Wired into LogSense" above),
#    so log_entries.embedding is populated and the TF-IDF vectorizer is persisted.

# 1. Fill in real chunk ids from the live corpus (does NOT invent mappings).
#    The golden set is pinned to the scripts/generate_sample_logs.py corpus -- see
#    the header comment in golden/golden_set.jsonl before you ingest anything.
python -m eval.bootstrap_golden stats                        # what the corpus supports
python -m eval.bootstrap_golden autofill                     # match rules -> golden_set.filled.jsonl
#   ... read the filled relevant_chunk_ids, spot-check a few, then adopt them:
mv eval/golden/golden_set.filled.jsonl eval/golden/golden_set.jsonl
python -m eval.bootstrap_golden validate                     # placeholders + bad ids + composition
#   The 4 pipeline_introspection questions have no match rule by design: label them
#   by hand from /api/v1/logs?anomalies_only=true and /api/v1/clusters (see their notes).

# 2. Check retrieval only. Free, deterministic, no API calls. Start here.
python -m eval.run_eval --k 5 --retrieval-only --tag retrieval-baseline

# 3. Full run including the judge
export ANTHROPIC_API_KEY=...
export JUDGE_MODEL=claude-sonnet-4-5          # any strong model != the llama3.2 generator
python -m eval.run_eval --k 5 --tag baseline

# 4. Validate the judge against your own labels
python -m eval.calibration export eval/results/baseline_<stamp>.json sheet.csv 40
# ... hand-label the human_label column ...
python -m eval.calibration score sheet.csv
```

---

## Building the golden set

`eval/golden/golden_set.jsonl` ships with 12 seed questions, 8 answerable and 4
deliberately unanswerable. They contain `REPLACE_WITH_REAL_CHUNK_ID` placeholders
that you fill in with real primary keys from your pgvector table.

**Target: roughly 80 questions.** Below about 50 the confidence intervals are
wide enough that run-to-run noise will swamp the effect of any change you make.
Eighty is enough to detect a meaningful regression without being a week of work.

**Composition that makes the numbers informative:**

| Slice | Share | Why |
|---|---|---|
| Single-chunk lookup | ~25% | Baseline. If this fails, nothing else matters. |
| Multi-hop (needs 2+ chunks) | ~25% | Where naive top-k retrieval starts breaking. |
| Aggregation / counting | ~15% | The answer exists in no single chunk. Usually your worst category. |
| Temporal ordering | ~10% | Embedding similarity ignores time. Known weak spot. |
| Pipeline introspection (DBSCAN clusters, rarity flags) | ~10% | Tests whether RAG can discuss your own ML output. |
| **Unanswerable** | **~15%** | See below. |

**The unanswerable slice is the highest-value part of the set** and the part
almost nobody includes. A RAG system that confidently answers a question its
corpus cannot support is worse than useless in an ops context, because it will
send someone chasing a fabricated root cause at 3am. Four flavours worth
covering: a metric the logs do not record, an entity they do not track, a
document type they do not contain, and a service that does not appear at all.
Measuring abstention rate on these gives you a number most portfolio projects
cannot produce.

**Label the relevant chunks yourself.** Do not have an LLM generate both the
questions and the ground-truth chunk IDs, then evaluate a system built on the
same embeddings. That is circular and an interviewer will spot it. Generating
draft questions with an LLM and then hand-verifying every chunk mapping is fine
and is what most teams actually do. Say so if asked.

---

## Metric definitions

Different papers define these differently, so state your conventions when you
publish numbers. This harness uses:

- **Recall@k**: relevant chunks in top k / all relevant chunks. Undefined for
  unanswerable questions, excluded from the mean rather than scored as zero.
- **Precision@k**: relevant chunks in top k / chunks actually returned, capped
  at k. A system returning 3 chunks when k=5 is not penalised for the missing 2.
- **MRR**: mean of 1/rank of the first relevant chunk. This is the metric that
  exposes bad ranking. Recall can sit at 90% while the right chunk is at
  position 9 and the generator never meaningfully uses it.
- **nDCG@k**: binary relevance, log-discounted by position.
- **Faithfulness**: supported claims / total claims, where the answer is first
  decomposed into atomic claims and each is verified against the retrieved
  context independently.
- **Hallucination rate**: share of answers containing at least one claim the
  context does not support. Stricter and more honest than mean faithfulness,
  since one fabricated claim in an otherwise correct answer still misleads.
- **Abstention rate**: on unanswerable questions, share where the system
  correctly declined. Paired with **false abstention rate** on answerable
  questions, because a system that refuses everything would otherwise score
  perfectly.

---

## Judge calibration: do not skip this

An LLM judge is a measurement instrument, and an uncalibrated instrument
produces numbers that look precise and mean nothing. The workflow in
`calibration.py` samples 40 claim verdicts at random, you label them by hand,
and it reports Cohen's kappa between you and the judge.

Report the kappa alongside your faithfulness number. "Faithfulness 91.2%
(judge: Claude Sonnet, kappa 0.74 against 40 hand-labelled claims)" is a
different class of claim from "faithfulness 91.2%", and the difference is
exactly what an interviewer is probing for when they ask how you know your
eval is any good.

**Two methodological traps, both worth being able to name:**

1. **Self-preference bias.** Do not use Llama 3 to judge answers Llama 3
   generated. Models systematically rate their own output higher. Use a
   different, ideally stronger model as the judge. This harness defaults to a
   separate provider for that reason. If cost forces you to judge locally, say
   so explicitly and treat the numbers as directional.
2. **Anchoring while labelling.** Hide the `judge_label` column while you fill
   in `human_label`, or your kappa measures how agreeable you are, not how
   accurate the judge is.

---

## Using this to actually improve the system

The harness exists to support a change, not to produce a screenshot. A useful
loop:

1. Run `--tag baseline`, commit the results JSON.
2. Change one thing. Chunk size, top-k, adding a reranker, tightening the
   generator's system prompt to require citing chunk IDs.
3. Re-run with a new tag. Diff the two JSONs.
4. Keep the change if it moved a metric you care about, revert if it did not.

Two changes worth trying first, because they usually move the numbers most:

- **A reranker over top-20 retrieved down to top-5.** Watch MRR and nDCG, not
  recall. Recall is already fixed by the k=20 fetch, so if MRR jumps the
  reranker is earning its latency.
- **Requiring the generator to cite chunk IDs inline.** Almost always improves
  faithfulness, and gives you a cheap deterministic cross-check: any cited ID
  that was not in the retrieved set is an unambiguous hallucination, no judge
  needed.

The story "faithfulness went from X to Y after I did Z, measured on an
80-question golden set with a judge calibrated at kappa 0.74" is worth
substantially more in an interview than any single static number.

---

## Writing this up

For the repo README, lead with the table the runner emits, then one paragraph on
methodology and one on what the numbers led you to change.

For the resume, one bullet, with the numbers you actually measured:

> Built an evaluation harness for a RAG log-analysis pipeline: 80-question
> golden set with a 15% unanswerable slice, deterministic retrieval metrics
> (recall@5, MRR, nDCG) and claim-level LLM-as-judge faithfulness scoring,
> with judge output validated against hand-labelled claims (Cohen's kappa 0.74).
> Used it to raise faithfulness from X% to Y% via reranking and citation-forced
> prompting.

Expect these interview questions, and have answers ready:

- How do you know your judge is right? (Kappa, and the labelling protocol.)
- Why not just use RAGAS? (You can. Know what it computes and why you chose to
  implement claim decomposition yourself: control over the rubric, and the
  ability to inspect which specific claim failed.)
- What is your worst-performing question category, and why? (Aggregation, almost
  certainly. The answer exists in no single chunk, so top-k retrieval
  structurally cannot supply it. The fix is a hybrid path, not better embeddings.)
- How would this run in CI? (Retrieval-only on every PR since it is free and
  deterministic; full judged run nightly or on release, since it costs money and
  has variance.)
