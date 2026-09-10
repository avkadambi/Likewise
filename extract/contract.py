"""What an extractor is allowed to hand the engine.

The engine consumes a flat record of published values. Under HMDA that record arrives
already structured, and the whole comparability argument rests on the regulator having
coarsened it. A court record arrives as prose, so something has to produce the same
object -- and the moment a model produces it, the interesting question is not accuracy
but what the model is permitted to say when it does not know.

Three statuses, and the distinction between the last two is the point.

    OBSERVED    the document states a value and the extractor is above its floor
    ABSTAINED   the extractor read something and was not confident enough to assert it
    ABSENT      the document does not speak to this dimension at all

OBSERVED emits the value. ABSTAINED and ABSENT both emit `None`, and the engine reads a
`None` on a premise dimension as UNRECORDED -- which, under a rule of precedence,
outranks distinguishing and breaks the bind. That is deliberate and it is the entire
safety property: an extractor that is unsure produces silence, and silence never binds.
The alternative -- emitting a best guess -- makes a precedent bind on a premise nobody
established, which is the failure `compare.py` split UNRECORDED out of AMBIGUOUS to
prevent.

ABSTAINED and ABSENT are nevertheless kept apart in the provenance, because they are
different facts about the world. "The model could not read this" is a defect in the
instrument. "The filing does not mention it" is a property of the filing. Collapsing
them would make the extractor's own error rate unmeasurable: an instrument whose misses
are indistinguishable from true absences cannot be validated against anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OBSERVED = "observed"
ABSTAINED = "abstained"
ABSENT = "absent"

STATUSES = (OBSERVED, ABSTAINED, ABSENT)
#: Statuses that reach the engine as a null. Both of them -- that is the safety property.
SILENT = frozenset({ABSTAINED, ABSENT})


@dataclass(frozen=True)
class Span:
    """Where in the source document a value was read. Character offsets, not token
    offsets: a reviewer opens the document, not the tokenizer."""
    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"degenerate span ({self.start}, {self.end})")


@dataclass(frozen=True)
class FieldValue:
    name: str
    status: str
    value: Any = None
    confidence: float | None = None
    span: Span | None = None
    floor: float | None = None          # the floor this decision was taken against

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if self.status == OBSERVED and self.value is None:
            raise ValueError(f"{self.name}: observed with no value is a contradiction")
        if self.status in SILENT and self.value is not None:
            # The one invariant worth being loud about. A silent field carrying a value
            # is how a guess reaches the gate wearing an abstention's clothes.
            raise ValueError(
                f"{self.name}: status {self.status} must not carry a value; "
                "an abstention that keeps its best guess is not an abstention")

    @property
    def silent(self) -> bool:
        return self.status in SILENT


@dataclass(frozen=True)
class ExtractedRecord:
    record_key: str
    fields: tuple[FieldValue, ...]
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        seen = [f.name for f in self.fields]
        if len(seen) != len(set(seen)):
            dupes = sorted({n for n in seen if seen.count(n) > 1})
            raise ValueError(f"{self.record_key}: repeated fields {dupes}")

    def by_name(self, name: str) -> FieldValue | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def to_engine_record(self) -> dict[str, Any]:
        """The flat record the loader and the engine consume.

        Every silent field is a `None`, and a `None` is what the engine already reads as
        UNRECORDED. Nothing about the engine changes to accept extracted data -- which is
        the test that the seam is in the right place.
        """
        out: dict[str, Any] = {"record_key": self.record_key}
        for f in self.fields:
            out[f.name] = f.value if f.status == OBSERVED else None
        return out

    def audit(self) -> dict[str, Any]:
        """What the engine does NOT see, and what validating the instrument requires.

        Emitted into the snapshot manifest rather than onto a finding: extraction is a
        property of how the snapshot was built, not of any pair compared within it.
        """
        return {
            "record_key": self.record_key,
            "provenance": dict(self.provenance),
            "fields": [
                {"name": f.name, "status": f.status,
                 "confidence": None if f.confidence is None else round(f.confidence, 6),
                 "floor": f.floor,
                 "span": None if f.span is None else [f.span.start, f.span.end]}
                for f in self.fields
            ],
        }


def coverage(records: list[ExtractedRecord]) -> dict[str, dict[str, int]]:
    """Per-field counts of the three statuses across a corpus.

    The number to watch is ABSTAINED. A field that abstains on most of the corpus is not
    a field the extractor supports, whatever its accuracy on the rest, and a premise
    dimension that is silent on most cases cannot carry a precedent. Reported so that is
    visible before anyone reads a result, not after.
    """
    out: dict[str, dict[str, int]] = {}
    for r in records:
        for f in r.fields:
            out.setdefault(f.name, {s: 0 for s in STATUSES})[f.status] += 1
    return out
