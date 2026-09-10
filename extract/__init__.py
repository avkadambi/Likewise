"""Offline extraction: prose in, the structured record the engine already consumes out.

Nothing here is imported by `likewise/`. The engine keeps its five runtime dependencies
and never sees torch; extraction is a pipeline stage that produces a snapshot, and its
provenance travels in the snapshot manifest. `tests/test_extraction.py` asserts the
separation over every file in the package.
"""
from .abstain import Calibration, floor_for_precision, span_confidence, temperature_scale
from .backbones import BACKBONES, DEFAULT_BACKBONE, Backbone
from .backends import (Backend, DeterministicBackend, LiteralMatchBackend, TokenScore,
                       TransformersBackend)
from .contract import (ABSENT, ABSTAINED, OBSERVED, SILENT, ExtractedRecord, FieldValue,
                       Span, coverage)
from .runner import extract_many, extract_one
from .spec import ExtractionSpec, ExtractionSpecError, load
from . import roundtrip

__all__ = [
    "ABSENT",
    "ABSTAINED",
    "BACKBONES",
    "DEFAULT_BACKBONE",
    "OBSERVED",
    "SILENT",
    "Backbone",
    "Backend",
    "Calibration",
    "DeterministicBackend",
    "ExtractedRecord",
    "ExtractionSpec",
    "ExtractionSpecError",
    "FieldValue",
    "LiteralMatchBackend",
    "Span",
    "TokenScore",
    "TransformersBackend",
    "coverage",
    "extract_many",
    "extract_one",
    "floor_for_precision",
    "load",
    "roundtrip",
    "span_confidence",
    "temperature_scale",
]
