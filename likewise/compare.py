"""The comparison lattice: what one dimension says about one pair.

Dominance used to be four Boolean clauses written directly into `evaluate()`, each one
folding the comparison and the decision rule together. That works for a single tested
denial reason and stops working the moment a second kind of question is asked of the
same machinery.

This module separates the two. A comparison answers *what the record shows* on one
dimension and returns a place in a five-element chain:

    STRICTLY_WORSE < WEAKLY_WORSE < {TIED, AMBIGUOUS, UNRECORDED} > WEAKLY_BETTER > STRICTLY_BETTER

The finding rule then quantifies over those results, and lives in the specification
rather than in this file.

Not being ordered is a first-class answer, not a missing one -- and it is THREE answers,
which an earlier version of this module collapsed into one:

    TIED        the order IS identified: the two records sit at the same value
    AMBIGUOUS   the published intervals overlap, so the record does not order them
    UNRECORDED  the record does not speak to this dimension at all

Under a flagging product the collapse is harmless: all three fail the existential strict
clause and nothing is emitted. Under a rule of PRECEDENCE the three diverge completely.
A tie is the strongest possible a-fortiori bind -- the present case matches the premise
exactly. An overlap is an ambiguous record. Silence is a dimension nobody checked. Read
as one value, the natural implementation binds in all three, and binding on silence
compels a disposition on a premise the case never established.

## The mathematics: a partial order, not a score

The object here is a PARTIAL ORDER over pairs, in the order-theory sense. A total order
ranks any two elements; a partial order admits pairs that are simply not comparable, and
that is not a gap to be filled but the honest content of the data. Two published
intervals that overlap are not ordered by the record, and no tie-break can create an
order the source does not contain.

The seven elements form a chain with a three-element unordered middle:

    STRICTLY_WORSE < WEAKLY_WORSE < {TIED, AMBIGUOUS, UNRECORDED} > WEAKLY_BETTER
                                                                  > STRICTLY_BETTER

Comparison is INTERVAL DOMINANCE. For intervals [a_lo, a_hi] and [d_lo, d_hi] and a
threshold t, one dominates the other only when it lies wholly beyond it by more than t:

    worse_by  = a_lo - d_hi        (when higher values are worse)
    better_by = d_lo - a_hi

Both quantities are computed, and the pair is decisive only when one exceeds t. Note
that these are NOT negatives of each other -- their sum is minus the combined interval
width -- so the relation is asymmetric in a way point comparison never is. A metamorphic
test pins that identity exactly.

Why a partial order rather than a similarity score: the admission region is a BOX, the
conjunction of per-dimension conditions. No additive or learned score has super-level
sets that are boxes in more than one dimension, so a score cannot reproduce this region;
it can only replace it with a different shape while reporting the same name.

`resolved` therefore marks TIED as resolved and the other two as not: an identified
equality is an order, an overlap and a silence are not.

In this domain the unordered family is also the common case: about 81.5% of
debt-to-income denials are structurally incapable of being ordered against any
comparator, because the file replaces the number with a band exactly where a lender
denying for debt-to-income would be. Folding that into "no finding" would report a
silence as an absence of a problem.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

# The chain, worst-for-the-approved-comparator first. `STRICTLY_WORSE` means the
# APPROVED record is worse than the denied one by more than the pair's threshold --
# which is the direction that makes the stated denial reason hard to justify.
STRICTLY_WORSE = "strictly_worse"
WEAKLY_WORSE = "weakly_worse"
TIED = "tied"
AMBIGUOUS = "ambiguous"
UNRECORDED = "unrecorded"
WEAKLY_BETTER = "weakly_better"
STRICTLY_BETTER = "strictly_better"

ORDERS = (STRICTLY_WORSE, WEAKLY_WORSE, TIED, AMBIGUOUS, UNRECORDED,
          WEAKLY_BETTER, STRICTLY_BETTER)

# The three ways a pair can fail to be ordered. Kept as a named set so a caller can ask
# the question without enumerating -- and so that adding a fourth is a change here
# rather than a silently missed branch somewhere else.
UNORDERED = frozenset({TIED, AMBIGUOUS, UNRECORDED})

# Legacy three-valued outcome, kept because it is what the finding schema, the web view
# and the mutation catalogue all speak. The lattice is the richer statement; this is the
# projection of it that the wire format has always carried.
LEGACY = {
    STRICTLY_WORSE: "not_supported",
    WEAKLY_WORSE: "below_resolution",
    TIED: "below_resolution",
    AMBIGUOUS: "below_resolution",
    UNRECORDED: "below_resolution",
    WEAKLY_BETTER: "below_resolution",
    STRICTLY_BETTER: "supported",
}


@dataclass(frozen=True)
class Comparison:
    """One dimension's verdict on one pair."""

    dimension: str
    order: str
    margin: float
    threshold: float
    resolved: bool          # did the published data identify an order at all?

    @property
    def outcome(self) -> str:
        return LEGACY[self.order]

    @property
    def decisive(self) -> bool:
        return self.order in (STRICTLY_WORSE, STRICTLY_BETTER)


def compare_intervals(dimension: str, a_iv: tuple[float, float],
                      d_iv: tuple[float, float], higher_is_worse: bool,
                      threshold: float) -> Comparison:
    """Place a pair on the chain from the two published intervals.

    The approved record is strictly worse only if its whole interval lies beyond the
    denied record's whole interval by more than the threshold. Where they overlap the
    order is not identified and the answer is AMBIGUOUS; where both are the same point
    value the order IS identified and the answer is TIED.

    WEAKLY_WORSE and WEAKLY_BETTER are the band between the two: the intervals do not
    overlap, so the direction IS identified, but the gap does not clear the pair's own
    resolution threshold. The legacy projection folds those into below_resolution --
    correctly, because a difference under the threshold is not a measurement -- but the
    distinction is real and worth carrying: "they do not overlap but the gap is under
    the floor" is a different statement from "the published values overlap".
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
        order = STRICTLY_WORSE
    elif better_by > threshold:
        order = STRICTLY_BETTER
    elif worse_by > 0:
        order = WEAKLY_WORSE
    elif better_by > 0:
        order = WEAKLY_BETTER
    elif a_lo == a_hi == d_lo == d_hi:
        # Two point values at the same place. The order IS identified -- they are equal --
        # and under a rule of precedence this is the strongest a-fortiori case there is.
        # Marking it unresolved made an exact match indistinguishable from a silence.
        order = TIED
    else:
        order = AMBIGUOUS

    margin = worse_by if math.isfinite(worse_by) else 0.0
    if order == STRICTLY_BETTER:
        margin = -better_by
    elif order == STRICTLY_WORSE:
        margin = worse_by
    # An identified equality is an order. An overlap and a silence are not.
    return Comparison(dimension, order, margin, threshold,
                      resolved=order not in (AMBIGUOUS, UNRECORDED))


def unresolved(dimension: str, threshold: float = 0.0) -> Comparison:
    """A dimension the record does not speak to at all -- a null on either side, or a
    value outside the window the regulator reports numbers in.

    Distinct from AMBIGUOUS, which is a record that spoke and did not settle the order.
    Under a rule of precedence the difference decides whether a premise was established."""
    return Comparison(dimension, UNRECORDED, float("nan"), threshold, resolved=False)
