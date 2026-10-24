"""Build evals/golden/curated.jsonl: 50 questions drafted with AI assistance from the 10-K text.

Every quote is checked to appear in its filing, every figure is read from the filing's
displayed inline-XBRL table, and every not-answerable question is checked by keyword
search to have no answer in the filing. Run from the project root after filingsqa-download:
    python scripts/build_curated.py
"""

import functools
import html as htmlmod
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ixfacts import facts

m = [json.loads(line) for line in open("data/manifest.jsonl")]
latest = {}
for r in m:
    if r["ticker"] not in latest or r["report_date"] > latest[r["ticker"]]["report_date"]:
        latest[r["ticker"]] = r
prior = {
    t: max(
        (r for r in m if r["ticker"] == t and r["report_date"] < latest[t]["report_date"]),
        key=lambda r: r["report_date"],
    )
    for t in latest
}


def possessive(name):
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def squash(s):
    return re.sub(r"\s+", "", s.replace("’", "'").replace("“", '"').replace("”", '"'))


@functools.cache
def doc_text(t):
    """Plain text of the latest filing, with table cells separated by ' | '."""
    raw = Path(latest[t]["local_path"]).read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", raw)
    raw = re.sub(r"(?i)</(p|div|tr|li|h\d|table)>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    t = htmlmod.unescape(re.sub(r"<[^>]+>", " ", raw))
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def src(t):
    r = latest[t]
    return {
        "ticker": t,
        "accession": r["accession"],
        "period_end": r["report_date"],
        "document": r["local_path"],
    }


Q = []


def add(qid, t, question, expected, category, difficulty, evidence):
    Q.append(
        {
            "id": f"cur-{qid}",
            "question": question,
            "expected": expected,
            "source": src(t),
            "category": category,
            "difficulty": difficulty,
            "origin": "curated",
            "evidence": evidence,
        }
    )


# ---------- qualitative / text facts (19) ----------
TXT = [
    (
        "aapl-employees",
        "AAPL",
        "Approximately how many full-time equivalent employees did Apple have as of September 27, 2025?",
        "Approximately 166,000 full-time equivalent employees.",
        ["166,000"],
        "easy",
        [
            "As of September 27, 2025, the Company had approximately 166,000 full-time equivalent employees."
        ],
    ),
    (
        "aapl-manufacturing",
        "AAPL",
        "According to Apple's fiscal 2025 10-K, where are the outsourcing partners that perform most of Apple's manufacturing primarily located?",
        "Primarily in China mainland, India, Japan, South Korea, Taiwan and Vietnam.",
        ["China mainland", "India", "Japan", "South Korea", "Taiwan", "Vietnam"],
        "medium",
        [
            "A significant majority of the Company’s manufacturing is performed in whole or in part by outsourcing partners located primarily in China mainland, India, Japan, South Korea, Taiwan and Vietnam"
        ],
    ),
    (
        "jpm-employees",
        "JPM",
        "How many employees did JPMorgan Chase have globally as of December 31, 2025?",
        "318,512 employees.",
        ["318,512"],
        "easy",
        ["As of December 31, 2025, JPMorganChase had 318,512 employees globally."],
    ),
    (
        "jpm-workforce-geo",
        "JPM",
        "In how many countries were JPMorgan Chase's employees located at the end of 2025, and what share were in the U.S.?",
        "66 countries; 58% of employees were in the U.S.",
        ["66 countries", "58%"],
        "medium",
        [
            "JPMorganChase’s employees are located in 66 countries, with 58% of the Firm’s employees located in the U.S."
        ],
    ),
    (
        "jpm-segments",
        "JPM",
        "What are JPMorgan Chase's reportable business segments in its 2025 10-K?",
        "Consumer & Community Banking (CCB), Commercial & Investment Bank (CIB) and Asset & Wealth Management (AWM), with remaining activities in Corporate.",
        [
            "Consumer & Community Banking",
            "Commercial & Investment Bank",
            "Asset & Wealth Management",
        ],
        "easy",
        [
            "the Firm has three reportable business segments – Consumer & Community Banking (“CCB”), Commercial & Investment Bank (“CIB”) and Asset & Wealth Management (“AWM”) – with the remaining activities in Corporate."
        ],
    ),
    (
        "ko-employees",
        "KO",
        "How many employees did Coca-Cola have at the end of 2025, and why did the number fall from 2024?",
        "Approximately 65,900 (down from about 69,700 at the end of 2024), primarily due to 2025 divestiture activity.",
        ["65,900", "69,700", "divestiture"],
        "medium",
        [
            "As of December 31, 2025 and 2024, our Company had approximately 65,900 and 69,700 employees, respectively",
            "The decrease in the total number of employees was primarily due to 2025 divestiture activity.",
        ],
    ),
    (
        "ko-countries",
        "KO",
        "In how many countries and territories are Coca-Cola's beverage products sold, according to its 2025 10-K?",
        "More than 200 countries and territories.",
        ["more than 200"],
        "easy",
        ["now sold in more than 200 countries and territories"],
    ),
    (
        "msft-employees",
        "MSFT",
        "How many full-time employees did Microsoft have as of June 30, 2026, and how many were in the U.S.?",
        "Approximately 223,000 full-time employees, of whom 121,000 were in the U.S. (102,000 internationally).",
        ["223,000", "121,000"],
        "medium",
        [
            "As of June 30, 2026, we employed approximately 223,000 people on a full-time basis, 121,000 in the U.S. and 102,000 internationally."
        ],
    ),
    (
        "msft-segments",
        "MSFT",
        "What three segments does Microsoft report in its fiscal 2026 10-K?",
        "Productivity and Business Processes, Intelligent Cloud, and More Personal Computing.",
        ["Productivity and Business Processes", "Intelligent Cloud", "More Personal Computing"],
        "easy",
        [
            "three segments: Productivity and Business Processes, Intelligent Cloud, and More Personal Computing"
        ],
    ),
    (
        "msft-openai-revenue",
        "MSFT",
        "How much revenue did Microsoft record from commercial arrangements with OpenAI in fiscal year 2026, and what was its receivable from OpenAI at June 30, 2026?",
        "$24.1 billion of revenue (inclusive of revenue-sharing payments); accounts receivable from OpenAI of $6.0 billion.",
        ["24.1 billion", "6.0 billion"],
        "hard",
        [
            "For fiscal year 2026, we recorded revenue from commercial arrangements with OpenAI, inclusive of revenue-sharing payments, of $ 24.1 billion, and accounts receivable from OpenAI as of June 30, 2026 was $ 6.0 billion."
        ],
    ),
    (
        "wmt-segments",
        "WMT",
        "What are Walmart's three reportable segments in its fiscal 2026 10-K?",
        "Walmart U.S., Walmart International and Sam's Club U.S.",
        ["Walmart U.S.", "Walmart International", "Sam's Club U.S."],
        "easy",
        [
            "Our operations comprise three reportable segments: Walmart U.S., Walmart International and Sam's Club U.S."
        ],
    ),
    (
        "nke-employees",
        "NKE",
        "Approximately how many employees did Nike have worldwide as of May 31, 2026?",
        "Approximately 73,000, including retail and part-time employees.",
        ["73,000"],
        "easy",
        [
            "As of May 31, 2026, we had approximately 73,000 employees worldwide, including retail and part-time employees."
        ],
    ),
    (
        "amzn-employees",
        "AMZN",
        "Approximately how many full-time and part-time employees did Amazon have as of December 31, 2025?",
        "Approximately 1,576,000.",
        ["1,576,000"],
        "easy",
        [
            "As of December 31, 2025, we employed approximately 1,576,000 full-time and part-time employees."
        ],
    ),
    (
        "bac-footprint",
        "BAC",
        "According to Bank of America's 2025 10-K, approximately how many retail financial centers and ATMs does it operate, and how many consumer and small business clients does it serve?",
        "About 3,600 retail financial centers and 15,000 ATMs, serving about 69 million consumer and small business clients.",
        ["3,600", "15,000", "69 million"],
        "medium",
        [
            "we serve approximately 69 million consumer and small business clients with approximately 3,600 retail financial centers, approximately 15,000 automated teller machines (ATMs)"
        ],
    ),
    (
        "axp-segments",
        "AXP",
        "What are American Express's reportable operating segments in its 2025 10-K?",
        "U.S. Consumer Services (USCS), Commercial Services (CS), International Card Services (ICS) and Global Merchant and Network Services (GMNS).",
        [
            "U.S. Consumer Services",
            "Commercial Services",
            "International Card Services",
            "Global Merchant and Network Services",
        ],
        "easy",
        [
            "four reportable operating segments: U.S. Consumer Services (USCS), Commercial Services (CS), International Card Services (ICS) and Global Merchant and Network Services (GMNS)."
        ],
    ),
    (
        "met-segments",
        "MET",
        "Into which segments is MetLife organized after its Strategic Reorganization, per its 2025 10-K?",
        "Six segments: Group Benefits; RIS; Asia; Latin America; Europe, the Middle East and Africa (EMEA); and MIM, plus Corporate & Other.",
        ["Group Benefits", "RIS", "Asia", "Latin America", "EMEA", "MIM"],
        "medium",
        [
            "MetLife is organized into the following six segments: Group Benefits; RIS; Asia; Latin America; Europe, the Middle East and Africa (“EMEA”); and MIM."
        ],
    ),
    (
        "pep-employees",
        "PEP",
        "How many people did PepsiCo employ worldwide as of December 27, 2025, and how many were in the United States?",
        "Approximately 306,000 worldwide, including approximately 125,000 in the United States.",
        ["306,000", "125,000"],
        "medium",
        [
            "We employed approximately 306,000 people worldwide as of December 27, 2025, including approximately 125,000 people within the United States."
        ],
    ),
    (
        "gs-segments",
        "GS",
        "In which business segments does Goldman Sachs manage and report its activities in its 2025 10-K?",
        "Global Banking & Markets, Asset & Wealth Management and Platform Solutions.",
        ["Global Banking & Markets", "Asset & Wealth Management", "Platform Solutions"],
        "easy",
        [
            "We manage and report our activities in three business segments: Global Banking & Markets, Asset & Wealth Management and Platform Solutions."
        ],
    ),
    (
        "trv-employees",
        "TRV",
        "Approximately how many employees did Travelers have at December 31, 2025, and what share were in the United States?",
        "Approximately 34,000, about 90% of them in the United States.",
        ["34,000", "90%"],
        "medium",
        [
            "As of December 31, 2025, the Company had approximately 34,000 employees, approximately 90% of whom are located in the United States."
        ],
    ),
]
for qid, t, q, ans, kp, diff, quotes in TXT:
    add(qid, t, q, {"text": ans, "key_points": kp}, "qualitative", diff, {"quotes": quotes})

# ---------- segment / dimensional numbers (10) ----------
SEG = [
    (
        "aapl-iphone",
        "AAPL",
        "What were Apple's iPhone net sales in fiscal 2025?",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "ProductOrServiceAxis=IPhoneMember$",
    ),
    (
        "aapl-services",
        "AAPL",
        "What were Apple's Services net sales in fiscal 2025?",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "ProductOrServiceAxis=ServiceMember$",
    ),
    (
        "aapl-greater-china",
        "AAPL",
        "What were net sales of Apple's Greater China segment in fiscal 2025?",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "StatementBusinessSegmentsAxis=GreaterChinaSegmentMember$",
    ),
    (
        "msft-intelligent-cloud",
        "MSFT",
        "What revenue did Microsoft's Intelligent Cloud segment report for fiscal year 2026?",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "^StatementBusinessSegmentsAxis=IntelligentCloudMember$",
    ),
    (
        "amzn-aws",
        "AMZN",
        "What were Amazon Web Services (AWS) segment net sales in 2025?",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "^StatementBusinessSegmentsAxis=AmazonWebServicesSegmentMember$",
    ),
    (
        "wmt-sams-club",
        "WMT",
        "What were Sam's Club U.S. segment net sales for Walmart's fiscal year ended January 31, 2026?",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "OperatingSegmentsMember;StatementBusinessSegmentsAxis=SamsClubUSMember$",
    ),
    (
        "wmt-us-ecommerce",
        "WMT",
        "What were Walmart U.S. eCommerce net sales for the fiscal year ended January 31, 2026?",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "MajorCustomersAxis=ECommerceMember;StatementBusinessSegmentsAxis=WalmartUSMember$",
    ),
    (
        "jpm-ccb-net-income",
        "JPM",
        "What net income did JPMorgan Chase's Consumer & Community Banking segment report for 2025?",
        "NetIncomeLoss",
        "StatementBusinessSegmentsAxis=ConsumerCommunityBankingMember$",
    ),
    (
        "gs-gbm-revenues",
        "GS",
        "What were total net revenues of Goldman Sachs's Global Banking & Markets segment in 2025?",
        "RevenuesNetOfInterestExpense",
        "^StatementBusinessSegmentsAxis=GlobalBankingAndMarketsMember$",
    ),
    (
        "nke-footwear",
        "NKE",
        "What were Nike, Inc.'s total footwear revenues (NIKE Brand and Converse) for fiscal 2026?",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "^ProductOrServiceAxis=FootwearMember$",
    ),
]
SCALE = {"6": "million", "9": "billion", "3": "thousand", "0": ""}
for qid, t, q, concept, dims in SEG:
    fs = [
        f
        for f in facts(
            latest[t]["local_path"], rf"us-gaap:{concept}$", latest[t]["report_date"], dims, 500
        )
        if f["start"]
    ]
    vals = {f["shown"] for f in fs}
    assert len(vals) == 1, (qid, fs)
    f = fs[0]
    v = float(f["shown"].replace(",", "")) * 10 ** int(f["scale"])
    add(
        qid,
        t,
        q,
        {"value": v, "unit": "USD", "display": f"${f['shown']} {SCALE[f['scale']]}".strip()},
        "segment_extraction",
        "medium",
        {
            "concept": f["concept"],
            "dimensions": f["dims"],
            "row_label": f["label"],
            "displayed": f["shown"],
            "scale": f["scale"],
            "period": [f["start"], f["end"]],
        },
    )

# ---------- year-over-year computations (10) ----------

YOY = [
    (
        "aapl-sales-growth",
        "AAPL",
        "total net sales",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "fiscal 2025",
        "fiscal 2024",
    ),
    (
        "msft-revenue-growth",
        "MSFT",
        "total revenue",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "fiscal year 2026",
        "fiscal year 2025",
    ),
    ("amzn-ni-growth", "AMZN", "net income", "NetIncomeLoss", "2025", "2024"),
    (
        "wmt-revenue-growth",
        "WMT",
        "total revenues",
        "Revenues",
        "the fiscal year ended January 31, 2026",
        "the prior fiscal year",
    ),
    ("jpm-ni-change", "JPM", "net income", "NetIncomeLoss", "2025", "2024"),
    ("bac-ni-growth", "BAC", "net income", "NetIncomeLoss", "2025", "2024"),
    ("pep-ni-change", "PEP", "net income attributable to PepsiCo", "NetIncomeLoss", "2025", "2024"),
    ("trv-ni-growth", "TRV", "net income", "NetIncomeLoss", "2025", "2024"),
    (
        "axp-revenue-growth",
        "AXP",
        "total revenues net of interest expense",
        "RevenuesNetOfInterestExpense",
        "2025",
        "2024",
    ),
    (
        "ko-ni-growth",
        "KO",
        "net income attributable to shareowners",
        "NetIncomeLoss",
        "2025",
        "2024",
    ),
]
NAMES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "WMT": "Walmart",
    "JPM": "JPMorgan Chase",
    "BAC": "Bank of America",
    "PEP": "PepsiCo",
    "TRV": "Travelers",
    "AXP": "American Express",
    "KO": "Coca-Cola",
}
for qid, t, label, concept, cur_p, prev_p in YOY:
    cur, prev = latest[t]["report_date"], prior[t]["report_date"]
    got = {}
    for f in facts(latest[t]["local_path"], rf"us-gaap:{concept}$", None, "^$", 3000):
        if (
            f["start"]
            and f["end"] in (cur, prev)
            and 330 <= (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days <= 380
        ):
            got.setdefault(f["end"], set()).add((f["shown"], f["scale"], f["label"]))
    assert all(len(got.get(e, ())) == 1 for e in (cur, prev)), (qid, got)
    ((a, sa, la),) = got[cur]
    ((b, sb, lb),) = got[prev]
    va, vb = float(a.replace(",", "")), float(b.replace(",", ""))
    pct = round((va - vb) / vb * 100, 1)
    add(
        qid,
        t,
        f"By what percentage did {possessive(NAMES[t])} {label} change in {cur_p} compared with {prev_p}?",
        {"value": pct, "unit": "percent", "tolerance": 0.1, "display": f"{pct:+.1f}%"},
        "multi_hop",
        "medium",
        {
            "concept": f"us-gaap:{concept}",
            "row_label": la,
            "current": {"period_end": cur, "displayed": a, "scale": sa},
            "prior": {"period_end": prev, "displayed": b, "scale": sb},
            "calculation": f"({a} - {b}) / {b} = {pct}%",
        },
    )

# ---------- not answerable from the filing (11) ----------
NA = [
    (
        "aapl-iphone-units",
        "AAPL",
        "How many iPhone units did Apple sell in fiscal 2025?",
        "Apple reports iPhone net sales in dollars but does not disclose unit sales in this 10-K.",
        [r"units? (sold|shipped)|unit sales", r"iPhone[^.]{0,60}units"],
    ),
    (
        "amzn-prime-members",
        "AMZN",
        "How many Amazon Prime members were there at the end of 2025?",
        "The 10-K discusses Prime membership fees and benefits but does not disclose a member count.",
        [r"\d[\d,.]* (million )?(paid )?Prime members", r"Prime members[^.]{0,40}[0-9]+ million"],
    ),
    (
        "bac-ceo-pay",
        "BAC",
        "What was the total 2025 compensation of Bank of America's chief executive officer?",
        "Executive compensation (Part III, Item 11) is incorporated by reference from the 2026 proxy statement, not stated in the 10-K.",
        [r"total compensation"],
    ),
    (
        "gs-share-price",
        "GS",
        "What was Goldman Sachs's closing share price on December 31, 2025?",
        "Not stated in the 10-K.",
        [
            r"(closing|stock|share) price on December 31",
            r"\$[0-9,]+\.[0-9]{2} per share on December 31",
        ],
    ),
    (
        "wmt-germany-stores",
        "WMT",
        "How many stores does Walmart operate in Germany?",
        "Germany is not among Walmart's markets in this 10-K; it is not mentioned.",
        [r"Germany"],
    ),
    (
        "nke-aj1-revenue",
        "NKE",
        "How much revenue did the Air Jordan 1 sneaker generate in fiscal 2026?",
        "Nike does not disclose revenue by individual shoe model; Air Jordan 1 is not mentioned.",
        [r"Air Jordan 1|Jordan 1\b"],
    ),
    (
        "pep-cans",
        "PEP",
        "How many cans of Pepsi did PepsiCo sell in 2025?",
        "Volume is not disclosed in cans; not stated in the 10-K.",
        [r"\bcans\b"],
    ),
    (
        "ko-india-share",
        "KO",
        "What was Coca-Cola's market share in India in 2025?",
        "No India market-share figure appears in the 10-K.",
        [r"market share[^.]{0,80}India|India[^.]{0,80}market share"],
    ),
    (
        "jpm-2026-ni-forecast",
        "JPM",
        "What net income does JPMorgan Chase forecast for 2026?",
        "The 10-K gives no net income forecast for 2026.",
        [r"2026[^.]{0,40}net income of", r"net income guidance", r"expect[^.]{0,30}net income"],
    ),
    (
        "trv-2026-cat-losses",
        "TRV",
        "What catastrophe losses does Travelers expect for 2026?",
        "The 10-K gives no 2026 catastrophe loss estimate.",
        [
            r"2026 catastrophe",
            r"catastrophe losses (in|for) 2026",
            r"expects?[^.]{0,60}catastrophe losses[^.]{0,40}2026",
        ],
    ),
    (
        "axp-2026-ni",
        "AXP",
        "What was American Express's net income for full-year 2026?",
        "The 10-K covers fiscal 2025; full-year 2026 results did not exist when it was filed.",
        [r"2026 net income", r"net income (for|in) 2026"],
    ),
]
for qid, t, q, reason, patterns in NA:
    text = doc_text(t).replace("\n", " ")
    hits = {p: len(re.findall(p, text, re.I)) for p in patterns}
    assert all(v == 0 for v in hits.values()), (qid, hits)
    ev = {"absence_check": {"patterns": patterns, "hits": 0}}
    if qid == "bac-ceo-pay":
        ev["quotes"] = [
            "Portions of the definitive proxy statement relating to the registrant’s 2026 annual meeting of shareholders are incorporated by reference in this Form 10-K in response to Items 10, 11, 12, 13 and 14 of Part III."
        ]
    add(qid, t, q, {"answerable": False, "reason": reason}, "not_answerable", "medium", ev)

# ---------- verify every quote is in its filing ----------
for q in Q:
    for quote in q["evidence"].get("quotes", []):
        assert squash(quote) in squash(doc_text(q["source"]["ticker"]).replace("\n", " ")), (
            q["id"],
            quote,
        )
assert len({q["id"] for q in Q}) == len(Q)
out = Path("evals/golden/curated.jsonl")
out.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in Q), encoding="utf-8")

print(
    len(Q),
    "questions ->",
    out,
    dict(Counter(q["category"] for q in Q)),
    "companies:",
    len({q["source"]["ticker"] for q in Q}),
)
