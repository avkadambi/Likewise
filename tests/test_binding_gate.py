"""The binding acceptance gate.

`admit` and `rule` have unit tests, which show they do what they were written to do.
Nothing showed that what they were written to do is right on a corpus. This is that
question, and most of these tests are about the honesty of the measurement rather than its
arithmetic: an engine that never binds must not score, an oracle nobody independent checked
must not pass, and one bind on one guard must fail however good the aggregate looks.
"""
import pytest

from likewise import binding_gate as bg
from likewise.compare import STRICTLY_WORSE
from likewise.precedent import (ALL_DISTINGUISHED, GOVERNED, NO_CANDIDATES,
                                NO_CONTROLLING, PREMISE_NOT_ESTABLISHED, Admission,
                                PremiseDim, Ruling, admit, rule)


def _ruling(outcome, controlling=None):
    return Ruling(outcome, controlling=controlling)


def _case(i, expected=GOVERNED, controlling="p1", **kw):
    return bg.OracleCase(f"c{i:05d}", expected,
                         controlling if expected == GOVERNED else None, **kw)


def _run(cases, rulings, **kw):
    m = dict(zip([c.case_id for c in cases], rulings, strict=True))
    return bg.evaluate(cases, lambda c: m[c.case_id], **kw)


# --- the verdict taxonomy ----------------------------------------------------
def test_binding_on_the_wrong_precedent_is_a_false_bind():
    """Agreeing that SOMETHING governs is not agreeing. A decision compelled by the wrong
    precedent is compelled by a precedent that does not govern, which is the error the
    gate is built to bound."""
    o = _case(1, GOVERNED, "p1")
    assert bg.verdict_for(_ruling(GOVERNED, "p1"), o) == bg.BIND_AGREED
    assert bg.verdict_for(_ruling(GOVERNED, "p2"), o) == bg.BIND_WRONG_PRECEDENT
    assert bg.BIND_WRONG_PRECEDENT in bg.FALSE_BINDS


def test_the_expensive_errors_are_exactly_the_binds():
    """A missed bind costs a reviewer a case they must decide themselves. A false bind
    compels a decision, and its audit trail is accurate in every field."""
    assert bg.FALSE_BINDS == {bg.FALSE_BIND, bg.BIND_WRONG_PRECEDENT}
    assert bg.FALSE_BINDS < bg.BINDS
    assert bg.MISSED_BIND not in bg.BINDS


def test_agreeing_to_abstain_for_different_reasons_is_not_agreeing():
    """The six outcomes exist so that "nothing retrieved" and "everything distinguished"
    do not collapse into one empty set. A run whose abstentions are all correct for the
    wrong reason passes the gate and is still telling you something."""
    o = _case(1, ALL_DISTINGUISHED, None)
    assert bg.verdict_for(_ruling(ALL_DISTINGUISHED), o) == bg.ABSTAIN_AGREED
    assert bg.verdict_for(_ruling(NO_CANDIDATES), o) == bg.ABSTAIN_DIVERGED
    assert bg.verdict_for(_ruling(PREMISE_NOT_ESTABLISHED), o) == bg.ABSTAIN_DIVERGED


def test_divergent_abstentions_are_recorded_not_silently_counted():
    cases = [_case(i, ALL_DISTINGUISHED, None) for i in range(4)]
    rep = _run(cases, [_ruling(NO_CANDIDATES)] * 4, min_binds=1)
    assert len(rep.diverged) == 4
    assert rep.detail["abstention_divergence_count"] == 4


def test_the_outcome_confusion_covers_all_six():
    scored = [bg.score(_ruling(NO_CANDIDATES), _case(1, ALL_DISTINGUISHED, None))]
    conf = bg.outcome_confusion(scored)
    assert conf[ALL_DISTINGUISHED][NO_CANDIDATES] == 1
    assert len(conf[ALL_DISTINGUISHED]) == 6


# --- the oracle's own invariants ---------------------------------------------
def test_a_guard_that_expects_a_bind_is_not_a_guard():
    with pytest.raises(ValueError, match="wrong by construction"):
        bg.OracleCase("g1", GOVERNED, "p1", guard=True)


def test_an_expected_bind_must_name_its_precedent():
    """Otherwise the oracle cannot tell a right bind from a wrong one, and
    BIND_WRONG_PRECEDENT becomes unobservable."""
    with pytest.raises(ValueError, match="must name its controlling"):
        bg.OracleCase("c1", GOVERNED)


def test_only_an_expected_bind_may_name_a_precedent():
    with pytest.raises(ValueError, match="only an expected GOVERNED"):
        bg.OracleCase("c1", ALL_DISTINGUISHED, "p1")


# --- the bound ---------------------------------------------------------------
def test_the_exact_bound_reproduces_the_rule_of_three():
    """Section 8 quotes 300 for a 1% bound and 3000 for 0.1%. Computed exactly rather
    than approximated, those floors are 299 and 2995 -- the section's numbers are right
    and slightly conservative, which is the correct direction to be wrong in."""
    assert bg.clopper_pearson_upper(0, 300) <= 0.01
    assert bg.clopper_pearson_upper(0, 3000) <= 0.001
    assert bg.rule_of_three_n(0.01) == 299
    assert bg.rule_of_three_n(0.001) == 2995


def test_the_bound_is_usable_when_there_are_failures():
    """The rule of three only says anything at zero failures. The exact limit gives a
    bound either way, which is what makes a near miss legible instead of just failing."""
    assert bg.clopper_pearson_upper(0, 300) < bg.clopper_pearson_upper(1, 300)
    assert bg.clopper_pearson_upper(2, 300) < bg.clopper_pearson_upper(5, 300)
    assert bg.clopper_pearson_upper(10, 10) == 1.0


def test_the_bound_survives_the_sizes_the_gate_actually_runs_at():
    """The assertion floor puts n in the low thousands, and the bisection has to evaluate
    the binomial CDF at every k on the way. Formed as a direct product, the term at
    k = n/2 needs comb(2995, 1497) -- an exact integer of some nine hundred digits -- to
    become a float, which raises OverflowError even though the product it appears in is a
    probability. The sum is therefore taken in log space.

    Found by cross-validating the bound against the Beta quantile, not by any test here:
    every test in this file happened to use a small k."""
    for n in (500, 2995, 4000):
        for k in (0, 1, n // 4, n // 2, n - 1):
            v = bg.clopper_pearson_upper(k, n)
            assert 0.0 < v <= 1.0, (n, k, v)
    # At k = n/2 the upper limit must sit just above one half: the point estimate is 0.5
    # and the bound is one-sided, so anything far from it means the CDF is wrong rather
    # than merely imprecise.
    mid = bg.clopper_pearson_upper(1497, 2995)
    assert 0.50 < mid < 0.55, mid
    # Monotone in k at a size where the naive form overflows.
    assert (bg.clopper_pearson_upper(1000, 2995)
            < bg.clopper_pearson_upper(1497, 2995)
            < bg.clopper_pearson_upper(2000, 2995))


def test_the_bound_is_the_root_it_claims_to_be():
    """The definition, checked against itself: the returned p must solve
    P(X <= k | n, p) = alpha. Recomputed here from math.comb at sizes small enough for
    exact integer arithmetic, which is an independent route to the same number."""
    import math
    for n, k, alpha in ((30, 3, 0.05), (100, 10, 0.01), (60, 0, 0.05)):
        p_hat = bg.clopper_pearson_upper(k, n, alpha)
        cdf = sum(math.comb(n, i) * p_hat**i * (1 - p_hat) ** (n - i) for i in range(k + 1))
        assert abs(cdf - alpha) < 1e-9, (n, k, alpha, cdf)


def test_the_bound_refuses_impossible_inputs():
    for k, n in ((1, 0), (5, 3), (-1, 10)):
        with pytest.raises(ValueError):
            bg.clopper_pearson_upper(k, n)


# --- the trap ----------------------------------------------------------------
def test_never_binding_is_not_a_pass():
    """A false-bind rate of zero is satisfiable by abstaining on everything. The bound is
    None rather than 0.0, and the verdict is inconclusive rather than pass."""
    cases = [_case(i, ALL_DISTINGUISHED, None) for i in range(1000)]
    rep = _run(cases, [_ruling(ALL_DISTINGUISHED)] * 1000)
    assert rep.binds == 0
    assert rep.false_bind_upper() is None
    assert rep.verdict == "inconclusive"
    assert "never binding" in rep.cause


def test_too_few_binds_is_inconclusive_even_when_all_are_right():
    cases = [_case(i) for i in range(50)]
    rep = _run(cases, [_ruling(GOVERNED, "p1")] * 50, min_independent_binds=0)
    assert rep.false_binds == 0
    assert rep.verdict == "inconclusive"


def test_an_absolute_provision_raises_the_floor():
    """Section 8: 3000 for an absolute provision, where the tolerance is zero and there
    is no margin to absorb an error."""
    cases = [_case(i, absolute=(i == 0)) for i in range(400)]
    rep = _run(cases, [_ruling(GOVERNED, "p1")] * 400, min_independent_binds=0)
    assert rep.detail["min_binds_required"] == 3000
    assert rep.verdict == "inconclusive"


def test_one_guard_bind_fails_at_any_n():
    cases = ([_case(i, arm=bg.INDEPENDENT_ARM) for i in range(5000)]
             + [_case(99999, ALL_DISTINGUISHED, None, guard=True)])
    rep = _run(cases, [_ruling(GOVERNED, "p1")] * 5000 + [_ruling(GOVERNED, "pX")])
    assert rep.verdict == "fail"
    assert len(rep.guard_binds) == 1
    assert rep.false_bind_upper() < 0.002       # the aggregate would have passed


# --- oracle independence ------------------------------------------------------
def test_a_pass_on_a_self_authored_oracle_alone_is_not_a_pass():
    """Section 8's named risk: computed ground truth is a second program written from the
    same rulebook, so a shared misreading reads as perfect precision. The section proposes
    reporting the independent arm separately. Reporting is not enough -- an arm that is
    only ever reported is the arm that is quietly left empty."""
    cases = [_case(i) for i in range(400)]      # every one on the engine arm
    rep = _run(cases, [_ruling(GOVERNED, "p1")] * 400)
    assert rep.false_binds == 0 and rep.binds == 400
    assert rep.verdict == "inconclusive"
    assert "self-authored oracle" in rep.cause


def test_the_independent_arm_is_bounded_separately():
    cases = ([_case(i) for i in range(400)]
             + [_case(1000 + i, arm=bg.INDEPENDENT_ARM) for i in range(60)])
    rulings = ([_ruling(GOVERNED, "p1")] * 400
               + [_ruling(GOVERNED, "p1")] * 59 + [_ruling(GOVERNED, "pX")])
    rep = _run(cases, rulings)
    ind = rep.detail["independent_arm"]
    assert ind["binds"] == 60 and ind["false_binds"] == 1
    # Bounded on its own 60, not diluted by the 400 the same author wrote.
    assert ind["false_bind_upper_bound"] > rep.false_bind_upper()


def test_a_clean_run_passes():
    cases = ([_case(i) for i in range(280)]
             + [_case(1000 + i, arm=bg.INDEPENDENT_ARM) for i in range(40)]
             + [_case(2000 + i, ALL_DISTINGUISHED, None, guard=True) for i in range(20)])
    rulings = ([_ruling(GOVERNED, "p1")] * 320 + [_ruling(ALL_DISTINGUISHED)] * 20)
    rep = _run(cases, rulings)
    assert rep.verdict == "pass", rep.cause
    assert rep.binds == 320 and rep.false_binds == 0
    assert rep.false_bind_upper() <= 0.01


# --- what is reported and not gated -------------------------------------------
def test_missed_binds_are_reported_and_never_gated():
    """Gating recall would trade the expensive error for the cheap one: an engine tuned to
    bind more often binds more often wrongly."""
    cases = ([_case(i) for i in range(320)]
             + [_case(1000 + i) for i in range(680)]
             + [_case(2000 + i, arm=bg.INDEPENDENT_ARM) for i in range(5)])
    rulings = ([_ruling(GOVERNED, "p1")] * 320 + [_ruling(ALL_DISTINGUISHED)] * 680
               + [_ruling(GOVERNED, "p1")] * 5)
    rep = _run(cases, rulings)
    assert rep.missed_bind_rate > 0.6           # it abstains on most of the docket
    assert rep.verdict == "pass", rep.cause     # and that is not what this gate measures


def test_evaluating_on_the_cases_the_tolerances_were_fitted_to_is_invalid():
    cases = [_case(i) for i in range(400)]
    rep = _run(cases, [_ruling(GOVERNED, "p1")] * 400,
               tolerance_selection_cases=["c00003", "c00007"])
    assert rep.verdict == "invalid"
    assert rep.detail["tolerance_selection_leak"] == ["c00003", "c00007"]


# --- the demonstration: guards catch a permissive engine ----------------------
def _permissive_rule(candidates):
    """The engine `precedent.py` was written NOT to be: silence on a premise dimension is
    read as the case being at least as strong, so an unproven premise binds.

    It is not a straw man. Treating a missing value as "no worse" is the natural
    implementation, and it is exactly what the status ladder -- where PREMISE_UNPROVEN
    outranks DISTINGUISHED -- exists to forbid.
    """
    admitted = [a for a in candidates
                if a.status != "distinguished"]          # unproven counts as admitted
    if not admitted:
        return Ruling(ALL_DISTINGUISHED, cause="all distinguished")
    if len(admitted) > 1:
        return Ruling(NO_CONTROLLING, cause="no authority order")
    return Ruling(GOVERNED, controlling=admitted[0].precedent_id,
                  admissions=tuple(admitted))


def test_a_guard_where_the_case_is_silent_catches_the_permissive_engine():
    """Built on the real `admit`, not a mock. The case records nothing on the premise
    dimension, so the correct outcome is PREMISE_NOT_ESTABLISHED. The correct engine
    abstains; the permissive one binds and the guard catches it."""
    premise = [PremiseDim("severity", "higher", tolerance=2.0)]
    reference = {"severity": 10.0}
    silent_case = {}                                     # says nothing about severity

    a = admit("p1", premise, silent_case, reference)
    assert a.unproven == ("severity",), a

    correct = rule([a])
    assert correct.outcome == PREMISE_NOT_ESTABLISHED

    permissive = _permissive_rule([a])
    assert permissive.outcome == GOVERNED                # binds on a premise nobody proved

    guard = bg.OracleCase("g1", PREMISE_NOT_ESTABLISHED, guard=True)
    good = bg.evaluate([guard], lambda c: correct, min_binds=1, min_independent_binds=0)
    bad = bg.evaluate([guard], lambda c: permissive, min_binds=1, min_independent_binds=0)
    assert not good.guard_binds
    assert bad.verdict == "fail" and len(bad.guard_binds) == 1


@pytest.mark.parametrize("severity,status,outcome", [
    (4.0, "a_fortiori", GOVERNED),     # clearly weaker than the premise: binds
    (10.0, "a_fortiori", GOVERNED),    # exactly the premise: the strongest bind there is
    (11.0, "tolerant", GOVERNED),      # worse, but inside tolerance: still binds
    (40.0, "distinguished", ALL_DISTINGUISHED),   # beyond tolerance: does not bind
])
def test_the_correct_engine_binds_when_the_premise_is_established(severity, status,
                                                                 outcome):
    """A guard suite that only rewards abstention is passed by an engine that never binds,
    and the n floor is then never met. The demonstration has to show both halves, so this
    pins the whole admission ladder against a real reference rather than one point on it.
    """
    premise = [PremiseDim("severity", "higher", tolerance=2.0)]
    a = admit("p1", premise, {"severity": severity}, {"severity": 10.0})
    assert a.status == status
    assert a.unproven == ()
    assert rule([a]).outcome == outcome


def test_a_distinguished_candidate_does_not_bind():
    premise = [PremiseDim("severity", "higher", tolerance=1.0)]
    a = admit("p1", premise, {"severity": 40.0}, {"severity": 10.0})
    assert a.comparisons[0].order == STRICTLY_WORSE
    assert not a.admitted
    assert a.distinguishing == ("severity",)
    assert rule([a]).outcome == ALL_DISTINGUISHED


def test_the_report_serialises_without_losing_the_verdict():
    cases = [_case(i, arm=bg.INDEPENDENT_ARM) for i in range(320)]
    rep = _run(cases, [_ruling(GOVERNED, "p1")] * 320)
    d = rep.as_dict()
    assert d["verdict"] == rep.verdict
    assert d["binds"] == 320 and d["false_bind_upper_bound"] is not None
    assert set(d["by_verdict"]) == set(bg.VERDICTS)


def test_admission_dataclass_is_what_the_gate_expects():
    """A shape test, so a change to Admission's fields fails here rather than in a corpus
    run six months later."""
    a = Admission("p1", "a_fortiori", ())
    assert hasattr(a, "admitted") and hasattr(a, "unproven")
