"""HTTP API for the question-answering system.

Run locally:   uvicorn filingsqa.api:app --reload
Deployed on:   Render (free web service), see render.yaml and Dockerfile

Configuration (environment variables):
    GROQ_API_KEY / LLM_*        the answering model (see llm.py)
    QDRANT_URL, QDRANT_API_KEY  Qdrant Cloud; without them the local data/qdrant is used
    INDEX_NAME                  default "baseline"
    RATE_PER_IP_PER_HOUR        default 10
    RATE_GLOBAL_PER_DAY         default 300: protects the free LLM quota from a public demo
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .rag import Answer

MAX_EXCERPT = 400


class Ask(BaseModel):
    question: str = Field(min_length=8, max_length=300)


class Source(BaseModel):
    n: int
    company: str
    ticker: str
    period_end: str
    doc_type: str
    document: str
    url: str = ""
    excerpt: str
    score: float


class Reply(BaseModel):
    question: str
    answer: str
    abstained: bool
    cited: list[int]
    sources: list[Source]
    model: str
    latency_ms: int


class SlidingWindowLimiter:
    """At most `limit` events per `window` seconds for each key. One process only."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            q = self._events[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def client_ip(request: Request) -> str:
    # Render and most hosts put the visitor's address first in X-Forwarded-For
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def to_reply(a: Answer) -> Reply:
    sources = [
        Source(
            n=i,
            company=h.meta.get("company", ""),
            ticker=h.meta.get("ticker", ""),
            period_end=h.meta.get("period_end", ""),
            doc_type=h.meta.get("doc_type", ""),
            document=h.meta.get("document", ""),
            url=h.meta.get("url", ""),
            excerpt=h.text[:MAX_EXCERPT],
            score=round(h.score, 4),
        )
        for i, h in enumerate(a.hits, 1)
    ]
    return Reply(
        question=a.question,
        answer=a.answer,
        abstained=a.abstained,
        cited=a.citations,
        sources=sources,
        model=a.model,
        latency_ms=a.latency_ms,
    )


def default_answer_fn() -> tuple[Callable[[str], Answer], dict, Callable[[], int]]:
    """Build the real pipeline from environment variables.

    Returns the answer function, public info, and a cheap vector-store ping (point count)."""
    from qdrant_client import QdrantClient

    from .embeddings import DEFAULT_MODEL, FastEmbedder
    from .env import load_dotenv
    from .index import QDRANT_PATH
    from .llm import ChatClient
    from .rag import Retriever, answer_question

    load_dotenv()
    url = os.environ.get("QDRANT_URL")
    client = (
        QdrantClient(url=url, api_key=os.environ.get("QDRANT_API_KEY"), timeout=30)
        if url
        else QdrantClient(path=QDRANT_PATH)
    )
    index = os.environ.get("INDEX_NAME", "baseline")
    retriever = Retriever(client, FastEmbedder(os.environ.get("EMBED_MODEL", DEFAULT_MODEL)), index)
    llm = ChatClient()
    info = {"index": index, "model": llm.model, "vector_store": "qdrant-cloud" if url else "local"}

    def ping() -> int:
        return client.count(retriever.collection).count

    return (lambda q: answer_question(q, retriever, llm, k=5)), info, ping


def create_app(
    answer_fn: Callable[[str], Answer] | None = None,
    info: dict | None = None,
    ping: Callable[[], int] | None = None,
    per_ip_per_hour: int | None = None,
    global_per_day: int | None = None,
) -> FastAPI:
    state: dict = {"answer_fn": answer_fn, "info": info or {}, "ping": ping}
    per_ip = SlidingWindowLimiter(
        per_ip_per_hour or int(os.environ.get("RATE_PER_IP_PER_HOUR", "10")), 3600
    )
    daily = SlidingWindowLimiter(
        global_per_day or int(os.environ.get("RATE_GLOBAL_PER_DAY", "300")), 86400
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if state["answer_fn"] is None:  # load models once at startup, not per request
            state["answer_fn"], state["info"], state["ping"] = default_answer_fn()
        yield

    app = FastAPI(
        title="FilingsQA",
        description="Cited answers from SEC 10-K filings. Not investment advice.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health(deep: bool = False) -> dict:
        """deep=true also queries the vector store. A scheduled GitHub Action calls it every
        few days, because Qdrant suspends free clusters left unused for a week."""
        out = {"status": "ok", **state["info"]}
        if deep and state["ping"] is not None:
            try:
                out["chunks"] = state["ping"]()
            except Exception as exc:
                raise HTTPException(503, f"Vector store unreachable: {type(exc).__name__}") from exc
        return out

    @app.post("/ask", response_model=Reply)
    def ask(body: Ask, request: Request) -> Reply:
        if not per_ip.allow(client_ip(request)):
            raise HTTPException(429, "Limit reached: 10 questions per hour per visitor.")
        if not daily.allow("all"):
            raise HTTPException(429, "The demo's daily question budget is used up. Try tomorrow.")
        try:
            return to_reply(state["answer_fn"](body.question.strip()))
        except Exception as exc:  # report upstream failures (LLM quota, vector store) cleanly
            raise HTTPException(503, f"Answering failed: {type(exc).__name__}") from exc

    return app


app = create_app()
