"""
LLM-as-judge scoring for the generation half of the pipeline.

Design decisions worth being able to defend in an interview:

* Faithfulness is scored by CLAIM DECOMPOSITION, not by asking the judge
  "is this answer faithful, 1 to 5". The answer is first split into atomic
  claims, then each claim is checked against the retrieved context
  independently. Holistic scoring collapses a five-claim answer with one
  fabrication and a five-claim answer with four fabrications into the same
  fuzzy "3/5". Per-claim scoring gives you a real ratio and, more usefully,
  tells you exactly which sentence was invented.

* The judge must NOT be the same model that generated the answer. Llama 3
  judging its own output exhibits self-preference bias and will inflate your
  faithfulness numbers. Use a different, ideally stronger model as judge, and
  state which one you used when you publish. This harness defaults to a
  separate judge provider for exactly that reason.

* Every judge call requests a fixed JSON schema at temperature 0. A judge that
  free-writes its verdict is not a measurement instrument.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Literal

import httpx

JudgeProvider = Literal["anthropic", "openai", "ollama"]

JUDGE_PROVIDER: JudgeProvider = os.getenv("JUDGE_PROVIDER", "anthropic")  # type: ignore[assignment]
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "claude-sonnet-4-5")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# Any OpenAI-compatible endpoint works via the "openai" provider: point this at
# Groq or Gemini's OpenAI-compat URL and put that service's key in OPENAI_API_KEY.
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
JUDGE_TIMEOUT = float(os.getenv("JUDGE_TIMEOUT", "120"))


# --------------------------------------------------------------------------
# Provider-agnostic completion call
# --------------------------------------------------------------------------

def _call_judge(system: str, user: str) -> str:
    """One completion at temperature 0. Returns raw text."""
    if JUDGE_PROVIDER == "anthropic":
        key = os.environ["ANTHROPIC_API_KEY"]
        with httpx.Client(timeout=JUDGE_TIMEOUT) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": JUDGE_MODEL,
                    "max_tokens": 1500,
                    "temperature": 0,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            resp.raise_for_status()
            return "".join(
                block["text"] for block in resp.json()["content"] if block["type"] == "text"
            )

    if JUDGE_PROVIDER == "openai":
        key = os.environ["OPENAI_API_KEY"]
        with httpx.Client(timeout=JUDGE_TIMEOUT) as client:
            resp = client.post(
                OPENAI_BASE_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": JUDGE_MODEL,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    # ollama -- free and local, but see the self-preference warning above
    with httpx.Client(timeout=JUDGE_TIMEOUT) as client:
        resp = client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": JUDGE_MODEL,
                "prompt": f"{system}\n\n{user}",
                "stream": False,
                "options": {"temperature": 0},
            },
        )
        resp.raise_for_status()
        return resp.json()["response"]


def _parse_json(raw: str) -> dict:
    """Judges wrap JSON in prose or fences more often than you would like."""
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]
    return json.loads(raw)


# --------------------------------------------------------------------------
# Claim decomposition
# --------------------------------------------------------------------------

_CLAIM_SYSTEM = """You decompose answers into atomic factual claims for verification.

An atomic claim states exactly one verifiable fact. Split compound sentences.
Drop hedging, pleasantries, and meta-commentary about the answer itself.
If the answer makes no factual claims (e.g. it is a refusal), return an empty list.

Respond with JSON only, no prose:
{"claims": ["...", "..."]}"""


def extract_claims(answer_text: str) -> list[str]:
    raw = _call_judge(_CLAIM_SYSTEM, f"ANSWER:\n{answer_text}")
    try:
        return [c.strip() for c in _parse_json(raw).get("claims", []) if c.strip()]
    except (json.JSONDecodeError, KeyError):
        return []


# --------------------------------------------------------------------------
# Faithfulness: is each claim supported by the retrieved context?
# --------------------------------------------------------------------------

_FAITHFULNESS_SYSTEM = """You verify whether a claim is supported by log excerpts.

Label each claim:
  "supported"     - the context directly states or unambiguously entails it
  "contradicted"  - the context states something incompatible with it
  "unsupported"   - the context neither supports nor contradicts it

Judge ONLY against the provided context. Do not use outside knowledge about how
logging, infrastructure, or software normally behaves. A claim that is true in
general but absent from the context is "unsupported".

Respond with JSON only, no prose:
{"verdicts": [{"claim_index": 0, "label": "supported", "evidence": "quoted span or null"}]}"""


@dataclass
class ClaimVerdict:
    claim: str
    label: Literal["supported", "contradicted", "unsupported"]
    evidence: str | None = None


def verify_claims(claims: list[str], context_chunks: list[str]) -> list[ClaimVerdict]:
    if not claims:
        return []

    context_block = "\n\n".join(f"[chunk {i}]\n{c}" for i, c in enumerate(context_chunks))
    claims_block = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
    raw = _call_judge(
        _FAITHFULNESS_SYSTEM,
        f"CONTEXT:\n{context_block}\n\nCLAIMS:\n{claims_block}",
    )

    try:
        verdicts = _parse_json(raw)["verdicts"]
    except (json.JSONDecodeError, KeyError):
        # Fail closed: an unparseable judge response must not be scored as a pass.
        return [ClaimVerdict(claim=c, label="unsupported") for c in claims]

    by_index = {v.get("claim_index"): v for v in verdicts}
    out: list[ClaimVerdict] = []
    for i, claim in enumerate(claims):
        v = by_index.get(i, {})
        label = v.get("label", "unsupported")
        if label not in ("supported", "contradicted", "unsupported"):
            label = "unsupported"
        out.append(ClaimVerdict(claim=claim, label=label, evidence=v.get("evidence")))
    return out


# --------------------------------------------------------------------------
# Answer relevance and abstention
# --------------------------------------------------------------------------

_RELEVANCE_SYSTEM = """You judge whether an answer actually addresses the question asked.

Score 0-2 only:
  2 - fully addresses the question
  1 - partially addresses it, or buries the answer in irrelevant material
  0 - does not address it, or answers a different question

Separately, report whether the answer is an ABSTENTION: a refusal or an explicit
statement that the logs do not contain enough information to answer.

Respond with JSON only, no prose:
{"relevance": 2, "is_abstention": false, "reason": "one sentence"}"""


@dataclass
class GenerationVerdict:
    question_id: str
    n_claims: int
    n_supported: int
    n_contradicted: int
    n_unsupported: int
    faithfulness: float | None       # supported / total claims
    relevance: int | None            # 0-2
    is_abstention: bool
    claim_verdicts: list[ClaimVerdict] = field(default_factory=list)
    reason: str | None = None

    @property
    def hallucinated(self) -> bool:
        """Any claim the context does not back is a hallucination for our purposes."""
        return (self.n_contradicted + self.n_unsupported) > 0


def judge_generation(
    question_id: str,
    question: str,
    answer_text: str,
    context_chunks: list[str],
) -> GenerationVerdict:
    raw = _call_judge(
        _RELEVANCE_SYSTEM,
        f"QUESTION:\n{question}\n\nANSWER:\n{answer_text}",
    )
    try:
        rel = _parse_json(raw)
        relevance = int(rel.get("relevance", 0))
        is_abstention = bool(rel.get("is_abstention", False))
        reason = rel.get("reason")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        relevance, is_abstention, reason = None, False, "judge parse failure"

    claims = extract_claims(answer_text)
    verdicts = verify_claims(claims, context_chunks)

    n_sup = sum(1 for v in verdicts if v.label == "supported")
    n_con = sum(1 for v in verdicts if v.label == "contradicted")
    n_uns = sum(1 for v in verdicts if v.label == "unsupported")

    return GenerationVerdict(
        question_id=question_id,
        n_claims=len(claims),
        n_supported=n_sup,
        n_contradicted=n_con,
        n_unsupported=n_uns,
        faithfulness=(n_sup / len(claims)) if claims else None,
        relevance=relevance,
        is_abstention=is_abstention,
        claim_verdicts=verdicts,
        reason=reason,
    )
