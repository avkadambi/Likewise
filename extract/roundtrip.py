"""Measuring an extractor against ground truth that already exists.

The judiciary corpora carry **computed** ground truth: a record's factor values are known
by construction, not by adjudication. That is what makes the binding acceptance gate in
PRECEDENCE section 8 possible, and it makes something else possible too.

Render a record whose values are known into the prose a court would have written, extract
it back, and compare against the values you started with. The comparison needs no human
labelling at all -- which matters, because the one input `calibrate_extractor.py` cannot
synthesise is adjudicated truth, and a calibration fitted against the model's own output
measures nothing.

## What this measures, and what it does not

**Round-trip accuracy is an UPPER BOUND, not an estimate.** The renderer and the extractor
share a vocabulary: the renderer writes "prior record category III" and the extractor has
been trained on renderer output, so it reads exactly that. A real filing was written by
someone who had never seen the renderer. The number produced here is what the extractor
achieves when the prose is as cooperative as it will ever be, and the gap to a real docket
is unmeasured and unbounded.

This is the same discipline that marks Rosenbaum's gamma `not_applicable: generated_corpus`
rather than transplanting a number that looks like the lending one. Every report this
module emits carries the caveat as a field, not as a footnote.

**Style disjointness is a requirement, not a nicety.** If the styles used to train the
extractor also appear in the evaluation set, the measurement is of memorisation. The
renderer takes an explicit style, `split_styles()` partitions them, and `report()` refuses
to compute a headline when the two sets overlap -- the extraction analogue of the held-out
corpus revision that tolerance selection may not touch.

## The mathematics

Almost none, and that is deliberate -- the honesty of this harness lies in its
bookkeeping rather than in any estimator.

**Assertion precision**, not F1 and not accuracy. Precision is correct assertions over
all assertions; it deliberately ignores everything the extractor stayed silent about,
because a silence is not a wrong answer here, it is the absence of an answer. F1 would
average the expensive error (a hallucinated premise, which binds) against the cheap one
(a miss, which abstains) and produce a number that improves when the system takes more
risk.

**The undefined case is preserved rather than filled.** With zero assertions, precision
is 0/0. It is reported as None, never as 1.0, because an extractor that never speaks
would otherwise score perfectly -- the same trap the binding gate guards, and the reason
both gates carry an attainability floor on the number of decisions actually taken.

**A guard is a deterministic counterexample, not a sample.** Guard records are
constructed so that the only correct behaviour is silence; a single assertion on one is
a proof that the floor does not hold, which is why it fails at any n rather than
contributing to a rate.

## Why seven verdicts and not four

The extractor has three statuses and the truth has two states, and the six-way product
does not collapse into right and wrong. Asserting the wrong value and staying silent on a
value that was there are both "not correct", and they are not remotely the same error: one
binds a decision to a premise that is false, the other abstains. The taxonomy keeps them
apart because the acceptance gate weighs them differently.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .contract import ABSENT, ABSTAINED, OBSERVED, ExtractedRecord

# --- verdicts ---------------------------------------------------------------
CORRECT = "correct"                  # asserted, and right
WRONG = "wrong"                      # asserted, and contradicts the truth
HALLUCINATED = "hallucinated"        # asserted a value the record does not have
MISSED = "missed"                    # truth had a value; the extractor abstained
NOT_RENDERED = "not_rendered"        # truth had a value; the extractor saw nothing
CORRECT_SILENCE = "correct_silence"  # truth absent, extractor absent
CAUTIOUS = "cautious"                # truth absent, extractor abstained

VERDICTS = (CORRECT, WRONG, HALLUCINATED, MISSED, NOT_RENDERED, CORRECT_SILENCE, CAUTIOUS)

#: The expensive errors. Each one puts a value the record does not support in front of the
#: gate, where it can bind a decision to a premise nobody established.
ASSERTION_ERRORS = frozenset({WRONG, HALLUCINATED})
#: Verdicts in which the extractor spoke. The denominator of assertion precision.
ASSERTIONS = frozenset({CORRECT, WRONG, HALLUCINATED})
#: Verdicts in which it stayed silent. Cheap by construction: silence abstains.
SILENCES = frozenset({MISSED, NOT_RENDERED, CORRECT_SILENCE, CAUTIOUS})


@dataclass(frozen=True)
class Rendering:
    """One record, written out, with the values it was written from."""
    record_key: str
    prose: str
    truth: dict[str, Any]        # field -> value, or None for "the record has no value"
    style: str
    guard: bool = False          # rendered ambiguously ON PURPOSE; must never be asserted

    def digest(self) -> str:
        return hashlib.sha256(self.prose.encode()).hexdigest()[:16]


# --- rendering --------------------------------------------------------------
# Styles are deliberately plural and deliberately awkward. A renderer with one phrasing
# measures a lookup table. Each style is a different way a court might write the same
# fact, and `guard` styles are ways it might write something that LOOKS like the fact and
# is not.
STYLES = ("plain", "formal", "narrative", "tabular", "elliptical")
GUARD_STYLES = ("hedged", "negated", "third_party")
ALL_STYLES = STYLES + GUARD_STYLES


def _phrase(style: str, name: str, value: Any) -> str:
    label = name.replace("_", " ")
    if style == "plain":
        return f"The {label} is {value}."
    if style == "formal":
        return f"The court finds the {label} to be {value}."
    if style == "narrative":
        return f"Having reviewed the record, the {label} was determined at {value}."
    if style == "tabular":
        return f"{label}: {value}"
    if style == "elliptical":
        return f"{label} — {value}, as stipulated."
    # --- guards: the value appears in the text and is NOT the record's value ---
    if style == "hedged":
        # The number is present and explicitly not found. An extractor keying on
        # proximity asserts it; a correct one abstains.
        return f"Counsel asserted a {label} of {value}, which the court did not reach."
    if style == "negated":
        return f"The {label} is not {value}."
    if style == "third_party":
        return f"In the cited matter the {label} was {value}; the present case differs."
    raise ValueError(f"unknown style {style!r}")


def render(record: dict[str, Any], fields: Sequence[str], style: str,
           absent: Sequence[str] = (), guard_fields: Sequence[str] = (),
           preamble: str = "") -> Rendering:
    """Write a structured record out as prose.

    `absent` names fields the rendered document genuinely does not mention -- the truth
    for those is `None`, and a correct extractor returns ABSENT. `guard_fields` are
    written in a guard style: the value appears in the text but the record does not carry
    it, so any assertion is a hallucination by construction.
    """
    if style not in ALL_STYLES:
        raise ValueError(f"unknown style {style!r}; known: {ALL_STYLES}")
    absent_set, guard_set = set(absent), set(guard_fields)
    if absent_set & guard_set:
        raise ValueError(
            f"{sorted(absent_set & guard_set)} cannot be both absent and guarded; a "
            "guard has to appear in the text to be a guard")

    lines = [preamble] if preamble else []
    truth: dict[str, Any] = {}
    for name in fields:
        if name in absent_set:
            truth[name] = None
            continue
        if name in guard_set:
            # The value is in the prose and is not the record's. Truth is None: asserting
            # anything here is a hallucination however confident the extractor is.
            lines.append(_phrase(_guard_style_for(name, style), name, record.get(name)))
            truth[name] = None
            continue
        lines.append(_phrase(style, name, record.get(name)))
        truth[name] = record.get(name)

    key = str(record.get("record_key", "unknown"))
    return Rendering(record_key=key, prose="\n".join(lines), truth=truth,
                     style=style, guard=bool(guard_set))


def _guard_style_for(name: str, style: str) -> str:
    """Deterministic, so a corpus re-renders identically."""
    h = int(hashlib.sha256(f"{name}\x1f{style}".encode()).hexdigest(), 16)
    return GUARD_STYLES[h % len(GUARD_STYLES)]


def split_styles(train_fraction: float = 0.6) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition the non-guard styles into train and eval, disjointly.

    Guard styles go to eval only. A guard the extractor was trained on is not a guard.
    """
    n = max(1, round(len(STYLES) * train_fraction))
    if n >= len(STYLES):
        raise ValueError("train_fraction leaves no styles to evaluate on")
    return STYLES[:n], STYLES[n:] + GUARD_STYLES


# --- scoring ----------------------------------------------------------------
def verdict_for(status: str, extracted: Any, truth: Any,
                equal=lambda a, b: str(a).strip() == str(b).strip()) -> str:
    if status == OBSERVED:
        if truth is None:
            return HALLUCINATED
        return CORRECT if equal(extracted, truth) else WRONG
    if status == ABSTAINED:
        return MISSED if truth is not None else CAUTIOUS
    if status == ABSENT:
        return NOT_RENDERED if truth is not None else CORRECT_SILENCE
    raise ValueError(f"unknown status {status!r}")


@dataclass(frozen=True)
class Scored:
    record_key: str
    style: str
    guard: bool
    field: str
    verdict: str
    confidence: float | None
    floor: float | None


def score(extracted: ExtractedRecord, rendering: Rendering, equal=None) -> list[Scored]:
    kw = {"equal": equal} if equal else {}
    out = []
    for f in extracted.fields:
        if f.name not in rendering.truth:
            continue
        v = verdict_for(f.status, f.value, rendering.truth[f.name], **kw)
        out.append(Scored(record_key=extracted.record_key, style=rendering.style,
                          guard=rendering.guard, field=f.name, verdict=v,
                          confidence=f.confidence, floor=f.floor))
    return out


@dataclass
class Report:
    n_records: int = 0
    n_decisions: int = 0
    by_verdict: dict[str, int] = field(default_factory=lambda: dict.fromkeys(VERDICTS, 0))
    by_field: dict[str, dict[str, int]] = field(default_factory=dict)
    guard_assertions: list[dict] = field(default_factory=list)
    styles_seen: set = field(default_factory=set)
    caveat: str = ""
    gate: dict = field(default_factory=dict)

    @property
    def assertions(self) -> int:
        return sum(self.by_verdict[v] for v in ASSERTIONS)

    @property
    def assertion_precision(self) -> float | None:
        """Correct assertions over all assertions. `None` when nothing was asserted --
        NOT 1.0, which is what an extractor that never speaks would otherwise score."""
        n = self.assertions
        return None if n == 0 else self.by_verdict[CORRECT] / n

    @property
    def silence_rate(self) -> float | None:
        return None if self.n_decisions == 0 else (
            sum(self.by_verdict[v] for v in SILENCES) / self.n_decisions)

    def as_dict(self) -> dict:
        return {
            "n_records": self.n_records, "n_decisions": self.n_decisions,
            "assertions": self.assertions,
            "assertion_precision": (None if self.assertion_precision is None
                                    else round(self.assertion_precision, 6)),
            "silence_rate": (None if self.silence_rate is None
                             else round(self.silence_rate, 6)),
            "by_verdict": dict(self.by_verdict),
            "by_field": {k: dict(v) for k, v in sorted(self.by_field.items())},
            "guard_assertions": self.guard_assertions,
            "styles_evaluated": sorted(self.styles_seen),
            "caveat": self.caveat,
            "gate": self.gate,
        }


UPPER_BOUND_CAVEAT = (
    "Round-trip accuracy is an UPPER BOUND, not an estimate. The renderer and the "
    "extractor share a vocabulary; a real filing was written by someone who had never "
    "seen the renderer. The gap to a real docket is unmeasured and unbounded. Do not "
    "report this number as extraction accuracy on real records.")


def report(scored: Sequence[Scored], *, train_styles: Sequence[str] = (),
           min_assertions: int = 300, target_precision: float = 0.98) -> Report:
    """Aggregate, and apply the acceptance gate.

    The gate mirrors the binding gate in PRECEDENCE section 8, and for the same reason:
    perfect precision is trivially satisfiable by never speaking. Below the assertion
    floor the verdict is `inconclusive`, never `pass`. A single guard assertion fails at
    any n -- a guard is a case engineered so that the only correct behaviour is silence,
    and one bind on one guard is a demonstration that the floor does not hold.
    """
    r = Report(caveat=UPPER_BOUND_CAVEAT)
    keys = set()
    for s in scored:
        keys.add(s.record_key)
        r.n_decisions += 1
        r.by_verdict[s.verdict] += 1
        r.by_field.setdefault(s.field, dict.fromkeys(VERDICTS, 0))[s.verdict] += 1
        r.styles_seen.add(s.style)
        if s.guard and s.verdict in ASSERTIONS:
            r.guard_assertions.append(
                {"record_key": s.record_key, "field": s.field, "style": s.style,
                 "verdict": s.verdict, "confidence": s.confidence, "floor": s.floor})
    r.n_records = len(keys)

    leak = sorted(r.styles_seen & set(train_styles))
    prec = r.assertion_precision
    if leak:
        verdict, why = "invalid", (
            f"styles {leak} appear in both training and evaluation; the measurement is "
            "of memorisation, not extraction")
    elif r.guard_assertions:
        verdict, why = "fail", (
            f"{len(r.guard_assertions)} guard assertion(s). A guard is a record where "
            "the only correct behaviour is silence; one is a failure at any n.")
    elif r.assertions < min_assertions:
        verdict, why = "inconclusive", (
            f"{r.assertions} assertions against a floor of {min_assertions}. Perfect "
            "precision is satisfiable by never speaking, so too few assertions is not a "
            "pass.")
    elif prec is not None and prec >= target_precision:
        verdict, why = "pass", f"assertion precision {prec:.4f} >= {target_precision}"
    else:
        verdict, why = "fail", (
            f"assertion precision {prec if prec is None else round(prec, 4)} < "
            f"{target_precision}")

    r.gate = {"verdict": verdict, "why": why, "min_assertions": min_assertions,
              "target_precision": target_precision,
              "train_styles": sorted(train_styles), "style_leak": leak}
    return r


# --- closing the loop -------------------------------------------------------
def readings(scored: Sequence[Scored]) -> list[dict]:
    """The labelled readings `tools/calibrate_extractor.py` consumes.

    This is the payoff. Calibration needs, per reading, whether it was correct -- and that
    normally means a human reading the document. Here it is computed, because the record
    the prose was written from is known.

    Only assertions carry a `correct` label. A silence is not a reading with a wrong
    answer; it is the absence of one, and feeding silences to a threshold fitter as
    negatives would push the floor DOWN, which is precisely backwards.
    """
    return [
        {"field": s.field, "confidence": s.confidence,
         "token_probs": [s.confidence], "logits": None, "label": 0,
         "correct": s.verdict == CORRECT, "guard": s.guard, "style": s.style,
         "record_key": s.record_key}
        for s in scored if s.verdict in ASSERTIONS and s.confidence is not None
    ]


def write_readings(scored: Sequence[Scored], path: str) -> int:
    rows = readings(scored)
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return len(rows)
