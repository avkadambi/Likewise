"""Generative tests over randomly drawn inputs.

Deliberately not Hypothesis. These check algebraic properties that must hold for every
input, and the properties are simple enough that a seeded loop states them as clearly as
a strategy would while adding no dependency. The seed is fixed so a failure is
reproducible; the counterexample is printed rather than shrunk.

Each property below is one the codebase has broken at least once.
"""
from __future__ import annotations
import random

import pytest

from likewise import core, stats

SEED = 20260909
N = 400


def _rng():
    return random.Random(SEED)


def test_tolerance_is_symmetric_for_every_pair():
    """match(a, b) must equal match(b, a). An asymmetric reference side made the
    matcher depend on which record happened to be the denial."""
    from likewise.specs import Tolerance

    rng = _rng()
    for _ in range(N):
        tol = Tolerance(field_name="income", tolerance=rng.choice([0.05, 0.10, 0.22]),
                        unit="relative", reference="min",
                        min_absolute=rng.choice([0.0, 1000.0, 20000.0]),
                        rationale="test", direction="higher_is_worse")
        a = rng.uniform(1.0, 1_000_000.0)
        b = rng.uniform(1.0, 1_000_000.0)
        assert tol.within(a, b) == tol.within(b, a), (a, b, tol.tolerance)
        # and the bound itself must not depend on argument order
        assert tol.bound(a, b) == pytest.approx(tol.bound(b, a)), (a, b)


def test_interval_dominance_is_antisymmetric_and_never_both_ways():
    """No pair may be simultaneously not_supported and supported. Swapping the two
    records must invert the verdict exactly, never produce agreement."""
    rng = _rng()
    for _ in range(N):
        thr = rng.choice([0.5, 1.0, 7.1, 10.0])
        a_lo = rng.uniform(0.0, 100.0)
        a_hi = a_lo + rng.choice([0.0, 0.5, 5.0])
        d_lo = rng.uniform(0.0, 100.0)
        d_hi = d_lo + rng.choice([0.0, 0.5, 5.0])

        _, fwd = core.interval_compare((a_lo, a_hi), (d_lo, d_hi), True, thr)
        _, rev = core.interval_compare((d_lo, d_hi), (a_lo, a_hi), True, thr)

        assert not (fwd == "not_supported" and rev == "not_supported")
        assert not (fwd == "supported" and rev == "supported")
        if fwd == "not_supported":
            assert rev == "supported", (a_lo, a_hi, d_lo, d_hi, thr)
        if fwd == "below_resolution":
            assert rev == "below_resolution", (a_lo, a_hi, d_lo, d_hi, thr)


def test_overlapping_intervals_are_never_decisive():
    """If the published intervals overlap at all, the order is not identified. This is
    the whole reason band comparison replaced numeric comparison."""
    rng = _rng()
    for _ in range(N):
        thr = rng.choice([0.0, 1.0, 7.1])
        lo = rng.uniform(0.0, 100.0)
        width = rng.uniform(0.1, 20.0)
        # construct a guaranteed overlap
        a = (lo, lo + width)
        d = (lo + width / 2, lo + width * 1.5)
        _, outcome = core.interval_compare(a, d, True, thr)
        assert outcome == "below_resolution", (a, d, thr)


def test_polarity_inverts_with_the_declared_direction():
    """higher_is_worse and higher_is_better must be exact mirrors of each other."""
    rng = _rng()
    for _ in range(N):
        thr = rng.choice([0.5, 1.0, 7.1])
        a = (rng.uniform(0, 100),) * 2
        d = (rng.uniform(0, 100),) * 2
        _, hiw = core.interval_compare(a, d, True, thr)
        _, hib = core.interval_compare(a, d, False, thr)
        flip = {"not_supported": "supported", "supported": "not_supported",
                "below_resolution": "below_resolution"}
        assert hib == flip[hiw], (a, d, thr, hiw, hib)


@pytest.mark.parametrize("higher_is_worse", [True, False])
def test_rank_p_value_is_bounded_and_monotone(higher_is_worse):
    """p lies in [1/n, 1], and moving the observation toward the worse end can only
    lower it. The floor is what keeps Gamma* finite."""
    rng = _rng()
    for _ in range(N):
        n = rng.randint(1, 25)
        vals = [round(rng.uniform(0, 50), rng.choice([0, 0, 1])) for _ in range(n)]
        obs = rng.choice(vals)
        p = stats.rank_p_value(vals, obs, higher_is_worse=higher_is_worse)
        assert 1.0 / n - 1e-12 <= p <= 1.0, (vals, obs, p)

        extreme = min(vals) if higher_is_worse else max(vals)
        assert stats.rank_p_value(vals, extreme, higher_is_worse=higher_is_worse) <= p + 1e-12


def test_min_attainable_p_bounds_every_realised_p():
    """No observation in a cell can produce a p below the cell's own tie-structure
    floor. Reporting one would be claiming resolution the coarsened data does not have."""
    rng = _rng()
    for _ in range(N):
        n = rng.randint(2, 20)
        vals = [float(rng.randint(0, 4)) for _ in range(n)]     # heavy ties on purpose
        floor = stats.min_attainable_p(vals, higher_is_worse=True)
        for obs in vals:
            assert stats.rank_p_value(vals, obs, higher_is_worse=True) >= floor - 1e-12


def test_gamma_star_is_monotone_decreasing_in_p():
    """A weaker result must never look more robust to unmeasured bias."""
    rng = _rng()
    for _ in range(N):
        alpha = rng.choice([0.05, 0.10])
        p1 = rng.uniform(1e-4, 0.99)
        p2 = rng.uniform(p1, 0.999)
        assert stats.gamma_star(p1, alpha) >= stats.gamma_star(p2, alpha) - 1e-9
        assert stats.gamma_star(p2, alpha) >= 0.0
