"""Pipeline tests that run offline: hash embeddings, in-memory Qdrant, scripted LLM."""

import json

import pytest
from qdrant_client import QdrantClient

from filingsqa.chunking import fixed_word_chunks
from filingsqa.embeddings import HashEmbedder
from filingsqa.evaluate import evidence_strings, grade, numbers_in, retrieval_hits, run, summarize
from filingsqa.index import build_index
from filingsqa.llm import ChatClient, LLMError
from filingsqa.rag import Retriever, answer_question, parse_reply
from filingsqa.text import html_to_text

# ---------------------------------------------------------------- text and chunks


def test_html_to_text_drops_hidden_xbrl_and_keeps_table_cells():
    raw = (
        "<html><body><ix:header><ix:hidden>secret 999</ix:hidden></ix:header>"
        "<p>Total net revenue</p><table><tr><td>2025</td><td>$</td><td>182,447</td></tr></table>"
        "</body></html>"
    )
    text = html_to_text(raw)
    assert "secret" not in text
    assert "Total net revenue" in text
    assert "2025 | $ | 182,447 |" in text


def test_fixed_word_chunks_overlap_and_cover_everything():
    words = [f"w{i}" for i in range(10)]
    chunks = fixed_word_chunks(" ".join(words), words=4, overlap=1)
    assert chunks == ["w0 w1 w2 w3", "w3 w4 w5 w6", "w6 w7 w8 w9"]
    assert fixed_word_chunks("", 4, 1) == []
    with pytest.raises(ValueError):
        fixed_word_chunks("a b", words=4, overlap=4)


# ---------------------------------------------------------------- end to end


class ScriptedLLM:
    """Stands in for the chat API; returns a fixed reply and records the prompt."""

    model = "scripted"

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def complete(self, messages, **kw):
        self.prompts.append(messages[-1]["content"])

        class C:
            text = self.reply
            prompt_tokens, completion_tokens, latency_ms, model = 100, 20, 5, "scripted"

        return C()


@pytest.fixture
def tiny_index(tmp_path):
    doc = tmp_path / "jpm.htm"
    doc.write_text(
        "<html><body><p>JPMorgan Chase had 318,512 employees globally.</p>"
        "<p>Net income was $57,048 million in 2025.</p></body></html>"
    )
    manifest = [
        {
            "ticker": "JPM",
            "company": "JPMORGAN CHASE & CO",
            "report_date": "2025-12-31",
            "accession": "0000019617-26-000001",
            "local_path": doc.as_posix(),
            "documents": [doc.as_posix()],
            "exhibits": [],
        }
    ]
    client = QdrantClient(":memory:")
    embedder = HashEmbedder()
    info = build_index(
        manifest,
        embedder,
        client,
        "t",
        words=8,
        overlap=2,
        out_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        progress=lambda *_: None,
    )
    return client, embedder, info


def test_index_and_answer_with_citations(tiny_index):
    client, embedder, info = tiny_index
    assert info["chunks"] >= 2
    retriever = Retriever(client, embedder, "t")
    llm = ScriptedLLM("ANSWER: JPMorgan had 318,512 employees [1].\nCITATIONS: [1]")
    a = answer_question("How many employees did JPMorgan have?", retriever, llm, k=2)
    assert a.citations == [1] and not a.abstained
    assert "318,512" in a.answer
    assert "[1] JPMORGAN CHASE & CO (JPM), 10-K" in llm.prompts[0]
    assert len(a.hits) == 2


def test_eval_run_grades_caches_and_resumes(tiny_index, tmp_path):
    client, embedder, _ = tiny_index
    retriever = Retriever(client, embedder, "t")
    q = {
        "id": "cur-jpm-employees",
        "category": "qualitative",
        "question": "How many employees did JPMorgan Chase have globally?",
        "expected": {"text": "318,512 employees.", "key_points": ["318,512"]},
        "source": {"ticker": "JPM", "period_end": "2025-12-31"},
        "evidence": {"quotes": ["JPMorgan Chase had 318,512 employees globally."]},
    }
    llm = ScriptedLLM("ANSWER: 318,512 employees [1]\nCITATIONS: [1]")
    items = run([q], lambda t: answer_question(t, retriever, llm, 3), tmp_path / "c", lambda *_: 0)
    assert items[0]["correct"] and items[0]["filing_hit"] and items[0]["evidence_hit"]
    # second run answers from the cache: the LLM is not called again
    run([q], lambda t: answer_question(t, retriever, llm, 3), tmp_path / "c", lambda *_: 0)
    assert len(llm.prompts) == 1
    s = summarize(items)
    assert s["accuracy"] == 1.0 and s["wrong_answer_rate"] == 0.0


# ---------------------------------------------------------------- grading


def test_parse_reply_handles_not_found_and_citations():
    assert parse_reply("ANSWER: NOT_FOUND\nCITATIONS: none") == ("NOT_FOUND", True, [])
    assert parse_reply("ANSWER: $1 million [2][3]\nCITATIONS: [2][3]")[2] == [2, 3]


def test_numbers_in_reads_scale_and_percent():
    n = numbers_in("Revenue was $182,447 million, up 6.4% from $171.1 billion.")
    assert n[0]["value"] == 182_447_000_000 and n[0]["money"]
    assert n[1]["value"] == 6.4 and n[1]["pct"]
    assert n[2]["value"] == pytest.approx(171.1e9)


USD_Q = {"category": "numeric_extraction", "expected": {"value": 182_447_000_000, "unit": "USD"}}


@pytest.mark.parametrize(
    "answer,ok",
    [
        ("Total net revenue was $182,447 million [1].", True),
        ("About $182.4 billion [1].", True),
        ("$182,447 [1]", False),  # scale dropped: not accepted
        ("$170,000 million in 2024 and $182,447 million in 2025.", False),  # first amount wrong
    ],
)
def test_grade_usd(answer, ok):
    assert grade(USD_Q, answer, False)["correct"] is ok


def test_grade_percent_needs_direction():
    q = {"category": "multi_hop", "expected": {"value": -2.4, "unit": "percent", "tolerance": 0.1}}
    assert grade(q, "Net income fell from $58,471M to $57,048M, a decrease of 2.4%.", False)[
        "correct"
    ]
    assert not grade(q, "Net income rose 2.4%.", False)["correct"]
    assert grade({**q, "expected": {**q["expected"], "value": 6.4}}, "up 6.4%", False)["correct"]


def test_grade_eps_and_text_and_abstention():
    eps = {"category": "numeric_extraction", "expected": {"value": 20.02, "unit": "USD/shares"}}
    assert grade(eps, "Diluted EPS was $20.02 per share.", False)["correct"]
    text = {
        "category": "qualitative",
        "expected": {"text": "x", "key_points": ["Consumer & Community Banking", "66 countries"]},
    }
    g = grade(text, "Consumer and Community Banking; staff in 66 countries.", False)
    assert g["correct"] and g["key_point_recall"] == 1.0
    na = {"category": "not_answerable", "expected": {"answerable": False, "reason": "r"}}
    assert grade(na, "NOT_FOUND", True)["correct"]
    assert not grade(na, "About 1 million", False)["correct"]
    assert grade(USD_Q, "NOT_FOUND", True) == {"correct": False, "answered": False}


def test_evidence_for_xbrl_question_is_the_figure_in_millions():
    q = {**USD_Q, "source": {"ticker": "JPM", "period_end": "2025-12-31"}}
    assert evidence_strings(q) == ["182,447"]
    hit = {"ticker": "JPM", "period_end": "2025-12-31", "text": "Total net revenue | 182,447 |"}
    assert retrieval_hits(q, [hit]) == {"filing_hit": True, "evidence_hit": True}
    other = {**hit, "ticker": "BAC"}
    assert retrieval_hits(q, [other]) == {"filing_hit": False, "evidence_hit": False}


# ---------------------------------------------------------------- LLM client


class FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._p, self.headers, self.text = status, payload, headers or {}, ""

    def json(self):
        return self._p


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        return self.responses.pop(0)


OK = FakeResp(
    200,
    {
        "choices": [{"message": {"content": "ANSWER: hi"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        "model": "m",
    },
)


def test_llm_client_waits_on_429_then_succeeds(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    waits = []
    s = FakeSession([FakeResp(429, headers={"retry-after": "7"}), OK])
    c = ChatClient(api_key="k", model="m", session=s, sleep=waits.append)
    out = c.complete([{"role": "user", "content": "x"}])
    assert out.text == "ANSWER: hi" and out.prompt_tokens == 10
    assert waits == [7.0]
    url, body, headers = s.calls[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert body["temperature"] == 0.0 and headers["Authorization"] == "Bearer k"


def test_llm_client_needs_a_key(monkeypatch):
    for v in ("LLM_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(LLMError):
        ChatClient()


def test_llm_client_does_not_retry_auth_errors():
    s = FakeSession([FakeResp(401)])
    with pytest.raises(LLMError):
        ChatClient(api_key="bad", session=s, sleep=lambda _: None).complete([])
    assert len(s.calls) == 1


def test_results_are_json_serializable(tiny_index, tmp_path):
    client, embedder, _ = tiny_index
    llm = ScriptedLLM("ANSWER: NOT_FOUND\nCITATIONS: none")
    q = {
        "id": "na",
        "category": "not_answerable",
        "question": "q",
        "expected": {"answerable": False, "reason": "r"},
        "source": {"ticker": "JPM", "period_end": "2025-12-31"},
    }
    items = run(
        [q],
        lambda t: answer_question(t, Retriever(client, embedder, "t"), llm, 2),
        tmp_path / "c",
        lambda *_: 0,
    )
    json.dumps(summarize(items))


def test_index_rebuild_reuses_cached_embeddings(tmp_path):
    doc = tmp_path / "a.htm"
    doc.write_text("<p>" + " ".join(f"word{i}" for i in range(50)) + "</p>")
    manifest = [
        {
            "ticker": "A",
            "company": "A",
            "report_date": "2025-12-31",
            "accession": "1",
            "local_path": doc.as_posix(),
            "documents": [doc.as_posix()],
        }
    ]

    class CountingEmbedder(HashEmbedder):
        calls = 0

        def embed_documents(self, texts):
            CountingEmbedder.calls += len(texts)
            return super().embed_documents(texts)

    emb, client = CountingEmbedder(), QdrantClient(":memory:")
    kw = dict(
        words=10, overlap=2, out_dir=tmp_path, cache_dir=tmp_path / "c", progress=lambda *_: 0
    )
    first = build_index(manifest, emb, client, "x", **kw)
    calls_after_first = CountingEmbedder.calls
    second = build_index(manifest, emb, client, "x", **kw)
    assert first["embedded_now"] == first["chunks"] and first["reused_from_cache"] == 0
    assert second["embedded_now"] == 0 and second["reused_from_cache"] == second["chunks"]
    assert CountingEmbedder.calls == calls_after_first  # nothing re-embedded
    assert client.count("filingsqa_x").count == second["chunks"]


class FakeGetSession(FakeSession):
    def __init__(self, models, responses=()):
        super().__init__(responses)
        self.models = models

    def get(self, url, headers=None, timeout=None):
        return FakeResp(200, {"data": [{"id": m} for m in self.models]})


def test_check_model_lists_alternatives_when_model_is_retired():
    s = FakeGetSession(["openai/gpt-oss-120b", "openai/gpt-oss-20b"])
    with pytest.raises(LLMError, match="openai/gpt-oss-120b, openai/gpt-oss-20b"):
        ChatClient(api_key="k", model="llama-3.3-70b-versatile", session=s).check_model()
    ChatClient(api_key="k", model="openai/gpt-oss-120b", session=s).check_model()


def test_reasoning_models_get_low_effort_and_hidden_reasoning():
    s = FakeSession([OK, OK])
    ChatClient(api_key="k", model="openai/gpt-oss-120b", session=s).complete([])
    body = s.calls[0][1]
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert body["max_completion_tokens"] == 1500
    ChatClient(api_key="k", model="some/other-model", session=s).complete([])
    assert "reasoning_effort" not in s.calls[1][1]


def test_amounts_must_match_at_the_precision_stated():
    aig = {"category": "numeric_extraction", "expected": {"value": 41_139_000_000, "unit": "USD"}}
    # the first baseline run's AIG answer: a different line item, 0.06% off
    assert not grade(aig, "Total equity was $41,162 million [2].", False)["correct"]
    assert grade(aig, "Shareholders' equity was $41,139 million [2].", False)["correct"]
    gs = {**aig, "expected": {"value": 41_453_000_000, "unit": "USD"}}
    assert grade(gs, "Net revenues were $41.45 billion.", False)["correct"]
    assert not grade(gs, "Net revenues were $41.3 billion.", False)["correct"]


def test_daily_limit_stops_instead_of_waiting():
    from filingsqa.llm import DailyLimitError

    msg = '{"error":{"message":"Rate limit reached ... tokens per day (TPD): Limit 200000"}}'
    resp = FakeResp(429, headers={"retry-after": "3600"})
    resp.text = msg
    with pytest.raises(DailyLimitError):
        ChatClient(api_key="k", session=FakeSession([resp]), sleep=lambda _: None).complete([])


def test_regrade_rescores_saved_answers_without_llm(tmp_path, monkeypatch):
    from filingsqa import evaluate

    golden = tmp_path / "evals" / "golden"
    golden.mkdir(parents=True)
    (tmp_path / "evals" / "results").mkdir()
    q = {
        "id": "xbrl-AIG-x",
        "category": "numeric_extraction",
        "origin": "xbrl",
        "question": "q",
        "expected": {"value": 41_139_000_000, "unit": "USD"},
        "source": {"ticker": "AIG", "period_end": "2025-12-31"},
    }
    (golden / "xbrl_numeric.jsonl").write_text(json.dumps(q) + "\n")
    hit = {"ticker": "AIG", "period_end": "2025-12-31", "text": "equity | 41,139 |"}
    item = {
        "id": q["id"],
        "category": q["category"],
        "question": "q",
        "expected": q["expected"],
        "answer": "$41,162 million",
        "abstained": False,
        "citations": [],
        "hits": [hit],
        "latency_ms": 10,
        "llm_latency_ms": 5,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "model": "m",
        "correct": True,
        "answered": True,
    }
    saved = tmp_path / "old.json"
    saved.write_text(
        json.dumps(
            {
                "config": {"k": 5, "index": {"name": "baseline"}},
                "config_key": "abc",
                "set": "smoke",
                "items": [item],
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(evaluate, "GOLDEN", golden)
    out = evaluate.regrade(saved)
    data = json.loads(out.read_text())
    assert data["items"][0]["correct"] is False  # the old grader's false positive is gone
    assert data["items"][0]["evidence_hit"] is True
    assert data["summary"]["accuracy"] == 0.0
