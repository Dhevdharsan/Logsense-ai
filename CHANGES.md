# CHANGES — RAG query path + evaluation harness

A summary of everything built and fixed to turn LogSense into a measurable RAG
system, in plain language. Deep results live in [eval/RESULTS.md](eval/RESULTS.md).

---

## The problem we started with

- LogSense could ingest logs, cluster them, flag anomalies, and summarize each
  cluster — but it **could not answer a natural-language question about the logs**.
- There was **no `/query` endpoint** and **no retrieval endpoint** at all.
- It built TF-IDF vectors for the logs but **never saved them to the database**, and
  **threw away the vectorizer** after each run — so there was no way to turn a new
  question into a searchable vector. Retrieval was impossible as-is.

---

## What we built

### 1. A real RAG query path (backend)
- **`/api/retrieve`** — returns the top-k matching log IDs. No AI, free, deterministic.
- **`/api/query`** — returns an answer plus the exact log lines used. The generator is
  told to **use only the retrieved logs** and to **say when it can't answer** (so we
  can measure honest refusals).
- New files: `rag_service.py`, `query.py` (router), `query_schema.py`.

### 2. Made retrieval possible
- The analysis pipeline now **saves each log's embedding into the database** and
  **saves the fitted vectorizer to disk**, so questions get embedded into the *same*
  number-space as the stored logs.
- New file: `vectorizer_store.py`. Edited: `ml_service.py`, `main.py`.

### 3. Wired in the evaluation harness
- Moved the harness into the repo as an `eval/` package.
- Built the endpoints to match the harness's expected contract, so **`adapters.py`
  needed no edits**.
- Measures two independent things:
  - **Retrieval** (free, repeatable): Recall@5, Precision@5, Hit@5, MRR, nDCG.
  - **Generation** (AI judge): faithfulness, hallucination, answer relevance,
    correct vs false abstention.

### 4. A real golden set
- Replaced 12 placeholder seeds with **49 questions grounded in the actual logs**,
  split into the recommended mix (single-chunk, multi-hop, aggregation, temporal,
  pipeline-introspection, and 18% unanswerable).
- **Pinned to one corpus** (`generate_sample_logs.py`) with a warning header —
  ingesting the other generator would secretly make "unanswerable" questions
  answerable and break the scoring.
- Each answerable question has a hidden keyword rule so real log IDs can be filled in
  automatically (then human-verified) — **not circular**.
- New tool: `bootstrap_golden.py` (`stats` / `search` / `autofill` / `validate`).

### 5. Free AI judge support
- Fixed the judge's default model name (was a non-existent id).
- Made the judge accept **any OpenAI-compatible endpoint** so it works with free
  providers (Groq, Gemini) or local Ollama — not just paid Anthropic/OpenAI.

---

## Bugs we found and fixed (during the live runs)

- **HTTP 500 on 4 questions** → root cause: questions with no word-overlap produced an
  all-zero vector; cosine distance to a zero vector is `NaN`; JSON can't encode `NaN`.
  **Fix:** a zero-overlap query now returns no chunks (the model correctly abstains),
  and any non-finite score is clamped to 0. (`rag_service.py`)
- **First misdiagnosis, corrected:** I initially blamed transient Ollama timeouts and
  added a retry. The real cause was the `NaN` above — deterministic, not transient.
  The retry stayed as harmless robustness; the NaN guard was the actual fix.
- **Judge calibration looked broken (kappa −0.035)** → root cause: the labeling sheet
  had no context, so labels were partly from memory. **Fix:** added `label_context.py`
  to attach the exact retrieved context; raw agreement jumped 74% → 92%.
- **Kappa still near-zero even at 92% agreement** → this is the *kappa paradox*: when
  ~97% of claims are "supported", chance agreement is already ~92%, so kappa collapses.
  **Fix:** added **Gwet's AC1** and **PABAK** (prevalence-robust) to `calibration.py`,
  which correctly read 0.92 / 0.85, plus an automatic warning note.

---

## Results (baseline run, judge = `gpt-4o-mini`)

| Area | Headline |
|---|---|
| Retrieval | **Hit@5 60% · MRR 0.60**; single-chunk **precision 92%** |
| Generation | **Faithfulness 99% · Hallucination 2.5%** · Relevance 0.80 |
| Abstention | Correct 67% on unanswerable; false 60% (concentrated in aggregation/multi-hop) |
| Judge trust | **Gwet's AC1 0.92** (92% raw agreement, 39 hand-labeled claims) |
| Latency | p50 1.4s · p95 2.6s |

**Key findings (in simple words):**
- Retrieval is **good where it should be** (single-chunk precision 92%). Report
  precision/hit, **not recall** — recall looks tiny only because we labeled *every*
  matching line as relevant (hundreds per question), which caps recall by math.
- The model **refuses most aggregation/multi-hop questions** — and that's **correct**:
  you can't count ~900 events from 5 retrieved lines. This is the data-backed case for
  a **hybrid retrieval path**, not a better model or better embeddings.
- One genuine failure: **`u07`** (SSL cert question) — the model answered a question
  about data that doesn't exist (a hallucination). Honest, useful signal.
- Calibration proved the **judge is reliable** and, along the way, caught that a naive
  kappa would have been misleading here.

---

## How to run it end-to-end

```bash
# 0. one-time
python3 -m pip install httpx

# 1. bring up the stack
docker compose up -d --build
curl -s http://localhost:8000/health

# 2. ingest ONE corpus (do not also run generate_new_logs.py — see golden set header)
python3 scripts/generate_sample_logs.py --count 300

# 3. run the pipeline (writes embeddings + saves the vectorizer)
curl -s -X POST http://localhost:8000/api/v1/analyze/run
# confirm retrieval is live (should return chunks, not a 503):
curl -s -X POST http://localhost:8000/api/retrieve -H 'content-type: application/json' \
  -d '{"query":"database connection pool","top_k":3}'

# 4. fill the golden set with real chunk ids, then verify
python3 -m eval.bootstrap_golden autofill
mv eval/golden/golden_set.filled.jsonl eval/golden/golden_set.jsonl
python3 -m eval.bootstrap_golden validate

# 5. retrieval metrics (free, start here)
python3 -m eval.run_eval --k 5 --retrieval-only --tag retrieval-baseline

# 6. full judged run (free judge options: Groq / Gemini / local Ollama)
export JUDGE_PROVIDER=openai
export OPENAI_BASE_URL=https://api.openai.com/v1/chat/completions   # or Groq/Gemini URL
export OPENAI_API_KEY='...'
export JUDGE_MODEL=gpt-4o-mini
python3 -m eval.run_eval --k 5 --tag baseline

# 7. validate the judge (label against real context)
python3 -m eval.calibration export eval/results/baseline_<stamp>.json sheet.csv 40
python3 -m eval.label_context sheet.csv          # adds the retrieved context column
# ... fill human_label in sheet.with_context.csv ...
python3 -m eval.calibration score sheet.with_context.csv
```

---

## Files added / changed

**Backend (new):** `app/ml/vectorizer_store.py`, `app/services/rag_service.py`,
`app/routers/query.py`, `app/schemas/query_schema.py`
**Backend (edited):** `app/services/ml_service.py`, `app/main.py`, `.gitignore`
**Eval (new):** whole `eval/` package + `bootstrap_golden.py`, `label_context.py`,
`golden/golden_set.jsonl` (rewritten to 49 questions), `RESULTS.md`
**Eval (edited):** `judge.py` (model fix + OpenAI-compatible base URL),
`calibration.py` (AC1/PABAK + paradox note), `README.md` (LogSense wiring)

## Known loose ends
- `p01–p04` (pipeline-introspection) still need hand-labeling from
  `/api/v1/clusters` and `/api/v1/logs?anomalies_only=true`; until then they drag the
  retrieval averages down.
- Golden set is 49 questions (target ~80). Extending needs a few more log scenarios,
  not more code — the tooling already scales.

---

## Résumé bullet

> Built a RAG evaluation harness for a log-analysis pipeline: 49-question golden set
> (18% unanswerable), deterministic retrieval metrics (Hit@5, MRR, nDCG) and
> claim-level LLM-as-judge faithfulness/abstention scoring; validated the judge
> against 39 hand-labeled claims (Gwet's AC1 0.92, after diagnosing and correcting for
> the Cohen's-kappa prevalence paradox). Used it to show aggregation/multi-hop
> questions fail structurally under top-k retrieval, motivating a hybrid retrieval path.

## For the main README

> ### Evaluation
> LogSense's RAG path is measured by a harness in [`eval/`](eval/): deterministic
> retrieval metrics (Hit@5, MRR, nDCG against a 49-question golden set) kept separate
> from claim-level, judge-scored generation metrics (faithfulness, hallucination,
> abstention). Baseline: **Hit@5 60%, faithfulness 99%, hallucination 2.5%**, with the
> judge validated at **Gwet's AC1 0.92**. Full write-up in [eval/RESULTS.md](eval/RESULTS.md).
