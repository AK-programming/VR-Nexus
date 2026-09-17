"""Tests for the scorer, not for extraction.

The scorer is the instrument. If it drifts, every extraction number it reports
drifts with it and the drift looks like an extraction change, which is the one
failure mode that would make the whole harness worse than useless. So its
calibration is pinned here:

  * a gold set scored against itself must be a perfect 100/100. Anything less
    means the similarity function cannot recognise identical text.
  * one tender's gold set scored against another's must score poorly. Both are
    Pakistani public-sector IT procurements full of the same vocabulary
    (proposal, bidder, technical, submit, form), so a similarity function that
    keys on that shared vocabulary rather than on the specific obligation will
    show high recall here. That is the false-positive trap, and this is the
    test that catches it.
  * duplicate emitted rows must not inflate recall, because the original
    problem was 12x duplication and a scorer that rewarded it would have
    reported the broken pipeline as healthy.

Runs with no database, no API key and no network.
"""
from tests.eval.score import load_gold, score, similarity


def test_gold_against_itself_is_perfect():
    gold = load_gold("smeda_dashboard")["rows"]
    result = score(gold, gold)
    assert result.recall == 1.0, f"identical input scored {result.recall:.1%} recall"
    assert result.precision == 1.0
    assert result.missed_gold == []


def test_different_tenders_do_not_match_each_other():
    smeda = load_gold("smeda_dashboard")["rows"]
    moitt = load_gold("moitt_node")["rows"]
    result = score(smeda, moitt)
    # Some genuine overlap is expected and correct: both tenders really do ask
    # for a bid securing declaration and audited financials, and the analysts
    # wrote those rows similarly. The bar is that the bulk must NOT match.
    assert result.recall < 0.20, (
        f"cross-tender recall {result.recall:.1%} is too high - the similarity "
        "function is keying on shared procurement vocabulary, not on obligations"
    )


def test_duplicate_rows_do_not_inflate_recall():
    gold = load_gold("smeda_dashboard")["rows"]
    tenfold = [dict(r) for r in gold for _ in range(10)]
    result = score(tenfold, gold)
    assert result.recall == 1.0
    # One-to-one matching is what makes this hold: 570 rows answering 57
    # obligations must score ~10% precision, not 100%.
    assert result.precision < 0.15, (
        f"precision {result.precision:.1%} on 10x duplicated input - matching is "
        "not one-to-one, so duplication is being rewarded"
    )


def test_paraphrase_matches_but_unrelated_does_not():
    analyst = {"description": "Provide NTN and STRN/PST registrations.", "reference": "Eligibility 2"}
    tender_wording = {
        "description": "Must be registered with relevant tax authorities. Must have NTN and STRN and PST registration.",
        "reference": "",
    }
    unrelated = {
        "description": "Submit the prescribed Bid Securing Declaration on legal stamp paper of minimum PKR 100.",
        "reference": "Eligibility 7",
    }
    assert similarity(tender_wording, analyst) >= 0.45, "honest paraphrase of the same obligation must match"
    assert similarity(unrelated, analyst) < 0.45, "two different eligibility criteria must not match"


def test_reference_agreement_lifts_a_partial_match_over_the_line():
    """REFERENCE_BONUS exists to rescue a row whose wording only partly
    survives the analyst's rewrite, and it is deliberately too small to rescue
    one whose wording does not survive at all.

    The ceiling is set by real data, not taste: four distinct obligations in the
    SMEDA gold set all cite "Evaluation 2.4" (TECH-4 parts a, b, c plus the
    presentation row). They sit at 0.25 to 0.32 similarity, so a bonus large
    enough to match rewritten text on a shared citation alone would also start
    matching those four to each other and reporting the confusion as recall.
    test_different_obligations_sharing_a_reference_stay_apart pins that.
    """
    analyst = {
        "description": "Submit the prescribed Bid Securing Declaration on legal stamp paper of minimum PKR 100 in favor of SMEDA.",
        "reference": "Eligibility 7",
    }
    partly_reworded = {
        "description": "Bid Securing Declaration on legal Stamp Paper of minimum PKR 100/- in favor of Small and Medium Enterprises Development Authority",
        "reference": "Eligibility 7",
    }
    without_reference = dict(partly_reworded, reference="")
    assert similarity(partly_reworded, analyst) >= 0.45
    # And the bonus is doing real work rather than being a no-op knob.
    assert similarity(partly_reworded, analyst) > similarity(without_reference, analyst)


def test_different_obligations_sharing_a_reference_stay_apart():
    """The false-positive trap the reference bonus could walk into."""
    gold = load_gold("smeda_dashboard")["rows"]
    family = [r for r in gold if r.get("reference", "").startswith("Evaluation 2.4")]
    assert len(family) >= 3, "gold set changed; this test needs the shared-reference family"
    for a in family:
        for b in family:
            if a is b:
                continue
            assert similarity(a, b) < 0.45, (
                f"two distinct obligations under one clause matched:\n  {a['reference']}\n  {b['reference']}"
            )


def test_empty_emitted_scores_zero_not_crash():
    gold = load_gold("smeda_dashboard")["rows"]
    result = score([], gold)
    assert result.recall == 0.0
    assert result.precision == 0.0
    assert result.f1 == 0.0
    assert len(result.missed_gold) == len(gold)
