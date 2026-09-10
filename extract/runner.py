"""One document in, one structured record out, with the provenance to audit it.

The order matters and is the whole design. The backend proposes readings and takes no
decision; `abstain.py` scales, aggregates and compares against a floor; `contract.py`
refuses to let a silent field carry a value. Nothing here decides anything on its own,
which is why the pipeline can be tested end to end without a model.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .abstain import Calibration, span_confidence
from .backends import Backend
from .contract import ABSENT, ABSTAINED, OBSERVED, ExtractedRecord, FieldValue, Span
from .spec import ExtractionSpec


def _provenance(sp: ExtractionSpec, backend: Backend, cal: Calibration) -> dict:
    """Cited on every extracted snapshot.

    The checkpoint is part of what produced the result, exactly as the materiality
    version is. A record whose extractor cannot be named cannot be replayed, and a
    corpus that cannot be replayed cannot be argued with.
    """
    return {
        "extraction_spec_version": sp.version,
        "extraction_spec_digest": sp.digest,
        "backbone": sp.backbone.name,
        "backbone_repo": sp.backbone.repo,
        "backbone_revision": sp.raw.get("backbone_revision"),
        "checkpoint": sp.checkpoint,
        "backend": backend.identity(),
        "calibration": {
            "corpus_id": cal.corpus_id, "temperature": cal.temperature,
            "aggregation": cal.aggregation, "target_precision": cal.target_precision,
            "fitted_n": cal.fitted_n,
        },
        # Not a claim about accuracy. A statement that this corpus was read by a model,
        # so that nothing downstream can mistake it for a regulator's filing.
        "extracted": True,
    }


def extract_one(document: str, record_key: str, fields: Sequence[str],
                backend: Backend, sp: ExtractionSpec,
                cal: Calibration | None = None) -> ExtractedRecord:
    cal = cal or sp.calibration
    if cal is None:
        raise RuntimeError(
            "no calibration. An extractor with no floors asserts everything it reads, "
            "and the abstention path -- the only thing between a guess and a bind -- is "
            "unreachable. Run tools/calibrate_extractor.py first.")

    proposed = {t.field: t for t in backend.score(document, fields)}
    out: list[FieldValue] = []
    for name in fields:
        floor = cal.floor_for(name)
        t = proposed.get(name)
        if t is None:
            # The document does not speak to it. Distinct from a low-confidence reading,
            # and kept distinct, because otherwise the extractor's own miss rate is
            # unmeasurable against true absences.
            out.append(FieldValue(name=name, status=ABSENT, floor=floor))
            continue
        conf = span_confidence(t.token_probs, cal.aggregation)
        if conf >= floor:
            out.append(FieldValue(name=name, status=OBSERVED, value=t.value,
                                  confidence=conf, floor=floor,
                                  span=Span(t.start, t.end, t.text)))
        else:
            # The value is dropped here, not carried along "for reference". A retained
            # guess is one refactor away from being read.
            out.append(FieldValue(name=name, status=ABSTAINED, confidence=conf,
                                  floor=floor, span=Span(t.start, t.end, t.text)))

    prov = _provenance(sp, backend, cal)
    prov["document_sha256"] = hashlib.sha256(document.encode()).hexdigest()
    return ExtractedRecord(record_key=record_key, fields=tuple(out), provenance=prov)


def extract_many(documents: dict[str, str], fields: Sequence[str], backend: Backend,
                 sp: ExtractionSpec, cal: Calibration | None = None) -> list[ExtractedRecord]:
    """Sorted by key, not by iteration order -- the same total-order discipline the scan
    needs. An extraction run that reorders its output produces a different snapshot from
    the same corpus."""
    return [extract_one(documents[k], k, fields, backend, sp, cal)
            for k in sorted(documents)]
