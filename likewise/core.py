"""Blocking, dominance, the reason engine and within-cell ranking.

This module owns the COMPARISON: which records may be compared at all, and what the
published record says about a pair once they can be. It does not own orchestration
(scan.py), suppression (scan.py), inference (stats.py) or thresholds (specs.py).

===============================================================================
THE MATHEMATICS IN THIS FILE
===============================================================================

1. BLOCKING, ALSO CALLED A MATCHED OR STRATIFIED DESIGN     -- candidate_sql, match
   The alternative to regression adjustment. Rather than modelling how each covariate
   relates to the outcome and subtracting its effect, you compare only records that are
   already alike on those covariates, and let the comparison be conditional on the
   block. It buys freedom from a functional-form assumption; it costs sample size, and
   here the cost is heavy -- roughly four denials in five find no comparable approved
   application at all.

   Implemented as an equi-join on the exact-match key plus a relative band on the
   numeric covariates. NULL never joins to NULL: SQL USING equality rejects nulls on
   either side by definition, and the null-equating join operators that would defeat
   that are banned outright by a lint over the generated SQL, because two records that
   merely both LACK a value are not alike on it.

   (The ban is enforced by scanning this file's own string content, so the forbidden
   operator cannot be named here either -- see FORBIDDEN_SQL in the egress contract
   test for the list.)

2. INTERVAL ARITHMETIC AND A PARTIAL ORDER          -- interval, interval_compare
   The heart of the method, and the part most often got wrong elsewhere.

   A published value is not a point. The regulator rounds loan amounts to $10,000 bins
   and replaces debt-to-income with a band outside 36-49, so what the file states is a
   WINDOW containing the truth. The standard response -- take the midpoint -- invents
   precision the data never had and propagates it into every downstream number.

   Carrying the window instead means the comparison is a PARTIAL ORDER rather than a
   total one. Two intervals are ordered only when one lies wholly beyond the other by
   more than the threshold; when they overlap, the published record genuinely does not
   rank the pair, and "cannot tell" is the correct answer rather than a failure. That
   third state is reported, never folded into "no problem found" -- roughly four in five
   debt-to-income denials land there at any sample size.

3. FOUR-CLAUSE DOMINANCE                                    -- evaluate
   The finding rule quantifies over the per-dimension comparisons: universally, that no
   dimension is decisively better; existentially, that at least one is decisively worse;
   plus a resolution requirement and a residual-risk check. Conjunction, not a weighted
   score -- the admission region is a BOX, and no additive score has box-shaped level
   sets in more than one dimension.

4. MIDRANKS UNDER TIES                                      -- midranks
   Tied values receive the average of the ranks they jointly occupy. Necessary because
   binned data ties constantly, and because any tie-break by a secondary key biases the
   statistic toward whatever that key correlates with and destroys the exactness of the
   permutation null downstream.

5. AN ATTAINABILITY FLOOR ON POWER                          -- cell_power
   Not a power calculation in the usual sense -- no effect size, no alternative
   hypothesis. It asks a purely arithmetic question: given this cell's size AND its tie
   structure, is the target significance level even reachable? Cells that fail are
   reported with their rank and margin, counted in their own denominator, and are not
   findings.

The original module summary follows.

Blocking, dominance, reason engine and ranking.

Candidate generation, dominance, the reason engine and within-cell ranking (midranks
and cell power). Tolerance semantics live in exactly one place -- Tolerance.bound in
specs.py -- so there is one implementation of the standard, not two.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from collections.abc import Iterable, Sequence

from .errors import SpecError
from .compare import UNRECORDED, compare_intervals, unresolved
from .specs import Spec, Tolerance, Dimension


# ---------------------------------------------------------------------------
# Sub-block cover
# ---------------------------------------------------------------------------
def boundary_sequence(tol: Tolerance, hi: float, lo: float = 0.0) -> list[float]:
    """Cumulative boundaries whose every step is at least the local band bound.

    Decile splitting loses every pair straddling a cut. A pure log-ratio cover is
    lossless only where the relative term dominates -- with a max(relative, absolute)
    bound the floor binds at small magnitudes and a constant ratio cover leaks there.
    Stepping by the bound evaluated at each boundary is lossless everywhere:
    no pair inside the band can span two buckets, so joining b to {b-1, b, b+1}
    provably preserves recall.
    """
    out, x = [lo], lo
    guard = 0
    while x < hi and guard < 100_000:
        step = tol.bound(x, x)
        if step <= 0:
            raise ValueError("non-positive band step")
        x += step
        out.append(x)
        guard += 1
    return out


def bucket_of(boundaries: Sequence[float], v: float) -> int:
    lo, hi = 0, len(boundaries) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if boundaries[mid] <= v:
            lo = mid
        else:
            hi = mid - 1
    return lo


# ---------------------------------------------------------------------------
# Candidate generation SQL
# ---------------------------------------------------------------------------
def candidate_sql(spec: Spec, files_param: str = "$files") -> str:
    key = spec.blocking_key
    band = spec.raw["blocking"]["band"]
    pop = spec.raw["population"]
    cols = _projection(spec)

    join_using = ", ".join(key)
    band_terms = []
    for f, b in band.items():
        band_terms.append(
            f"abs(a.{f} - d.{f}) <= greatest({float(b['relative'])} * least(a.{f}, d.{f}), "
            f"{float(b['min_absolute'])})")
    excl = " AND ".join(f"coalesce({k},0) <> {v}" for k, v in pop.get("exclude_flags", {}).items())
    excl = (" AND " + excl) if excl else ""

    return f"""
WITH src AS (
  SELECT {cols}
  FROM read_parquet({files_param})
  WHERE coalesce(total_units, 1) <= {int(pop.get('max_total_units', 4))}{excl}
),
app AS (SELECT * FROM src WHERE list_contains($approved, action_taken)),
den AS (SELECT * FROM src WHERE list_contains($denied,   action_taken))
SELECT
  a.record_key AS approved_key,
  d.record_key AS denied_key,
  least(a.record_key, d.record_key)    AS key_lo,
  greatest(a.record_key, d.record_key) AS key_hi,
  {", ".join(f"a.{k} AS blk_{k}" for k in key)},
  {", ".join(f"a.{c} AS a_{c}" for c in _pair_cols(spec))},
  {", ".join(f"d.{c} AS d_{c}" for c in _pair_cols(spec))}
FROM app a
JOIN den d USING ({join_using})
WHERE {" AND ".join(band_terms)}
ORDER BY denied_key, approved_key
"""
# NOTE: USING equality rejects NULL on either side by SQL semantics. The design forbids
# IS NOT DISTINCT FROM here unconditionally; enforced by the SQL lint in tests.
#
# The ORDER BY is not cosmetic and not a convenience for reading the output. The scan
# reads `comparators[0]` to build the reference distribution and to decide the untestable
# cause, and breaks ties in two `max()` calls. `preserve_insertion_order=false` is set on
# the connection and the build runs multi-threaded, so without a total order those reads
# are a coin flip: the same input, the same code and the same specification can produce
# two different nulls. `(denied_key, approved_key)` is unique per row, so this is a TOTAL
# order, not a partial one -- a partial order would leave exactly the ties that matter.
# `content_hash` cannot detect the difference, because the inputs are identical.
# Enforced by the ordering lint in tests.


def _pair_cols(spec: Spec) -> list[str]:
    out = ["record_key", "action_taken", "loan_amount", "income", "property_value",
           "combined_loan_to_value_ratio", "debt_to_income_ratio",
           "denial_reason_1", "denial_reason_2", "denial_reason_3", "denial_reason_4"]
    for c in list(spec.control) + list(spec.residual) + sorted(spec.tested_dimensions):
        if c not in out:
            out.append(c)
    return out


def _projection(spec: Spec) -> str:
    cols = set(spec.blocking_key) | set(spec.exact_match) | set(_pair_cols(spec)) | {
        "record_key", "lei", "activity_year", "action_taken", "total_units",
        "open_end_line_of_credit", "reverse_mortgage", "business_or_commercial_purpose"}
    return ", ".join(sorted(cols))


# ---------------------------------------------------------------------------
# Matcher: exact match plus control tolerances
# ---------------------------------------------------------------------------
@dataclass
class MatchResult:
    matched: bool
    incomplete: bool
    deltas: dict[str, dict]
    exact_mismatch: list[str] = field(default_factory=list)


def match(a: dict, d: dict, spec: Spec) -> MatchResult:
    """All deltas computed -- no early return.

    Returning at the first failing feature made the attributed cause depend on spec key
    order and left `deltas` partial, so a sample stratified by delta-to-tolerance ratio
    could not be built from it.
    """
    ok, mismatch, incomplete = True, [], False
    for f in spec.exact_match:
        av, dv = a.get(f), d.get(f)
        if av is None or dv is None:
            incomplete = True
            ok = False
            mismatch.append(f)
            continue                      # record it; do not return early
        if av != dv:
            ok = False
            mismatch.append(f)

    deltas: dict[str, dict] = {}
    for name, tol in spec.control.items():
        av, dv = a.get(name), d.get(name)
        if av is None or dv is None:
            # Null in a compared field disqualifies the pair and is COUNTED, but the
            # remaining deltas are still computed so a delta-to-tolerance stratified
            # sample can be built from the full candidate set.
            deltas[name] = {"a": av, "d": dv, "delta": None, "bound": None,
                            "ratio": None, "within": False, "null": True}
            incomplete = True
            ok = False
            continue
        bound = tol.bound(av, dv)
        delta = abs(av - dv)
        within = delta <= bound
        deltas[name] = {"a": av, "d": dv, "delta": delta, "bound": bound,
                        "ratio": (delta / bound) if bound else math.inf, "within": within}
        ok = ok and within
    return MatchResult(ok and not incomplete, incomplete, deltas, mismatch)


# ---------------------------------------------------------------------------
# Dominance -- four clauses, stated separately on purpose
# ---------------------------------------------------------------------------
@dataclass
class TestedDim:
    dimension: str
    direction: str
    margin: float
    decisive_threshold: float
    outcome: str          # not_supported | supported | below_resolution
    # Where the pair sits on the comparison lattice. `outcome` is the three-valued
    # projection the wire format has always carried; `order` is the finer statement,
    # and it separates "the intervals overlap so the record does not order them" from
    # "they do not overlap but the gap is under the pair's own resolution floor". Both
    # project to below_resolution and they are not the same fact.
    order: str = UNRECORDED

    def as_dict(self) -> dict:
        return {"dimension": self.dimension, "direction": self.direction,
                "margin": round(self.margin, 6),
                "decisive_threshold": self.decisive_threshold, "outcome": self.outcome}


@dataclass
class Outcome:
    outcome: str                    # not_supported_by_public_record | supported | untestable
    cause: str | None
    tested: list[TestedDim]
    residual_block: str | None = None

    @property
    def informative(self) -> list[TestedDim]:
        return [t for t in self.tested if t.outcome != "below_resolution"]


def interval(spec: Spec, dim: str, value: float | None,
             band: str | None = None) -> tuple[float, float] | None:
    """The closed interval a published value actually denotes.

    A reported number is a number only inside the window the regulator reports numbers
    in. Outside it the file carries a band, and a band is an interval, not a missing
    value. Debt-to-income is published as an exact integer only between 36 and 49; above
    that it is ">60%" or "50%-60%", which is exactly where a lender denying for
    debt-to-income would be. Treating those as absent discards the largest denial reason
    in the country; treating them as numbers invents precision that was never filed.

    An interval is neither. It supports the only comparison the design needs -- a strict
    order with a real margin in the dimension's own unit -- and it refuses to answer
    where the published values genuinely overlap.
    """
    bands = spec.budget.raw["dimensions"].get(dim, {}).get("bands") or {}
    if band is not None and band in bands:
        lo, hi = bands[band]
        return (float(lo), float("inf") if hi is None else float(hi))
    if value is None:
        return None
    bd = spec.budget.raw["dimensions"].get(dim, {})
    rng = bd.get("integer_range")
    if rng and not (rng[0] <= value <= rng[1]):
        # A value outside the reported window is a band midpoint at best; refuse it
        # rather than compare it as though it were exact.
        return None
    half = float(bd.get("reported_half_width", 0.0))
    return (value - half, value + half)


def interval_compare(a_iv: tuple[float, float], d_iv: tuple[float, float],
                     higher_is_worse: bool, threshold: float) -> tuple[float, str]:
    """Dominance between two intervals. Returns (margin, outcome).

    The approved file is decisively worse only if its whole interval lies beyond the
    denied file's whole interval by more than the threshold. Where the intervals overlap
    the order is not identified by the published record and the pair says nothing --
    which is the honest answer, and is why "50%-60%" against ">60%" is not a finding
    even though one band is nominally higher.
    """
    a_lo, a_hi = a_iv
    d_lo, d_hi = d_iv
    if higher_is_worse:
        worse_by = a_lo - d_hi
        better_by = d_lo - a_hi
    else:
        worse_by = d_lo - a_hi
        better_by = a_lo - d_hi
    if worse_by > threshold:
        return worse_by, "not_supported"
    if better_by > threshold:
        return -better_by, "supported"
    return (worse_by if math.isfinite(worse_by) else 0.0), "below_resolution"


def _dim_applicable(spec: Spec, dim: str, av: float, dv: float) -> bool:
    bd = spec.budget.raw["dimensions"].get(dim, {})
    if bd.get("restricted_to_integer_range"):
        lo, hi = bd.get("integer_range", (-math.inf, math.inf))
        return (lo <= av <= hi) and (lo <= dv <= hi)
    return True


def evaluate(approved: dict, denied: dict, codes: Iterable[int], spec: Spec) -> Outcome:
    """Dominance evaluation. Clauses 2 and 3 are separate quantifiers over T(r):
    universal weak dominance, plus existential strict dominance at resolution.
    """
    codes = [c for c in codes if c is not None]
    if not codes:
        return Outcome("untestable", "no_reason_code", [])
    entries = [spec.reason(int(c)) for c in codes]

    # Multi-code policy, declared in the specification rather than implied here.
    #
    # `conservative` -- a denial citing ANY untestable code is untestable as a whole.
    # Reasons are first-sufficient, unranked and non-exhaustive, so the claim "the public
    # record does not support the reason you cited" is only defensible when every cited
    # reason was examined. `any_testable` weakens it to "at least one of the reasons",
    # which is a different estimand and gameable in the opposite direction.
    policy = (spec.raw.get("comparison") or {}).get("multi_code_policy", "conservative")
    if policy not in ("conservative", "any_testable"):
        raise SpecError("unknown_multi_code_policy",
                        [{"multi_code_policy": policy,
                          "known": ["conservative", "any_testable"]}])
    if policy == "conservative" and any(not e.testable for e in entries):
        return Outcome("untestable", "untestable_code_present", [])
    entries = [e for e in entries if e.testable]
    if not entries:
        return Outcome("untestable", "untestable_code_present", [])

    tested: list[TestedDim] = []
    seen: set[str] = set()
    for e in entries:
        for dim in e.dimensions:
            if dim.name in seen:
                continue
            seen.add(dim.name)
            av, dv = approved.get(dim.name), denied.get(dim.name)
            if av is None or dv is None:
                c = unresolved(dim.name)
                tested.append(TestedDim(dim.name, dim.direction, float("nan"), 0.0,
                                        c.outcome, order=c.order))
                continue
            # The threshold is a property of THIS pair, not of the dimension. The
            # comparability floor is 100*max(0.05L, 20000)/V for a ratio of two binned
            # quantities, so it is 7.0 points at a $285,000 property and 16.0 points at
            # a $125,000 one. A single declared scalar is correct at one magnitude and
            # wrong everywhere below it, in the direction that manufactures findings --
            # and it manufactures them preferentially in cheap markets.
            thr = spec.pair_threshold(dim.name, approved, denied)
            a_iv = interval(spec, dim.name, av, approved.get(dim.name + "_band"))
            d_iv = interval(spec, dim.name, dv, denied.get(dim.name + "_band"))
            if a_iv is None or d_iv is None:
                c = unresolved(dim.name, thr)
                tested.append(TestedDim(dim.name, dim.direction, float("nan"), thr,
                                        c.outcome, order=c.order))
                continue
            c = compare_intervals(dim.name, a_iv, d_iv,
                                  dim.direction == "higher_is_worse", thr)
            tested.append(TestedDim(dim.name, dim.direction, c.margin, thr,
                                    c.outcome, order=c.order))

    informative = [t for t in tested if t.outcome != "below_resolution"]
    if not informative:
        # A conjunction over an empty set is true; the explicit guard is why this
        # does not silently become "not supported".
        return Outcome("untestable", "below_resolution", tested)

    # Clause 2 (universal weak) and clause 3 (existential strict at resolution).
    clause2 = all(t.outcome != "supported" for t in tested if not math.isnan(t.margin))
    clause3 = any(t.outcome == "not_supported" for t in informative)
    if not (clause2 and clause3):
        return Outcome("supported", None, tested)

    # Clause 4 -- residual risk set. The approved comparator must not be strictly
    # better than the denied file beyond tolerance on any residual dimension.
    for name, tol in spec.residual.items():
        av, dv = approved.get(name), denied.get(name)
        if av is None or dv is None:
            continue
        aw = tol.applies_when or {}
        if aw.get("integer_range") and not _dim_applicable(spec, name, av, dv):
            continue
        d = Dimension(name, tol.direction or "higher_is_worse")
        # margin < 0 means the DENIED file is no worse; a strictly BETTER approved
        # comparator on a residual risk dimension is margin > tolerance.
        m = d.margin(av, dv)
        if m > tol.bound(av, dv):
            return Outcome("supported", f"residual_risk:{name}", tested, residual_block=name)

    return Outcome("not_supported_by_public_record", None, tested)


# ---------------------------------------------------------------------------
# Ranking within a cell -- midranks, cell power
# ---------------------------------------------------------------------------
def midranks(values: Sequence[float], higher_is_worse: bool = True) -> list[float]:
    """Average ranks for ties.

    The tested dimension is published at bin resolution and DTI is bucketed, so ties
    are the common case rather than an edge case. Breaking ties with a secondary key
    biases the statistic toward whatever that key correlates with and destroys the
    exactness of the permutation null.
    """
    n = len(values)
    # Sort positions, not values, so the result can be written back in input order. The
    # sign flip carries the direction: ranks always run worst-to-best in the dimension's
    # own sense, so the caller never has to remember which way round a dimension is.
    order = sorted(range(n), key=lambda i: (values[i] if higher_is_worse else -values[i]))
    out = [0.0] * n
    i = 0
    while i < n:
        # Walk forward over the block of equal values starting at i. j ends on the last
        # member of the tie block, so [i, j] is one block and blocks partition the cell.
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # The midrank: the mean of the 1-based ranks i+1 .. j+1, which for a contiguous
        # run is just the midpoint of its endpoints. Every member of the block receives
        # it, so the total of all ranks is preserved at n(n+1)/2 -- the property the
        # pooled test's exact mean and variance depend on.
        mid = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = mid
        i = j + 1
    return out


def cell_power(values: Sequence[float], q: float,
               higher_is_worse: bool = True) -> tuple[str, float]:
    """Whether this cell could ever reach q, given its size AND its ties.

    The floor is not 1/n. A record can be no more extreme than the tie block it belongs
    to, so the smallest attainable p is the size of the best block over n -- and the
    tested dimensions are published at bin resolution, so blocks are large. A cell of
    twenty whose ten lowest values are identical cannot report below 0.5.

    Cells below the floor are reported with their rank and margin and counted in their
    own denominator. They are not findings.
    """
    # Imported here rather than at module scope: core is the lower layer and stats
    # depends on nothing, so a top-level import would be the wrong way round.
    from . import stats
    n = len(values)
    if n <= 0:
        return "underpowered", 1.0
    # The comparison is between the SMALLEST p this cell could ever produce and the
    # target level. If the floor is already above the target, no effect size whatsoever
    # can reach it -- the cell is arithmetically incapable, and that is a fact about the
    # cell rather than about the lender.
    min_p = stats.min_attainable_p(values, higher_is_worse)
    return ("adequate" if min_p <= q else "underpowered"), min_p
