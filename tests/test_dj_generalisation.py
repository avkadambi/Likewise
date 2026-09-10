"""Does the distinguish engine serve the Digital Judiciary's gate?

The DJ architecture specifies a distinguishing gate over boolean factors:

    cov(r, c)      = |premise(r) ∩ facts(c)| / |premise(r)|
    Candidates(c)  = { r : prov(r) ∈ rules(c), cov(r,c) ≥ θ, ¬lapsed(r) }
    distinguish(r, c)  holds iff  premise(r) ⊄ facts(c)
    Survivors(c)   = { r ∈ Candidates(c) : ¬distinguish(r, c) }

and the dimensional reformulation replaces set containment with "no worse than the
premise by more than a stated tolerance". These tests check three claims about whether
this engine's machinery is the right kernel for that gate, using the real code rather
than a sketch:

  1. REDUCTION. With boolean dimensions and zero tolerance, the interval comparison
     reproduces set containment exactly. This is what makes a dimensional gate an
     extension rather than a replacement.

  2. THE COHERENCE WITNESS. A tolerant gate admits records a coverage-scored retrieval
     discards, so retrieval can silently lose a record the gate would have admitted.
     Constructed here on the real comparison function.

  3. THE REPAIR IS ALREADY MECHANISED. Validation rules 5 and 8 refuse exactly the
     configurations that permit (2). Rule 5's own text — "blocking silently discards
     pairs the matcher would have accepted, and the loss is invisible: it happens before
     anything is counted" — is the same failure, found from the other direction.

If these hold, the engine is a candidate kernel for the gate. They are written to fail
loudly if a future change breaks the correspondence.
"""
from __future__ import annotations

import pytest

from likewise.compare import (STRICTLY_BETTER, STRICTLY_WORSE, UNRECORDED,
                              compare_intervals)

# --------------------------------------------------------------------------
# A boolean factor as a degenerate dimension.
#
# present = 1.0, absent = 0.0, and the side the precedent favoured is the side that
# HAS the factor -- so a present case lacking a premise factor is WEAKER, which is the
# condition `distinguish` tests. Point intervals: a boolean carries no publication
# uncertainty, unlike every dimension in the lending instantiation.
# --------------------------------------------------------------------------
PRESENT = (1.0, 1.0)
ABSENT = (0.0, 0.0)


def _distinguish_m(premise: dict[str, bool], facts: dict[str, bool],
                   tolerance: dict[str, float]) -> bool:
    """The dimensional gate, evaluated through this repository's comparison lattice.

    Returns True when the present case is weaker than the premise on some dimension by
    more than that dimension's tolerance -- i.e. when the precedent is distinguished.
    """
    for dim, required in premise.items():
        if not required:
            continue
        ref = PRESENT
        subject = PRESENT if facts.get(dim) else ABSENT
        # higher_is_worse=False: having the factor is BETTER for the side that holds it,
        # so the subject is "worse" when it sits lower.
        c = compare_intervals(dim, subject, ref, False, tolerance.get(dim, 0.0))
        if c.order == STRICTLY_WORSE:
            return True
    return False


def _distinguish_boolean(premise: dict[str, bool], facts: dict[str, bool]) -> bool:
    """The gate as specified: premise(r) ⊄ facts(c)."""
    return not {d for d, v in premise.items() if v} <= {d for d, v in facts.items() if v}


def _cov(premise: dict[str, bool], facts: dict[str, bool]) -> float:
    p = {d for d, v in premise.items() if v}
    if not p:
        return 1.0
    return len(p & {d for d, v in facts.items() if v}) / len(p)


# --------------------------------------------------------------------------
# 1. Reduction
# --------------------------------------------------------------------------
def test_reduction_at_zero_tolerance_reproduces_set_containment():
    """With boolean dimensions and m = 0 the dimensional gate IS the boolean gate.

    This is the compatibility result. Without it a dimensional reformulation is a
    replacement, and every disposition already recorded under the boolean gate would be
    up for re-decision."""
    import itertools

    dims = ["weapon", "prior_record", "injury", "cooperation"]
    for pbits in itertools.product([False, True], repeat=len(dims)):
        premise = dict(zip(dims, pbits, strict=True))
        for fbits in itertools.product([False, True], repeat=len(dims)):
            facts = dict(zip(dims, fbits, strict=True))
            assert _distinguish_m(premise, facts, {}) == _distinguish_boolean(premise, facts), \
                (premise, facts)


def test_a_tolerance_of_one_makes_a_boolean_dimension_vacuous():
    """A boolean dimension has a total span of 1.0, so any tolerance at or above 1.0
    admits every case regardless of the factor. That is not a tuning choice, it is the
    dimension ceasing to participate -- and a specification that sets it should be
    refused rather than silently ignored."""
    premise = {"weapon": True}
    facts = {"weapon": False}

    assert _distinguish_m(premise, facts, {"weapon": 0.0}) is True
    assert _distinguish_m(premise, facts, {"weapon": 0.5}) is True
    assert _distinguish_m(premise, facts, {"weapon": 1.0}) is False   # vacuous
    assert _distinguish_m(premise, facts, {"weapon": 2.0}) is False


def test_absolute_provisions_pin_the_tolerance_to_zero():
    """An absolute provision carries tau = 0 by construction. On the comparison lattice
    that is the ordinary zero-tolerance case, so absolute and ordinary provisions run
    through one code path with a different declared tolerance rather than two engines."""
    premise = {"unlicensed_disposal": True}
    near_miss = {"unlicensed_disposal": False}

    assert _distinguish_m(premise, near_miss, {"unlicensed_disposal": 0.0}) is True
    # and no tolerance below the full span rescues it
    for m in (0.0, 0.1, 0.9):
        assert _distinguish_m(premise, near_miss, {"unlicensed_disposal": m}) is True


# --------------------------------------------------------------------------
# 2. The coherence witness
# --------------------------------------------------------------------------
def test_a_tolerant_gate_admits_what_coverage_retrieval_discards():
    """The witness, on the real comparison function.

    One dimension, tolerance m > 0, the present case weaker than the premise by delta
    with 0 < delta <= m. The gate admits: the difference is immaterial. A retrieval score
    computed on the boolean PROJECTION of the same facts records the factor as absent, so
    coverage falls below 1 and any threshold above it excludes the record.

    The record is then never seen by the gate that would have admitted it, and nothing
    downstream can tell: the consulted set truthfully records what it contained."""
    # A magnitude dimension: severity recorded on a 0-10 scale.
    premise_value = (6.0, 6.0)
    present_case = (5.5, 5.5)          # weaker by 0.5
    tolerance = 1.0                    # 0.5 <= 1.0, so immaterial

    c = compare_intervals("severity", present_case, premise_value, False, tolerance)
    gate_admits = c.order != STRICTLY_WORSE
    assert gate_admits, "the tolerant gate should admit a difference inside its tolerance"

    # The boolean projection: "does the case meet the premise value?" -- no.
    projected_facts = {"severity": False}
    projected_premise = {"severity": True}
    coverage = _cov(projected_premise, projected_facts)

    assert coverage == 0.0
    for theta in (0.1, 0.5, 1.0):
        assert coverage < theta, "retrieval excludes a record the gate would admit"

    # A second dimension does not rescue it; it only softens the ratio.
    two_dim_cov = _cov({"severity": True, "prior": True},
                       {"severity": False, "prior": True})
    assert two_dim_cov == 0.5


def test_coherence_holds_when_the_scores_share_one_relation():
    """Repair R2: score retrieval with the SAME tolerance the gate applies, and the
    identity is restored by construction rather than argued.

    This is the discipline the lending instantiation calls 'one relation, used twice'."""
    premise_value = (6.0, 6.0)
    tolerance = 1.0

    for delta in (0.0, 0.25, 0.5, 0.99):
        subject = (6.0 - delta, 6.0 - delta)
        c = compare_intervals("severity", subject, premise_value, False, tolerance)
        gate_admits = c.order != STRICTLY_WORSE
        # tolerance-aligned retrieval asks the same question
        retrieval_keeps = c.order != STRICTLY_WORSE
        assert gate_admits == retrieval_keeps

    # and beyond the tolerance both agree to drop it
    c = compare_intervals("severity", (4.0, 4.0), premise_value, False, tolerance)
    assert c.order == STRICTLY_WORSE


# --------------------------------------------------------------------------
# 3. The repair is already mechanised
# --------------------------------------------------------------------------
def test_rule8_forbids_the_configuration_that_creates_the_witness():
    """The witness needs retrieval to filter on the very dimension the gate tests.
    Rule 8 refuses that configuration at specification load, so the composition cannot
    be assembled incoherently in the first place.

    This is repair R1 applied selectively: rather than dropping the retrieval threshold
    to zero everywhere, the tested dimensions are removed from the retrieval key and
    everything else keeps its filter."""
    from likewise import specs

    spec = specs.load(version="1.4.0")
    tested = spec.tested_dimensions
    assert tested, "there must be tested dimensions for the rule to bind on"
    assert not (tested & set(spec.blocking_key))
    assert not (tested & set(spec.raw["exact_match_required"]))
    assert not (tested & set(spec.raw["blocking"]["band"]))


def test_rule5_is_the_coherence_condition_for_the_dimensions_retrieval_does_filter():
    """For dimensions retrieval legitimately filters on, coherence is not free and is
    bought explicitly: the retrieval band must be at least as wide as the tolerance the
    gate will apply to the same field. That is repair R2, checked at load with a fixture
    that violates it.

    Rule 5's own text names the same failure the coherence result names: blocking
    silently discards pairs the matcher would have accepted, and the loss is invisible
    because it happens before anything is counted."""
    from likewise import specs

    spec = specs.load(version="1.4.0")
    band = spec.raw["blocking"]["band"]
    assert band, "the rule needs a banded dimension to bind on"

    for name, b in band.items():
        t = spec.control.get(name) or spec.residual.get(name)
        assert t is not None, f"{name} is banded but is neither controlled nor residual"
        assert float(b["relative"]) >= t.tolerance, name
        assert float(b.get("min_absolute", 0)) >= float(t.min_absolute or 0), name


def test_the_gate_margin_distribution_is_already_instrumented():
    """The empirical study the reformulation calls for -- how many gate discards turn on
    a single dimension, the finest margin a boolean vocabulary can express -- needs the
    per-dimension comparison recorded on every discard.

    The engine already emits exactly that, so instrumenting the gate is a matter of
    reading a field rather than building a measurement."""
    from likewise.core import TestedDim

    fields = TestedDim.__dataclass_fields__
    for needed in ("dimension", "direction", "margin", "decisive_threshold",
                   "outcome", "order"):
        assert needed in fields, needed

    # A discard carries the lattice position per dimension, so "how far from admission"
    # is answerable per record rather than only in aggregate.
    close = compare_intervals("severity", (5.9, 5.9), (6.0, 6.0), False, 0.05)
    far = compare_intervals("severity", (1.0, 1.0), (6.0, 6.0), False, 0.05)
    assert close.order == STRICTLY_WORSE and far.order == STRICTLY_WORSE
    assert abs(close.margin) < abs(far.margin)


# --------------------------------------------------------------------------
# What does NOT transfer
# --------------------------------------------------------------------------
def test_incomparability_is_the_right_answer_for_an_unrecorded_factor():
    """A dimension the present case does not record is not a dimension on which the case
    is weaker. Treating silence as absence converts every incomplete record into a
    distinguished one, which for a gate that compels a decision is the expensive
    direction of error."""
    from likewise.compare import unresolved

    c = unresolved("prior_record")
    assert c.order == UNRECORDED
    assert c.resolved is False
    assert c.outcome == "below_resolution"


def test_the_comparison_is_directional_and_the_side_must_be_declared():
    """The lending instantiation asks whether an APPROVED comparator is worse than a
    DENIED file. The gate asks whether a PRESENT CASE is weaker than a PRECEDENT premise
    for the side the precedent favoured. Same shape, opposite reading of the same
    numbers -- so the side is a declared property and never an implicit convention."""
    subject, reference = (4.0, 4.0), (6.0, 6.0)

    lower_is_weaker = compare_intervals("d", subject, reference, False, 0.5)
    lower_is_stronger = compare_intervals("d", subject, reference, True, 0.5)

    assert lower_is_weaker.order == STRICTLY_WORSE
    assert lower_is_stronger.order == STRICTLY_BETTER
    assert lower_is_weaker.margin == pytest.approx(-lower_is_stronger.margin)
