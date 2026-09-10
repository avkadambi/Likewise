"""Admission under a rule of precedence.

The lending instantiation asks whether a comparator undermines a stated reason, and the
answer is a place to look. This module answers a different question with the same
machinery: **does a prior adjudication govern the present case?**

Under a rule of precedence the cost of being wrong inverts. A false flag costs a reviewer
an hour with a file. A false bind compels a disposition and produces a written
justification for it, and the record of that decision is accurate in every field — the
defect is that "not shown weaker" was read as "shown at least as strong".

Four consequences, each of which is a design rule here rather than a caution:

**Bindingness is a partial order, never a score.** A precedent governs when the present
case is not weaker than its premise beyond the declared tolerance — a conjunction of
per-dimension comparisons. It is not a similarity crossing a threshold. The admission
region is a box, and no weighted or additive score has a box for a superlevel set in more
than one dimension, so no such score can be made order-consistent with admission at any
weights for any threshold. `tests/test_precedent.py` mechanises that as an assertion.

**Silence never binds.** A premise dimension the present case does not record is not a
dimension on which the case is at least as strong. It is a premise nobody established.
Under flagging this was harmless — an unrecorded dimension failed the existential strict
clause and nothing was emitted. Under precedence the same record passes "not distinguished"
and governs. `UNRECORDED` therefore forces abstention and outranks every other status.

**The empty set has four causes and they are not the same event.** Nothing retrieved,
everything distinguished, a premise never established, and admitted-but-not-orderable are
four different states that a naive implementation collapses into one empty list. Each
routes differently and each is recorded.

**A-fortiori is a distinct, stronger status.** Where the present case is at least as
strong on every premise dimension with the tolerance set to zero, the admission does not
depend on the tolerance vector at all. That is a different warrant from an admission that
rests on a declared materiality judgment, and it is reported separately rather than
averaged in.

This module surfaces a controlling precedent. It does not dispose of a case. What a
decision-maker owes a surfaced precedent — apply it, or distinguish it in writing — is a
question for the constitution, not for this file.


## The mathematics

No statistics at all. This module is pure order theory and its correctness is a matter
of which lattice elements map to which status, not of any estimate.

**Admission is set containment, relaxed by a tolerance.** The judiciary formulation says
a precedent is distinguished when its premise is not contained in the present case's
facts. Relaxing containment to "no worse by more than a declared tolerance" generalises
that to magnitudes, and at tolerance zero it reduces EXACTLY to the boolean containment
test -- a reduction a test verifies over all 256 combinations of an eight-factor premise.

**The status ladder is a total order on a partial order's outcomes.** Four admission
statuses, ranked so that PREMISE_UNPROVEN outranks DISTINGUISHED outranks TOLERANT
outranks A_FORTIORI. That ordering carries the whole safety property: a dimension the
present case does not record is not one it is at least as strong on, so silence must
defeat a precedent that distinguishing alone would not.

**Chebyshev slack**, in `slack`, is the only scalar here, and it is a diagnostic that
never reaches a ruling. It is the minimum over dimensions of (tolerance - delta) /
tolerance -- an L-infinity distance to the admission boundary in tolerance units. The
minimum is the ONLY aggregation whose super-level sets are boxes, which is precisely why
it is order-consistent with a box-shaped admission region and why a mean or a sum would
not be. Its sign is its entire content: positive is admitted, negative is distinguished.

**Ties in the authority order abstain rather than resolve.** A preorder that is not
total on the admitted set has no least element, and inventing one by sort position is
the failure this module exists to prevent.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from .compare import (AMBIGUOUS, STRICTLY_WORSE, TIED, UNRECORDED, Comparison,
                      compare_intervals, unresolved)

# ---------------------------------------------------------------------------
# Admission status for ONE candidate precedent against the present case.
# ---------------------------------------------------------------------------
A_FORTIORI = "a_fortiori"          # at least as strong on every premise dimension at m=0
TOLERANT = "tolerant"              # admitted, but the admission rests on the tolerance
DISTINGUISHED = "distinguished"    # weaker beyond tolerance on some premise dimension
PREMISE_UNPROVEN = "premise_unproven"   # the case is silent on a premise dimension

ADMISSION_STATUS = (A_FORTIORI, TOLERANT, DISTINGUISHED, PREMISE_UNPROVEN)
ADMITTED = frozenset({A_FORTIORI, TOLERANT})

# ---------------------------------------------------------------------------
# The outcome for the CASE. Mutually exclusive and exhaustive: every case gets
# exactly one, and the counts sum to the docket by construction.
# ---------------------------------------------------------------------------
GOVERNED = "governed"                       # a controlling precedent was found
NO_CANDIDATES = "no_candidates"             # retrieval returned nothing
ALL_DISTINGUISHED = "all_distinguished"     # candidates existed; every one was distinguished
PREMISE_NOT_ESTABLISHED = "premise_not_established"   # silence on a premise dimension
NO_CONTROLLING = "no_controlling"           # admitted, but the authority order is not total
CONFLICT_UNRESOLVED = "conflict_unresolved"  # admitted precedents disagree on disposition

CASE_OUTCOMES = (GOVERNED, NO_CANDIDATES, ALL_DISTINGUISHED, PREMISE_NOT_ESTABLISHED,
                 NO_CONTROLLING, CONFLICT_UNRESOLVED)
ABSTENTIONS = frozenset(CASE_OUTCOMES) - {GOVERNED}


@dataclass(frozen=True)
class PremiseDim:
    """One dimension of a precedent's premise.

    `weaker_when` is declared, never inferred from an argument name. The lending
    instantiation asks whether an approved comparator is worse than a denied file; the
    gate asks whether a present case is weaker than a precedent's premise for the side
    the precedent favoured. Same arithmetic, opposite reading, so the reading is carried
    on the dimension and validated at load.
    """

    name: str
    weaker_when: str            # "lower" | "higher"
    tolerance: float = 0.0      # 0.0 for an absolute provision

    def __post_init__(self):
        if self.weaker_when not in ("lower", "higher"):
            raise ValueError(f"weaker_when must be lower|higher, got {self.weaker_when!r}")
        if self.tolerance < 0:
            raise ValueError(f"negative tolerance on {self.name}")


@dataclass(frozen=True)
class Admission:
    """What one candidate precedent says about the present case."""

    precedent_id: str
    status: str
    comparisons: tuple[Comparison, ...]
    distinguishing: tuple[str, ...] = ()    # dimensions that defeated it
    unproven: tuple[str, ...] = ()          # premise dimensions the case is silent on

    @property
    def admitted(self) -> bool:
        return self.status in ADMITTED


@dataclass(frozen=True)
class Ruling:
    """The outcome for one case. Deliberately carries no score and no disposition."""

    outcome: str
    cause: str | None = None
    controlling: str | None = None
    admissions: tuple[Admission, ...] = ()
    in_force: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.outcome not in CASE_OUTCOMES:
            raise ValueError(f"unknown outcome {self.outcome!r}")
        if self.outcome == GOVERNED and self.controlling is None:
            raise ValueError("a governed case must name its controlling precedent")
        if self.outcome != GOVERNED and self.controlling is not None:
            raise ValueError("only a governed case may name a controlling precedent")


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------
def admit(precedent_id: str, premise: Sequence[PremiseDim], facts: Mapping[str, object],
          reference: Mapping[str, object],
          interval: Callable[[str, object], tuple[float, float] | None] | None = None
          ) -> Admission:
    """Does this precedent govern, on the premise dimensions it rested on?

    The status ladder is ordered and the order is the whole safety argument:

        PREMISE_UNPROVEN  outranks  DISTINGUISHED  outranks  TOLERANT  outranks  A_FORTIORI

    Silence first, because a premise nobody established cannot govern however favourable
    the recorded dimensions look. Distinguished next. Only then the two admitting statuses,
    separated by whether the admission needed the tolerance at all.
    """
    iv = interval or _point_interval
    comparisons: list[Comparison] = []
    distinguishing: list[str] = []
    unproven: list[str] = []

    for dim in premise:
        subject_iv = iv(dim.name, facts.get(dim.name))
        reference_iv = iv(dim.name, reference.get(dim.name))
        if subject_iv is None or reference_iv is None:
            c = unresolved(dim.name, dim.tolerance)
            comparisons.append(c)
            unproven.append(dim.name)
            continue
        c = compare_intervals(dim.name, subject_iv, reference_iv,
                              dim.weaker_when == "higher", dim.tolerance)
        comparisons.append(c)
        if c.order == STRICTLY_WORSE:
            distinguishing.append(dim.name)
        elif c.order in (AMBIGUOUS, UNRECORDED):
            # The record spoke and did not settle the order. Not a silence, but not an
            # order either -- and a premise that is not settled is not established.
            unproven.append(dim.name)

    cmp_t = tuple(comparisons)
    if unproven:
        return Admission(precedent_id, PREMISE_UNPROVEN, cmp_t,
                         tuple(distinguishing), tuple(unproven))
    if distinguishing:
        return Admission(precedent_id, DISTINGUISHED, cmp_t, tuple(distinguishing))
    # Admitted. A-fortiori iff no dimension is weaker AT ALL -- so the admission would
    # survive the tolerance being set to zero, and does not rest on a policy judgment.
    if all(c.order in (TIED, "weakly_better", "strictly_better") for c in cmp_t):
        return Admission(precedent_id, A_FORTIORI, cmp_t)
    return Admission(precedent_id, TOLERANT, cmp_t)


def slack(comparisons: Sequence[Comparison]) -> float | None:
    """Chebyshev slack in tolerance units: min over dimensions of (tolerance - delta)/tolerance.

    The ONLY scalar that is order-consistent with admission, because the admission region
    is a box and a minimum is the one aggregation whose superlevel sets are boxes. Positive
    means admitted, negative means distinguished, and the sign is the whole content.

    Deliberately NOT part of `Ruling`. It is a diagnostic for a specification author
    asking "how close was that", not a field on a decision — a number published beside a
    binding is read as the criterion for the binding no matter what it is called, and the
    criterion is the partial order. `tests/test_precedent.py` enforces its absence from
    the emitted record.
    """
    worst: float | None = None
    for c in comparisons:
        if c.threshold <= 0 or c.margin != c.margin:      # NaN margin, or an exact test
            continue
        s = (c.threshold - c.margin) / c.threshold
        worst = s if worst is None else min(worst, s)
    return worst


# ---------------------------------------------------------------------------
# Ruling
# ---------------------------------------------------------------------------
def rule(candidates: Sequence[Admission],
         authority: Callable[[Admission], tuple] | None = None,
         disposition: Callable[[str], object] | None = None,
         retrieved_any: bool = True,
         in_force: Mapping[str, str] | None = None) -> Ruling:
    """Which admitted precedent governs, or why none does.

    `authority` orders admitted precedents. It is deliberately a caller-supplied preorder
    and it never sees a margin, a rank or a p-value: authority is a property of a
    precedent's standing, and wiring evidential strength into it would let the engine
    promote the most extreme comparator rather than the most authoritative one.

    A tie in the authority order is NOT broken here. Two precedents of equal standing is a
    question for the constitution, and picking one silently is the failure this module
    exists to avoid.
    """
    inf = dict(in_force or {})

    if not retrieved_any:
        return Ruling(NO_CANDIDATES, cause="retrieval returned no candidate", in_force=inf)
    if not candidates:
        return Ruling(NO_CANDIDATES, cause="retrieval returned no candidate", in_force=inf)

    admitted = tuple(a for a in candidates if a.admitted)
    if not admitted:
        # Silence outranks distinguishing: a case that never established a premise is not
        # a case whose precedents were all distinguished on the merits.
        if any(a.status == PREMISE_UNPROVEN for a in candidates):
            return Ruling(PREMISE_NOT_ESTABLISHED,
                          cause="the case is silent on a premise dimension",
                          admissions=tuple(candidates), in_force=inf)
        return Ruling(ALL_DISTINGUISHED, cause="every candidate was distinguished",
                      admissions=tuple(candidates), in_force=inf)

    if disposition is not None:
        outcomes = {disposition(a.precedent_id) for a in admitted}
        if len(outcomes) > 1:
            return Ruling(CONFLICT_UNRESOLVED,
                          cause="admitted precedents disagree on disposition",
                          admissions=admitted, in_force=inf)

    if authority is None:
        if len(admitted) > 1:
            return Ruling(NO_CONTROLLING,
                          cause="more than one admitted precedent and no authority order",
                          admissions=admitted, in_force=inf)
        return Ruling(GOVERNED, controlling=admitted[0].precedent_id,
                      admissions=admitted, in_force=inf)

    ranked = sorted(admitted, key=authority)
    if len(ranked) > 1 and authority(ranked[0]) == authority(ranked[1]):
        return Ruling(NO_CONTROLLING,
                      cause="the authority order is not total on the admitted set",
                      admissions=admitted, in_force=inf)
    return Ruling(GOVERNED, controlling=ranked[0].precedent_id,
                  admissions=admitted, in_force=inf)


def _point_interval(dim: str, value: object) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return (1.0, 1.0) if value else (0.0, 0.0)
    try:
        v = float(value)                      # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return (v, v)
