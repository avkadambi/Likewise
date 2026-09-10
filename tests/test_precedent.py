"""Admission under a rule of precedence.

Under flagging, the cost of a wrong answer is an hour with a file. Under precedence it is
a compelled disposition with an accurate audit trail attached. These tests pin the four
properties that difference forces.
"""
from __future__ import annotations

import pytest

from likewise.compare import STRICTLY_WORSE, TIED, WEAKLY_WORSE
from likewise.precedent import (A_FORTIORI, ALL_DISTINGUISHED, CASE_OUTCOMES,
                                CONFLICT_UNRESOLVED, DISTINGUISHED, GOVERNED,
                                NO_CANDIDATES, NO_CONTROLLING, PREMISE_NOT_ESTABLISHED,
                                PREMISE_UNPROVEN, TOLERANT, Admission, PremiseDim,
                                Ruling, admit, rule, slack)

SEVERITY = PremiseDim("severity", weaker_when="lower", tolerance=1.0)
PRIORS = PremiseDim("priors", weaker_when="lower", tolerance=2.0)
ABSOLUTE = PremiseDim("unlicensed", weaker_when="lower", tolerance=0.0)


def _adm(pid, status):
    return Admission(pid, status, ())


# --------------------------------------------------------------------------
# 1. Silence never binds
# --------------------------------------------------------------------------
def test_a_case_silent_on_a_premise_dimension_does_not_bind():
    """The failure this module exists to prevent.

    Under flagging an unrecorded dimension produced a NaN margin, was excluded from the
    conjunction, failed the existential strict clause, and nothing was emitted -- the
    incompleteness was absorbed harmlessly. Under precedence the same record passes
    "not distinguished" and governs, and every field on the resulting decision is
    accurate. The defect is that "not shown weaker" was read as "shown at least as
    strong"."""
    a = admit("P1", [SEVERITY, PRIORS], facts={"severity": 6.0}, reference={"severity": 6.0,
                                                                            "priors": 2.0})
    assert a.status == PREMISE_UNPROVEN
    assert a.unproven == ("priors",)
    assert not a.admitted

    r = rule([a], retrieved_any=True)
    assert r.outcome == PREMISE_NOT_ESTABLISHED
    assert r.controlling is None


def test_silence_outranks_every_other_status():
    """A favourable recorded dimension must not rescue an unestablished premise. The
    ladder is ordered: unproven, then distinguished, then admitted."""
    # strong on severity, silent on priors
    a = admit("P1", [SEVERITY, PRIORS], facts={"severity": 9.0}, reference={"severity": 6.0,
                                                                            "priors": 2.0})
    assert a.status == PREMISE_UNPROVEN

    # weaker on severity AND silent on priors -- still unproven, not distinguished
    b = admit("P2", [SEVERITY, PRIORS], facts={"severity": 1.0}, reference={"severity": 6.0,
                                                                            "priors": 2.0})
    assert b.status == PREMISE_UNPROVEN
    assert b.distinguishing == ("severity",)


def test_an_ambiguous_interval_is_not_an_established_premise():
    """A record that spoke and did not settle the order is not a silence, but it is not
    an order either. Under precedence both fail to establish the premise."""
    def band(dim, value):
        if value is None:
            return None
        return (value - 1.0, value + 1.0) if dim == "severity" else (value, value)

    a = admit("P1", [SEVERITY], facts={"severity": 6.0}, reference={"severity": 6.0},
              interval=band)
    assert a.status == PREMISE_UNPROVEN
    assert a.unproven == ("severity",)


# --------------------------------------------------------------------------
# 2. A-fortiori is a distinct, stronger warrant
# --------------------------------------------------------------------------
def test_a_fortiori_does_not_depend_on_the_tolerance():
    """An admission where the case is at least as strong on every dimension survives the
    tolerance being set to zero. That is a different warrant from one resting on a
    declared materiality judgment, and the two are different liability positions."""
    exact = admit("P1", [SEVERITY], facts={"severity": 6.0}, reference={"severity": 6.0})
    assert exact.status == A_FORTIORI
    assert exact.comparisons[0].order == TIED

    stronger = admit("P2", [SEVERITY], facts={"severity": 9.0}, reference={"severity": 6.0})
    assert stronger.status == A_FORTIORI

    inside = admit("P3", [SEVERITY], facts={"severity": 5.5}, reference={"severity": 6.0})
    assert inside.status == TOLERANT
    assert inside.comparisons[0].order == WEAKLY_WORSE

    outside = admit("P4", [SEVERITY], facts={"severity": 2.0}, reference={"severity": 6.0})
    assert outside.status == DISTINGUISHED
    assert outside.comparisons[0].order == STRICTLY_WORSE

    # and the a-fortiori cases still admit with the tolerance removed entirely
    zero = PremiseDim("severity", weaker_when="lower", tolerance=0.0)
    assert admit("P1", [zero], {"severity": 6.0}, {"severity": 6.0}).status == A_FORTIORI
    assert admit("P3", [zero], {"severity": 5.5}, {"severity": 6.0}).status == DISTINGUISHED


def test_an_absolute_provision_admits_only_a_fortiori():
    """tau = 0 by construction, so there is no tolerant band to admit into."""
    assert admit("P", [ABSOLUTE], {"unlicensed": 1.0}, {"unlicensed": 1.0}).status == A_FORTIORI
    assert admit("P", [ABSOLUTE], {"unlicensed": 0.0}, {"unlicensed": 1.0}).status == DISTINGUISHED


# --------------------------------------------------------------------------
# 3. The empty set has four causes
# --------------------------------------------------------------------------
def test_the_abstention_causes_are_distinguishable():
    """Nothing retrieved, everything distinguished, a premise never established, and
    admitted-but-not-orderable are four different events. A naive implementation returns
    an empty list for all four and the audit trail cannot tell them apart."""
    assert rule([], retrieved_any=False).outcome == NO_CANDIDATES
    assert rule([_adm("A", DISTINGUISHED)]).outcome == ALL_DISTINGUISHED
    assert rule([_adm("A", PREMISE_UNPROVEN)]).outcome == PREMISE_NOT_ESTABLISHED
    assert rule([_adm("A", TOLERANT), _adm("B", TOLERANT)]).outcome == NO_CONTROLLING

    conflicting = [_adm("A", A_FORTIORI), _adm("B", A_FORTIORI)]
    r = rule(conflicting, authority=lambda a: (0,), disposition=lambda pid: pid)
    assert r.outcome == CONFLICT_UNRESOLVED

    assert {o for o in CASE_OUTCOMES} == {
        GOVERNED, NO_CANDIDATES, ALL_DISTINGUISHED, PREMISE_NOT_ESTABLISHED,
        NO_CONTROLLING, CONFLICT_UNRESOLVED}


def test_an_untotal_authority_order_abstains_rather_than_picking():
    """Two precedents of equal standing is a question for the constitution. Picking one
    silently -- by arrival order, which is what a max() over an unsorted set does -- is
    the failure mode this module exists to avoid."""
    tie = rule([_adm("A", A_FORTIORI), _adm("B", A_FORTIORI)], authority=lambda a: (1,))
    assert tie.outcome == NO_CONTROLLING

    ordered = rule([_adm("A", A_FORTIORI), _adm("B", A_FORTIORI)],
                   authority=lambda a: (0,) if a.precedent_id == "B" else (1,))
    assert ordered.outcome == GOVERNED
    assert ordered.controlling == "B"


def test_a_governed_ruling_must_name_its_controlling_precedent():
    """Enforced by the type, not by convention."""
    with pytest.raises(ValueError):
        Ruling(GOVERNED)
    with pytest.raises(ValueError):
        Ruling(NO_CANDIDATES, controlling="P1")
    with pytest.raises(ValueError):
        Ruling("something_else")


# --------------------------------------------------------------------------
# 4. No scalar can stand in for the partial order
# --------------------------------------------------------------------------
def test_no_weighted_score_reproduces_the_admission_region():
    """The admission region is a box: every dimension within its own tolerance. A
    weighted or additive score has a halfspace for a superlevel set, and a halfspace is a
    box only in one dimension.

    So no weighted similarity can be made order-consistent with admission, at any
    weights, for any threshold. This converts that from an argument into a failing
    assertion the moment somebody adds a score."""
    tol = {"a": 1.0, "b": 2.0}
    grid = [(x / 10, y / 10) for x in range(31) for y in range(41)]
    admits = {p: (p[0] <= tol["a"] and p[1] <= tol["b"]) for p in grid}

    for wa in (0.1, 0.25, 0.5, 0.75, 0.9):
        for t in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            scored = {p: (wa * p[0] + (1 - wa) * p[1] <= t) for p in grid}
            assert scored != admits, f"a halfspace matched the box at w={wa}, t={t}"

    # the Chebyshev minimum does reproduce it, exactly -- it is the admission test
    # wearing a number rather than a similarity
    cheb = {p: min(tol["a"] - p[0], tol["b"] - p[1]) >= 0 for p in grid}
    assert cheb == admits


def test_slack_is_signed_and_order_consistent():
    """Positive means admitted, negative means distinguished, and the sign is the whole
    content. It is a diagnostic for a specification author, not a field on a decision."""
    inside = admit("P", [SEVERITY], {"severity": 5.5}, {"severity": 6.0})
    outside = admit("P", [SEVERITY], {"severity": 2.0}, {"severity": 6.0})

    assert slack(inside.comparisons) > 0
    assert slack(outside.comparisons) < 0
    assert slack([]) is None


def test_a_ruling_carries_no_score_and_no_disposition():
    """Mechanised, because a caveat string has already failed at lower severity: this
    repository publishes rank_p_value and gamma_star per finding beside a field that says
    no significance is attached. A number printed next to a binding is read as the
    criterion for the binding whatever it is called.

    A future commit that adds a closeness score to the decision record breaks a test
    rather than a norm."""
    fields = Ruling.__dataclass_fields__
    banned = {"score", "similarity", "confidence", "closeness", "probability",
              "disposition", "p_value", "gamma_star"}
    assert not (set(fields) & banned), set(fields) & banned

    for name, f in fields.items():
        assert f.type != "float", f"{name} is a bare float on a decision record"


def test_the_side_is_declared_and_never_inferred():
    """The lending instantiation asks whether an approved comparator is worse than a
    denied file; the gate asks whether a present case is weaker than a precedent's
    premise. Same arithmetic, opposite reading -- so the reading is carried on the
    dimension and validated on construction."""
    lower_weak = PremiseDim("d", weaker_when="lower", tolerance=0.5)
    higher_weak = PremiseDim("d", weaker_when="higher", tolerance=0.5)

    assert admit("P", [lower_weak], {"d": 4.0}, {"d": 6.0}).status == DISTINGUISHED
    assert admit("P", [higher_weak], {"d": 4.0}, {"d": 6.0}).status == A_FORTIORI

    with pytest.raises(ValueError):
        PremiseDim("d", weaker_when="sideways")
    with pytest.raises(ValueError):
        PremiseDim("d", weaker_when="lower", tolerance=-1.0)
