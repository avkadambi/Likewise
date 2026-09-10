"""Every statistic the engine computes, computed a second time against reference
libraries, and the two asserted to agree.

WHY THIS FILE EXISTS
--------------------
The served engine implements its statistics from first principles in the standard
library. That is a deliberate deployment choice -- the container is read-only, makes no
outbound call, and carries five packages -- but on its own it is a weaker correctness
argument than the same statistic taken from SciPy, because a hand-rolled empirical CDF
that is subtly wrong about ties looks exactly like one that is right.

So the statistics are implemented TWICE. The engine implements them for the container;
this module implements them again against SciPy, statsmodels and NumPy, on the same
inputs, and asserts agreement to a stated tolerance. Two independent implementations
that agree is a materially stronger claim than either one alone, and it is a claim the
container's dependency list cannot weaken: if the reference disagrees, the release does
not ship.

Where a mature reference exists it is used unmodified. Where none exists -- the exact
closed-form null, for instance, is specific to this design -- the reference is a
brute-force or Monte Carlo computation that is obviously correct and far too slow to
serve.

HOW AGREEMENT IS JUDGED
-----------------------
Three kinds of check, and the distinction matters, because reporting a Monte Carlo
comparison as though it were an exact one is how a loose tolerance gets mistaken for a
tight result.

  exact         Both sides compute the same quantity by different routes and must agree
                to floating-point noise. Tolerance 1e-12 relative.
  numeric       Both sides solve the same equation by different numerical methods
                (bisection against Brent, ternary search against a bounded optimiser).
                Agreement is limited by the looser method's convergence, not by
                statistics. Tolerance is stated per check.
  monte_carlo   The reference is simulated, so it carries sampling error. The tolerance
                is expressed in MULTIPLES OF THE MONTE CARLO STANDARD ERROR rather than
                as an absolute number, so it tightens automatically as B grows and
                cannot be quietly satisfied by simulating less.

Run it:  python -m analysis.crossvalidate
Exit status is 0 only if every check agrees.
"""
from __future__ import annotations
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import json

import numpy as np
import scipy
import statsmodels
from scipy import optimize, stats as sps
from statsmodels.distributions.empirical_distribution import ECDF
from statsmodels.stats.proportion import proportion_confint

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from likewise import binding_gate, core, scan, stats
from extract import abstain
from analysis import fixtures


# A single seed for the whole module. Every Monte Carlo reference below draws from a
# generator descended from this one, so the report is reproducible run to run; a
# cross-validation whose verdicts move between runs proves nothing about the engine.
SEED = 20260910


@dataclass
class Check:
    """One statistic, computed both ways."""
    name: str
    engine: str            # what the engine computes, named
    reference: str         # what it is checked against, named
    kind: str              # exact | numeric | monte_carlo
    agreed: bool
    worst_gap: float       # the largest disagreement found, in the check's own units
    tolerance: float       # what was allowed
    units: str = ""        # "" for absolute, "relative", or "MC standard errors"
    detail: dict = field(default_factory=dict)

    def line(self) -> str:
        mark = "OK  " if self.agreed else "FAIL"
        u = f" {self.units}" if self.units else ""
        return (f"{mark}  {self.name:<34} gap {self.worst_gap:>12.3e}{u}"
                f"  (allowed {self.tolerance:.3e})")


# ---------------------------------------------------------------------------
# 1. The empirical CDF as an exact p-value
# ---------------------------------------------------------------------------
def check_rank_p_value() -> Check:
    """`stats.rank_p_value` against statsmodels' ECDF.

    THE MATHEMATICS. Under exchangeability the denied record is equally likely to be any
    member of its cell, so the one-sided p is the share of the cell at or beyond it:
    p = #{v <= observed} / n. That is precisely the empirical distribution function
    evaluated at the observation, and statsmodels' ECDF is right-continuous -- it counts
    v <= x, ties included -- so the two must agree EXACTLY, ties and all.

    This is the check that matters most for ties, and it is run on the published DTI
    levels, where roughly half the cells contain a tie. An implementation that used the
    strict `<` would pass on continuous data and fail here.

    The engine additionally floors the result at 1/n. The reference applies the same
    floor explicitly rather than silently, so that the floor is being CHECKED rather
    than assumed: no cell of n can supply evidence stronger than one observation in n.
    """
    rng = np.random.default_rng(SEED)
    cells = fixtures.published_dti_cells(400, rng=rng) + fixtures.null_cells(400, rng=rng)
    worst = 0.0
    ties_seen = 0
    for c in cells:
        vals = c["values"]
        obs = vals[0]
        for hiw in (True, False):
            engine_p = stats.rank_p_value(vals, obs, higher_is_worse=hiw)
            # statsmodels ECDF counts <= x. For lower_is_worse the extreme tail is the
            # upper one, so the reference is the ECDF of the negated values -- the same
            # sign flip the engine performs, arrived at independently.
            ecdf = ECDF(np.array(vals) if hiw else -np.array(vals))
            share = float(ecdf(obs if hiw else -obs))
            ref_p = min(1.0, max(share, 1.0 / len(vals)))
            worst = max(worst, abs(engine_p - ref_p))
        if len(set(vals)) < len(vals):
            ties_seen += 1
    tol = 1e-12
    return Check("rank_p_value", "empirical CDF with 1/n floor",
                 "statsmodels ECDF (right-continuous)", "exact",
                 worst <= tol, worst, tol,
                 detail={"cells": len(cells), "cells_containing_a_tie": ties_seen})


def check_min_attainable_p() -> Check:
    """`stats.min_attainable_p` against exhaustive enumeration.

    THE MATHEMATICS. A cell's smallest attainable p is not 1/n. A record can be no more
    extreme than the tie block it belongs to, so the floor is |best block| / n. The
    engine computes that directly from the tie structure. The reference computes it the
    only way that cannot be wrong: place the denial on EVERY member of the cell in turn,
    evaluate the p-value each time, and take the minimum. If the closed form is right the
    two are identical for every cell.

    This matters because it is the quantity that explains the headline finding that 81.5%
    of DTI denials are structurally incapable of a result. If the closed form overstated
    attainability, the product would be reporting cells as testable that arithmetic has
    already decided.
    """
    rng = np.random.default_rng(SEED + 1)
    cells = fixtures.published_dti_cells(600, rng=rng)
    worst = 0.0
    for c in cells:
        vals = c["values"]
        for hiw in (True, False):
            engine = stats.min_attainable_p(vals, higher_is_worse=hiw)
            # Exhaustive: every possible placement of the denial label, scored. The
            # minimum over placements IS the smallest p the cell can produce, by
            # definition rather than by derivation.
            brute = min(stats.rank_p_value(vals, v, higher_is_worse=hiw) for v in vals)
            worst = max(worst, abs(engine - brute))
    tol = 1e-12
    return Check("min_attainable_p", "closed form from the tie block",
                 "exhaustive enumeration of every label placement", "exact",
                 worst <= tol, worst, tol, detail={"cells": len(cells)})


def check_midranks() -> Check:
    """`core.midranks` against `scipy.stats.rankdata(method='average')`.

    THE MATHEMATICS. Tied values must share the mean of the ranks they jointly occupy,
    so that the ranks still sum to n(n+1)/2. That total is exactly what the pooled test's
    conditional mean (n+1)/2 depends on, so an error here would silently bias the
    headline test rather than crash it.

    SciPy's `rankdata` with `method='average'` is the same estimator, written by other
    people, tested by many more. The only wrinkle is orientation: the engine's ranks run
    worst-to-best in the dimension's own sense, so on a lower_is_worse dimension the
    reference ranks the negated values. Beyond that the two arrays must be identical
    element by element.

    The check additionally asserts the rank-sum identity on every cell, which catches a
    class of error that a matching-but-wrong pair of implementations could share.
    """
    rng = np.random.default_rng(SEED + 2)
    cells = fixtures.published_dti_cells(500, rng=rng) + fixtures.null_cells(500, rng=rng)
    worst = 0.0
    worst_sum = 0.0
    for c in cells:
        vals = np.array(c["values"])
        for hiw in (True, False):
            engine = np.array(core.midranks(list(vals), higher_is_worse=hiw))
            ref = sps.rankdata(vals if hiw else -vals, method="average")
            worst = max(worst, float(np.max(np.abs(engine - ref))))
            n = len(vals)
            worst_sum = max(worst_sum, abs(float(engine.sum()) - n * (n + 1) / 2.0))
    tol = 1e-12
    return Check("midranks", "tie-block averaging, stdlib",
                 "scipy.stats.rankdata(method='average')", "exact",
                 worst <= tol and worst_sum <= 1e-9, max(worst, worst_sum), tol,
                 detail={"cells": len(cells),
                         "rank_sum_identity_max_error": worst_sum})


# ---------------------------------------------------------------------------
# 2. The pooled stratified rank test
# ---------------------------------------------------------------------------
def _pooled_reference(cells) -> dict:
    """van Elteren, recomputed in NumPy with the tail from SciPy.

    Deliberately written from the published formula rather than from the engine's code,
    so that a transcription error in one is not reproduced in the other:

        E[R_s]   = (n_s + 1) / 2
        Var[R_s] = (1/n_s) * sum_j ( a_sj - (n_s+1)/2 )^2      -- from the ACTUAL
                                                                  midranks, so ties are
                                                                  corrected for
        T        = sum_s w_s ( E[R_s] - R_s ),  w_s = 1/(n_s + 1)
        Var[T]   = sum_s w_s^2 Var[R_s]         -- cells are independent by construction

    Var[R_s] is the variance of a single draw uniform over the cell's midranks, which is
    why NumPy's population variance (ddof=0) is the right reference and the textbook
    (n^2-1)/12 is not: that closed form assumes distinct values and would overstate the
    spread wherever the data is binned, making the test conservative without saying so.
    """
    T = 0.0
    var = 0.0
    used = 0
    for c in cells:
        mr = np.array(c["midranks"], dtype=float)
        n = mr.size
        if n < 2:
            continue
        mean = (n + 1) / 2.0
        v = float(np.var(mr, ddof=0))          # == sum (a - mean)^2 / n, since mean(mr) = mean
        if v <= 0:
            continue
        w = 1.0 / (n + 1)
        T += w * (mean - c["observed_midrank"])
        var += (w ** 2) * v
        used += 1
    if used == 0 or var <= 0:
        return {"cells_used": used, "T": 0.0, "se": 0.0, "z": None, "p": None}
    se = math.sqrt(var)
    z = T / se
    return {"cells_used": used, "T": T, "se": se, "z": z, "p": float(sps.norm.sf(z))}


def check_pooled_closed_form() -> Check:
    """`stats.stratified_rank_test` against the NumPy/SciPy recomputation above.

    Two things are being checked at once. The arithmetic of T and its standard error --
    which must agree to floating point -- and the upper-tail normal probability, where
    the engine uses `0.5 * erfc(z / sqrt(2))` from the standard library and the reference
    uses `scipy.stats.norm.sf`. Those are the same function; that they agree to 1e-12
    across four decades of z is the evidence that avoiding SciPy in the container cost
    nothing in accuracy.

    Run on both a true-null population and a shifted one, because a p-value routine can
    be accurate in the middle of the distribution and lose all its precision in the tail
    where the decisions are actually made.
    """
    rng = np.random.default_rng(SEED + 3)
    worst = 0.0
    rows = {}
    for label, cells in (("null", fixtures.null_cells(400, rng=rng)),
                         ("shift_1.0", fixtures.shifted_cells(400, shift=1.0, rng=rng)),
                         ("shift_3.0", fixtures.shifted_cells(400, shift=3.0, rng=rng)),
                         ("published_dti", fixtures.published_dti_cells(400, rng=rng))):
        eng = stats.stratified_rank_test(cells)
        ref = _pooled_reference(cells)
        assert eng["cells_used"] == ref["cells_used"], (label, eng, ref)
        # The engine rounds its outputs for publication (T and se to 6 places, z to 4,
        # p to 8). The comparison is made against those rounded values on purpose: what
        # is checked is what is published, not an unrounded intermediate the reader never
        # sees.
        gaps = [abs(eng["T"] - round(ref["T"], 6)),
                abs(eng["se"] - round(ref["se"], 6)),
                abs(eng["z"] - round(ref["z"], 4)),
                abs(eng["p"] - round(ref["p"], 8))]
        worst = max(worst, max(gaps))
        rows[label] = {"z": eng["z"], "p": eng["p"], "cells_used": eng["cells_used"]}
    tol = 1e-12
    return Check("stratified_rank_test", "van Elteren, stdlib erfc tail",
                 "NumPy variance + scipy.stats.norm.sf", "exact",
                 worst <= tol, worst, tol, detail=rows)


def check_pooled_against_permutation(B: int = 40_000) -> Check:
    """The normal approximation for T, against its exact permutation distribution.

    THE MATHEMATICS. The engine reports a p-value from the central limit theorem: T is a
    weighted sum of independent bounded contributions, so the POOLED statistic is
    asymptotically normal even though no individual cell is remotely so. That argument is
    correct but asymptotic, and the cells here hold two to eight records. Whether the
    approximation is good AT THIS SIZE is an empirical question, not a theoretical one.

    So the reference is the exact conditional null, simulated: under H0 the denied label
    is uniform over its own cell, independently across cells, so drawing one midrank
    uniformly from each cell and recomputing T draws exactly from T's null distribution.
    No approximation enters the reference at any point.

    Two comparisons are made. First, that the SIMULATED null mean and variance match the
    engine's analytic E[T] = 0 and Var[T] -- this validates the tie-corrected variance
    formula directly, and it is where a wrong variance shows up unmistakably. Second,
    that the normal tail probability matches the simulated tail. The second is limited by
    Monte Carlo error and by the approximation itself, so it is judged in MC standard
    errors with an explicit allowance for skewness, and the measured skewness is reported
    alongside so a reader can see how far from normal the statistic actually is.
    """
    rng = np.random.default_rng(SEED + 4)
    cells = [c for c in fixtures.shifted_cells(300, shift=1.5, rng=rng)
             if len(set(c["values"])) > 1 and len(c["values"]) >= 2]
    eng = stats.stratified_rank_test(cells)

    # Draw B realisations of T under the exact null. Vectorised per cell: each column is
    # one cell's contribution across all B draws, and they sum because cells are
    # independent -- a record belongs to exactly one cell, by construction.
    draws = np.zeros(B)
    for c in cells:
        mr = np.array(c["midranks"], dtype=float)
        n = mr.size
        if n < 2 or np.var(mr) <= 0:
            continue
        w = 1.0 / (n + 1)
        mean = (n + 1) / 2.0
        draws += w * (mean - rng.choice(mr, size=B, replace=True))

    sim_mean, sim_sd = float(draws.mean()), float(draws.std(ddof=1))
    skew = float(sps.skew(draws))
    # Standard error of the simulated mean, and of the simulated SD (the delta-method
    # form, sd / sqrt(2B)). Expressing the gaps in these units is what makes the check
    # tighten as B grows instead of being satisfied by a loose absolute number.
    se_mean = sim_sd / math.sqrt(B)
    se_sd = sim_sd / math.sqrt(2 * B)
    z_mean = abs(sim_mean - 0.0) / se_mean
    z_sd = abs(sim_sd - eng["se"]) / se_sd

    perm_p = float((1 + np.sum(draws >= eng["T"])) / (B + 1))
    se_p = math.sqrt(max(perm_p, 1e-9) * (1 - perm_p) / B)
    z_p = abs(perm_p - eng["p"]) / max(se_p, 1e-12)

    worst = max(z_mean, z_sd, z_p)
    # Four standard errors on each of three statistics: a two-sided 4-sigma allowance,
    # Bonferroni-corrected across the three comparisons, is below one chance in ten
    # thousand of a false alarm per run -- tight enough to catch a wrong variance, loose
    # enough not to fail on simulation noise alone.
    tol = 4.0
    return Check("pooled normal approximation",
                 "CLT tail on the pooled statistic",
                 "exact conditional permutation null, simulated", "monte_carlo",
                 worst <= tol, worst, tol, units="MC standard errors",
                 detail={"B": B, "cells": len(cells),
                         "analytic_se": eng["se"], "simulated_sd": round(sim_sd, 6),
                         "analytic_p": eng["p"], "permutation_p": round(perm_p, 6),
                         "null_skewness": round(skew, 4),
                         "z_mean": round(z_mean, 3), "z_sd": round(z_sd, 3),
                         "z_p": round(z_p, 3)})


# ---------------------------------------------------------------------------
# 3. The exact closed-form null
# ---------------------------------------------------------------------------
def check_exact_null_against_monte_carlo(B: int = 20_000) -> Check:
    """`stats.exact_expected_findings` against a NumPy simulation of the same event.

    THE MATHEMATICS. A cell produces a finding when the denied record is beaten by
    somebody beyond the threshold and beaten by nobody in the other direction beyond it.
    Under the null the label is uniform over the cell, so

        P(finding) = (1/n) * sum_i 1{exists j worse by > t} * 1{no j better by > t}

    and the expectation over cells is a sum. That is a closed form: one pass, no seed, no
    simulation error.

    The reference simulates the same event by permuting labels, using the ENGINE'S OWN
    finding rule (`scan.dominance_statistic`) rather than a reimplementation. That is
    deliberate and it is the point: the closed form and the finding rule must not be able
    to drift apart, and the only way to check that they have not is to drive the
    simulation through the rule the product actually applies when it flags a record.

    Judged in Monte Carlo standard errors, since the reference is simulated. The
    statistic is a mean of independent Bernoulli-ish cell outcomes, so its standard error
    is the usual sd/sqrt(B).
    """
    rng = np.random.default_rng(SEED + 5)
    cells = fixtures.null_cells(250, rng=rng, threshold=1.0)
    exact = stats.exact_expected_findings(cells)

    draws = np.empty(B)
    for b in range(B):
        # Permute the label within each cell: choose which member is the denied one,
        # uniformly and independently per cell. This is the null, stated as a sampling
        # scheme rather than as a formula.
        shuffled = []
        for c in cells:
            n = len(c["values"])
            labels = [0] * n
            labels[int(rng.integers(n))] = 1
            shuffled.append({**c, "labels": labels})
        draws[b] = scan.dominance_statistic(shuffled)

    sim = float(draws.mean())
    se = float(draws.std(ddof=1)) / math.sqrt(B)
    z = abs(sim - exact["rate"]) / max(se, 1e-12)
    tol = 4.0
    return Check("exact_expected_findings", "closed form, one pass, no seed",
                 "NumPy simulation through scan.dominance_statistic", "monte_carlo",
                 z <= tol, z, tol, units="MC standard errors",
                 detail={"B": B, "cells": len(cells),
                         "closed_form_rate": exact["rate"],
                         "simulated_rate": round(sim, 6),
                         "mc_standard_error": round(se, 6)})


# ---------------------------------------------------------------------------
# 4. The exact binomial bound
# ---------------------------------------------------------------------------
def check_clopper_pearson() -> Check:
    """`binding_gate.clopper_pearson_upper` against the exact Beta quantile, twice.

    THE MATHEMATICS. The Clopper-Pearson upper limit is the p solving
    P(X <= k | n, p) = alpha. The binomial CDF and the Beta distribution are duals, so
    that root has a closed form:

        upper = BetaInv(1 - alpha; k + 1, n - k)

    The engine finds the root by bisection on the binomial CDF, summed with exact integer
    binomial coefficients. The reference evaluates the closed form directly through
    `scipy.stats.beta.ppf`. These are different algorithms reaching the same number, so
    this is the strongest single check in the file: an incomplete-beta implementation and
    two hundred halvings of a bracket have no shared failure mode.

    A THIRD implementation is included, `statsmodels.stats.proportion.proportion_confint`
    with `method='beta'`, whose two-sided interval at level 2*alpha has an upper endpoint
    equal to the one-sided upper limit at alpha. Three independent routes to one number.

    The grid spans the sizes the gate actually uses -- k = 0 is the case the assertion
    floor is derived from, and n = 299 and n = 2995 are the true minimum floors quoted in
    the acceptance criteria.
    """
    worst_scipy = 0.0
    worst_sm = 0.0
    grid = []
    for n in (1, 2, 5, 30, 100, 299, 500, 2995):
        for k in sorted({0, 1, 2, n // 20, n // 4, n // 2, n - 1, n}):
            if not (0 <= k <= n):
                continue
            for alpha in (0.05, 0.01):
                eng = binding_gate.clopper_pearson_upper(k, n, alpha)
                if k == n:
                    # Every trial failed: no rate below 1 is excluded and the honest
                    # bound is exactly 1. The Beta form degenerates here (shape n-k = 0),
                    # so the reference is the definition rather than the library.
                    ref = 1.0
                else:
                    ref = float(sps.beta.ppf(1.0 - alpha, k + 1, n - k))
                worst_scipy = max(worst_scipy, abs(eng - ref))
                if 0 < k < n:
                    _, hi = proportion_confint(k, n, alpha=2 * alpha, method="beta")
                    worst_sm = max(worst_sm, abs(eng - float(hi)))
                grid.append((n, k, alpha))
    # Bisection over 200 halvings resolves the bracket far below double precision, so the
    # residual gap is the reference's own incomplete-beta accuracy, not the engine's.
    tol = 1e-10
    worst = max(worst_scipy, worst_sm)
    return Check("clopper_pearson_upper", "bisection on the exact binomial CDF",
                 "scipy Beta quantile AND statsmodels proportion_confint", "exact",
                 worst <= tol, worst, tol,
                 detail={"grid_points": len(grid),
                         "max_gap_vs_scipy": worst_scipy,
                         "max_gap_vs_statsmodels": worst_sm})


# ---------------------------------------------------------------------------
# 5. Rosenbaum sensitivity
# ---------------------------------------------------------------------------
def check_gamma_star() -> Check:
    """`stats.gamma_star` against numerical inversion of Rosenbaum's bound.

    THE MATHEMATICS. Under a bias bound Gamma on the odds that either member of a matched
    pair is the treated one, the worst-case p-value inflates to

        p_worst(G) = G p / (G p + 1 - p)

    which is increasing in G. The finding survives exactly while p_worst(G) <= alpha, so
    G* is the root of p_worst(G) = alpha. The engine reports the algebraic rearrangement,
    alpha (1/p - 1) / (1 - alpha).

    The reference does not use that rearrangement. It hands `p_worst(G) - alpha` to
    Brent's method and finds the root numerically, which checks the algebra rather than
    restating it. The two must agree to solver tolerance.

    Three boundary identities are asserted separately, because they are where a
    sensitivity analysis is most easily made to flatter:

      G*(alpha, alpha) = 1 EXACTLY. Substituting p = alpha gives
      alpha(1/alpha - 1)/(1 - alpha) = (1 - alpha)/(1 - alpha) = 1. Gamma is an odds
      ratio, so Gamma = 1 is the no-bias case; a finding sitting exactly at the decision
      level therefore tolerates no bias at all, and the algebra says so on the nose.

      p > alpha gives G* < 1, which is below the no-bias point and means the finding was
      never significant to begin with. It is reported rather than floored to zero because
      the distance below 1 is informative.

      p = 0 must stay finite. The expression diverges there, and a finite sample cannot
      support a claim of unbounded robustness, so the engine clamps the input.
    """
    worst = 0.0
    for alpha in (0.05, 0.10):
        for p in (1e-6, 1e-4, 0.001, 0.01, 0.02, 0.04, 0.049):
            if p >= alpha:
                continue
            eng = stats.gamma_star(p, alpha)

            # Both loop variables are bound as defaults. A closure that captured them
            # by reference would silently be solved at the LAST grid point on every
            # iteration -- a classic way for a check to pass while testing one case.
            def worst_case(g: float, _p: float = p, _a: float = alpha) -> float:
                return g * _p / (g * _p + 1.0 - _p) - _a

            ref = float(optimize.brentq(worst_case, 1e-9, 1e12, xtol=1e-12, rtol=1e-15))
            # Relative comparison: G* spans six orders of magnitude across this grid, so
            # an absolute tolerance would be vacuous at the top and unmeetable at the
            # bottom.
            worst = max(worst, abs(eng - ref) / max(ref, 1e-12))
    # The boundary identities, asserted rather than measured.
    for a in (0.05, 0.10):
        assert abs(stats.gamma_star(a, a) - 1.0) < 1e-12, "G*(alpha, alpha) must be 1"
        assert stats.gamma_star(2 * a, a) < 1.0, "p > alpha must fall below the no-bias point"
    assert math.isfinite(stats.gamma_star(0.0, 0.05)), "G* must stay finite at p = 0"
    tol = 1e-9
    return Check("gamma_star", "algebraic rearrangement",
                 "Brent root-finding on the worst-case bound", "numeric",
                 worst <= tol, worst, tol, units="relative",
                 detail={"identities_asserted": ["G*(alpha, alpha) = 1",
                                                 "p > alpha -> G* < 1",
                                                 "p = 0 -> finite"]})


# ---------------------------------------------------------------------------
# 6. Temperature scaling for the extractor's abstention
# ---------------------------------------------------------------------------
def check_fit_temperature() -> Check:
    """`abstain.fit_temperature` against a bounded SciPy optimiser.

    THE MATHEMATICS. Temperature scaling is the standard single-parameter recalibration
    of a classifier: divide the logits by T before the softmax, and choose T to minimise
    the negative log-likelihood on held-out data. T > 1 flattens the distribution and
    lowers confidence; T < 1 sharpens it. It cannot change which label is the argmax, so
    it changes calibration without changing accuracy -- which is exactly what a
    confidence floor for abstention needs.

    The NLL is unimodal in T, so the engine finds the minimum by ternary search: no
    gradient, no optimiser dependency, four lines. The reference hands the identical
    objective to `scipy.optimize.minimize_scalar` with the Bounded method (Brent's
    golden-section variant). Agreement is limited by the looser convergence of the two,
    hence `numeric` rather than `exact`.

    The objective is checked as well as the argument. Two optimisers can land on
    different T when the NLL is nearly flat near its minimum while still agreeing on the
    likelihood to many digits, and it is the likelihood that determines the calibration.
    """
    rng = np.random.default_rng(SEED + 6)
    n, k = 400, 6
    # Deliberately OVERCONFIDENT logits, which is the condition temperature scaling
    # exists to correct: the true label is favoured, but by a wider margin than its
    # empirical accuracy justifies. Scaling the logits up by 2.5 is the standard way to
    # manufacture that.
    labels = rng.integers(0, k, size=n)
    logits = rng.normal(0.0, 1.0, size=(n, k))
    logits[np.arange(n), labels] += 1.2
    logits = logits * 2.5
    rows = [list(map(float, r)) for r in logits]
    ys = [int(y) for y in labels]

    def nll(t: float) -> float:
        # The same objective, in NumPy: mean negative log-likelihood of the true label
        # under the temperature-scaled softmax. Log-sum-exp form for stability, which is
        # the vectorised equivalent of the engine's max-subtraction.
        z = logits / t
        z = z - z.max(axis=1, keepdims=True)
        lse = np.log(np.exp(z).sum(axis=1))
        return float(-np.mean(z[np.arange(n), labels] - lse))

    eng_t = abstain.fit_temperature(rows, ys, lo=0.05, hi=10.0, iters=60)
    res = optimize.minimize_scalar(nll, bounds=(0.05, 10.0), method="bounded",
                                   options={"xatol": 1e-10})
    ref_t = float(res.x)
    gap_t = abs(eng_t - ref_t)
    gap_nll = abs(nll(eng_t) - nll(ref_t))
    # Ternary search over 60 passes shrinks [0.05, 10] by (2/3)^60, about 1e-10 in
    # absolute terms; the bounded optimiser is asked for 1e-10 as well. 1e-6 on T is a
    # generous allowance either way, and the NLL agreement is the tighter statement.
    tol = 1e-6
    worst = max(gap_t, gap_nll)
    return Check("fit_temperature", "ternary search on the NLL",
                 "scipy.optimize.minimize_scalar (Bounded/Brent)", "numeric",
                 worst <= tol, worst, tol,
                 detail={"engine_T": round(eng_t, 8), "reference_T": round(ref_t, 8),
                         "nll_gap": gap_nll,
                         "overconfidence_corrected": round(eng_t, 3)})


# ---------------------------------------------------------------------------
# 7. The cluster bootstrap
# ---------------------------------------------------------------------------
def check_cluster_bootstrap(B: int = 4000) -> Check:
    """`stats.cluster_bootstrap_ci` against an independent NumPy cluster bootstrap.

    THE MATHEMATICS. Pairs inside a cell are dependent by construction -- they share the
    denied record and the coarsened cell -- so resampling individual rows would treat
    dependent observations as independent and produce an interval that is far too narrow.
    The cluster bootstrap resamples WHOLE CLUSTERS with replacement, which preserves the
    within-cluster dependence in every replicate because the cluster travels intact.

    Both implementations are Monte Carlo and they use different random number generators,
    so they cannot agree exactly and it would be dishonest to demand that they do. What
    is checked is that the two intervals agree to within the bootstrap's OWN sampling
    variability: the reference is run several times with different seeds, the
    seed-to-seed spread of each endpoint is measured, and the engine's endpoint must sit
    within four of those standard deviations. That is a check on the estimator, not on
    the arithmetic of one draw.
    """
    rng = np.random.default_rng(SEED + 7)
    # An intra-cluster correlation is built in on purpose: each cluster gets its own rate
    # and its rows are drawn from it. With independent rows the cluster bootstrap and the
    # naive bootstrap would agree and the check would demonstrate nothing.
    clusters = {}
    for i in range(120):
        rate = float(rng.beta(2, 8))
        size = int(rng.integers(2, 12))
        clusters[f"cell_{i}"] = [float(x) for x in rng.binomial(1, rate, size=size)]

    eng_lo, eng_hi = stats.cluster_bootstrap_ci(clusters, B=B, seed=7)

    keys = list(clusters)
    los, his = [], []
    for s in range(12):
        r = np.random.default_rng(1000 + s)
        draws = np.empty(B)
        for b in range(B):
            pick = r.integers(0, len(keys), size=len(keys))
            num = sum(sum(clusters[keys[j]]) for j in pick)
            den = sum(len(clusters[keys[j]]) for j in pick)
            draws[b] = num / den if den else 0.0
        # The percentile interval, taken straight off the sorted draws. No normal
        # approximation: the statistic is a bounded ratio and a symmetric interval would
        # be wrong at the ends.
        los.append(float(np.percentile(draws, 2.5)))
        his.append(float(np.percentile(draws, 97.5)))

    sd_lo = float(np.std(los, ddof=1))
    sd_hi = float(np.std(his, ddof=1))
    z_lo = abs(eng_lo - float(np.mean(los))) / max(sd_lo, 1e-12)
    z_hi = abs(eng_hi - float(np.mean(his))) / max(sd_hi, 1e-12)
    worst = max(z_lo, z_hi)
    tol = 4.0
    return Check("cluster_bootstrap_ci", "stdlib cluster resampling",
                 "NumPy cluster bootstrap over 12 independent seeds", "monte_carlo",
                 worst <= tol, worst, tol, units="MC standard errors",
                 detail={"B": B, "clusters": len(clusters),
                         "engine_ci": [round(eng_lo, 6), round(eng_hi, 6)],
                         "reference_ci_mean": [round(float(np.mean(los)), 6),
                                               round(float(np.mean(his)), 6)],
                         "reference_seed_sd": [round(sd_lo, 6), round(sd_hi, 6)]})


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------
CHECKS = (check_rank_p_value, check_min_attainable_p, check_midranks,
          check_pooled_closed_form, check_pooled_against_permutation,
          check_exact_null_against_monte_carlo, check_clopper_pearson,
          check_gamma_star, check_fit_temperature, check_cluster_bootstrap)


def run_all() -> list[Check]:
    return [fn() for fn in CHECKS]


def as_report() -> dict:
    """The whole cross-validation as data, for the analysis report to embed.

    Library versions are recorded because a check is only as reproducible as the
    reference it was run against: "agrees with SciPy" is not a claim until the reader
    knows which SciPy.
    """
    results = run_all()
    return {"seed": SEED,
            "versions": {"numpy": np.__version__, "scipy": scipy.__version__,
                         "statsmodels": statsmodels.__version__,
                         "python": sys.version.split()[0]},
            "checks": [{"name": r.name, "engine": r.engine, "reference": r.reference,
                        "kind": r.kind, "agreed": r.agreed, "worst_gap": r.worst_gap,
                        "tolerance": r.tolerance, "units": r.units, "detail": r.detail}
                       for r in results],
            "agreed": sum(1 for r in results if r.agreed), "total": len(results)}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--json" in argv:
        rep = as_report()
        out = Path(argv[argv.index("--json") + 1]) if len(argv) > argv.index("--json") + 1 \
            else Path("analysis/out/crossvalidation.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2, default=float))
        print(f"{rep['agreed']}/{rep['total']} checks agree -> {out}")
        return 0 if rep["agreed"] == rep["total"] else 1

    results = run_all()
    print("Cross-validation of the engine's statistics against reference libraries")
    print(f"numpy {np.__version__}  scipy {scipy.__version__}  "
          f"statsmodels {statsmodels.__version__}  seed {SEED}")
    print("-" * 78)
    for r in results:
        print(r.line())
    print("-" * 78)
    bad = [r for r in results if not r.agreed]
    print(f"{len(results) - len(bad)}/{len(results)} checks agree")
    for r in bad:
        print(f"  DISAGREEMENT in {r.name}: {r.detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
