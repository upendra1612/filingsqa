from fastapi.testclient import TestClient

from filingsqa.api import SlidingWindowLimiter, create_app
from filingsqa.rag import Answer, Hit


def fake_answer(question: str) -> Answer:
    hit = Hit(
        0.81,
        "As of December 31, 2025, JPMorganChase had 318,512 employees globally." * 20,
        {
            "company": "JPMORGAN CHASE & CO",
            "ticker": "JPM",
            "period_end": "2025-12-31",
            "doc_type": "10-K",
            "document": "jpm-20251231.htm",
            "url": "https://www.sec.gov/Archives/edgar/data/19617/x/jpm-20251231.htm",
        },
    )
    return Answer(
        question=question,
        answer="318,512 employees [1].",
        abstained=False,
        citations=[1],
        hits=[hit],
        model="fake",
        latency_ms=12,
    )


def client(**kw):
    return TestClient(create_app(answer_fn=fake_answer, info={"index": "t"}, **kw))


def test_health():
    with client() as c:
        assert c.get("/health").json() == {"status": "ok", "index": "t"}


def test_ask_returns_answer_and_cited_sources():
    with client() as c:
        r = c.post("/ask", json={"question": "How many employees did JPMorgan have?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "318,512 employees [1]." and body["cited"] == [1]
    src = body["sources"][0]
    assert src["ticker"] == "JPM" and src["url"].startswith("https://www.sec.gov/")
    assert len(src["excerpt"]) == 400  # long passages are trimmed for the UI


def test_rejects_too_short_or_too_long_questions():
    with client() as c:
        assert c.post("/ask", json={"question": "hi"}).status_code == 422
        assert c.post("/ask", json={"question": "x" * 301}).status_code == 422


def test_rate_limits_per_visitor_and_globally():
    with client(per_ip_per_hour=2, global_per_day=100) as c:
        q = {"question": "How many employees did JPMorgan have?"}
        h1, h2 = {"x-forwarded-for": "1.1.1.1"}, {"x-forwarded-for": "2.2.2.2"}
        assert c.post("/ask", json=q, headers=h1).status_code == 200
        assert c.post("/ask", json=q, headers=h1).status_code == 200
        assert c.post("/ask", json=q, headers=h1).status_code == 429
        assert c.post("/ask", json=q, headers=h2).status_code == 200  # other visitors unaffected
    with client(per_ip_per_hour=100, global_per_day=1) as c:
        assert c.post("/ask", json=q).status_code == 200
        assert c.post("/ask", json=q).status_code == 429


def test_upstream_failure_is_a_clean_503():
    def broken(_q):
        raise RuntimeError("quota")

    with TestClient(create_app(answer_fn=broken, info={})) as c:
        r = c.post("/ask", json={"question": "How many employees did JPMorgan have?"})
    assert r.status_code == 503 and "RuntimeError" in r.json()["detail"]


def test_sliding_window_frees_slots_over_time():
    now = [0.0]
    lim = SlidingWindowLimiter(1, 10, clock=lambda: now[0])
    assert lim.allow("a") and not lim.allow("a")
    now[0] = 10.0
    assert lim.allow("a")


def test_deep_health_queries_the_vector_store():
    with TestClient(create_app(answer_fn=fake_answer, info={}, ping=lambda: 17580)) as c:
        deep = c.get("/health?deep=true").json()
        assert deep["chunks"] == 17580
        assert set(deep.get("memory_mb", {"now": 1, "peak": 1})) == {"now", "peak"}
        assert c.get("/health").json() == {"status": "ok"}

    def down():
        raise ConnectionError

    with TestClient(create_app(answer_fn=fake_answer, info={}, ping=down)) as c:
        assert c.get("/health?deep=true").status_code == 503
