"""Metamorphic properties over the full candidate set.
Millions of assertions, free, over real data -- not three hand-built fixtures."""
import glob, math, pytest, duckdb
from likewise import core, scan


@pytest.fixture(scope="module")
def pairs(spec):
    files = sorted(glob.glob("data/curated/**/*.parquet", recursive=True))
    if not files:
        pytest.skip("no fixture data; run tools/make_fixture.py")
    con = scan.configure(duckdb.connect())
    pop = spec.raw["population"]
    cur = con.execute(core.candidate_sql(spec),
                      {"files": files, "approved": pop["approved_actions"],
                       "denied": pop["denied_actions"]})
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall()[:6000]:
        row = dict(zip(cols, r, strict=False))
        nz = lambda v: None if v is None or (isinstance(v, float) and math.isnan(v)) else v
        a = {k[2:]: nz(v) for k, v in row.items() if k.startswith("a_")}
        d = {k[2:]: nz(v) for k, v in row.items() if k.startswith("d_")}
        for k in spec.exact_match:
            a.setdefault(k, row.get(f"blk_{k}")); d.setdefault(k, row.get(f"blk_{k}"))
        out.append((row, a, d))
    return out


def test_match_is_symmetric(spec, pairs):
    for _, a, d in pairs:
        assert core.match(a, d, spec).matched == core.match(d, a, spec).matched


def test_swapping_roles_inverts_every_resolved_margin(spec, pairs):
    """Swapping the two sides inverts the margin -- but only where the comparison is
    RESOLVED, and the exception is exact rather than approximate.

    A resolved margin is a signed dominance: `worse_by(a,d)` when the approved file is
    decisively worse, `-better_by(a,d)` when it is decisively better. Swapping exchanges
    those two quantities, so the sign flips exactly.

    An unresolved margin is not a dominance at all. It is reported as `worse_by`, a
    SLACK -- how far the pair is from being orderable -- and slack does not invert,
    because both directions are measured across the same pair of intervals:

        worse_by(a,d) + worse_by(d,a) = (a_lo - d_hi) + (d_lo - a_hi) = -(w_a + w_d)

    where w is an interval's width. This test asserts the inversion where it holds and
    the width identity where it does not, so neither is left to a tolerance.

    It previously asserted plain inversion on every pair and passed, because the suite
    ran a specification under which every reported half-width was zero. Under the
    specification in force, combined loan-to-value carries three published decimals and
    the identity is off by exactly 4 x 0.0005.
    """
    inverted = slack = 0
    for _, a, d in pairs:
        o1 = core.evaluate(a, d, [4], spec)
        o2 = core.evaluate(d, a, [4], spec)
        t1 = {t.dimension: t for t in o1.tested}
        t2 = {t.dimension: t for t in o2.tested}
        for k, x in t1.items():
            y = t2.get(k)
            if y is None or math.isnan(x.margin) or math.isnan(y.margin):
                continue
            if x.outcome != "below_resolution" and y.outcome != "below_resolution":
                assert x.margin == pytest.approx(-y.margin); inverted += 1
            elif x.outcome == "below_resolution" and y.outcome == "below_resolution":
                half = float(spec.budget.raw["dimensions"].get(k, {})
                             .get("reported_half_width", 0.0))
                assert x.margin + y.margin == pytest.approx(-4.0 * half, abs=1e-6)
                slack += 1
    assert inverted > 0, "no resolved pair exercised the inversion"
    assert slack > 100


def test_shifting_both_sides_preserves_match(spec, pairs):
    """Adding a constant to both property values must not change `matched`."""
    for _, a, d in pairs[:1500]:
        if a.get("property_value") is None or d.get("property_value") is None: continue
        before = core.match(a, d, spec).matched
        a2 = dict(a, property_value=a["property_value"] + 12345)
        d2 = dict(d, property_value=d["property_value"] + 12345)
        assert core.match(a2, d2, spec).matched == before


def test_null_in_tested_dimension_never_becomes_a_finding(spec, pairs):
    for _, a, d in pairs[:2000]:
        d2 = dict(d, combined_loan_to_value_ratio=None, property_value=None)
        o = core.evaluate(a, d2, [4], spec)
        assert o.outcome != "not_supported_by_public_record"


def test_monotonicity_is_true_by_construction(spec, pairs):
    """Retained as a regression guard, not as evidence: loosening a tolerance over a
    fixed candidate set cannot reduce the matched count."""
    import copy
    base = sum(core.match(a, d, spec).matched for _, a, d in pairs[:1500])
    loose = copy.deepcopy(spec.raw)
    for f in loose["control_features"]:
        loose["control_features"][f]["tolerance"] *= 2
    s2 = type(spec)(spec.version, loose, spec.digest, spec.budget, spec.reasons,
                    spec.reasons_digest, spec.snapshot, spec.snapshot_id)
    assert sum(core.match(a, d, s2).matched for _, a, d in pairs[:1500]) >= base
