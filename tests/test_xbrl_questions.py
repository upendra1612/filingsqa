from filingsqa.xbrl_questions import METRICS, build_questions, find_fact, format_period

ACCN = "0000000001-26-000010"
END = "2025-12-31"

REVENUE = next(m for m in METRICS if m.key == "revenue")
ASSETS = next(m for m in METRICS if m.key == "total_assets")


def facts(**concepts):
    return {"facts": {"us-gaap": {name: {"units": units} for name, units in concepts.items()}}}


def fy(val, start="2025-01-01", end=END, accn=ACCN, form="10-K"):
    return {"start": start, "end": end, "val": val, "accn": accn, "form": form}


def test_picks_annual_value_from_this_filing():
    f = facts(
        Revenues={
            "USD": [
                fy(100),  # the one we want
                fy(90, start="2024-01-01", end="2024-12-31"),  # prior year, same filing
                fy(25, start="2025-10-01"),  # a quarter
                fy(100, accn="other"),  # same number in a different filing
            ]
        }
    )
    assert find_fact(f, REVENUE, ACCN, END) == ("Revenues", 100)


def test_falls_back_to_alias_concept():
    f = facts(RevenueFromContractWithCustomerExcludingAssessedTax={"USD": [fy(42)]})
    assert find_fact(f, REVENUE, ACCN, END) == (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        42,
    )


def test_conflicting_values_are_skipped_not_guessed():
    f = facts(Revenues={"USD": [fy(100), fy(101)]})
    assert find_fact(f, REVENUE, ACCN, END) == "ambiguous"


def test_instant_metric_ignores_duration_facts():
    f = facts(Assets={"USD": [{"end": END, "val": 500, "accn": ACCN, "form": "10-K"}]})
    assert find_fact(f, ASSETS, ACCN, END) == ("Assets", 500)


def test_missing_metric_returns_none():
    assert find_fact(facts(), REVENUE, ACCN, END) is None


def test_build_questions_end_to_end():
    manifest = [
        {
            "ticker": "TST",
            "company": "Test Corp",
            "accession": ACCN,
            "report_date": END,
            "local_path": "data/raw/TST/x.htm",
        }
    ]
    qs, stats = build_questions(manifest, {"TST": facts(Revenues={"USD": [fy(100)]})})
    assert stats["generated"] == 1
    assert qs[0]["question"] == (
        "What was Test Corp's total revenue for the fiscal year ended December 31, 2025?"
    )
    assert qs[0]["expected"] == {"value": 100, "unit": "USD"}
    assert qs[0]["source"]["concept"] == "us-gaap:Revenues"


def test_format_period_has_no_leading_zero():
    assert format_period("2024-09-01") == "September 1, 2024"
