"""Specification loading, validation and the startup gate.

Seven validation rules and the startup gate. Everything here is
FAIL-CLOSED: a running service always holds a valid, loaded, digested specification.

Frozen dataclasses, not Pydantic: Pydantic coerces "1.0" to 1.0 and fills
defaults the author did not write, so the parsed object stops being a faithful function
of the bytes whose digest every finding cites.


===============================================================================
THE ARITHMETIC IN THIS FILE: WHERE A "REAL DIFFERENCE" COMES FROM
===============================================================================

No inference happens here. What happens is ERROR PROPAGATION, and it decides the single
most consequential number in the product: how far apart two records must be before the
difference is treated as real.

The principle is the one every laboratory uses. You cannot measure a difference finer
than the resolution of your instrument, and when a quantity is DERIVED from other
measured quantities, the uncertainties of the inputs propagate into it. Here the
"instrument" is the regulator's rounding, and the derived quantity is typically a ratio.

Three floors compete, and the largest wins (`pair_threshold`):

  1. THE DECLARED MINIMUM -- a policy choice written into the signed budget. It is a
     floor, never a target, and it is never fitted to results.

  2. THE PUBLICATION FLOOR -- what the bin widths alone imply. If loan amount is
     published on $10,000 midpoints, no statement about a $3,000 difference in it is a
     measurement. Zero for a dimension the lender reports directly.

  3. THE COMPARABILITY FLOOR -- the interesting one. The matcher admits records that
     differ by up to its own tolerances, and for a DERIVED dimension that admitted slack
     propagates. Combined loan-to-value is 100*L/V, so a pair admitted with loan amounts
     differing by up to max(0.05L, $20,000) can differ in loan-to-value by

         100 * max(0.05L, 20000) / V

     purely from the matching tolerance, with no underwriting difference whatsoever.

That last expression is why the threshold is computed PER PAIR rather than declared once.
At a $285,000 property it is 7.0 percentage points; at $125,000 it is 16.0. A single
threshold certified at one reference magnitude passes wherever that reference sits and
fails everywhere cheaper -- failing, note, in the direction that MANUFACTURES findings,
in exactly the markets least able to absorb a false one. Below roughly $282,000 the
required gap exceeds the range most applications occupy at all, and the honest output is
that the method cannot speak there.

The resolution models (`RESOLUTION_MODELS`) are a CLOSED, NAMED set rather than
caller-supplied functions. A specification is signed and cited by digest on every result;
a digest over an arbitrary callable certifies nothing, so the set of ways to combine
these floors is fixed and versioned like everything else.

The eleven validation rules enforce the relationships between these quantities -- most
importantly rule 3 (a tolerance must be STRICTLY wider than granularity, or the band it
defines is empty) and rule 10 (a tolerance at or above a dimension's span switches the
dimension off rather than loosening it).
"""
from __future__ import annotations
import hashlib, json, math, os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import SpecError
from .schema import INTERNAL_SCHEMA, PROTECTED_CLASS_FIELDS


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Tolerance:
    field_name: str
    tolerance: float
    unit: str                      # relative | percentage_points | usd
    reference: str | None          # min | max | mean  (relative only)
    min_absolute: float | None
    rationale: str
    direction: str | None = None   # residual-risk dimensions only
    applies_when: dict | None = None

    def bound(self, a: float, b: float) -> float:
        """Absolute permitted difference for this pair.

        reference='min' makes the test symmetric, so match(a,b) == match(b,a)
        An unspecified denominator is how matching became asymmetric.
        """
        if self.unit != "relative":
            return float(self.tolerance)
        ref = min(a, b) if self.reference == "min" else (
            max(a, b) if self.reference == "max" else (a + b) / 2.0)
        return max(self.tolerance * abs(ref), self.min_absolute or 0.0)

    def within(self, a: float, b: float) -> bool:
        return abs(a - b) <= self.bound(a, b)


@dataclass(frozen=True)
class Dimension:
    name: str
    direction: str                 # higher_is_worse | higher_is_better

    def margin(self, approved: float, denied: float) -> float:
        """Signed margin. Negative => the DENIED file is no worse than the approved
        comparator on this dimension."""
        if self.direction == "higher_is_worse":
            return denied - approved
        if self.direction == "higher_is_better":
            return approved - denied
        raise ValueError(f"unknown direction {self.direction!r} on {self.name}")


@dataclass(frozen=True)
class ReasonCode:
    code: int
    label: str
    testable: bool
    dimensions: tuple[Dimension, ...]


@dataclass(frozen=True)
class Budget:
    version: str
    raw: dict
    digest: str

    def granularity(self, dim: str, value: float | None = None) -> float:
        d = self.raw["dimensions"][dim]
        g = float(d["granularity"])
        rng = d.get("integer_range")
        if rng and value is not None and not (rng[0] <= value <= rng[1]):
            return float(d.get("outside_range_width", g))
        return g

    def resolution_model(self, dim: str) -> str:
        """Which named model composes this dimension's threshold. Defaults to the
        strictest composition, which is what every dimension used before the models were
        named -- so an existing budget keeps its behaviour without being edited."""
        return self.raw["dimensions"].get(dim, {}).get("resolution_model", "strictest")

    def decisive_threshold(self, dim: str) -> float | None:
        v = self.raw["dimensions"].get(dim, {}).get("decisive_threshold")
        return None if v is None else float(v)

    def publication_floor(self, dim: str, ref: dict) -> float:
        """Irreducible resolution floor from publication binning alone, matcher
        tolerance set to zero. Nothing can measure below this on public data."""
        bd = self.raw["dimensions"].get(dim, {})
        tot = 0.0
        for src in (bd.get("depends_on") or []):
            w = self.raw.get("_bin_widths", {}).get(src)
            if w is None:
                continue
            d = _partial(dim, src, ref)
            if d is None:
                continue
            tot += (abs(d) * w / 2.0) ** 2
        return tot ** 0.5

    def worst_granularity(self, dim: str) -> float:
        d = self.raw["dimensions"][dim]
        return max(float(d["granularity"]), float(d.get("outside_range_width", 0.0)))


@dataclass(frozen=True)
class Spec:
    version: str
    raw: dict
    digest: str
    budget: Budget
    reasons: dict
    reasons_digest: str
    snapshot: dict
    snapshot_id: str

    # ---- derived accessors -------------------------------------------------
    def pair_threshold(self, dim: str, approved: dict, denied: dict) -> float:
        """The decisive threshold for one pair, at that pair's own magnitudes.

        Three quantities compete and the largest wins:

          * the declared minimum in the budget, which is a floor and a policy choice;
          * the publication floor, from the bin widths of whatever the dimension is
            derived from -- zero for a dimension the lender reports directly;
          * the comparability floor, the slack the matcher's own tolerances propagate
            into this dimension at these magnitudes.

        The third is why a scalar will not do. For a ratio of two binned quantities the
        comparability floor is 100*max(0.05L, 20000)/V, which is 7.0 percentage points
        at a $285,000 property and 16.0 at a $125,000 one. Certifying the threshold at a
        single reference point passes wherever the reference sits and fails everywhere
        cheaper -- in the direction that produces findings, in the markets least able to
        absorb a false one.
        """
        # Which of the named combination rules applies. Dispatch by NAME, not by a
        # supplied callable, so the choice is part of the signed artefact.
        model = self.budget.resolution_model(dim)
        if model not in RESOLUTION_MODELS:
            raise SpecError("unknown_resolution_model",
                            [{"dimension": dim, "resolution_model": model,
                              "known": sorted(RESOLUTION_MODELS)}])
        declared = self.budget.decisive_threshold(dim)
        base = float(declared) if declared is not None else 0.0
        # Evaluate the floors at the MINIMUM of the pair on each magnitude. Minimum,
        # not mean or maximum, because the floors are decreasing in the denominator: the
        # smaller magnitude produces the larger required gap, and taking anything else
        # would certify a threshold the cheaper half of the pair does not support.
        ref = {}
        for k in ("loan_amount", "property_value", "income",
                  "combined_loan_to_value_ratio", "debt_to_income_ratio"):
            vals = [v for v in (approved.get(k), denied.get(k)) if v is not None]
            if vals:
                ref[k] = min(vals)
        if not ref:
            return base or self.budget.granularity(dim, denied.get(dim))
        try:
            comp, _ = comparability_floor(self, dim, ref)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            # A dimension with no usable reference contributes no floor. Narrowed from a
            # bare catch: anything outside this set is a defect in the budget arithmetic
            # and must not be silently rounded down to zero, which would let a threshold
            # below the resolution the data supports pass the gate.
            comp = 0.0
        pub = self.budget.publication_floor(dim, ref)
        gran = self.budget.granularity(dim, denied.get(dim))
        return RESOLUTION_MODELS[model](base, comp, pub, gran)

    @property
    def blocking_key(self) -> list[str]:
        return list(self.raw["blocking"]["key"])

    @property
    def exact_match(self) -> list[str]:
        return list(self.raw["exact_match_required"])

    @property
    def control(self) -> dict[str, Tolerance]:
        return {k: Tolerance(k, float(v["tolerance"]), v["unit"], v.get("reference"),
                             v.get("min_absolute"), v.get("rationale", ""))
                for k, v in self.raw.get("control_features", {}).items()}

    @property
    def residual(self) -> dict[str, Tolerance]:
        return {k: Tolerance(k, float(v["tolerance"]), v["unit"], v.get("reference"),
                             v.get("min_absolute"), v.get("rationale", ""), v.get("direction"),
                             v.get("applies_when"))
                for k, v in self.raw.get("residual_risk", {}).items()}

    def reason(self, code: int) -> ReasonCode:
        r = self.reasons["codes"][code]
        dims = tuple(Dimension(d["field"], d["direction"]) for d in r.get("dimensions", []))
        return ReasonCode(code, r["label"], bool(r["testable"]), dims)

    @property
    def tested_dimensions(self) -> set[str]:
        out: set[str] = set()
        for r in self.reasons["codes"].values():
            if r.get("testable"):
                out.update(d["field"] for d in r.get("dimensions", []))
        return out

    @property
    def digests(self) -> dict[str, str]:
        return {"materiality": self.digest, "reasons": self.reasons_digest,
                "budget": self.budget.digest}

    def stat(self, key: str, default=None):
        return self.raw.get("statistics", {}).get(key, default)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Resolution models
# ---------------------------------------------------------------------------
# How the competing floors combine into the threshold that decides one pair. Named,
# closed, and selected by string in the budget specification.
#
# A closed set rather than a user-supplied callable, deliberately. The specification is
# a signed, digested governance artifact that a lender has to be able to reproduce and
# rebut from the published file. An arbitrary function in a spec is neither reviewable
# nor comparable across versions by digest, and it reintroduces the "given our model"
# problem that keeping the standard declarative exists to avoid. Adding a model is a
# code change with a review; choosing one is a specification change with a rationale.
#
# Each takes the four candidate floors and returns the applied threshold:
#   declared -- the policy minimum stated in the budget
#   comp     -- slack the matcher's own tolerances propagate into this dimension
#   pub      -- irreducible floor from publication binning alone
#   gran     -- the dimension's own published granularity

def _strictest(declared: float, comp: float, pub: float, gran: float) -> float:
    """Every floor binds; the largest wins. Correct whenever a dimension is downstream
    of matched fields, which is the case that motivated the whole resolution budget."""
    return max(declared, comp, pub, gran)


def _declared_only(declared: float, comp: float, pub: float, gran: float) -> float:
    """The policy minimum alone, floored at the dimension's own granularity. For a
    dimension with no algebraic dependence on any matched field, where the comparability
    floor is zero by construction and computing it only adds a way to be wrong."""
    return max(declared, gran)


def _publication_only(declared: float, comp: float, pub: float, gran: float) -> float:
    """Publication binning and granularity, ignoring matcher slack. For a dimension that
    is tested but not matched on, and not derived from anything that is."""
    return max(declared, pub, gran)


RESOLUTION_MODELS = {
    "strictest": _strictest,
    "declared_only": _declared_only,
    "publication_only": _publication_only,
}


# Cross-feature comparability
# ---------------------------------------------------------------------------
def comparability_floor(spec: Spec, dim: str, ref: dict[str, float]) -> tuple[float, dict]:
    """Uncertainty in `dim` induced by fields the matcher treats as equal-within-tolerance.

    A tested dimension algebraically downstream of a matched control field inherits that
    field's permitted slack. If the slack exceeds the margin we call decisive, the
    "finding" is inside noise the matcher itself allows.

    Returns (floor, explanation).
    """
    bd = spec.budget.raw["dimensions"].get(dim, {})
    depends = bd.get("depends_on") or []
    ctrl = spec.control
    terms = {}
    total = 0.0
    for src in depends:
        if src not in ctrl:
            continue                      # not matched => contributes no *matching* slack
        v = ref.get(src)
        if v is None:
            continue
        slack = ctrl[src].bound(v, v)     # permitted |delta| at this magnitude
        d = _partial(dim, src, ref)
        if d is None:
            continue
        contrib = abs(d) * slack
        terms[src] = {"slack": slack, "d_dim_d_src": d, "contribution": contrib}
        total += contrib ** 2
    return math.sqrt(total), {"terms": terms, "reference": ref}


def _partial(dim: str, src: str, ref: dict[str, float]) -> float | None:
    """Analytic partial derivative for the derivations we support."""
    if dim == "combined_loan_to_value_ratio":
        L, V = ref.get("loan_amount"), ref.get("property_value")
        if not L or not V:
            return None
        if src == "loan_amount":
            return 100.0 / V
        if src == "property_value":
            return -100.0 * L / (V * V)
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate(spec: Spec, gate_reference: dict[str, float]) -> None:
    f: list[dict[str, Any]] = []
    raw, budget = spec.raw, spec.budget

    # Rule 1 -- every named field exists in the internal schema.
    named = set(spec.blocking_key) | set(spec.exact_match) | set(spec.control) \
        | set(spec.residual) | spec.tested_dimensions
    for name in sorted(named):
        if name not in INTERNAL_SCHEMA:
            f.append({"rule": 1, "field": name, "problem": "not in internal schema"})

    # Rule 1b -- protected-class guard.
    for name in sorted(named & PROTECTED_CLASS_FIELDS):
        f.append({"rule": "1b", "field": name,
                  "problem": "protected-class field may not appear in key/features"})

    # Rule 2 -- relative tolerances declare reference and min_absolute.
    for group in (spec.control, spec.residual):
        for name, t in group.items():
            if t.unit == "relative":
                if t.reference is None:
                    f.append({"rule": 2, "field": name, "problem": "relative tolerance without 'reference'"})
                if t.min_absolute is None:
                    f.append({"rule": 2, "field": name, "problem": "relative tolerance without 'min_absolute'"})

    # Rule 3 -- tolerance STRICTLY greater than granularity.
    for name, t in {**spec.control, **spec.residual}.items():
        if name not in budget.raw["dimensions"]:
            continue
        aw = getattr(t, "applies_when", None)
        if aw and aw.get("integer_range"):
            rng = budget.raw["dimensions"][name].get("integer_range")
            g = budget.granularity(name, (rng[0] + rng[1]) / 2 if rng else None)
        else:
            g = budget.worst_granularity(name)
        if t.unit == "relative":
            bound = t.bound(gate_reference.get(name, 0.0) or 0.0, gate_reference.get(name, 0.0) or 0.0)
        else:
            bound = t.tolerance
        if not bound > g:
            f.append({"rule": 3, "field": name, "tolerance_at_reference": bound,
                      "granularity": g, "problem": "tolerance must be STRICTLY greater than granularity"})

    # Rule 4 -- blocking key subset of exact-match, and includes lei.
    if "lei" not in spec.blocking_key:
        f.append({"rule": 4, "problem": "blocking.key must include 'lei'"})
    extra = sorted(set(spec.blocking_key) - set(spec.exact_match) - {"lei"})
    if extra:
        f.append({"rule": 4, "fields": extra,
                  "problem": "blocking.key must be a subset of exact_match_required (union lei); "
                             "otherwise blocking can drop a pair the matcher would accept"})

    # Rule 5 -- the blocking band must be at least as wide as whatever tolerance the
    # matcher will apply to the same field, on BOTH terms. Otherwise blocking silently
    # discards pairs the matcher would have accepted, and the loss is invisible: it
    # happens before anything is counted.
    #
    # A banded field may be a control feature (a two-sided membership condition) or a
    # residual-risk dimension (a one-sided condition on the finding). Either way the
    # band has to cover it. A band on a field that is neither is a constraint nothing
    # justifies, and is rejected as dead configuration rather than left to puzzle a
    # reader.
    band = raw["blocking"]["band"]
    for name, b in band.items():
        t = spec.control.get(name) or spec.residual.get(name)
        if t is None:
            f.append({"rule": 5, "field": name,
                      "problem": "banded field is neither a control feature nor a "
                                 "residual-risk dimension"})
            continue
        if float(b.get("relative", 0)) < t.tolerance:
            f.append({"rule": 5, "field": name, "band_relative": b.get("relative"),
                      "tolerance": t.tolerance, "problem": "band.relative < feature.tolerance"})
        if float(b.get("min_absolute", 0)) < float(t.min_absolute or 0):
            f.append({"rule": 5, "field": name, "band_min_absolute": b.get("min_absolute"),
                      "min_absolute": t.min_absolute,
                      "problem": "band.min_absolute < feature.min_absolute -- blocking would drop "
                                 "pairs the matcher accepts, concentrated at low magnitudes"})

    # Rule 6 -- disclosure floor.
    disc = raw.get("disclosure", {})
    if int(disc.get("k_min", 0)) < 5:
        f.append({"rule": 6, "k_min": disc.get("k_min"), "problem": "k_min must be >= 5"})
    if disc.get("geography_ceiling") != "county":
        f.append({"rule": 6, "geography_ceiling": disc.get("geography_ceiling"),
                  "problem": "geography_ceiling must be 'county'"})

    # Rule 7 -- every tolerance carries a rationale.
    for name, t in {**spec.control, **spec.residual}.items():
        if not t.rationale.strip():
            f.append({"rule": 7, "field": name, "problem": "missing rationale"})

    # Rule 8 -- a tested dimension is never matched on.
    #
    # Matching a dimension and then testing it are contradictory operations: the matcher
    # forces the two records close on the field, and the test then asks whether they
    # differ on it. Whatever survives is a difference the matcher already declared
    # immaterial. Dominance replaces the tolerance on the tested dimension, and the
    # tested dimension must therefore be absent from the key, the exact-match set and
    # the bands.
    #
    # The design has said this since dominance was introduced. Nothing checked it, so it
    # held only because the specification in force happened to satisfy it -- which is
    # the same shape as every other defect this gate exists to catch.
    tested = spec.tested_dimensions
    for where, fields in (("blocking.key", set(spec.blocking_key)),
                          ("exact_match_required", set(raw.get("exact_match_required") or [])),
                          ("blocking.band", set((raw.get("blocking") or {}).get("band") or {}))):
        clash = sorted(tested & fields)
        if clash:
            f.append({"rule": 8, "where": where, "fields": clash,
                      "problem": "a tested dimension may not also be matched on; "
                                 "dominance replaces the tolerance on the tested dimension"})

    # Rule 10 -- a tolerance at or above a dimension's own span is not a tolerance.
    #
    # A boolean factor spans 1.0, so a tolerance of 1.0 admits every case regardless of
    # the factor: the dimension has stopped participating. Under a flagging product that
    # only loses findings. Under a rule of precedence it means a premise dimension is
    # silently switched off and the precedent binds on the rest -- a policy change with
    # no version, no author and no rationale, effected by a number.
    for name, t in {**spec.control, **spec.residual}.items():
        span = _declared_span(spec, name)
        if span is not None and t.tolerance >= span:
            f.append({"rule": 10, "field": name, "tolerance": t.tolerance, "span": span,
                      "problem": "tolerance at or above the dimension's own span; the "
                                 "dimension cannot distinguish anything and has been "
                                 "switched off rather than loosened"})

    # Rule 11 -- a relative tolerance declares which side it is measured against.
    #
    # Rule 5 compares the band coefficient against the tolerance coefficient as scalars.
    # That comparison is sound only when the tolerance is evaluated at the SMALLER of the
    # two magnitudes; at "max" or "mean" the same coefficient buys a wider absolute
    # window than the band, and blocking can drop a pair the matcher accepts -- exactly
    # the loss rule 5 exists to prevent, reintroduced through the reference side.
    for name, t in {**spec.control, **spec.residual}.items():
        if t.unit != "relative":
            continue
        if t.reference is None:
            f.append({"rule": 11, "field": name,
                      "problem": "relative tolerance without a declared reference side"})
        elif t.reference != "min" and name in (raw.get("blocking") or {}).get("band", {}):
            f.append({"rule": 11, "field": name, "reference": t.reference,
                      "problem": "a banded relative tolerance must be referenced to 'min'; "
                                 "rule 5's scalar comparison is unsound otherwise"})

    # Rule 9 -- a residual-risk band must be strictly wider than its own tolerance.
    #
    # Clause 4 asks whether the approved comparator is strictly BETTER beyond tolerance
    # on a residual dimension. If blocking already bands that dimension at exactly the
    # tolerance, every pair that could fire the clause was filtered out before the clause
    # ran: the test is live in the code and dead in effect. Rule 5 requires band >=
    # tolerance for coverage; this requires the inequality to be strict, for power.
    band = (raw.get("blocking") or {}).get("band") or {}
    for name, t in spec.residual.items():
        b = band.get(name)
        if not b:
            continue
        rel, tol = float(b.get("relative", 0.0)), float(t.tolerance)
        if rel <= tol:
            f.append({"rule": 9, "field": name, "band_relative": rel, "tolerance": tol,
                      "problem": "residual-risk band is not wider than its own tolerance, "
                                 "so blocking removes every pair the residual clause "
                                 "could fire on"})

    if f:
        raise SpecError("materiality_specification_invalid", f)


# The version in force. A DEFAULT ARGUMENT IS NOT A DECISION: `load(spec_dir)` with no
# version silently served materiality 1.0.0 -- unsigned, with no `comparison` block, so
# the multi-code policy came from a Python fallback rather than from the specification
# that declares it a versioned decision with a rationale. Naming it here makes the choice
# visible in one place and lets the serve-time check below refuse an unsigned one.
IN_FORCE = "1.4.0"


def load_in_force(spec_dir: str | Path = "specs",
                  gate_reference: dict[str, float] | None = None) -> Spec:
    """Load the specification a SERVICE may serve, as opposed to one a replay may read.

    Historical versions load fine for replay -- a decision must be reproducible against
    the standard in force when it was made. But a service may not serve a specification
    that has not been signed: a governance artifact claiming an authority it does not
    carry is worse than one that admits it has none.
    """
    version = os.environ.get("LIKEWISE_SPEC_VERSION", IN_FORCE)
    spec = load(spec_dir, version=version, gate_reference=gate_reference)
    author = str(spec.raw.get("author") or "").strip()
    if not author or author.lower() == "unsigned":
        raise SpecError("unsigned_specification_in_force",
                        [{"version": spec.version, "author": spec.raw.get("author"),
                          "problem": "a service may not serve an unsigned specification; "
                                     "historical versions remain loadable for replay"}])
    return spec


def _declared_span(spec: Spec, dim: str) -> float | None:
    """The full range a dimension can take, where the budget declares one.

    Returns None when no span is declared -- an unbounded dimension cannot have a
    vacuous tolerance, so the rule does not bind on it.
    """
    bd = spec.budget.raw["dimensions"].get(dim, {})
    span = bd.get("span")
    if span is not None:
        return float(span)
    rng = bd.get("integer_range")
    if rng:
        return float(rng[1]) - float(rng[0])
    return None


def _startup_gate(spec: Spec, gate_reference: dict[str, float]) -> dict:
    """The startup gate.

    Under dominance (s8.1) a tested dimension has no upper tolerance, so the v0.5 band
    check `granularity < |m| <= tolerance` no longer applies as written. What must still
    hold is the substantive condition it was standing in for:

        the margin we are willing to call decisive must exceed the uncertainty
        propagated from the fields the matcher treats as equal.

    Otherwise a finding sits inside slack the matcher itself permits.
    """
    failures: list[dict[str, Any]] = []
    report: dict[str, Any] = {}

    for dim in sorted(spec.tested_dimensions):
        bd = spec.budget.raw["dimensions"].get(dim)
        if bd is None:
            failures.append({"gate": "budget_entry_missing", "dimension": dim,
                             "problem": "tested dimension has no resolution-budget entry"})
            continue
        rod = bd.get("reported_or_derived")
        if rod not in ("reported", "derived"):
            failures.append({"gate": "reported_or_derived_undeclared", "dimension": dim})
            continue
        if rod == "derived" and not bd.get("derivation"):
            failures.append({"gate": "derivation_missing", "dimension": dim,
                             "problem": "derived dimension must show its derivation"})
        bdim = spec.budget.raw["dimensions"][dim]
        if bdim.get("restricted_to_integer_range"):
            rng = bdim.get("integer_range")
            g = spec.budget.granularity(dim, (rng[0] + rng[1]) / 2 if rng else None)
        else:
            g = spec.budget.worst_granularity(dim)
        floor, expl = comparability_floor(spec, dim, gate_reference)
        pub = spec.budget.publication_floor(dim, gate_reference)
        required = max(g, floor, pub)
        declared = spec.budget.decisive_threshold(dim)
        decisive = declared if declared is not None else required
        report[dim] = {"reported_or_derived": rod, "granularity": g,
                       "restricted_to_integer_range": bool(bdim.get("restricted_to_integer_range")),
                       "comparability_floor": round(floor, 4),
                       "publication_floor": round(pub, 4),
                       "decisive_threshold": decisive,
                       "declared": declared is not None,
                       "propagation": expl["terms"]}
        if declared is not None and declared + 1e-9 < required:
            failures.append({
                "gate": "decisive_threshold_below_floor", "dimension": dim,
                "declared": declared, "required": round(required, 4),
                "granularity": g, "comparability_floor": round(floor, 4),
                "publication_floor": round(pub, 4),
                "problem": "declared decisive_threshold is below the resolution the data supports"})
        elif declared is None and floor > g:
            failures.append({
                "gate": "cross_feature_consistency", "dimension": dim,
                "granularity": g, "comparability_floor": round(floor, 4),
                "reference": gate_reference, "propagation": expl["terms"],
                "problem": ("uncertainty propagated from matched control fields exceeds this "
                            "dimension's own granularity; a margin at granularity would be "
                            "inside slack the matcher permits"),
                "remedy": ("tighten the control tolerance on the contributing field(s), or "
                           "declare a decisive_threshold >= the floor, or drop the dimension"),
            })
    if failures:
        raise SpecError("startup_gate_failed", failures)
    return report


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
DEFAULT_GATE_REFERENCE = {"loan_amount": 270000.0, "property_value": 285000.0,
                          "income": 88000.0, "debt_to_income_ratio": 40.0,
                          "combined_loan_to_value_ratio": 94.0}


def load(spec_dir: str | Path = "specs", version: str | None = None,
         gate_reference: dict[str, float] | None = None) -> Spec:
    """Load a specification. `version=None` means the one IN FORCE.

    This default used to be the string "1.0.0", and every caller that did not pass a
    version inherited it: the whole test suite through its shared fixture, `run_scan.py`,
    and -- until 0.8.0 -- the service itself. The service was fixed and the rest was not,
    which left the product validating and scanning under a standard three versions behind
    the one it served. A default that names a specific historical version is a decision
    nobody revisits, so there is no longer one: a caller either accepts what is in force
    or names the version it means, and naming it is what a replay is supposed to do.
    """
    version = version or IN_FORCE
    d = Path(spec_dir)
    mraw = (d / "materiality" / f"{version}.yaml").read_bytes()
    m = yaml.safe_load(mraw)
    braw = (d / "budget" / f"{m['budget']}.json").read_bytes()
    b = json.loads(braw)
    rver = m.get("reasons", "1.0.0")
    rraw = (d / "reasons" / f"{rver}.yaml").read_bytes()
    r = yaml.safe_load(rraw)
    sraw = (d / "snapshots" / f"{m['bin_snapshot']}.json").read_bytes()
    s = json.loads(sraw)

    spec = Spec(version=m["version"], raw=m, digest=_digest(mraw),
                budget=Budget(b["version"], b, _digest(braw)),
                reasons=r, reasons_digest=_digest(rraw),
                snapshot=s, snapshot_id=s["snapshot_id"])

    ref = gate_reference or DEFAULT_GATE_REFERENCE
    _validate(spec, ref)
    object.__setattr__(spec, "gate_report", _startup_gate(spec, ref))
    return spec
