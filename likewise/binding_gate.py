"""The binding acceptance gate: is `precedent.py` fit to compel a decision?

`PRECEDENCE.md` section 8 specified this in words and nothing implemented it. `admit` and
`rule` have unit tests, which establish that they do what they were written to do; nothing
established that what they were written to do is *right* on a corpus. This module is how
that question is asked.

The judiciary corpora carry computed ground truth, so a case's correct disposition is
known by construction. That makes the precision of a binding directly measurable -- unlike
the lending instantiation, where the core value claim is admitted to be unevaluable.

## The error asymmetry, and why the gate is one-sided

A missed bind costs a reviewer a case they must decide themselves. A **false bind**
compels a decision from a precedent that does not govern, and its audit trail is accurate
in every field, so nothing downstream can catch it. The gate therefore bounds false binds
and merely *reports* missed ones. Gating recall would trade the expensive error for the
cheap one, which is the same mistake as fitting an extraction floor for F1.

## The trap this gate exists to avoid

**Perfect precision is satisfiable by never binding.** An engine that abstains on
everything has a false-bind rate of zero and is useless. So the verdict is `inconclusive`
below a floor on the number of binds actually made -- never `pass`.

## Guard items

Cases engineered so that the only correct behaviour is abstention or distinguishing. A
single guard bind fails at any n: a guard is a case where binding is wrong by construction,
so one bind is a demonstration that the floor does not hold, whatever the aggregate says.

## The mathematics

Two ideas, and only two.

**The Clopper-Pearson exact binomial confidence limit.** Every bind is a Bernoulli
trial: it was either right or it was a false bind. From k failures in n trials we want
an upper bound on the underlying failure rate that is honest at small k -- and k is
usually zero, which is exactly where the normal approximation is worst (it returns an
interval of width zero). Clopper-Pearson inverts the binomial test instead: the upper
limit is the largest rate p for which observing k or fewer failures would still be
plausible at level alpha, i.e. the p solving P(X <= k | n, p) = alpha. The binomial CDF
is monotone decreasing in p, so that root is unique and bisection finds it exactly.

At k = 0 the answer reduces to 1 - alpha^(1/n), of which the familiar RULE OF THREE
(3/n at 95% confidence) is the large-n approximation. Computing it exactly rather than
by the rule of three costs nothing, sharpens the floors slightly, and -- the real
reason -- still returns a usable bound when k > 0, where the rule of three says nothing
at all. A near miss becomes legible instead of merely failed.

**A one-sided decision rule with an attainability floor.** There is no second test. The
bound is compared to a target, and the comparison is refused when the evidence base is
too thin to support it. That floor is the mathematical content of the trap above: with
zero binds the bound is undefined, not zero, and `false_bind_upper` returns None to
make that impossible to misread.

Deliberately absent: any aggregate scoring of abstentions, any weighting of cases by
difficulty, any model of the corpus. The gate counts events and bounds a rate.

## Oracle independence

Computed ground truth is a second program written from the same rulebook, and guard items
written by the same authors. A shared misreading of a provision reads as 100% precision and
is in fact measured agreement between two implementations of one error. Section 8 names
this and proposes the mitigation: a stated fraction of items authored by someone who did
not write the engine's rulebook reading, reported separately.

This module goes one step further than the proposal. **A pass on a self-authored oracle
alone is not a pass** -- it is `inconclusive`, with the cause named. Reporting the
independent arm separately is not enough if nothing ever refuses on its absence, because
the arm that is only reported is the arm that is quietly left empty.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .precedent import ABSTENTIONS, CASE_OUTCOMES, GOVERNED, Ruling

# --- verdicts ---------------------------------------------------------------
BIND_AGREED = "bind_agreed"                    # bound, and on the precedent the oracle names
BIND_WRONG_PRECEDENT = "bind_wrong_precedent"  # bound, on the wrong precedent
FALSE_BIND = "false_bind"                      # bound where the oracle abstains
MISSED_BIND = "missed_bind"                    # abstained where the oracle binds
ABSTAIN_AGREED = "abstain_agreed"              # abstained, same cause
ABSTAIN_DIVERGED = "abstain_diverged"          # abstained, different cause

VERDICTS = (BIND_AGREED, BIND_WRONG_PRECEDENT, FALSE_BIND, MISSED_BIND,
            ABSTAIN_AGREED, ABSTAIN_DIVERGED)

#: The expensive errors. Both compel a decision the record does not support; the audit
#: trail of each is accurate in every field, so nothing downstream can catch them.
FALSE_BINDS = frozenset({FALSE_BIND, BIND_WRONG_PRECEDENT})
#: Every verdict in which the engine bound. The denominator of the false-bind rate.
BINDS = frozenset({BIND_AGREED, BIND_WRONG_PRECEDENT, FALSE_BIND})

ENGINE_ARM = "engine"
INDEPENDENT_ARM = "independent"


@dataclass(frozen=True)
class OracleCase:
    """One case, and what the corpus says the answer is."""

    case_id: str
    expected: str                          # a CASE_OUTCOME
    expected_controlling: str | None = None
    guard: bool = False                    # binding is wrong by construction
    arm: str = ENGINE_ARM                  # who authored the expectation
    provision: str | None = None
    absolute: bool = False                 # absolute provision: a higher n floor

    def __post_init__(self) -> None:
        if self.expected not in CASE_OUTCOMES:
            raise ValueError(f"unknown expected outcome {self.expected!r}")
        if self.expected == GOVERNED and not self.expected_controlling:
            raise ValueError(
                f"{self.case_id}: an expected GOVERNED must name its controlling "
                "precedent, or the oracle cannot tell a right bind from a wrong one")
        if self.expected != GOVERNED and self.expected_controlling:
            raise ValueError(
                f"{self.case_id}: only an expected GOVERNED may name a controlling "
                "precedent")
        if self.guard and self.expected == GOVERNED:
            raise ValueError(
                f"{self.case_id}: a guard is a case where binding is wrong by "
                "construction; one that expects GOVERNED is not a guard")
        if self.arm not in (ENGINE_ARM, INDEPENDENT_ARM):
            raise ValueError(f"unknown arm {self.arm!r}")


@dataclass(frozen=True)
class Scored:
    case_id: str
    verdict: str
    guard: bool
    arm: str
    absolute: bool
    expected: str
    got: str
    expected_controlling: str | None = None
    got_controlling: str | None = None


def verdict_for(ruling: Ruling, oracle: OracleCase) -> str:
    engine_bound = ruling.outcome == GOVERNED
    oracle_binds = oracle.expected == GOVERNED
    if engine_bound and oracle_binds:
        return (BIND_AGREED if ruling.controlling == oracle.expected_controlling
                else BIND_WRONG_PRECEDENT)
    if engine_bound and not oracle_binds:
        return FALSE_BIND
    if not engine_bound and oracle_binds:
        return MISSED_BIND
    # Both abstained. The six outcomes exist so that "nothing retrieved", "everything
    # distinguished", "premise not established" and "admitted but not orderable" stay
    # apart; agreeing to abstain for different reasons is not the same as agreeing.
    return ABSTAIN_AGREED if ruling.outcome == oracle.expected else ABSTAIN_DIVERGED


def score(ruling: Ruling, oracle: OracleCase) -> Scored:
    return Scored(case_id=oracle.case_id, verdict=verdict_for(ruling, oracle),
                  guard=oracle.guard, arm=oracle.arm, absolute=oracle.absolute,
                  expected=oracle.expected, got=ruling.outcome,
                  expected_controlling=oracle.expected_controlling,
                  got_controlling=ruling.controlling)


# --- the bound ---------------------------------------------------------------
def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """Exact one-sided upper confidence limit on a binomial rate.

    Solves `P(X <= k | n, p) = alpha` for p by bisection; the binomial CDF is monotone
    decreasing in p, so the root is unique. Standard library only -- `math.comb` is exact
    in integers, and the whole engine avoids scipy deliberately.

    At `k = 0` this is `1 - alpha**(1/n)`, of which the rule of three (`3/n` at 95%) is the
    large-n approximation. Section 8 quotes the rule of three; this computes the exact
    quantity, which also gives a usable bound when k > 0 rather than only when k == 0.
    """
    if n <= 0:
        raise ValueError("no trials")
    if not (0 <= k <= n):
        raise ValueError(f"{k} failures in {n} trials is not possible")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0, 1)")
    # Every trial failed: no rate below 1 is excluded, and the honest bound is 1.
    if k == n:
        return 1.0

    def cdf(p: float) -> float:
        # P(X <= k) for X ~ Binomial(n, p), summed in LOG SPACE.
        #
        # The obvious form -- sum of comb(n, i) * p**i * (1-p)**(n-i) -- cannot be used at
        # the sizes this gate runs at. The assertion floor puts n in the low thousands,
        # and comb(2995, 1497) is an exact integer with about nine hundred digits. Python
        # keeps it exactly, then raises OverflowError the moment it has to become a float
        # to meet p**i -- even though the PRODUCT is a probability in [0, 1]. The huge
        # coefficient and the vanishing powers have to cancel before either is materialised.
        #
        # So each term is formed as exp( log C(n,i) + i log p + (n-i) log(1-p) ), with the
        # log binomial coefficient from lgamma. Nothing leaves log space until it is
        # already of order one. log1p(-p) rather than log(1-p) keeps the second factor
        # accurate when p is small, which is the regime the bisection spends most of its
        # time in. Standard library throughout -- lgamma is in math.
        if p <= 0.0:
            return 1.0                          # X is identically 0, so P(X <= k) = 1
        if p >= 1.0:
            return 1.0 if k >= n else 0.0       # X is identically n
        lp, lq = math.log(p), math.log1p(-p)
        lgn = math.lgamma(n + 1)
        total = 0.0
        for i in range(k + 1):
            total += math.exp(lgn - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                              + i * lp + (n - i) * lq)
        # Rounding in the individual terms can push the sum a hair above 1; the CDF is a
        # probability and the bisection invariant below compares it against alpha, so it
        # is clamped rather than left to drift.
        return min(total, 1.0)

    # Bisection on p. cdf is strictly DECREASING in p -- a higher true failure rate makes
    # "k or fewer failures" less likely -- so cdf(p) = alpha has exactly one root, and
    # the invariant below is cdf(lo) > alpha >= cdf(hi). 200 halvings take the bracket
    # from width 1 to far below floating-point resolution; the loop is cheap enough that
    # there is no reason to tune the count.
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if cdf(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def rule_of_three_n(target: float, alpha: float = 0.05) -> int:
    """The smallest n at which zero failures bounds the rate at `target`."""
    if not (0.0 < target < 1.0):
        raise ValueError("target must be in (0, 1)")
    # Linear search rather than solving 1 - alpha^(1/n) <= target for n directly. The
    # closed form would be one line, but this asks the SAME function the gate uses, so
    # the floor reported here cannot drift from the bound actually applied. n is in the
    # low thousands and this runs once.
    n = 1
    while clopper_pearson_upper(0, n, alpha) > target:
        n += 1
    return n


# --- the gate ----------------------------------------------------------------
@dataclass
class GateReport:
    n_cases: int = 0
    by_verdict: dict[str, int] = field(default_factory=lambda: dict.fromkeys(VERDICTS, 0))
    by_arm: dict[str, dict[str, int]] = field(default_factory=dict)
    guard_binds: list[dict] = field(default_factory=list)
    diverged: list[dict] = field(default_factory=list)
    verdict: str = "inconclusive"
    cause: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def binds(self) -> int:
        return sum(self.by_verdict[v] for v in BINDS)

    @property
    def false_binds(self) -> int:
        return sum(self.by_verdict[v] for v in FALSE_BINDS)

    def false_bind_upper(self, alpha: float = 0.05) -> float | None:
        """`None` when nothing was bound -- NOT zero, which is what an engine that never
        binds would otherwise report."""
        return (None if self.binds == 0
                else clopper_pearson_upper(self.false_binds, self.binds, alpha))

    @property
    def missed_bind_rate(self) -> float | None:
        """Reported, never gated. Gating recall would trade the expensive error for the
        cheap one: an engine tuned to bind more often binds more often wrongly."""
        opportunities = self.by_verdict[BIND_AGREED] + self.by_verdict[
            BIND_WRONG_PRECEDENT] + self.by_verdict[MISSED_BIND]
        return (None if opportunities == 0
                else self.by_verdict[MISSED_BIND] / opportunities)

    def as_dict(self, alpha: float = 0.05) -> dict:
        ub = self.false_bind_upper(alpha)
        return {
            "verdict": self.verdict, "cause": self.cause,
            "n_cases": self.n_cases, "binds": self.binds,
            "false_binds": self.false_binds,
            "false_bind_upper_bound": None if ub is None else round(ub, 6),
            "missed_bind_rate": (None if self.missed_bind_rate is None
                                 else round(self.missed_bind_rate, 6)),
            "by_verdict": dict(self.by_verdict),
            "by_arm": {k: dict(v) for k, v in sorted(self.by_arm.items())},
            "guard_binds": self.guard_binds,
            "abstention_divergences": self.diverged,
            "detail": self.detail,
        }


def evaluate(cases: Sequence[OracleCase], decide: Callable[[OracleCase], Ruling],
             *, tolerance_selection_cases: Sequence[str] = (),
             min_binds: int = 300, min_binds_absolute: int = 3000,
             target_false_bind_rate: float = 0.01, alpha: float = 0.05,
             min_independent_binds: int = 1) -> GateReport:
    """Run the engine over an oracle corpus and apply the gate.

    `tolerance_selection_cases` names cases used to choose the tolerances. Any overlap
    invalidates the run: a gate evaluated on the cases its thresholds were fitted to
    measures the fit, not the engine. Same discipline as the held-out corpus revision in
    section 8, and as style disjointness in the extraction harness.
    """
    r = GateReport()
    fitted = set(tolerance_selection_cases)
    leak = sorted({c.case_id for c in cases} & fitted)

    absolute_present = False
    for c in cases:
        s = score(decide(c), c)
        r.n_cases += 1
        r.by_verdict[s.verdict] += 1
        r.by_arm.setdefault(s.arm, dict.fromkeys(VERDICTS, 0))[s.verdict] += 1
        absolute_present = absolute_present or c.absolute
        if s.guard and s.verdict in BINDS:
            r.guard_binds.append({"case_id": s.case_id, "verdict": s.verdict,
                                  "arm": s.arm, "expected": s.expected,
                                  "got_controlling": s.got_controlling})
        if s.verdict == ABSTAIN_DIVERGED:
            r.diverged.append({"case_id": s.case_id, "expected": s.expected,
                               "got": s.got})

    floor = min_binds_absolute if absolute_present else min_binds
    ind = r.by_arm.get(INDEPENDENT_ARM, {})
    ind_binds = sum(ind.get(v, 0) for v in BINDS)
    ind_false = sum(ind.get(v, 0) for v in FALSE_BINDS)
    ub = r.false_bind_upper(alpha)

    r.detail = {
        "min_binds_required": floor,
        "floor_reason": ("an absolute provision is present" if absolute_present
                         else "no absolute provision present"),
        "target_false_bind_rate": target_false_bind_rate, "alpha": alpha,
        "independent_arm": {
            "binds": ind_binds, "false_binds": ind_false,
            "required": min_independent_binds,
            "false_bind_upper_bound": (None if ind_binds == 0 else
                                       round(clopper_pearson_upper(ind_false, ind_binds,
                                                                   alpha), 6)),
        },
        "tolerance_selection_leak": leak,
        "abstention_divergence_count": len(r.diverged),
    }

    if leak:
        r.verdict, r.cause = "invalid", (
            f"{len(leak)} case(s) were used to select the tolerances and also to evaluate "
            f"them: {leak[:5]}{' ...' if len(leak) > 5 else ''}. That measures the fit, "
            "not the engine.")
    elif r.guard_binds:
        r.verdict, r.cause = "fail", (
            f"{len(r.guard_binds)} guard bind(s). A guard is a case where binding is "
            "wrong by construction; one fails at any n.")
    elif r.binds < floor:
        r.verdict, r.cause = "inconclusive", (
            f"{r.binds} binds against a floor of {floor}. A false-bind rate of zero is "
            "satisfiable by never binding, so too few binds is not a pass.")
    elif ind_binds < min_independent_binds:
        # Section 8's named risk, made refusable. Reporting the independent arm without
        # ever refusing on its absence leaves it quietly empty.
        r.verdict, r.cause = "inconclusive", (
            f"{ind_binds} bind(s) on the independently-authored arm against a required "
            f"{min_independent_binds}. Computed ground truth is a second program written "
            "from the same rulebook; a shared misreading reads as perfect precision. A "
            "pass on a self-authored oracle alone is not a pass.")
    elif ub is not None and ub <= target_false_bind_rate:
        r.verdict, r.cause = "pass", (
            f"{r.false_binds} false bind(s) in {r.binds}; {int((1 - alpha) * 100)}% upper "
            f"bound {ub:.4f} <= {target_false_bind_rate}")
    else:
        r.verdict, r.cause = "fail", (
            f"{r.false_binds} false bind(s) in {r.binds}; {int((1 - alpha) * 100)}% upper "
            f"bound {ub if ub is None else round(ub, 4)} > {target_false_bind_rate}")
    return r


def outcome_confusion(scored: Sequence[Scored]) -> dict[str, dict[str, int]]:
    """Expected outcome against observed, over all six.

    A separate view from the verdicts, and the one that says whether the abstention
    *causes* agree. The six outcomes exist so that "nothing retrieved" and "everything
    distinguished" do not collapse into one empty set; a run where every abstention is
    correct but for the wrong reason passes the gate and is still telling you something.
    """
    out: dict[str, dict[str, int]] = {}
    for s in scored:
        out.setdefault(s.expected, dict.fromkeys(CASE_OUTCOMES, 0))[s.got] += 1
    return out


__all__ = [
    "ABSTAIN_AGREED",
    "ABSTAIN_DIVERGED",
    "ABSTENTIONS",
    "BINDS",
    "BIND_AGREED",
    "BIND_WRONG_PRECEDENT",
    "ENGINE_ARM",
    "FALSE_BIND",
    "FALSE_BINDS",
    "INDEPENDENT_ARM",
    "MISSED_BIND",
    "VERDICTS",
    "GateReport",
    "OracleCase",
    "Scored",
    "clopper_pearson_upper",
    "evaluate",
    "outcome_confusion",
    "rule_of_three_n",
    "score",
    "verdict_for",
]
