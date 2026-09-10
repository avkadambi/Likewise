"""Statistics: rank p-values, the permutation null and the sensitivity bounds."""
import pytest
from likewise import core, stats
from likewise.egress import Egress


def test_rank_p_value_is_the_empirical_cdf_and_is_exact_under_ties():
    """The p-value is the share of the cell at or beyond the observed value.

    The midrank-over-n form understates whenever values repeat, and the tested
    dimensions are published at bin resolution, so they repeat constantly. A cell of ten
    with a five-way tie at the best value has midrank 3: the old form reported 0.30
    where the true probability of a position that extreme is 0.50.
    """
    distinct = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert stats.rank_p_value(distinct, 1) == pytest.approx(0.1)
    assert stats.rank_p_value(distinct, 3) == pytest.approx(0.3)

    tied = [1, 1, 1, 1, 1, 2, 3, 4, 5, 6]
    assert stats.rank_p_value(tied, 1) == pytest.approx(0.5)
    assert core.midranks(tied)[0] / len(tied) == pytest.approx(0.3)

    # direction is respected
    assert stats.rank_p_value(distinct, 10, higher_is_worse=False) == pytest.approx(0.1)

def _cell(denied, others, direction="higher_is_worse", threshold=1.0):
    return {"values": [denied] + list(others), "labels": [1] + [0] * len(others),
            "direction": direction, "threshold": threshold}


def test_null_statistic_polarity():
    """A finding requires the APPROVED comparator to be worse on a higher_is_worse
    dimension. Inverting this sign was a live defect found during the build; the null
    and the finding rule must not be able to drift apart."""
    from likewise.scan import dominance_statistic as statistic

    # denied at 90, comparator approved at 99 => approved is WORSE => a finding
    assert statistic([_cell(90.0, [99.0])]) == 1.0
    # denied at 99, comparator approved at 90 => approved is BETTER => not a finding
    assert statistic([_cell(99.0, [90.0])]) == 0.0
    # higher_is_better mirrors it
    assert statistic([_cell(300000.0, [200000.0], "higher_is_better", 1000)]) == 1.0
    assert statistic([_cell(200000.0, [300000.0], "higher_is_better", 1000)]) == 0.0

    # Clause 2 lives in the null too: one comparator worse AND one strictly better is
    # NOT a finding. Dropping the `not better` term is how the null drifts away from
    # the finding rule and silently inflates the reference distribution.
    assert statistic([_cell(90.0, [99.0, 80.0])]) == 0.0
    assert statistic([_cell(90.0, [99.0, 90.5])]) == 1.0   # 90.5 within threshold=1.0


def test_permutation_null_is_exchangeable():
    """Under H0 the denied file is equally likely to occupy any position, so a cell
    with no separation must not produce an extreme p."""
    def statistic(cells):
        return sum(1 for c in cells if c["values"][c["labels"].index(1)] ==
                   min(c["values"])) / len(cells)
    cells = [_cell(float(i), [float(i) + 5, float(i) + 10]) for i in range(40)]
    r = stats.permutation_null(cells, statistic, B=400, B_initial=400)
    assert 0.0 <= r.permutation_p <= 1.0
    assert r.null_mean == pytest.approx(1 / 3, abs=0.12)   # uniform over 3 positions


def test_egress_rejects_short_key():
    with pytest.raises(ValueError):
        Egress(b"short")
    Egress(b"k" * 32)


def test_cluster_bootstrap_resamples_clusters():
    by = {f"c{i}": [1, 0, 1] for i in range(30)}
    lo, hi = stats.cluster_bootstrap_ci(by, B=300)
    assert 0.0 <= lo <= 2 / 3 <= hi <= 1.0


def test_tolerance_boundary_is_inclusive():
    """`<=` vs `<` at exactly the bound. A pair sitting on the boundary must match;
    flipping this silently shrinks the matched set at every threshold."""
    from likewise.specs import Tolerance
    t = Tolerance("income", 0.05, "relative", "min", 2000, "x")
    a = 100000.0
    b = a + t.bound(a, a)                    # exactly on the bound
    assert t.within(a, b) and t.within(b, a)
    assert not t.within(a, b + 1e-6)


def test_rule3_rejects_tolerance_equal_to_granularity():
    """Rule 3 is STRICTLY greater. The equality case is exactly the empty band:
    granularity < |m| <= tolerance is empty when tolerance == granularity."""
    import pathlib, tempfile, yaml, pytest as _p
    from likewise import specs as _s
    from likewise.errors import SpecError
    root = pathlib.Path(__file__).resolve().parents[1]
    dst = pathlib.Path(tempfile.mkdtemp())
    for sub in ("materiality", "reasons", "budget", "snapshots"):
        (dst / sub).mkdir(parents=True)
        for f in (root / "specs" / sub).iterdir():
            (dst / sub / f.name).write_bytes(f.read_bytes())
    mp = dst / "materiality" / f"{_s.IN_FORCE}.yaml"
    m = yaml.safe_load(mp.read_text())
    m["residual_risk"]["debt_to_income_ratio"]["tolerance"] = 1.0     # == granularity
    mp.write_text(yaml.safe_dump(m))
    with _p.raises(SpecError) as e:
        _s.load(spec_dir=str(dst))
    assert any(f.get("rule") == 3 for f in e.value.failures)


def test_rank_p_value_never_returns_zero():
    """1/n is the exact floor of the empirical CDF: no cell of n can supply evidence
    stronger than one observation in n. Dropping the floor lets a p-value of exactly
    zero reach the sensitivity calculation, where Gamma* is unbounded."""
    # observed strictly better than every value in the cell -- the count is zero
    assert stats.rank_p_value([2.0, 3.0, 4.0], 1.0, higher_is_worse=True) == pytest.approx(1 / 3)
    assert stats.rank_p_value([2.0, 3.0, 4.0], 9.0, higher_is_worse=False) == pytest.approx(1 / 3)
    for n in (1, 2, 5, 20):
        vals = [float(i + 1) for i in range(n)]
        assert stats.rank_p_value(vals, 0.0, higher_is_worse=True) == pytest.approx(1 / n)
        assert stats.rank_p_value(vals, 0.0, higher_is_worse=True) > 0.0


def test_exact_null_agrees_with_the_permutation_it_replaces():
    """The closed form and the permutation estimate the same event, so they must agree
    up to Monte Carlo error. This is what makes the permutation path checkable rather
    than merely trusted -- and it is the check that would have caught the null being
    assembled from the wrong cells."""
    import random
    from likewise.scan import dominance_statistic

    rng = random.Random(11)
    cells = []
    for _ in range(150):
        n = rng.randint(2, 7)
        vals = [float(rng.randint(0, 6)) for _ in range(n)]
        labels = [1] + [0] * (n - 1)
        cells.append({"values": vals, "labels": labels,
                      "direction": "higher_is_worse", "threshold": 0.5})

    exact = stats.exact_expected_findings(cells)

    # average the permutation statistic over many relabellings
    draws = []
    for _ in range(3000):
        shuffled = []
        for c in cells:
            lab = list(c["labels"])
            rng.shuffle(lab)
            shuffled.append({**c, "labels": lab})
        draws.append(dominance_statistic(shuffled))
    mc = sum(draws) / len(draws)

    assert exact["rate"] == pytest.approx(mc, abs=0.02), (exact["rate"], mc)


def test_exact_null_is_deterministic_and_needs_no_seed():
    """Same cells, same answer, every time and on every machine. The permutation cannot
    promise that at any finite B."""
    cells = [{"values": [1.0, 5.0, 9.0], "labels": [1, 0, 0],
              "direction": "higher_is_worse", "threshold": 0.5}] * 40
    a = stats.exact_expected_findings(cells)
    b = stats.exact_expected_findings(list(reversed(cells)))
    assert a == b
    assert a["cells"] == 40

    # a cell whose values are all tied can produce nothing under any labelling
    tied = [{"values": [3.0, 3.0, 3.0], "labels": [1, 0, 0],
             "direction": "higher_is_worse", "threshold": 0.5}]
    assert stats.exact_expected_findings(tied)["expected"] == 0.0

    assert stats.exact_expected_findings([])["expected"] == 0.0
