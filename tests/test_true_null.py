"""The fixture that should have existed first.

Generate data with no signal in it — the denial label assigned uniformly at random
inside each cell — and check that the machinery says so. Three defects survived a
47-test suite, a 100% mutation kill rate and a full architectural review because
nothing ever asked the pipeline what it does when there is nothing to find:

  * the reference distribution was assembled only from cells that had already produced
    a finding, so it was conditioned on the event under test and rejected at close to
    certainty on data with no signal in it;
  * the p-value divided a midrank by the cell size, which understates by up to a factor
    of two whenever values repeat — and the tested dimensions are published at bin
    resolution, so they repeat constantly;
  * cells that could not reach the threshold at any effect size were counted as
    findings.

A test suite that only ever asks "does it find the planted thing" cannot catch any
of those. This one asks the opposite question.
"""
import random
import pytest
from typing import ClassVar

from likewise import core, stats


def _cell(n, rng, distinct=True):
    """One cell of n records with no relationship between position and label."""
    if distinct:
        vals = [rng.gauss(90, 6) for _ in range(n)]
    else:                                   # published at bin resolution: ties everywhere
        vals = [round(rng.gauss(90, 6) / 5.0) * 5.0 for _ in range(n)]
    rng.shuffle(vals)
    mr = core.midranks(vals, higher_is_worse=True)
    return {"values": vals, "midranks": mr, "observed_midrank": mr[0],
            "direction": "higher_is_worse", "threshold": 1.0}


@pytest.mark.parametrize("n", [4, 6, 10, 20])
def test_p_values_are_uniform_under_a_true_null(n):
    """The one property every p-value must have. Under no signal, P(p <= a) <= a.

    The previous form failed this badly and in the dangerous direction: at a cell size
    of four it reported p <= 0.05 essentially always.
    """
    rng = random.Random(11 + n)
    ps = []
    for _ in range(3000):
        c = _cell(n, rng)
        ps.append(stats.rank_p_value(c["values"], c["values"][0], higher_is_worse=True))
    for alpha in (0.05, 0.10, 0.25, 0.50):
        rate = sum(1 for p in ps if p <= alpha) / len(ps)
        assert rate <= alpha + 0.03, (
            f"n={n}: P(p<={alpha}) = {rate:.3f}, which is anticonservative")


@pytest.mark.parametrize("n", [8, 16, 32])
def test_p_values_stay_valid_when_the_values_are_coarsened(n):
    """Ties are the operating condition, not an edge case. A p-value that is only valid
    on distinct values is not valid on this data."""
    rng = random.Random(400 + n)
    ps = [stats.rank_p_value(c["values"], c["values"][0])
          for c in (_cell(n, rng, distinct=False) for _ in range(3000))]
    for alpha in (0.05, 0.10, 0.25):
        rate = sum(1 for p in ps if p <= alpha) / len(ps)
        assert rate <= alpha + 0.03, f"n={n}: P(p<={alpha}) = {rate:.3f} on coarsened values"


def test_the_pooled_test_does_not_reject_under_a_true_null():
    """The scan-level claim must also survive the absence of a claim."""
    rng = random.Random(7)
    rejects = 0
    trials = 300
    for _ in range(trials):
        cells = [_cell(rng.choice([2, 3, 5, 9, 14]), rng) for _ in range(150)]
        r = stats.stratified_rank_test(cells)
        if r["p"] is not None and r["p"] <= 0.05:
            rejects += 1
    rate = rejects / trials
    assert rate <= 0.10, f"pooled test rejected {rate:.3f} of true nulls at alpha=0.05"


def test_the_pooled_test_finds_a_real_effect_that_no_single_cell_could():
    """The reason for pooling. Each cell here holds three records, so the smallest p any
    one of them can produce is 1/3 — no per-cell test can ever reject. Across three
    hundred such cells the effect is plain."""
    rng = random.Random(21)
    cells = []
    for _ in range(300):
        vals = sorted(rng.gauss(90, 6) for _ in range(3))
        # the denied record sits at the best position more often than chance
        idx = 0 if rng.random() < 0.62 else rng.choice([1, 2])
        v = vals[idx]
        rest = [x for k, x in enumerate(vals) if k != idx]
        ordered = [v] + rest
        mr = core.midranks(ordered, higher_is_worse=True)
        cells.append({"values": ordered, "midranks": mr, "observed_midrank": mr[0],
                      "direction": "higher_is_worse", "threshold": 1.0})
    assert core.cell_power(cells[0]["values"], 0.10)[0] == "underpowered"
    r = stats.stratified_rank_test(cells)
    assert r["p"] is not None and r["p"] < 0.01, r


def test_a_cell_with_no_order_contributes_nothing_rather_than_noise():
    """Every value tied: the cell cannot order anything, and must not be allowed to
    contribute a spurious zero-variance term."""
    cells = [{"values": [5.0] * 6, "midranks": [3.5] * 6, "observed_midrank": 3.5,
              "direction": "higher_is_worse", "threshold": 1.0}]
    assert stats.stratified_rank_test(cells)["cells_used"] == 0


def test_a_reported_fraction_can_never_exceed_one():
    """Numerator and denominator must be counted over the same population.

    Matched denials are counted over every denial in scope; the non-exempt count is a
    subset of that. Dividing one by the other produced a matched 'fraction' of 1.06 as
    soon as coverage improved enough to make it visible.
    """
    from likewise import scan as scan_mod

    class _S:
        raw: ClassVar[dict] = {
            "tripwires": {"matched_fraction": {"low": 0.02, "high": 0.60}}}

    summary = {"rate_post_suppression": 0.05, "margin_ratio_median": 3.0,
               "counts": {"denials_in_scope": 7223, "denials_non_exempt": 6620,
                          "denials_with_matched_comparator": 6986}}
    breaches = scan_mod.tripwires(summary, _S())
    vals = [b["value"] for b in breaches if b.get("value") is not None]
    assert all(v <= 1.0 for v in vals), breaches


def test_power_counts_never_promote_an_underpowered_cell():
    """The three counts are emitted together and must agree by construction. Counting
    dominating comparators from cells below the power floor as findings inflates the
    headline rate the tripwire reads -- a cell that cannot reach the threshold at any
    effect size is geometry, not evidence."""
    from likewise.scan import power_counts

    findings = ([{"cell_power": "adequate"}] * 7) + ([{"cell_power": "underpowered"}] * 3)
    adequate, counts = power_counts(findings)

    assert len(adequate) == 7
    assert counts["denials_with_dominating_comparator"] == 10
    assert counts["denials_with_finding"] == 7
    assert counts["findings_below_power_floor"] == 3
    assert (counts["denials_with_finding"] + counts["findings_below_power_floor"]
            == counts["denials_with_dominating_comparator"])

    # and the degenerate cases
    for f in ([], [{"cell_power": "underpowered"}]):
        adequate, counts = power_counts(f)
        assert counts["denials_with_finding"] == len(adequate)
        assert (counts["denials_with_finding"] + counts["findings_below_power_floor"]
                == counts["denials_with_dominating_comparator"])


def test_a_missing_value_is_not_a_resubmission_signature():
    """Two records that merely both LACK an income and a property value are not the same
    applicant resubmitting. Null used to compare equal to null here, so such pairs were
    routed out of the analysis and appeared in no denominator except that one -- the same
    null-equality the SQL lint bans unconditionally everywhere else."""
    from likewise import scan as scan_mod, specs

    spec = specs.load(version="1.3.0")
    blk = {"blk_lei": "X", "blk_county_code": "06073", "blk_loan_purpose": 1,
           "blk_occupancy_type": 1, "blk_lien_status": 1}

    both_null = dict(blk, a_property_value=None, a_income=None,
                     d_property_value=None, d_income=None)
    assert scan_mod._resub_signature(spec, both_null, "a") is None
    assert scan_mod._resub_signature(spec, both_null, "d") is None

    one_null = dict(blk, a_property_value=None, a_income=95000.0,
                    d_property_value=285000.0, d_income=95000.0)
    assert scan_mod._resub_signature(spec, one_null, "a") is None
    assert scan_mod._resub_signature(spec, one_null, "d") is not None

    # A genuine signature still matches itself, and still separates on the bin.
    same = dict(blk, a_property_value=285000.0, a_income=95000.0,
                d_property_value=285000.0, d_income=95000.0)
    assert scan_mod._resub_signature(spec, same, "a") == scan_mod._resub_signature(spec, same, "d")

    apart = dict(blk, a_property_value=285000.0, a_income=95000.0,
                 d_property_value=985000.0, d_income=95000.0)
    assert scan_mod._resub_signature(spec, apart, "a") != scan_mod._resub_signature(spec, apart, "d")


def test_resubmission_bins_are_half_open_at_the_boundary():
    """The signature bins property value and income. A value sitting exactly on a bin
    edge must land in exactly one bin, and two values one cent apart across an edge must
    not be read as the same applicant."""
    from likewise import scan as scan_mod, specs

    spec = specs.load(version="1.3.0")
    pw = spec.raw["suspected_resubmission"]["property_value_bin_width"]
    blk = {"blk_lei": "X", "blk_county_code": "06073", "blk_loan_purpose": 1,
           "blk_occupancy_type": 1, "blk_lien_status": 1}

    edge = dict(blk, a_property_value=float(pw), a_income=95000.0,
                d_property_value=float(pw) - 0.01, d_income=95000.0)
    assert scan_mod._resub_signature(spec, edge, "a") != scan_mod._resub_signature(spec, edge, "d")

    inside = dict(blk, a_property_value=float(pw), a_income=95000.0,
                  d_property_value=float(pw) + 0.01, d_income=95000.0)
    assert scan_mod._resub_signature(spec, inside, "a") == scan_mod._resub_signature(spec, inside, "d")


def test_the_scan_level_claim_is_actually_gated():
    """The pooled test is the only inferential claim the product makes. It was published
    and read by nothing -- a statistic no gate checks is documentation, not a control.

    Banded on one side by design: a positive z is the claim being raised and must be
    re-derived by a human first; the negative side is the stated reason holding up, and
    |z| scales with the square root of the cell count, so a lower bound could only be
    read off whatever scan happened to be in front of us."""
    from likewise import scan as scan_mod, specs

    spec = specs.load(version="1.4.0")
    assert "scan_level_z" in spec.raw["tripwires"], "the claim must have a gate"
    assert "low" not in spec.raw["tripwires"]["scan_level_z"], \
        "a lower bound on z would be calibrated to one scan"

    def fire(z):
        summary = {"rate_post_suppression": 0.05, "margin_ratio_median": 3.0,
                   "scan_level_test": {"z": z},
                   "counts": {"denials_in_scope": 1000,
                              "denials_with_matched_comparator": 300}}
        return [t for t in scan_mod.tripwires(summary, spec)
                if t["tripwire"] == "scan_level_z"]

    assert not fire(-34.6)          # the reason holding up: expected, not a surprise
    assert not fire(2.9)
    assert fire(3.1)[0]["breach"] == "above_upper"
    assert fire(12.0)
    # a missing statistic is reported, never treated as a pass
    assert fire(None)[0]["breach"] == "not_computable"


def test_incomparability_is_counted_in_its_own_right():
    """Roughly four in five debt-to-income denials cannot be ordered against any
    comparator at any sample size, because the file replaces the number with a band
    exactly where a lender denying for debt-to-income would be. Folding that into
    "no finding" reports a silence as an absence of a problem."""
    import json, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    p = root / "data" / "store" / "scans"
    summaries = list(p.glob("*/summary.json"))
    if not summaries:
        # data/store is generated, not tracked. On a fresh checkout there is nothing to
        # check, and this asserted instead of skipping -- so the suite passed here and
        # failed for anyone who cloned it. Same shape as every other data-dependent test.
        pytest.skip("no scan artifacts; run `make example` or `make fixture` then `make scan`")
    for f in summaries:
        c = json.load(open(f)).get("counts", {})
        if "denials_incomparable" not in c:
            continue                      # written before 1.4.0
        assert c["denials_incomparable"] == c["untestable_below_resolution"]
        assert isinstance(c["denials_incomparable"], int)
