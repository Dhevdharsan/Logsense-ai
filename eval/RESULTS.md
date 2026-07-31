# LogSense RAG — Evaluation Results

Baseline run of the evaluation harness against the LogSense RAG pipeline.

- **Run:** `baseline-openai` · k=5 · 49-question golden set
- **System under test:** TF-IDF retrieval over pgvector → Ollama `llama3.2:3b` generator
- **Judge:** `gpt-4o-mini` (a different model family from the generator — no self-preference bias)
- **Corpus:** pinned to `scripts/generate_sample_logs.py` (payment / auth / api-gateway / user services)

## TL;DR

> Retrieval **Hit@5 60% · MRR 0.60**; on single-chunk lookups **precision 92%**.
> Generation **faithfulness 99% · hallucination 2.5%**, judge validated at
> **Gwet's AC1 0.92** (92% raw agreement, 39 hand-labeled claims).
> Worst categories are aggregation / multi-hop — **by design**: their answers live
> in no single chunk, so top-k retrieval structurally cannot serve them. The fix is
> a hybrid retrieval path, not a better generator or better embeddings.

---

## 1. Retrieval (deterministic, no LLM)

| Category | n | Recall@5 | Precision@5 | Hit@5 | avg #relevant |
|---|---|---|---|---|---|
| single_chunk_lookup | 12 | 4.3% | **92%** | **92%** | 119 |
| aggregation | 7 | 2.4% | 71% | 71% | 903 |
| multi_hop | 12 | 1.2% | 50% | 50% | 263 |
| temporal | 5 | 1.3% | 40% | 40% | 189 |
| pipeline_introspection | 4 | 0.0% | 0% | 0% | 1* |
| **Overall** | 40 | 2.2% | 60% | 60% | — |

**Read this with precision/hit, not recall.** The `avg #relevant` column is the key:
ground truth labels *every* matching log line as relevant, so a single-chunk
question has ~119 correct chunks and an aggregation question ~900. Recall@5 is
therefore capped at 5 ÷ (#relevant) — for single-chunk that ceiling is 4.2%, and it
scored 4.3%, i.e. it hit the ceiling. **Precision 92% on single-chunk is the real
signal: nearly every retrieved line is relevant.** Recall@5 is only a meaningful
lens for aggregation, where a low number is *correct*.

\* `pipeline_introspection` questions (p01–p04) are not yet hand-labeled (they must
be labeled from the clusters / anomalies output, not by lexical match), so their
retrieval scores are placeholders and drag the overall averages down.

## 2. Generation (LLM-as-judge)

| Metric | Value |
|---|---|
| Faithfulness (supported claims / total) | **99.0%** |
| Hallucination rate (≥1 ungrounded claim) | 2.5% |
| Answer relevance (0–2) | 0.80 |
| Correct abstention on unanswerable | 66.7% (6/9) |
| False abstention on answerable | 60.0% |
| Latency | p50 1440 ms · p95 2552 ms |

### The abstention story (the most important finding)

False abstention is not uniform — it is concentrated exactly where retrieval is
structurally weak:

| Category | Abstained | Faithful |
|---|---|---|
| single_chunk_lookup | **1/12** | 98% |
| multi_hop | 10/12 | 100% |
| aggregation | 6/7 | 100% |
| temporal | 4/5 | 100% |

On single-chunk questions — the fair test of the generator — the model answers
almost every time (1/12 abstain), is 98% faithful, and 1.83/2 relevant. It only
declines on aggregation / multi-hop / temporal, because you genuinely cannot count
~900 events or order a timeline from 5 retrieved lines. **The generator is behaving
correctly; top-k retrieval is the ceiling.** That is the concrete case for a hybrid
retrieval path (keyword + aggregation) rather than prompt- or model-tuning.

### Abstention failures (honest)

Three unanswerable questions were not refused:
- **`u07` (SSL certificate expiry) — a genuine hallucination**, faithfulness 0%: the
  model answered with ungrounded claims about data that does not exist.
- `u06` (Elasticsearch) and `u08` (disk usage) answered "no evidence in the logs" —
  correct in substance, but phrased as a statement so the judge did not count them
  as abstentions. A measurement nuance in abstention detection, not a hallucination.

## 3. Judge calibration

Validated on 39 hand-labeled claims, labeled against the exact retrieved context:

| Coefficient | Value |
|---|---|
| Raw agreement | 92.3% |
| Gwet's AC1 | **0.917** (almost perfect) |
| PABAK | 0.846 |
| Cohen's kappa | −0.035 (**uninformative here**) |

**Why not kappa?** 97% of sampled claims are `supported` (because faithfulness is
genuinely high), which pushes chance agreement to ~92%. Under that prevalence,
Cohen's kappa collapses toward zero even at 92% agreement — the well-known *kappa
paradox*. Gwet's AC1 is the prevalence-robust coefficient and reads 0.92, confirming
the judge is reliable.

**Limitation:** with faithfulness ~99% there are very few unfaithful claims to test
against, so this calibration strongly confirms the judge recognizes *supported*
claims but cannot yet prove it reliably *catches* unfaithful ones. A targeted
calibration over the minority (`unsupported` / `contradicted`) claims is the next
step — though at a 2.5% hallucination rate there may be too few to be conclusive.

## 4. What the numbers say to do next

1. **Hybrid retrieval** for aggregation/temporal (keyword + count/order path), not
   better embeddings — this is where the false-abstention is concentrated.
2. **A reranker** over a larger fetch (k=20 → 5): watch MRR/nDCG, not recall.
3. **Finish labeling** p01–p04 from the clusters/anomalies endpoints so pipeline
   introspection stops dragging the retrieval averages.
4. **Re-scope single-chunk ground truth** to "any one matching line suffices" so
   recall@5 becomes meaningful for lookups (or keep reporting hit-rate for them).

## Reproduce

```bash
docker compose up -d
python scripts/generate_sample_logs.py --count 300
curl -X POST http://localhost:8000/api/v1/analyze/run
python -m eval.bootstrap_golden autofill && mv eval/golden/golden_set.filled.jsonl eval/golden/golden_set.jsonl
python -m eval.run_eval --k 5 --retrieval-only --tag retrieval-baseline   # free
JUDGE_PROVIDER=openai JUDGE_MODEL=gpt-4o-mini python -m eval.run_eval --k 5 --tag baseline
python -m eval.calibration export eval/results/baseline_<stamp>.json sheet.csv 40
python -m eval.label_context sheet.csv        # label against real context
python -m eval.calibration score sheet.with_context.csv
```
