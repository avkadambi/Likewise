"""Every statistical claim the product makes, and nothing else.

This module owns the inference. It sees values and labels; it never sees a record, a
key or a field name, which is why nothing here can leak and why every function in it is
testable from a list of numbers.

The null is exact: it needs no superpopulation, no unconfoundedness assumption about
the unobservables, and no cluster-variance approximation -- which matters because there
is no clustering partition available (records are nodes, pairs are edges, cells are
near-cliques, and the sub-block cover deliberately overlaps).

===============================================================================
THE MATHEMATICS IN THIS FILE, IN ORDER
===============================================================================

Five distinct models live here. Read this map first; each function then states its own
formula and, more importantly, why that formula and not the obvious alternative.

1. THE EMPIRICAL CDF AS AN EXACT p-VALUE          -- rank_p_value, min_attainable_p
   The oldest idea in nonparametric statistics. Under the null hypothesis that the
   denied record is exchangeable with the approved records in its cell, its rank is
   uniform over the cell, so the probability of a position at least this extreme is
   simply the share of the cell at or beyond it. No distribution is assumed, nothing is
   estimated, and the answer is exact for any n.

   The subtlety, and the reason this is not one line: TIES. Published mortgage data is
   binned, so ties are the rule. The textbook "rank / n" understates the p-value when
   values repeat, and `min_attainable_p` exists because a cell can be arithmetically
   incapable of producing a small p at all.

2. ROSENBAUM SENSITIVITY ANALYSIS                 -- gamma_star, gamma_max
   The central tool of observational causal inference. Since the data was not
   randomised, some unmeasured variable might explain the whole result. You cannot rule
   that out; what you CAN do is compute how strong such a variable would have to be.
   Gamma is a bound on the odds that two matched records differ in their chance of being
   the denied one. Gamma* is the largest such bias the finding still survives.

   Reported honestly, this number is frequently unflattering, and here it is: see
   METHOD.md for the measured values and what they mean for the product's claims.

3. THE VAN ELTEREN / COCHRAN-MANTEL-HAENSZEL POOLED RANK TEST -- stratified_rank_test
   The problem this solves: the median cell holds three records, and the smallest
   p-value a cell of three can produce is 1/3. No within-cell test can ever reject.
   Pooling recovers the information -- each cell contributes its own standardised rank,
   weighted so that one huge cell cannot drown two hundred small ones. This is the
   standard design for many-tiny-strata data; the same test is used in multi-centre
   clinical trials where each hospital enrols a handful of patients.

   This is THE ONLY INFERENTIAL CLAIM THE PRODUCT MAKES. It is a statement about the
   filer, pooled across the filing. There is deliberately no per-finding p-value.

4. THE PERMUTATION (RANDOMISATION) TEST           -- permutation_null, NullResult
   Fisher's randomisation argument. Shuffle the approved/denied labels within each cell,
   recompute the whole statistic, repeat. That constructs the exact distribution of the
   statistic in a world where the label is unrelated to the number -- no formula, no
   asymptotics. The observed value is then read off against that distribution.

   Implemented adaptively: it starts with a small number of draws and only continues
   when the answer is near the decision boundary, because most scans are not close and
   spending five thousand draws to confirm it is waste.

5. THE EXACT CLOSED FORM OF THE SAME NULL         -- exact_expected_findings
   The permutation test above is Monte Carlo, so it carries simulation error and depends
   on a seed. For the expected NUMBER of findings the answer can be written down in
   closed form and computed in one pass, with no randomness at all. A test asserts the
   two agree within Monte Carlo error, which is a strong check on both.

   Preferred wherever it applies, precisely because a headline that shifts with a seed
   is a headline nobody can replay.

PLUS, for the publication gate:

6. THE CLUSTER BOOTSTRAP AND A RATIO CONTROL      -- cluster_bootstrap_ci, ratio_control
   Resampling whole clusters, not individual observations, because observations inside a
   cluster are not independent. Used to put an interval around the ratio of the cited
   reason's finding rate to a placebo reason's -- the negative control that blocks
   publication if the machinery fires as readily on a reason the lender never gave.

WHAT IS DELIBERATELY ABSENT: any per-finding false-discovery-rate estimator. They were
implemented, found to be arithmetically unattainable at this cell size, and deleted
rather than left unreachable. See the note above stratified_rank_test.
"""
from __future__ import annotations
import math, random
from dataclasses import dataclass, field
from collections.abc import Callable, Sequence


# ---------------------------------------------------------------------------
# Rank statistic under exchangeability
# ---------------------------------------------------------------------------
def rank_p_value(values: Sequence[float], observed: float,
                 higher_is_worse: bool = True) -> float:
    """One-sided exact p for the denied record's position among its cell.

    The p-value is the empirical CDF, not the midrank divided by n. Under H0 the denied
    record is equally likely to be any member of the cell, so the exact probability of a
    position at least this extreme is the share of the cell at or beyond the observed
    value:

        p = #{ v <= observed } / n            (higher_is_worse)

    This is identical to rank/n when every value is distinct, and it is the only form
    that stays valid when they are not. The midrank form understates: a cell of ten with
    a five-way tie at the best value has midrank 3, reporting p = 0.30 where the true
    probability is 0.50. Ties are the common case here, not an edge case -- the tested
    dimensions are published at bin resolution -- so the distinction is the rule rather
    than the exception.
    """
    n = len(values)
    if n <= 0:
        return 1.0
    # Count the cell members at least as extreme as the observation. The comparison is
    # NON-STRICT (<= rather than <): a record tied with the observation is a position the
    # denied record could equally have occupied under the null, so it belongs in the
    # numerator. Using < here is the classic understatement of a tied p-value.
    if higher_is_worse:
        k = sum(1 for v in values if v <= observed)
    else:
        k = sum(1 for v in values if v >= observed)
    # max(k, 1) is the 1/n floor: no cell of n can supply evidence stronger than one
    # observation in n, and a p-value of exactly zero would make the sensitivity bound
    # below infinite, which is a claim no finite sample can support.
    return min(1.0, max(k, 1) / n)


def min_attainable_p(values: Sequence[float], higher_is_worse: bool = True) -> float:
    """The smallest p this cell can produce, given its ties.

    Not 1/n. A record can only be as extreme as the tie block it sits in, so the floor
    is the size of the best block over n. A cell of twenty whose ten lowest values are
    identical cannot report below 0.5 however large the effect.
    """
    n = len(values)
    if n <= 0:
        return 1.0
    # The most extreme value present, then the size of the tie block sitting on it. A
    # record cannot be more extreme than its own tie block, so that block's share of the
    # cell is a hard floor on the p-value -- a property of the cell's tie structure, not
    # of the effect size.
    best = min(values) if higher_is_worse else max(values)
    return sum(1 for v in values if v == best) / n


def gamma_star(p: float, alpha: float) -> float:
    """Rosenbaum sensitivity: the largest bias in treatment odds this finding survives.

    For a one-sided rank p at level alpha, the worst-case p under a bias bound G is
    G*p/(G*p + 1 - p), so the finding survives exactly while

        G <= alpha (1/p - 1) / (1 - alpha)

    G* = 1 means the finding tolerates no unmeasured confounding at all: two applicants
    identical on every published field can differ by 80 credit-score points, which is
    already a bias factor in the mid single digits.
    """
    # Clamped away from both endpoints. At p = 0 the expression diverges and would
    # report unbounded robustness from a finite sample; at p = 1 it is undefined.
    p = min(max(p, 1e-12), 1.0 - 1e-12)
    # G <= alpha (1/p - 1) / (1 - alpha), rearranged from Rosenbaum's worst-case bound
    # G*p / (G*p + 1 - p) <= alpha. Floored at zero: a negative G* is meaningless, and
    # arises only when p already exceeds alpha, i.e. the finding was never significant.
    return max(0.0, alpha * (1.0 / p - 1.0) / (1.0 - alpha))


def gamma_max(best_level_share: float, alpha: float) -> float:
    """The ceiling on sensitivity imposed by coarsening alone.

    Once a dimension is reported on a discrete published scale, the smallest tie-exact p
    is the population share of its best level, whatever the sample size. G_max is what
    G* would be at that floor: a property of the specification, not of the data.
    """
    return gamma_star(best_level_share, alpha)


def stratified_rank_test(cells: Sequence[dict]) -> dict:
    """Pooled rank test across cells -- van Elteren, the CMH score test for 1:M sets.

    The within-cell test throws away everything between cells, which is why a design
    whose median cell holds three records can never reject: the smallest p a cell of
    three can produce is 1/3. Pooling recovers it. Cells of two and three contribute
    here; they cannot contribute to a per-cell test at any useful level.

    Each cell contributes the denied record's midrank against its own exact conditional
    mean and variance, weighted by 1/(n+1) so that a cell of four hundred does not drown
    two hundred cells of three.

        E[R_s]   = (n_s + 1) / 2
        Var[R_s] = (1/n_s) * sum_j ( a_sj - (n_s+1)/2 )^2        tie-corrected
        T        = sum_s w_s ( E[R_s] - R_s ),   w_s = 1/(n_s + 1)

    The statistic is signed so that positive T means denials sit better than chance on
    the dimension their own stated reason names -- which is the direction that would
    make the reason hard to justify.
    """
    # T accumulates the signed statistic, var its variance. Both are sums over cells,
    # because cells are independent by construction -- a record belongs to exactly one.
    T = 0.0
    var = 0.0
    used = 0
    for c in cells:
        vals = c["values"]
        n = len(vals)
        # A cell of one has no internal order and contributes nothing to a rank test.
        if n < 2:
            continue
        mr = c["midranks"]
        # E[R] = (n+1)/2 -- the mean rank under the null, where every position is equally
        # likely. This is exact, not an approximation: it follows from the ranks being a
        # permutation of 1..n.
        mean = (n + 1) / 2.0
        # Var[R] computed from the ACTUAL midranks rather than the textbook
        # (n^2 - 1)/12. That closed form assumes distinct values; midranks under ties
        # have smaller spread, and using the untied formula would overstate the variance
        # and silently make the test too conservative. This is the tie correction.
        v = sum((a - mean) ** 2 for a in mr) / n
        if v <= 0:                       # every value tied: the cell carries no order
            continue
        # van Elteren's weight, w = 1/(n+1). The choice of weight is what distinguishes
        # members of this test family: this one is optimal against location-shift
        # alternatives and, more practically here, stops a single cell of four hundred
        # from drowning two hundred cells of three.
        w = 1.0 / (n + 1)
        # Signed so POSITIVE T means the denied records sit BETTER than chance on the
        # dimension their own stated reason names -- the direction that makes the stated
        # reason hard to justify. Getting this sign backwards would invert the product.
        T += w * (mean - c["observed_midrank"])
        # Variances of independent contributions add; the weight enters squared.
        var += (w ** 2) * v
        used += 1
    if used == 0 or var <= 0:
        return {"cells_used": used, "T": 0.0, "se": 0.0, "z": None, "p": None}
    se = math.sqrt(var)
    z = T / se
    # T is a sum of many independent bounded contributions, so the central limit theorem
    # applies to the POOLED statistic even though no single cell is remotely normal.
    # erfc gives the upper-tail normal probability without needing scipy:
    # P(Z > z) = 0.5 * erfc(z / sqrt(2)). One-sided, because only one direction of
    # departure is a claim about the filer.
    p = 0.5 * math.erfc(z / math.sqrt(2.0))          # one-sided, upper tail
    return {"cells_used": used, "T": round(T, 6), "se": round(se, 6),
            "z": round(z, 4), "p": round(p, 8)}


# ---------------------------------------------------------------------------
# Permutation null over the whole scan
# ---------------------------------------------------------------------------
@dataclass
class NullResult:
    B: int
    observed: float
    null_mean: float
    null_ci95: tuple[float, float]
    observed_percentile: float
    permutation_p: float
    permutation_p_lower: float = 1.0
    null_draws: list[float] = field(repr=False, default_factory=list)

    def as_dict(self) -> dict:
        direction = ("above_null" if self.observed > self.null_ci95[1] else
                     "below_null" if self.observed < self.null_ci95[0] else "inside_null")
        return {"B": self.B, "observed": round(self.observed, 6), "direction": direction,
                "null_mean": round(self.null_mean, 6),
                "null_ci95": [round(self.null_ci95[0], 6), round(self.null_ci95[1], 6)],
                "observed_percentile": round(self.observed_percentile, 4),
                "permutation_p_upper": round(self.permutation_p, 6),
                "permutation_p_lower": round(self.permutation_p_lower, 6),
                "mc_se": round(math.sqrt(max(self.permutation_p, 1e-9) *
                                         (1 - self.permutation_p) / max(self.B, 1)), 6)}


def permutation_null(cells: Sequence[dict], statistic: Callable[[Sequence[dict]], float],
                     B: int = 2000, B_initial: int = 200, B_max: int = 5000,
                     seed: int = 20260907) -> NullResult:
    """Shuffle the approved/denied labels WITHIN each cell, preserving the cell's
    covariate multiset and its approved/denied counts, and recompute the statistic.

    Adaptive: start at B_initial and continue only while the interim p is within a
    factor of 3 of the decision threshold, to a cap of B_max. Protects the latency
    budget without
    fixing B at its worst case for every scan.
    """
    # A FIXED seed, so the same scan reproduces the same envelope. A randomisation test
    # whose interval moves between runs of identical input is not replayable, and replay
    # is the property the whole product rests on.
    rng = random.Random(seed)
    observed = statistic(cells)
    draws: list[float] = []

    def _one() -> float:
        # One draw from the null: permute labels WITHIN each cell, never across cells.
        # Shuffling across cells would destroy the matching and test a different, much
        # weaker hypothesis -- the whole point of blocking is that the comparison is
        # conditional on the cell.
        shuffled = []
        for c in cells:
            labels = list(c["labels"])
            rng.shuffle(labels)
            shuffled.append({**c, "labels": labels})
        return statistic(shuffled)

    # Adaptive sampling. Draws are only worth buying where they might change the answer,
    # so the loop doubles the budget while the interim p is within a factor of three of
    # the 0.10 decision boundary, and stops early otherwise. A scan whose p is 0.9 or
    # 0.001 does not become more decided by four thousand further draws.
    target = B_initial
    while True:
        while len(draws) < target:
            draws.append(_one())
        ge = sum(1 for d in draws if d >= observed)
        # The (1 + ge) / (n + 1) form, not ge / n. Counting the observed value as one of
        # its own reference draws is the standard Monte Carlo p-value: it keeps the test
        # exact-valid and, like the 1/n floor above, forbids a p-value of zero.
        p = (1 + ge) / (len(draws) + 1)
        if target >= min(B, B_max) or not (p / 3.0 <= 0.10 <= p * 3.0):
            break
        target = min(target * 2, B_max)

    # The published envelope is a PERCENTILE interval taken straight off the sorted
    # draws -- the 2.5th and 97.5th. No normal approximation is used, because the null
    # distribution of a finding count is discrete, skewed and bounded below by zero, and
    # a symmetric interval around the mean would run negative on sparse scans.
    draws_sorted = sorted(draws)
    n = len(draws_sorted)
    lo = draws_sorted[max(0, int(0.025 * n) - 1)] if n else 0.0
    hi = draws_sorted[min(n - 1, int(0.975 * n))] if n else 0.0
    pct = sum(1 for d in draws if d < observed) / n if n else 0.0
    ge = sum(1 for d in draws if d >= observed)
    le = sum(1 for d in draws if d <= observed)
    return NullResult(n, observed, (sum(draws) / n if n else 0.0), (lo, hi), pct,
                      (1 + ge) / (n + 1), (1 + le) / (n + 1), draws)


# ---------------------------------------------------------------------------
# The exact null
# ---------------------------------------------------------------------------
def exact_expected_findings(cells: Sequence[dict]) -> dict:
    """Expected finding count under within-cell exchangeability, computed exactly.

    No Monte Carlo, no replicate count, no seed, and therefore no wall-clock exposure:
    the answer is a closed form and the whole computation is one O(sum n^2) pass.

    Within a cell of values v_1..v_n and threshold t, the denial label is equally likely
    to sit on any member. The cell produces a finding when the labelled member is beaten
    by somebody beyond t and beaten by nobody in the other direction beyond t, so

        P(finding in this cell) = (1/n) * sum_i  1{exists j: v_j worse than v_i by > t}
                                              * 1{no j:     v_j better than v_i by > t}

    Summing over cells gives the exact expectation. This is the same event the
    permutation draws estimate, so the two must agree up to Monte Carlo error -- and a
    test asserts they do, which is what makes the permutation path checkable rather than
    merely trusted.

    Why the permutation is still run: the exact form gives the MEAN, and the tripwire
    and the published envelope want an interval as well. The exact value is the anchor;
    the draws supply the spread.
    """
    if not cells:
        return {"cells": 0, "expected": 0.0, "rate": 0.0}
    total = 0.0
    for c in cells:
        vals = c["values"]
        n = len(vals)
        if n <= 0:
            continue
        thr = c["threshold"]
        hiw = c["direction"] == "higher_is_worse"
        # `hits` counts how many of the n possible label placements would produce a
        # finding. Divided by n at the end, that IS the probability, because the label is
        # uniform over the cell under the null -- no simulation required.
        hits = 0
        # The O(n^2) pass: every member against every other member. n is a cell size, in
        # the low tens, so the quadratic cost is irrelevant and buys an exact answer.
        for v in vals:
            worse = better = False
            for o in vals:
                # Same orientation as Dimension.margin: margin(approved=o, denied=v).
                m = (v - o) if hiw else (o - v)
                if m < -thr:
                    worse = True
                elif m > thr:
                    better = True
            if worse and not better:
                hits += 1
        total += hits / n
    return {"cells": len(cells), "expected": round(total, 6),
            "rate": round(total / len(cells), 6)}


# Negative controls
# ---------------------------------------------------------------------------
@dataclass
class ControlResult:
    name: str
    rate: float
    n: int
    ci95: tuple[float, float]
    gate: str          # pass | fail | inconclusive
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"control": self.name, "rate": round(self.rate, 6), "n": self.n,
                "ci95": [round(self.ci95[0], 6), round(self.ci95[1], 6)],
                "gate": self.gate, **self.detail}


def cluster_bootstrap_ci(values_by_cluster: dict, B: int = 2000, seed: int = 7,
                         alpha: float = 0.05) -> tuple[float, float]:
    """Resample CLUSTERS, not rows. Pairs within a cell are dependent by construction."""
    rng = random.Random(seed)
    keys = list(values_by_cluster)
    if not keys:
        return (0.0, 0.0)
    draws = []
    for _ in range(B):
        pick = [values_by_cluster[rng.choice(keys)] for _ in keys]
        num = sum(sum(v) for v in pick)
        den = sum(len(v) for v in pick)
        draws.append(num / den if den else 0.0)
    draws.sort()
    lo = draws[max(0, int((alpha / 2) * B) - 1)]
    hi = draws[min(B - 1, int((1 - alpha / 2) * B))]
    return (lo, hi)


def ratio_control(cited: dict, placebo: dict, min_ratio: float = 2.0,
                  ci_floor: float = 1.2, B: int = 2000) -> ControlResult:
    """Control (a): uncited-dimension placebo.

    Gate: R_cited / R_placebo >= 2.0 with 95% CI lower bound > 1.2.
    Lower bound <= 1.0 => no rate may be published.
    Power is checked: a non-significant result on an underpowered control is not
    evidence of specificity, and reporting it as a pass is how a weak product
    survives its own gate.
    """
    rng = random.Random(11)
    keys = sorted(set(cited) | set(placebo))
    n = sum(len(cited.get(k, [])) for k in keys)
    num = sum(sum(cited.get(k, [])) for k in keys)
    den_n = sum(len(placebo.get(k, [])) for k in keys)
    den = sum(sum(placebo.get(k, [])) for k in keys)
    rc = num / n if n else 0.0
    rp = den / den_n if den_n else 0.0
    ratio = (rc / rp) if rp > 0 else (math.inf if rc > 0 else 0.0)

    draws = []
    for _ in range(B):
        pick = [rng.choice(keys) for _ in keys]
        cn = sum(sum(cited.get(k, [])) for k in pick)
        cd = sum(len(cited.get(k, [])) for k in pick)
        pn = sum(sum(placebo.get(k, [])) for k in pick)
        pd = sum(len(placebo.get(k, [])) for k in pick)
        a = cn / cd if cd else 0.0
        b = pn / pd if pd else 0.0
        draws.append((a / b) if b > 0 else (10.0 if a > 0 else 1.0))
    draws.sort()
    lo, hi = draws[max(0, int(0.025 * B) - 1)], draws[min(B - 1, int(0.975 * B))]

    # Power: can this n distinguish ratio=min_ratio from ratio=1?
    powered = n >= 30 and den_n >= 30
    if not powered:
        gate = "inconclusive"
    elif ratio >= min_ratio and lo > ci_floor:
        gate = "pass"
    else:
        gate = "fail"
    return ControlResult("uncited_dimension_placebo", ratio, n, (lo, hi), gate,
                         {"rate_cited": round(rc, 6), "rate_placebo": round(rp, 6),
                          "n_cited": n, "n_placebo": den_n,
                          "min_ratio": min_ratio, "ci_floor": ci_floor,
                          "powered": powered,
                          "publication_blocked": lo <= 1.0})
