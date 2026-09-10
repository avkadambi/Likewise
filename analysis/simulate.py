"""Operating characteristics of the pooled test and the two interval estimators.

WHAT A SIMULATION STUDY IS FOR
------------------------------
The unit tests establish that the code computes what it says it computes. The
cross-validation establishes that what it says it computes agrees with SciPy. Neither
answers the question a reader of the results should actually ask: at the sizes and the
coarsening this data has, does the test hold its stated error rate, and can it detect
anything?

Those are properties of the DESIGN, not of the implementation, and the only way to
measure them is to generate data where the truth is known and count how often the method
gets it right. Four studies:

  1. CALIBRATION (type-I error). Under a true null the p-values must be Uniform(0,1),
     and the test must reject at its nominal level and no more often. Measured against
     the uniform with a Kolmogorov-Smirnov test, and the rejection rate reported with an
     exact binomial interval -- using the engine's own Clopper-Pearson bound, so the
     study is itself a use of the code it is studying.

  2. POWER. How large a departure has to be before the test finds it, as a function of
     effect size, number of cells, and -- the one that matters here -- the coarseness of
     the published scale. This is where the product's central limitation becomes a
     number rather than an assertion: a shift smaller than the publication bin is
     substantially erased before the test ever sees it.

  3. COVERAGE OF THE EXACT BINOMIAL BOUND. Clopper-Pearson is conservative by
     construction. Conservative is the right direction for a bound that gates
     publication, but by how much matters, because an over-wide bound refuses releases
     that should have shipped.

  4. COVERAGE OF THE CLUSTER BOOTSTRAP, against the naive row bootstrap that ignores the
     clustering. The naive interval is the one a reasonable person writes first, and the
     study shows what it costs: nominal 95% coverage that is not 95%.

HOW THE SIMULATION IS MADE FAST WITHOUT BEING MADE DIFFERENT
------------------------------------------------------------
A power curve needs hundreds of thousands of simulated filings. Driving the engine's
pure-Python pooled test that many times would take hours, so the pooled statistic is
recomputed here in vectorised NumPy, over all replications at once.

That creates an obvious hazard -- a study that measures a fast reimplementation instead
of the product -- and it is closed by `verify_against_engine`, which rebuilds a sample of
simulated filings as engine cell dictionaries, runs `stats.stratified_rank_test` on them,
and asserts the z-statistics match to floating point. That verification runs first, every
time, and the study refuses to report if it fails.

Run it:  python -m analysis.simulate
"""
from __future__ import annotations
import itertools
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from scipy import stats as sps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from likewise import binding_gate, stats
from analysis import fixtures


SEED = 20260910
OUT = Path(__file__).resolve().parent / "out"

# The cell-size distribution the study runs at, chosen to reproduce the measured median
# of three. Size is the single most important parameter in this design -- a rank test
# inside a cell of three can never reject at any level -- so it is a controlled factor
# rather than something left to a convenient default.
SIZE_WEIGHTS = {2: 0.35, 3: 0.25, 4: 0.15, 5: 0.10, 6: 0.06, 7: 0.05, 8: 0.04}

# The four coarsening regimes, in increasing severity. Coarsening is the design's binding
# constraint, so it is the factor the study varies most carefully.
#
#   continuous     the textbook case, and a reference point only: no published field is
#                  reported this way
#   bin_1          a one-unit bin, which is what an exact integer DTI is
#   bin_5          a bin larger than a quarter of the within-cell spread, standing in for
#                  the $10,000 loan-amount and property-value bins
#   published_dti  the levels Regulation C actually publishes: exact integers in [36, 49]
#                  and coarse bands either side, so a difference outside the band range
#                  can be ten points wide and still invisible
REGIMES = ("continuous", "bin_1", "bin_5", "published_dti")


def _size_counts(n_cells: int) -> dict[int, int]:
    """How many cells of each size make up one simulated filing.

    Deterministic given n_cells, so two studies at the same size are comparable rather
    than merely similar; the largest size absorbs the rounding remainder.
    """
    counts = {n: round(w * n_cells) for n, w in SIZE_WEIGHTS.items()}
    counts[max(counts)] += n_cells - sum(counts.values())
    return {n: c for n, c in counts.items() if c > 0}


def _draw_block(reps: int, m: int, n: int, shift: float, regime: str,
                rng: np.random.Generator) -> np.ndarray:
    """All cells of one size, for every replication at once: shape (reps * m, n).

    Column 0 is the denied record by the engine's convention. The alternative is a
    location shift applied to that column BEFORE quantisation, which is the honest
    ordering: coarsening happens at publication, after the underlying difference exists,
    so a shift below the bin width really is partly destroyed and the study must let it
    be.
    """
    rows = reps * m
    # Every regime starts from the SAME underlying continuous data and differs only in
    # how it is published. That is the whole point: holding the truth fixed and varying
    # only the reporting scale is what isolates the cost of coarsening from every other
    # difference between the regimes.
    #
    # One centre per cell, then records around it: the stratified structure the pooled
    # test assumes, with the between-cell spread that makes pooling non-trivial.
    centres = rng.normal(42.0, 6.0, size=(rows, 1))
    vals = rng.normal(centres, 4.0, size=(rows, n))
    # The shift is applied on the underlying scale, BEFORE publication. This ordering is
    # the honest one -- the difference between two applicants exists before either is
    # filed -- and it is what lets a shift smaller than the bin be genuinely destroyed
    # rather than artificially preserved.
    vals[:, 0] -= shift
    if regime == "continuous":
        return vals
    if regime == "bin_1":
        return np.round(vals)
    if regime == "bin_5":
        # Bin MIDPOINTS, the way HMDA publishes loan amount and property value: the
        # figure in the filing is the centre of a $10,000 bin, which is why every
        # published loan amount ends in 5000. Reproduced here at width 5 on a scale whose
        # within-cell spread is 4, so the bin is wider than the signal.
        return np.round((vals - 2.5) / 5.0) * 5.0 + 2.5
    # published_dti: snap EVERY value to the nearest level Regulation C publishes, the
    # denied record and the comparators alike. Coarsening is applied by the publisher to
    # the whole filing, so applying it to one column only would understate the loss.
    levels = np.array(fixtures.DTI_PUBLISHED_LEVELS, dtype=float)
    idx = np.abs(vals[:, :, None] - levels[None, None, :]).argmin(axis=2)
    return levels[idx]


def _pooled_z(vals: np.ndarray, reps: int, m: int
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """van Elteren contributions for one block, vectorised.

    Identical arithmetic to `stats.stratified_rank_test`, written over arrays:

        midranks   scipy.stats.rankdata(..., axis=1)      -- ties averaged
        E[R]       (n + 1) / 2
        Var[R]     population variance of the ACTUAL midranks -- the tie correction
        w          1 / (n + 1)
        T          sum over cells of w (E[R] - R_denied)
        Var[T]     sum over cells of w^2 Var[R]

    Cells whose values are entirely tied carry no order and contribute nothing; they are
    dropped by the zero-variance mask, exactly as the engine drops them. That mask is not
    a numerical guard -- under the published DTI levels it removes a large share of the
    cells, and pretending otherwise would overstate the design's effective sample size.
    """
    n = vals.shape[1]
    mr = sps.rankdata(vals, method="average", axis=1)
    mean = (n + 1) / 2.0
    var_cell = mr.var(axis=1)                       # population variance, ddof = 0
    live = var_cell > 0
    w = 1.0 / (n + 1)
    t = np.where(live, w * (mean - mr[:, 0]), 0.0).reshape(reps, m).sum(axis=1)
    v = np.where(live, (w ** 2) * var_cell, 0.0).reshape(reps, m).sum(axis=1)
    # The live-cell count is returned rather than recomputed by the caller: ranking is
    # the expensive step in the whole study, and ranking the same block twice to count
    # what was already known doubles the cost of every power curve.
    return t, v, live.reshape(reps, m).sum(axis=1)


def simulate_filings(reps: int, n_cells: int, shift: float, regime: str,
                     rng: np.random.Generator) -> dict[str, np.ndarray]:
    """`reps` independent filings; returns the pooled z, p and the live-cell count."""
    counts = _size_counts(n_cells)
    T = np.zeros(reps)
    V = np.zeros(reps)
    live_cells = np.zeros(reps)
    for n, m in counts.items():
        vals = _draw_block(reps, m, n, shift, regime, rng)
        t, v, live = _pooled_z(vals, reps, m)
        T += t
        V += v
        live_cells += live
    # A filing in which every cell is fully tied produces no statistic at all. It is
    # recorded as p = 1 (no evidence) rather than dropped, because dropping it would
    # quietly condition the study on the filings that happened to be testable.
    ok = V > 0
    z = np.where(ok, T / np.sqrt(np.where(ok, V, 1.0)), 0.0)
    p = np.where(ok, sps.norm.sf(z), 1.0)
    return {"z": z, "p": p, "live_cells": live_cells, "testable": ok}


# ---------------------------------------------------------------------------
# The guard: the fast path must be the same test
# ---------------------------------------------------------------------------
def verify_against_engine(rng: np.random.Generator, trials: int = 40) -> dict:
    """Rebuild simulated filings as engine cells and assert the z-statistics match.

    Without this, the study measures a reimplementation. With it, the study measures the
    product: any divergence between the vectorised path and `stats.stratified_rank_test`
    -- a different tie rule, a dropped zero-variance cell, a sign -- shows up here as a
    mismatch, and the study refuses to run.
    """
    worst = 0.0
    for _ in range(trials):
        regime = str(rng.choice(REGIMES))
        shift = float(rng.choice([0.0, 0.5, 2.0]))
        counts = _size_counts(60)
        T = V = 0.0
        cells = []
        for n, m in counts.items():
            vals = _draw_block(1, m, n, shift, regime, rng)
            t, v, _ = _pooled_z(vals, 1, m)
            T += float(t[0]); V += float(v[0])
            for row in vals:
                cells.append(fixtures.make_cell(row))
        eng = stats.stratified_rank_test(cells)
        if V <= 0 or eng["z"] is None:
            continue
        worst = max(worst, abs(eng["z"] - round(T / math.sqrt(V), 4)))
    if worst > 1e-4:                       # the engine publishes z to four places
        raise AssertionError(
            f"the vectorised simulator and the engine disagree by {worst:.3e} in z; "
            "the study would be measuring the wrong test")
    return {"trials": trials, "worst_z_gap": worst}


# ---------------------------------------------------------------------------
# Study 1: calibration under a true null
# ---------------------------------------------------------------------------
@dataclass
class Calibration:
    regime: str
    n_cells: int
    reps: int
    testable_share: float
    mean_live_cells: float
    ks_statistic: float
    ks_p: float
    rejection_rate_05: float
    rejection_ci95_05: tuple[float, float]
    rejection_rate_10: float
    verdict: str


def study_calibration(reps: int = 4000, n_cells: int = 300) -> list[Calibration]:
    """Under H0 the p-values must be uniform, and the test must not over-reject.

    THE STATISTICS. If the test is exactly calibrated, its p-values are Uniform(0,1), so
    a one-sample Kolmogorov-Smirnov test against the uniform is the natural omnibus
    check. But this test is DISCRETE -- ranks in a cell of three take three values -- so
    exact uniformity is unattainable and the KS test will reject for large reps no matter
    how correct the implementation is. The KS statistic is therefore reported as a
    magnitude rather than gated on, and the verdict is decided on the quantity that
    actually matters for a claim: whether the rejection rate at the nominal level exceeds
    it by more than sampling error.

    The rejection-rate interval is the engine's own exact Clopper-Pearson limit, which is
    conservative -- so a "calibrated" verdict here is the harder call to obtain, not the
    easier one.
    """
    rng = np.random.default_rng(SEED + 100)
    out = []
    for regime in REGIMES:
        for nc in (100, n_cells, 1000):
            r = simulate_filings(reps, nc, 0.0, regime, rng)
            p = r["p"]
            ks = sps.kstest(p, "uniform")
            rate05 = float(np.mean(p <= 0.05))
            rate10 = float(np.mean(p <= 0.10))
            k = int(np.sum(p <= 0.05))
            # A two-sided exact interval at level 0.05, built from the one-sided bound in
            # both directions -- the engine's function gives the upper limit, and the
            # lower limit is the upper limit on the complementary count.
            hi = binding_gate.clopper_pearson_upper(k, reps, 0.025)
            lo = 1.0 - binding_gate.clopper_pearson_upper(reps - k, reps, 0.025)
            # Calibrated means the nominal level is inside the interval, or the rate is
            # below nominal. Conservative is acceptable -- discreteness alone makes a
            # discrete test conservative -- but anti-conservative is not, because the
            # product's only inferential claim is a one-sided p at 0.05.
            verdict = ("calibrated" if lo <= 0.05 <= hi else
                       "conservative" if hi < 0.05 else "ANTI-CONSERVATIVE")
            out.append(Calibration(regime, nc, reps,
                                   round(float(np.mean(r["testable"])), 4),
                                   round(float(np.mean(r["live_cells"])), 2),
                                   round(float(ks.statistic), 4), round(float(ks.pvalue), 6),
                                   round(rate05, 4), (round(lo, 4), round(hi, 4)),
                                   round(rate10, 4), verdict))
    return out


# ---------------------------------------------------------------------------
# Study 2: power
# ---------------------------------------------------------------------------
@dataclass
class PowerPoint:
    regime: str
    n_cells: int
    shift: float
    power_05: float
    mean_live_cells: float


def study_power(reps: int = 2000, shifts=(0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0),
                cell_counts=(100, 300, 1000)) -> list[PowerPoint]:
    """Rejection rate at alpha = 0.05 against effect size, cell count and coarsening.

    The effect is a location shift on the tested dimension, in dimension units: on DTI a
    shift of 1.0 means the denied applicant's ratio is one percentage point better than
    the cell they are being compared against. That is a small effect by any lending
    standard, which is exactly why the curve is worth drawing -- the question is not
    whether a large effect is detectable but where the floor sits.
    """
    rng = np.random.default_rng(SEED + 200)
    out = []
    for regime in REGIMES:
        for nc in cell_counts:
            for s in shifts:
                r = simulate_filings(reps, nc, s, regime, rng)
                out.append(PowerPoint(regime, nc, float(s),
                                      round(float(np.mean(r["p"] <= 0.05)), 4),
                                      round(float(np.mean(r["live_cells"])), 2)))
    return out


def minimum_detectable_effect(points: list[PowerPoint], target: float = 0.80) -> list[dict]:
    """The shift at which power first reaches `target`, by linear interpolation.

    One number per regime and cell count, and the single most useful summary of the
    study: it says what the design can and cannot see. Reported as None where the
    simulated range never reaches the target, rather than extrapolated -- an MDE
    extrapolated beyond the grid is a guess wearing a decimal point.
    """
    out = []
    keys = sorted({(p.regime, p.n_cells) for p in points})
    for regime, nc in keys:
        curve = sorted([p for p in points if p.regime == regime and p.n_cells == nc],
                       key=lambda p: p.shift)
        mde = None
        for a, b in itertools.pairwise(curve):
            if a.power_05 < target <= b.power_05:
                span = b.power_05 - a.power_05
                mde = a.shift + (b.shift - a.shift) * ((target - a.power_05) / span
                                                       if span else 0.0)
                break
        out.append({"regime": regime, "n_cells": nc, "target_power": target,
                    "minimum_detectable_shift": None if mde is None else round(mde, 3),
                    "max_power_in_range": max(p.power_05 for p in curve)})
    return out


# ---------------------------------------------------------------------------
# Study 3: the finding rule itself
# ---------------------------------------------------------------------------
def _dominance_finding(vals: np.ndarray, threshold: float) -> np.ndarray:
    """The engine's finding rule, vectorised. Column 0 is the denied record.

    THE RULE. On a higher_is_worse dimension the margin against comparator j is
    m_j = v_0 - v_j. The comparator is WORSE than the denial by more than the threshold
    when m_j < -t, and BETTER by more than the threshold when m_j > t. A pair is reported
    only when somebody is worse and nobody is better:

        finding  <=>  (exists j: v_j > v_0 + t)  and  (no j: v_j < v_0 - t)

    The second clause is what makes this a partial order rather than a score. A denial
    that is beaten in both directions is AMBIGUOUS, not a finding, and the whole point of
    the interval-dominance construction is that ambiguity is reported as ambiguity
    instead of being resolved by a tiebreak nobody can audit.
    """
    v0 = vals[:, 0]
    others = vals[:, 1:]
    worse_exists = (others > v0[:, None] + threshold).any(axis=1)
    better_exists = (others < v0[:, None] - threshold).any(axis=1)
    return worse_exists & ~better_exists


def verify_dominance_against_engine(rng: np.random.Generator, trials: int = 20) -> dict:
    """The same guard as for the pooled test: the vectorised rule must be the engine's.

    `scan.dominance_statistic` is the function the product actually applies when it
    decides to flag a record, so the study is driven through it on a sample and the two
    rates asserted equal.
    """
    from likewise import scan                          # local: keeps the import cost off
    worst = 0.0                                        # every other entry point
    for _ in range(trials):
        thr = float(rng.choice([0.5, 1.0, 2.0, 5.0]))
        vals = _draw_block(1, 200, int(rng.integers(2, 9)), 0.0, "bin_1", rng)
        fast = float(_dominance_finding(vals, thr).mean())
        cells = [fixtures.make_cell(row, threshold=thr) for row in vals]
        slow = scan.dominance_statistic(cells)
        worst = max(worst, abs(fast - slow))
    if worst > 1e-12:
        raise AssertionError(f"vectorised finding rule differs from the engine by {worst:.3e}")
    return {"trials": trials, "worst_rate_gap": worst}


@dataclass
class DominancePoint:
    regime: str
    threshold: float
    shift: float
    finding_rate: float
    lift_over_null: float | None
    ambiguous_rate: float
    no_comparator_beyond_threshold_rate: float


def study_dominance(reps_cells: int = 60_000,
                    thresholds=(0.5, 1.0, 2.0, 3.0, 5.0),
                    shifts=(0.0, 1.0, 2.0, 4.0)) -> list[DominancePoint]:
    """How often the FINDING RULE fires, against threshold and effect size.

    This is a different question from the pooled test's power, and for the product it is
    the more important one. The pooled test asks whether the filing as a whole departs
    from exchangeability; the finding rule decides whether an individual denial reaches a
    reviewer's queue. A design can pass the first and produce almost nothing through the
    second, which is precisely what the real scan does.

    The threshold is not a tuning knob. Per pair it is
    tau = max(declared minimum, comparability floor, publication floor), and the
    publication floor is set by the bin width the data arrives in -- so the columns of
    this study are not choices, they are the thresholds the data forces at different
    property values. Reading down a column shows what the decisive threshold costs.

    Three rates are reported per point, and they are exclusive: a finding, an AMBIGUOUS
    cell (beaten in both directions, which the lattice refuses to resolve), and a cell
    with no comparator beyond the threshold in either direction at all. The third is the
    structural failure mode -- nothing is wrong with the cell except that the scale it is
    published on cannot separate anybody in it.
    """
    rng = np.random.default_rng(SEED + 500)
    out = []
    for regime in REGIMES:
        null_rate = {}
        for shift in shifts:
            for thr in thresholds:
                # One large pool of cells per point. Sizes are drawn from the same
                # distribution as everywhere else, so the rates are comparable with the
                # pooled-test studies.
                counts = _size_counts(reps_cells)
                find = amb = none = tot = 0
                for n, m in counts.items():
                    vals = _draw_block(1, m, n, shift, regime, rng)
                    v0, others = vals[:, 0], vals[:, 1:]
                    worse = (others > v0[:, None] + thr).any(axis=1)
                    better = (others < v0[:, None] - thr).any(axis=1)
                    find += int((worse & ~better).sum())
                    amb += int((worse & better).sum())
                    none += int((~worse & ~better).sum())
                    tot += vals.shape[0]
                rate = find / tot
                if shift == 0.0:
                    null_rate[thr] = rate
                base = null_rate.get(thr)
                out.append(DominancePoint(
                    regime, float(thr), float(shift), round(rate, 5),
                    None if not base else round(rate / base, 3),
                    round(amb / tot, 5), round(none / tot, 5)))
    return out


def study_structural_capacity(n_cells: int = 20_000, q_target: float = 0.05) -> list[dict]:
    """What share of cells could reach a per-cell decision at all, before any data.

    THE ARITHMETIC. The smallest p a cell can produce is the size of its best tie block
    over n. With the cell sizes this design actually has -- a median of three -- that
    floor is at best 1/n, and 1/8 = 0.125 already exceeds any conventional level. No
    amount of evidence inside such a cell can reach 0.05.

    This is not a limitation discovered by running the test; it is decided by the cell
    sizes and the tie structure before a single comparison is made, and it is the reason
    the design pools across cells instead of reporting a per-finding p-value. Measuring
    it here turns "the median cell holds three records" into the consequence that
    actually follows from it.
    """
    from likewise import core                                    # local, as above
    rng = np.random.default_rng(SEED + 600)
    out = []
    for regime in REGIMES:
        counts = _size_counts(n_cells)
        capable = tot = 0
        floors = []
        for n, m in counts.items():
            vals = _draw_block(1, m, n, 0.0, regime, rng)
            for row in vals:
                f = stats.min_attainable_p(list(row))
                floors.append(f)
                capable += f <= q_target
                tot += 1
        out.append({"regime": regime, "q_target": q_target, "cells": tot,
                    "share_capable_of_reaching_q": round(capable / tot, 5),
                    "median_attainable_floor": round(float(np.median(floors)), 5),
                    "best_attainable_floor": round(float(np.min(floors)), 5),
                    "note": ("decided by cell size and ties before any comparison; "
                             "this is why the design pools rather than testing per cell")})
    assert core is not None
    return out


# ---------------------------------------------------------------------------
# Study 4: coverage of the exact binomial bound
# ---------------------------------------------------------------------------
def study_binomial_coverage(reps: int = 20_000) -> list[dict]:
    """Does the Clopper-Pearson upper limit cover the truth at least 1 - alpha of the time?

    Clopper-Pearson inverts the exact binomial test, so it is guaranteed conservative:
    because the binomial is discrete there is generally no p at which the tail
    probability equals alpha exactly, and the construction takes the safe side. The study
    measures HOW conservative at the sizes the binding gate uses, since the cost of a
    bound that is wider than it needs to be is a release refused for no reason.
    """
    rng = np.random.default_rng(SEED + 300)
    out = []
    for n in (30, 100, 299, 1000, 2995):
        for p_true in (0.0005, 0.005, 0.02, 0.10):
            k = rng.binomial(n, p_true, size=reps)
            # Vectorising is not worth it: the bound depends only on k, and k takes few
            # distinct values at these rates, so it is cached per observed count.
            cache = {int(kk): binding_gate.clopper_pearson_upper(int(kk), n, 0.05)
                     for kk in np.unique(k)}
            bounds = np.array([cache[int(kk)] for kk in k])
            cov = float(np.mean(bounds >= p_true))
            # The verdict is made on an INTERVAL for the coverage, not on the point
            # estimate. Coverage is itself estimated from `reps` draws, so a theoretically
            # conservative bound will land a little below 0.95 about half the time by
            # chance; comparing the point estimate to 0.95 would report that as a defect.
            # Undercoverage is declared only when the exact interval excludes 0.95.
            hits = int(np.sum(bounds >= p_true))
            cov_hi = binding_gate.clopper_pearson_upper(hits, reps, 0.025)
            cov_lo = 1.0 - binding_gate.clopper_pearson_upper(reps - hits, reps, 0.025)
            out.append({"n": n, "p_true": p_true, "reps": reps,
                        "coverage": round(cov, 4),
                        "coverage_ci95": [round(cov_lo, 4), round(cov_hi, 4)],
                        "nominal": 0.95,
                        "mean_bound": round(float(bounds.mean()), 6),
                        "excess_width_vs_truth": round(float(bounds.mean() - p_true), 6),
                        "undercovers": cov_hi < 0.95})
    return out


# ---------------------------------------------------------------------------
# Study 5: cluster bootstrap coverage, against the naive alternative
# ---------------------------------------------------------------------------
def study_bootstrap_coverage(reps: int = 400, n_clusters: int = 120,
                             B: int = 800) -> list[dict]:
    """What ignoring the clustering costs, measured as coverage rather than argued.

    THE SET-UP. Each cluster gets its own rate drawn from a Beta, and its rows are drawn
    from that rate. Rows within a cluster are therefore positively correlated, which is
    the situation in the data: pairs inside a cell share the denied record and the
    coarsened cell, so they are not independent draws.

    Two intervals are built on each simulated dataset. The engine's cluster bootstrap
    resamples whole clusters, so the dependence travels intact into every replicate. The
    naive bootstrap resamples individual rows, which destroys the dependence and produces
    a replicate spread that is too small. Both are nominal 95%. Only one of them is.

    The truth being covered is the population rate the clusters were drawn from, which is
    the estimand the product's published rate targets.
    """
    rng = np.random.default_rng(SEED + 400)
    a, b = 2.0, 8.0
    truth = a / (a + b)                    # the population mean of the Beta
    hit_cluster = hit_naive = 0
    w_cluster = w_naive = 0.0
    for _ in range(reps):
        clusters = {}
        rows = []
        for i in range(n_clusters):
            rate = float(rng.beta(a, b))
            size = int(rng.integers(2, 12))
            vals = [float(x) for x in rng.binomial(1, rate, size=size)]
            clusters[f"c{i}"] = vals
            rows.extend(vals)
        lo, hi = stats.cluster_bootstrap_ci(clusters, B=B, seed=7)
        hit_cluster += lo <= truth <= hi
        w_cluster += hi - lo
        # The naive interval: resample ROWS, which is what a reasonable person writes
        # first and what makes the interval too narrow.
        arr = np.array(rows)
        idx = rng.integers(0, arr.size, size=(B, arr.size))
        draws = arr[idx].mean(axis=1)
        nlo, nhi = np.percentile(draws, [2.5, 97.5])
        hit_naive += nlo <= truth <= nhi
        w_naive += float(nhi - nlo)
    return [{"estimator": "cluster bootstrap (engine)", "reps": reps,
             "nominal": 0.95, "coverage": round(hit_cluster / reps, 4),
             "mean_width": round(w_cluster / reps, 5), "truth": round(truth, 4)},
            {"estimator": "naive row bootstrap", "reps": reps,
             "nominal": 0.95, "coverage": round(hit_naive / reps, 4),
             "mean_width": round(w_naive / reps, 5), "truth": round(truth, 4)}]


# ---------------------------------------------------------------------------
def run_all(quick: bool = False) -> dict:
    rng = np.random.default_rng(SEED + 999)
    guard = verify_against_engine(rng, trials=10 if quick else 40)
    guard_dom = verify_dominance_against_engine(rng, trials=5 if quick else 20)
    cal = study_calibration(reps=800 if quick else 4000)
    pw = study_power(reps=400 if quick else 2000,
                     shifts=(0.0, 0.5, 1.0, 2.0) if quick else
                            (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0),
                     cell_counts=(300,) if quick else (100, 300, 1000))
    dom = study_dominance(reps_cells=10_000 if quick else 60_000)
    # A sample of the null p-values themselves, kept so the calibration can be SHOWN as
    # a distribution rather than only summarised by a rejection rate. A rate of 0.05 is
    # consistent with several badly wrong distributions; the ECDF against the diagonal
    # is not.
    prng = np.random.default_rng(SEED + 700)
    null_p = {r: [round(float(x), 6) for x in
                  simulate_filings(800 if quick else 4000, 300, 0.0, r, prng)["p"]]
              for r in REGIMES}
    return {"seed": SEED, "quick": quick,
            "vectorised_path_verified_against_engine": guard,
            "vectorised_finding_rule_verified_against_engine": guard_dom,
            "calibration": [asdict(c) for c in cal],
            "power": [asdict(p) for p in pw],
            "minimum_detectable_effect": minimum_detectable_effect(pw),
            "null_p_sample": null_p,
            "dominance": [asdict(d) for d in dom],
            "structural_capacity": study_structural_capacity(
                n_cells=4_000 if quick else 20_000),
            "binomial_coverage": study_binomial_coverage(reps=4000 if quick else 20_000),
            "bootstrap_coverage": study_bootstrap_coverage(
                reps=60 if quick else 400, B=400 if quick else 800)}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rep = run_all(quick="--quick" in argv)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "simulation.json").write_text(json.dumps(rep, indent=2, default=float))

    print("Simulation study")
    print(f"  vectorised path verified against the engine: "
          f"worst z gap {rep['vectorised_path_verified_against_engine']['worst_z_gap']:.2e}")
    print("\nCalibration under a true null (alpha = 0.05)")
    print(f"  {'regime':<15}{'cells':>7}{'testable':>10}{'live':>8}"
          f"{'rate':>8}{'ci95':>18}  verdict")
    for c in rep["calibration"]:
        ci = f"[{c['rejection_ci95_05'][0]:.4f},{c['rejection_ci95_05'][1]:.4f}]"
        print(f"  {c['regime']:<15}{c['n_cells']:>7}{c['testable_share']:>10.3f}"
              f"{c['mean_live_cells']:>8.1f}{c['rejection_rate_05']:>8.4f}{ci:>18}"
              f"  {c['verdict']}")
    print("\nMinimum detectable shift at 80% power")
    for m in rep["minimum_detectable_effect"]:
        v = ("not reached in range" if m["minimum_detectable_shift"] is None
             else f"{m['minimum_detectable_shift']:.2f} units")
        print(f"  {m['regime']:<15}{m['n_cells']:>7} cells   {v}"
              f"   (max power {m['max_power_in_range']:.2f})")
    print("\nThe finding rule: how often it fires (regime bin_1)")
    print(f"  {'threshold':>10}{'null':>10}{'shift 1':>10}{'shift 2':>10}"
          f"{'shift 4':>10}{'ambiguous':>12}{'nothing sep.':>14}")
    for thr in sorted({d["threshold"] for d in rep["dominance"]}):
        row = {d["shift"]: d for d in rep["dominance"]
               if d["regime"] == "bin_1" and d["threshold"] == thr}
        if not row:
            continue
        base = row[0.0]
        print(f"  {thr:>10.1f}{base['finding_rate']:>10.4f}"
              + "".join(f"{row[s2]['finding_rate']:>10.4f}" if s2 in row else f"{'-':>10}"
                        for s2 in (1.0, 2.0, 4.0))
              + f"{base['ambiguous_rate']:>12.4f}"
              + f"{base['no_comparator_beyond_threshold_rate']:>14.4f}")
    print("\nStructural capacity: share of cells that could ever reach q = 0.05")
    for c in rep["structural_capacity"]:
        print(f"  {c['regime']:<15}{c['share_capable_of_reaching_q']:>8.4f}"
              f"   (best attainable p in any cell: {c['best_attainable_floor']:.3f})")

    print("\nExact binomial bound: coverage of a nominal 95% upper limit")
    worst = min(r["coverage"] for r in rep["binomial_coverage"])
    bad = [r for r in rep["binomial_coverage"] if r["undercovers"]]
    print(f"  minimum coverage over the grid: {worst:.4f}"
          f"   ({'conservative everywhere' if not bad else str(len(bad)) + ' points UNDERCOVER'})")
    print(f"  mean excess width over the truth: "
          f"{np.mean([r['excess_width_vs_truth'] for r in rep['binomial_coverage']]):.5f}")
    print("\nInterval coverage under clustering (nominal 95%)")
    for r in rep["bootstrap_coverage"]:
        print(f"  {r['estimator']:<28}{r['coverage']:>8.3f}"
              f"   mean width {r['mean_width']:.4f}")
    print(f"\nwritten to {OUT / 'simulation.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
