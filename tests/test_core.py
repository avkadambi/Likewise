"""Matcher, dominance and the reason engine."""
import pytest
from likewise import core
from likewise.specs import Tolerance, Dimension


def test_tolerance_is_symmetric():
    """reference=min makes match(a,b) == match(b,a). An unspecified denominator is
    how matching became asymmetric; this is the property that can actually fail."""
    t = Tolerance("income", 0.05, "relative", "min", 2000, "x")
    for a, b in [(88000, 87000), (10000, 60000), (5000, 5200), (1e6, 9.9e5)]:
        assert t.within(a, b) == t.within(b, a)


def test_min_absolute_floor_binds_at_low_magnitude():
    t = Tolerance("income", 0.05, "relative", "min", 2000, "x")
    assert t.bound(10000, 10000) == 2000          # floor, not 500
    assert t.bound(100000, 100000) == 5000        # relative


def test_match_computes_all_deltas_no_early_return(spec_v1, base_pair):
    """Returning at the first failure made the attributed cause depend on spec key
    order and left deltas partial, so a delta-to-tolerance stratification could not
    be built from it.

    Driven from 1.0.0 deliberately. The property is about the LOOP, and the loop needs
    at least two control features to have anything to be early about; the specification
    in force has none, so under it this test would pass without executing the branch it
    exists to guard. Naming the version keeps the regression guard alive and keeps the
    reason visible.
    """
    a, d = base_pair
    d = dict(d, income=1_000_000.0, loan_amount=10.0)
    m = core.match(a, d, spec_v1)
    assert len(spec_v1.control) >= 2, "the guard is vacuous without a multi-key loop"
    assert not m.matched
    assert set(m.deltas) == set(spec_v1.control)  # every control delta present


def test_the_matcher_in_force_is_exact_match_only(spec):
    """The live configuration, stated rather than assumed.

    1.3.0 moved income and loan amount out of the control set into residual risk, which
    left `control_features` empty: the Python matcher now applies exact-match equality
    and nothing else, and `MatchResult.deltas` is empty on every pair. The coarse
    numeric filter still runs -- as the blocking bands, in SQL, before `match()` is
    reached -- so the pipeline is unaffected. What is gone is the delta-to-tolerance
    stratification the docstring above describes; it cannot be built from a matcher that
    computes no deltas. This test exists so that is a recorded fact rather than a
    surprise to whoever next looks for those numbers.
    """
    assert dict(spec.control) == {}
    assert set(spec.raw["blocking"]["band"]) == {"loan_amount", "income"}


def test_null_in_exact_field_is_incomplete_not_a_match(spec, base_pair):
    a, d = base_pair
    a = dict(a); a["county_code"] = None; d = dict(d); d["county_code"] = None
    for f in spec.exact_match:
        a.setdefault(f, 1); d.setdefault(f, 1)
    m = core.match(a, d, spec)
    assert m.incomplete and not m.matched        # NULL == NULL must never match


def test_margin_polarity_per_direction():
    hw = Dimension("cltv", "higher_is_worse")
    hb = Dimension("property_value", "higher_is_better")
    # denied no worse => negative margin, in BOTH directions
    assert hw.margin(approved=95.0, denied=90.0) < 0
    assert hb.margin(approved=200000, denied=300000) < 0
    assert hw.margin(approved=90.0, denied=95.0) > 0
    assert hb.margin(approved=300000, denied=200000) > 0


def test_below_resolution_does_not_disqualify_the_denial(spec, base_pair):
    """The v0.5 defect: returning untestable on the FIRST below-resolution dimension
    made every code-4 denial untestable, because matching already forces the two
    property values inside tolerance on a rounded field."""
    a, d = base_pair
    a = dict(a, combined_loan_to_value_ratio=105.0)   # decisive on CLTV
    d = dict(d, combined_loan_to_value_ratio=94.6)
    a["property_value"] = d["property_value"] = 285000.0   # tied -> below_resolution
    o = core.evaluate(a, d, [4], spec)
    outs = {t.dimension: t.outcome for t in o.tested}
    assert outs["property_value"] == "below_resolution"
    assert outs["combined_loan_to_value_ratio"] == "not_supported"
    assert o.outcome == "not_supported_by_public_record"


def test_all_below_resolution_is_untestable_not_a_finding(spec, base_pair):
    """A conjunction over an empty set is true; the explicit guard is why this does
    not silently become 'not supported'."""
    a, d = base_pair
    a = dict(a); d = dict(d, combined_loan_to_value_ratio=a["combined_loan_to_value_ratio"])
    o = core.evaluate(a, d, [4], spec)
    assert o.outcome == "untestable" and o.cause == "below_resolution"
    assert o.tested        # per-dimension evidence survives an untestable outcome


def test_untestable_code_makes_the_denial_untestable(spec, base_pair):
    a, d = base_pair
    a = dict(a, combined_loan_to_value_ratio=110.0)
    o = core.evaluate(a, d, [4, 3], spec)          # 3 = credit history, untestable
    assert o.outcome == "untestable" and o.cause == "untestable_code_present"


def test_residual_risk_blocks_a_finding(spec, base_pair):
    """Clause 4: a collateral finding where the comparator is materially stronger on
    capacity is not a finding."""
    a, d = base_pair
    a = dict(a, combined_loan_to_value_ratio=110.0, debt_to_income_ratio=38.0)
    d = dict(d, debt_to_income_ratio=48.0)
    o = core.evaluate(a, d, [4], spec)
    assert o.outcome == "supported" and o.residual_block == "debt_to_income_ratio"


def test_midranks_not_arbitrary_tiebreak():
    assert core.midranks([10, 10, 20, 5]) == [2.5, 2.5, 4.0, 1.0]
    assert core.midranks([7, 7, 7, 7]) == [2.5] * 4


@pytest.mark.parametrize("n,expected", [(2, "underpowered"), (9, "underpowered"),
                                        (10, "adequate"), (25, "adequate")])
def test_cell_power_floor_at_ten(n, expected):
    """A cell of size 9 cannot reach q=0.10 however strong the effect."""
    assert core.cell_power(list(range(n)), 0.10)[0] == expected


def test_cell_power_reads_ties_not_just_size():
    """Size alone is not power. A large cell whose best value is shared by half its
    members cannot reach the threshold either, and the old size-only rule called it
    adequate."""
    assert core.cell_power(list(range(20)), 0.10)[0] == "adequate"
    assert core.cell_power([0] * 10 + list(range(1, 11)), 0.10)[0] == "underpowered"


def test_boundary_cover_is_lossless():
    """Decile splitting loses every pair straddling a cut. Stepping by the local band
    bound is lossless everywhere: no in-band pair spans two buckets."""
    t = Tolerance("loan_amount", 0.10, "relative", "min", 20000, "x")
    bs = core.boundary_sequence(t, 2_000_000)
    import random
    rng = random.Random(5)
    for _ in range(4000):
        a = rng.uniform(1000, 1_900_000)
        b = a + rng.uniform(-1, 1) * t.bound(a, a)
        if b <= 0: continue
        if t.within(a, b):
            assert abs(core.bucket_of(bs, a) - core.bucket_of(bs, b)) <= 1


def test_resolution_boundary_is_inclusive(spec, base_pair):
    """M03. A margin exactly AT the decisive threshold is below_resolution, not a
    verdict. `<` instead of `<=` turns every exactly-at-threshold pair into evidence."""
    a, d = base_pair
    thr = spec.budget.decisive_threshold("property_value")
    a = dict(a, combined_loan_to_value_ratio=110.0,           # decisive on CLTV
             property_value=d["property_value"] + thr)        # exactly at threshold
    o = core.evaluate(a, d, [4], spec)
    outs = {t.dimension: t.outcome for t in o.tested}
    assert outs["property_value"] == "below_resolution"
    assert o.outcome == "not_supported_by_public_record"


def test_clause2_is_universal_not_existential(spec, base_pair):
    """M04. One tested dimension strictly favouring the approved comparator defeats
    the finding, even when another dimension supports it. Weakening `all` to `any`
    turns a mixed pair into a finding."""
    a, d = base_pair
    a = dict(a, combined_loan_to_value_ratio=110.0,   # approved worse on collateral
             property_value=400000.0)                 # but materially better on value
    o = core.evaluate(a, d, [4], spec)
    outs = {t.dimension: t.outcome for t in o.tested}
    assert outs["combined_loan_to_value_ratio"] == "not_supported"
    assert outs["property_value"] == "supported"
    assert o.outcome == "supported"          # clause 2 fails; not a finding


def test_interval_compare_boundary_is_not_a_verdict():
    """A margin exactly AT the decisive threshold is below_resolution, not evidence.
    Interval comparison already consumes the reported half-width on both sides, so the
    boundary case has to be constructed on the intervals themselves rather than on raw
    values -- which is why an earlier test aimed at this line never reached it.

    Values are chosen to be exact in binary so the boundary is the boundary and not a
    rounding artefact."""
    thr = 7.0
    # approved lower bound sits exactly `thr` above the denied upper bound
    worse, outcome = core.interval_compare((97.0, 97.0), (90.0, 90.0), True, thr)
    assert outcome == "below_resolution"
    assert worse == 7.0

    # one step beyond, and it is a verdict
    _, outcome = core.interval_compare((97.5, 97.5), (90.0, 90.0), True, thr)
    assert outcome == "not_supported"

    # symmetric on the other side: exactly at threshold says nothing, beyond it does
    _, outcome = core.interval_compare((90.0, 90.0), (97.0, 97.0), True, thr)
    assert outcome == "below_resolution"
    _, outcome = core.interval_compare((90.0, 90.0), (97.5, 97.5), True, thr)
    assert outcome == "supported"

    # and with the polarity declared the other way round
    _, outcome = core.interval_compare((90.0, 90.0), (97.0, 97.0), False, thr)
    assert outcome == "below_resolution"
    _, outcome = core.interval_compare((90.0, 90.0), (97.5, 97.5), False, thr)
    assert outcome == "not_supported"
