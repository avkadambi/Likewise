"""Turning token probabilities into a decision to speak or stay silent.

This is the part of the extractor that carries the safety property, and it is written
against a measured finding rather than an intuition: encoder confidence collapses under
domain shift. In the one study that measures it on NER (arXiv 2608.19558), error-detection
AUROC fell from 0.922 in-domain to 0.633 out-of-domain, with expected calibration error
between 0.36 and 0.41 -- severely overconfident. Nothing published measures calibration
for ModernBERT, Ettin, EuroBERT, NeoBERT or mmBERT at all.

Three consequences, all implemented here:

1. **Temperature scaling, fitted per corpus.** Raw softmax outputs are not probabilities
   and must not be compared against a threshold as though they were.
2. **Span-level aggregation, weakest link by default.** The same study found span-
   restricted probability substantially more robust than sequence probability. `min` is
   the default because a span is only as identified as its least certain token, and a
   mean lets one confident token carry three unreadable ones.
3. **The floor is per corpus and per field, and it expires.** A threshold fitted on one
   court's filings says nothing about another's. `Calibration` carries the corpus it was
   fitted on so that using it elsewhere is a visible act.

## The mathematics

Three pieces, none of them exotic, all of them chosen for the same reason: they are the
smallest thing that does the job without importing a numerical stack the served engine
must never carry.

**Temperature scaling** (`temperature_scale`, `fit_temperature`). A single-parameter
recalibration: divide the logits by T before the softmax. T > 1 flattens the
distribution, T < 1 sharpens it, T = 1 is the identity. Crucially it is MONOTONE, so it
never changes which label wins -- accuracy is untouched and only the confidence moves.
T is fitted by minimising negative log-likelihood on held-out data. NLL is unimodal in
T, so a ternary search converges without a gradient, without an optimiser, and without
scipy: sixty iterations narrow [0.05, 10] to well below 1e-6.

**Span aggregation** (`span_confidence`). One number from several per-token
probabilities. The default is the MINIMUM -- the weakest link -- because a span is only
as identified as its least certain token, and because the published evidence on NER
under domain shift finds span-restricted probability more robust than the alternatives.
`mean` lets one confident token carry three unreadable ones; `product` is the joint
probability under an independence assumption the tokens plainly violate. Both are
available and declared; neither is the default.

**A precision-constrained threshold** (`floor_for_precision`). Not an F1 optimisation
and not a ROC point. Sweep every observed confidence as a candidate cut, keep those
whose precision meets a declared target, and among those take the LOWEST -- the most
permissive, because any higher cut buys precision the constraint did not ask for at the
cost of coverage. If no cut reaches the target, the function returns the achieved
precision rather than rounding up, and the calling tool refuses rather than lowering the
bar.

The error asymmetry runs the opposite way to a normal extraction task. A missed field is
cheap: it produces silence, and silence abstains. A hallucinated field is expensive: it
produces a bind on a premise nobody established. Fit for precision at a target recall,
never for F1 -- `floor_for_precision` does exactly that and nothing else.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

MIN = "min"
MEAN = "mean"
PRODUCT = "product"
AGGREGATIONS = (MIN, MEAN, PRODUCT)
DEFAULT_AGGREGATION = MIN


def temperature_scale(logits: Sequence[float], temperature: float) -> list[float]:
    """Softmax at temperature T. T == 1 is the identity; T > 1 flattens.

    Stdlib only. The whole engine avoids numpy deliberately, and a softmax over a label
    set of a few dozen does not need it.
    """
    if not (temperature > 0.0):
        raise ValueError(f"temperature must be positive, got {temperature}")
    if not logits:
        raise ValueError("no logits")
    # Divide by T, then softmax. Dividing BEFORE the exponential is what makes this a
    # temperature: it rescales the gaps between logits, which is what confidence is made
    # of, without reordering them.
    z = [v / temperature for v in logits]
    # Subtracting the maximum is the standard log-sum-exp trick. exp() of a large logit
    # overflows to inf; subtracting a constant from every term leaves the softmax exactly
    # unchanged (the constant cancels in numerator and denominator) and bounds every
    # exponent at zero.
    m = max(z)
    e = [math.exp(v - m) for v in z]          # shift for stability, not for taste
    s = sum(e)
    return [v / s for v in e]


def span_confidence(token_probs: Sequence[float],
                    aggregation: str = DEFAULT_AGGREGATION) -> float:
    """One number for a span, from its per-token probabilities."""
    if aggregation not in AGGREGATIONS:
        raise ValueError(f"unknown aggregation {aggregation!r}; known: {AGGREGATIONS}")
    if not token_probs:
        raise ValueError("a span with no tokens has no confidence")
    for p in token_probs:
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"{p} is not a probability")
    if aggregation == MIN:
        return min(token_probs)
    if aggregation == MEAN:
        return sum(token_probs) / len(token_probs)
    out = 1.0
    for p in token_probs:
        out *= p
    return out


@dataclass(frozen=True)
class Calibration:
    """A fitted decision rule, and the corpus it is only valid on."""
    corpus_id: str
    temperature: float
    aggregation: str
    floors: dict[str, float]              # per field
    target_precision: float
    fitted_n: int

    def __post_init__(self) -> None:
        if not (self.temperature > 0.0):
            raise ValueError("temperature must be positive")
        if self.aggregation not in AGGREGATIONS:
            raise ValueError(f"unknown aggregation {self.aggregation!r}")
        if not (0.0 < self.target_precision <= 1.0):
            raise ValueError("target_precision must be in (0, 1]")
        for k, v in self.floors.items():
            # A floor of zero is not a lenient threshold, it is the absence of one: the
            # extractor would assert every field it produced any output for, and the
            # abstention path -- the only thing standing between a guess and a bind --
            # would be unreachable.
            if not (0.0 < v <= 1.0):
                raise ValueError(
                    f"floor for {k!r} is {v}; must be in (0, 1]. A floor of 0 makes "
                    "abstention unreachable and is refused rather than clamped.")

    def floor_for(self, field_name: str) -> float:
        if field_name not in self.floors:
            raise KeyError(
                f"no floor calibrated for {field_name!r}. An uncalibrated field is not "
                "given a default -- a borrowed threshold is the failure this class of "
                "system is most prone to.")
        return self.floors[field_name]


def decide(field_name: str, value, confidence: float, cal: Calibration) -> tuple[str, float]:
    """(status, floor). The value itself is dropped by the caller when silent."""
    from .contract import ABSENT, ABSTAINED, OBSERVED
    floor = cal.floor_for(field_name)
    if value is None:
        return ABSENT, floor
    return (OBSERVED if confidence >= floor else ABSTAINED), floor


def floor_for_precision(scored: Sequence[tuple[float, bool]],
                        target_precision: float) -> tuple[float, float, float]:
    """The lowest threshold whose precision still meets the target.

    `scored` is (confidence, correct) over a held-out set. Returns
    (floor, precision_at_floor, recall_at_floor).

    Lowest, not best: among the thresholds that satisfy the precision constraint the one
    that keeps the most recall is chosen, because every point above it buys precision the
    constraint did not ask for at the cost of coverage the corpus cannot spare. If no
    threshold reaches the target the highest observed confidence is returned with its
    achieved precision, and the caller is expected to refuse rather than round up.
    """
    if not scored:
        raise ValueError("nothing to calibrate on")
    if not (0.0 < target_precision <= 1.0):
        raise ValueError("target_precision must be in (0, 1]")
    # Recall is measured against the correct readings available, not against every
    # reading: a threshold cannot recover something that was never right to begin with.
    total_correct = sum(1 for _, ok in scored if ok)
    # Only observed confidences can be optimal cut points -- between two adjacent
    # observed values every threshold keeps exactly the same set, so the finite candidate
    # list loses nothing. Sorted ASCENDING, which is what makes the first hit below the
    # most permissive qualifying threshold rather than merely a qualifying one.
    cands = sorted({c for c, _ in scored})
    best = None
    for t in cands:
        kept = [(c, ok) for c, ok in scored if c >= t]
        if not kept:
            continue
        prec = sum(1 for _, ok in kept if ok) / len(kept)
        rec = (sum(1 for _, ok in kept if ok) / total_correct) if total_correct else 0.0
        if prec >= target_precision:
            best = (t, prec, rec)
            break                      # ascending, so the first is the most permissive
    if best is None:
        t = cands[-1]
        kept = [(c, ok) for c, ok in scored if c >= t]
        prec = sum(1 for _, ok in kept if ok) / len(kept)
        rec = (sum(1 for _, ok in kept if ok) / total_correct) if total_correct else 0.0
        return t, prec, rec
    return best


def fit_temperature(logit_rows: Sequence[Sequence[float]], labels: Sequence[int],
                    lo: float = 0.05, hi: float = 10.0, iters: int = 60) -> float:
    """Temperature minimising negative log-likelihood, by ternary search.

    NLL in T is unimodal, so ternary search converges without a gradient and without
    scipy. Sixty iterations narrows [0.05, 10] to well under 1e-6.
    """
    if len(logit_rows) != len(labels):
        raise ValueError("logits and labels differ in length")
    if not logit_rows:
        raise ValueError("nothing to fit on")

    def nll(t: float) -> float:
        s = 0.0
        for row, y in zip(logit_rows, labels, strict=True):
            p = temperature_scale(row, t)[y]
            s -= math.log(max(p, 1e-12))
        return s / len(labels)

    # Ternary search on a unimodal function. Probe at the two points that divide the
    # bracket into thirds; whichever side has the higher NLL cannot contain the minimum,
    # so that third is discarded. Each pass keeps 2/3 of the interval, so sixty passes
    # shrink it by a factor of about (2/3)^60 -- far below any temperature that would
    # change a decision. No derivative is needed, which is why this is four lines rather
    # than an optimiser dependency.
    for _ in range(iters):
        a = lo + (hi - lo) / 3.0
        b = hi - (hi - lo) / 3.0
        if nll(a) < nll(b):
            hi = b
        else:
            lo = a
    return (lo + hi) / 2.0
