"""Retrieve passages from the filings and answer with citations.

Baseline behaviour, on purpose: dense search only, top-k chunks, one LLM call, no
company or year filter, no calculator. Each later improvement is measured against it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .embeddings import Embedder
from .index import collection_name
from .llm import ChatClient

NOT_FOUND = "NOT_FOUND"

SYSTEM_PROMPT = f"""You answer questions about companies' SEC 10-K filings.
Use ONLY the numbered context passages. Do not use outside knowledge.

Rules:
- Cite the passages you used, like [1] or [2][4].
- For amounts, give the figure with its unit and scale exactly as the filing states it,
  e.g. "$182,447 million" or "$20.02 per share". Never drop the scale.
- For a percentage change, show the two figures you used and the result to one decimal.
- If the passages do not contain the answer, reply exactly: ANSWER: {NOT_FOUND}
  A confident wrong number is much worse than {NOT_FOUND}.

Reply in exactly this format:
ANSWER: <one or two sentences>
CITATIONS: <e.g. [1][3], or none>"""


@dataclass
class Hit:
    score: float
    text: str
    meta: dict


@dataclass
class Answer:
    question: str
    answer: str
    abstained: bool
    citations: list[int]
    hits: list[Hit]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0  # wall clock, including any rate-limit waits
    llm_latency_ms: int = 0  # the successful model call alone
    model: str = ""
    raw: str = field(default="", repr=False)


class Retriever:
    def __init__(self, client, embedder: Embedder, index_name: str = "baseline"):
        self.client = client
        self.embedder = embedder
        self.collection = collection_name(index_name)

    def search(self, query: str, k: int = 5) -> list[Hit]:
        res = self.client.query_points(
            self.collection, query=self.embedder.embed_query(query), limit=k, with_payload=True
        )
        return [Hit(p.score, p.payload["text"], p.payload) for p in res.points]


def format_context(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        m = h.meta
        blocks.append(
            f"[{i}] {m['company']} ({m['ticker']}), {m['doc_type']} for fiscal year ending "
            f"{m['period_end']}\n{h.text}"
        )
    return "\n\n".join(blocks)


def parse_reply(text: str) -> tuple[str, bool, list[int]]:
    """Split the model reply into answer text, abstention flag and cited passage numbers."""
    m = re.search(r"ANSWER:\s*(.*?)(?:\n\s*CITATIONS:|$)", text, re.S | re.I)
    answer = (m.group(1) if m else text).strip()
    cm = re.search(r"CITATIONS:\s*(.*)$", text, re.S | re.I)
    citations = sorted({int(n) for n in re.findall(r"\[(\d+)\]", cm.group(1) if cm else answer)})
    abstained = NOT_FOUND in answer.upper().replace(" ", "_")
    return answer, abstained, citations


def answer_question(question: str, retriever: Retriever, llm: ChatClient, k: int = 5) -> Answer:
    started = time.time()
    hits = retriever.search(question, k)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Context passages:\n\n{format_context(hits)}\n\nQuestion: {question}",
        },
    ]
    out = llm.complete(messages)
    answer, abstained, citations = parse_reply(out.text)
    return Answer(
        question=question,
        answer=answer,
        abstained=abstained,
        citations=[c for c in citations if 1 <= c <= len(hits)],
        hits=hits,
        prompt_tokens=out.prompt_tokens,
        completion_tokens=out.completion_tokens,
        latency_ms=int((time.time() - started) * 1000),
        llm_latency_ms=out.latency_ms,
        model=out.model,
        raw=out.text,
    )
