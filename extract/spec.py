"""The extraction specification, and the gate it has to pass.

Same posture as `likewise/specs.py`: a governance artefact, loaded through a validator
that refuses rather than repairs, with the failures named. The rules are few because the
surface is small, and every one of them is a mistake that would otherwise be silent.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import backbones
from .abstain import AGGREGATIONS, Calibration

IN_FORCE = "1.0.0"


class ExtractionSpecError(Exception):
    def __init__(self, kind: str, failures: list[dict]):
        super().__init__(f"{kind}: {failures}")
        self.kind = kind
        self.failures = failures


@dataclass(frozen=True)
class ExtractionSpec:
    version: str
    raw: dict[str, Any]
    digest: str
    backbone: backbones.Backbone
    calibration: Calibration | None

    @property
    def checkpoint(self) -> str | None:
        return self.raw.get("checkpoint")

    def fields(self) -> list[str]:
        return sorted((self.raw.get("floors") or {}))


def _validate(raw: dict, path: str) -> list[dict]:
    f: list[dict] = []

    name = raw.get("backbone")
    if name not in backbones.BACKBONES:
        # E1. The set is closed for the same reason resolution models are: a signed
        # artefact must be digest-comparable, and an arbitrary repository name is not.
        f.append({"rule": "E1", "field": "backbone", "value": name,
                  "known": sorted(backbones.BACKBONES),
                  "why": "backbone is not a member of the closed set"})
    else:
        bb = backbones.get(name)
        rev = raw.get("backbone_revision")
        if not rev:
            f.append({"rule": "E2", "field": "backbone_revision",
                      "why": "no revision pinned"})
        elif rev == "main" and raw.get("checkpoint"):
            # E2. A pin is only meaningful once something has been produced against it.
            # An unfilled template may say "main"; a specification that produced a
            # snapshot may not, because "main" identifies different weights on different
            # days and a result cited against it cannot be replayed.
            f.append({"rule": "E2", "field": "backbone_revision", "value": rev,
                      "why": "a specification with a checkpoint must pin a commit, "
                             "not a moving branch"})
        if bb.family == "modernbert" and not bb.add_prefix_space:
            f.append({"rule": "E5", "field": "add_prefix_space", "backbone": name,
                      "why": "ModernBERT-family tokenizers prepend whitespace on a plain "
                             "call; leaving add_prefix_space false costs ~1.7 NER F1"})

    cal = raw.get("calibration") or {}
    t = cal.get("temperature")
    if not isinstance(t, (int, float)) or not (t > 0):
        f.append({"rule": "E3", "field": "calibration.temperature", "value": t,
                  "why": "temperature must be positive"})
    if cal.get("aggregation") not in AGGREGATIONS:
        f.append({"rule": "E3", "field": "calibration.aggregation",
                  "value": cal.get("aggregation"), "known": list(AGGREGATIONS)})
    tp = cal.get("target_precision")
    if not isinstance(tp, (int, float)) or not (0 < tp <= 1):
        f.append({"rule": "E3", "field": "calibration.target_precision", "value": tp})

    floors = raw.get("floors") or {}
    for k, v in floors.items():
        if not isinstance(v, (int, float)) or not (0 < v <= 1):
            # E4. Zero is the interesting case and it is refused, not clamped: it makes
            # abstention unreachable, so every reading is asserted however weak.
            f.append({"rule": "E4", "field": f"floors.{k}", "value": v,
                      "why": "floor must be in (0, 1]; 0 makes abstention unreachable"})

    if raw.get("checkpoint"):
        # A specification that has produced data must be complete. Refusing here rather
        # than at read time means an under-specified extractor cannot quietly emit a
        # corpus that looks like every other corpus.
        if not floors:
            f.append({"rule": "E6", "field": "floors",
                      "why": "a specification with a checkpoint must calibrate at least "
                             "one field; an uncalibrated extractor has no floor to fail"})
        if not cal.get("corpus_id"):
            f.append({"rule": "E6", "field": "calibration.corpus_id",
                      "why": "a floor is only valid on the corpus it was fitted on, so "
                             "the corpus has to be named"})
        if not cal.get("fitted_n"):
            f.append({"rule": "E6", "field": "calibration.fitted_n",
                      "why": "a calibration fitted on nothing is a guess with a version "
                             "number"})

    author = (raw.get("author") or "").strip()
    if not author or author.lower() == "unsigned":
        f.append({"rule": "E7", "field": "author",
                  "why": "an extraction standard states when the system may speak; it is "
                         "signed like any other governance artefact"})
    if path and f:
        for x in f:
            x.setdefault("spec", path)
    return f


def load(spec_dir: str | Path = "specs", version: str | None = None) -> ExtractionSpec:
    version = version or IN_FORCE
    p = Path(spec_dir) / "extraction" / f"{version}.yaml"
    raw_bytes = p.read_bytes()
    raw = yaml.safe_load(raw_bytes)
    failures = _validate(raw, str(p))
    if failures:
        raise ExtractionSpecError("extraction_gate_failed", failures)
    cal_raw = raw.get("calibration") or {}
    cal = None
    if raw.get("floors"):
        cal = Calibration(
            corpus_id=cal_raw.get("corpus_id") or "uncalibrated",
            temperature=float(cal_raw["temperature"]),
            aggregation=cal_raw["aggregation"],
            floors={k: float(v) for k, v in raw["floors"].items()},
            target_precision=float(cal_raw["target_precision"]),
            fitted_n=int(cal_raw.get("fitted_n") or 0))
    return ExtractionSpec(
        version=raw["version"], raw=raw,
        digest="sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
        backbone=backbones.get(raw["backbone"]), calibration=cal)


def digest_of(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
