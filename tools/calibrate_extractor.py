#!/usr/bin/env python3
"""Fit the temperature and the per-field confidence floors, and write a new extraction
specification version.

Calibration is a governance act, not a training step, so its output is a versioned,
signed YAML file with a named corpus rather than a pickle beside a checkpoint. Two
properties are enforced here rather than left to the operator:

  * the floors are fitted for PRECISION at a declared target, never for F1. A missed
    field abstains, which is cheap; a hallucinated field binds, which is not.
  * the corpus is recorded, because a floor fitted on one court's filings does not
    transfer. Encoder confidence collapses under domain shift -- error-detection AUROC
    0.922 in-domain against 0.633 out -- so carrying a threshold across corpora is the
    characteristic failure of this design.

Input is JSONL, one held-out labelled reading per line:

    {"field": "prior_category", "logits": [1.2, -0.4, ...], "label": 0, "correct": true}

`correct` is the adjudicated truth for that reading. It has to come from a human reading
the document; there is no way to produce it from the model, and a calibration fitted
against the model's own output measures nothing.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import yaml

from extract.abstain import (AGGREGATIONS, floor_for_precision, span_confidence,
                             temperature_scale)
from extract.abstain import fit_temperature


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readings", required=True, help="held-out labelled readings, JSONL")
    ap.add_argument("--corpus-id", required=True,
                    help="the corpus these floors are valid on, and only on")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--backbone-revision", required=True,
                    help="the pinned commit; a moving branch cannot be replayed")
    ap.add_argument("--author", required=True)
    ap.add_argument("--target-precision", type=float, default=0.98)
    ap.add_argument("--aggregation", default="min", choices=list(AGGREGATIONS))
    ap.add_argument("--base", default="specs/extraction/1.0.0.yaml")
    ap.add_argument("--out", required=True, help="new specs/extraction/<version>.yaml")
    ap.add_argument("--version", required=True)
    a = ap.parse_args()

    rows = [json.loads(x) for x in pathlib.Path(a.readings).read_text().splitlines() if x.strip()]
    if not rows:
        print("no readings", file=sys.stderr)
        return 2

    t = fit_temperature([r["logits"] for r in rows], [int(r["label"]) for r in rows])

    by_field: dict[str, list[tuple[float, bool]]] = {}
    for r in rows:
        probs = temperature_scale(r["logits"], t)
        # A single-token reading is the common case in these files; a multi-token span
        # supplies its own per-token probabilities under "token_probs".
        tp = r.get("token_probs") or [probs[int(r["label"])]]
        by_field.setdefault(r["field"], []).append(
            (span_confidence(tp, a.aggregation), bool(r["correct"])))

    floors, report = {}, {}
    for fname, scored in sorted(by_field.items()):
        floor, prec, rec = floor_for_precision(scored, a.target_precision)
        floors[fname] = round(floor, 6)
        report[fname] = {"n": len(scored), "precision": round(prec, 4),
                         "recall": round(rec, 4), "floor": round(floor, 6),
                         "met_target": prec >= a.target_precision}

    spec = yaml.safe_load(pathlib.Path(a.base).read_text())
    spec.update({
        "version": a.version, "author": a.author, "checkpoint": a.checkpoint,
        "backbone_revision": a.backbone_revision, "floors": floors,
        "calibration": {"corpus_id": a.corpus_id, "temperature": round(t, 6),
                        "aggregation": a.aggregation,
                        "target_precision": a.target_precision, "fitted_n": len(rows)},
    })
    pathlib.Path(a.out).write_text(yaml.safe_dump(spec, sort_keys=False))

    print(json.dumps({"temperature": round(t, 6), "n": len(rows), "fields": report},
                     indent=2))
    missed = [f for f, r in report.items() if not r["met_target"]]
    if missed:
        # Not an error the tool fixes by lowering the bar. A field that cannot reach the
        # target precision at ANY threshold is a field the extractor does not support on
        # this corpus, and the honest response is to drop it rather than publish it with
        # a floor that does not deliver what it claims.
        print(f"\nREFUSED: {missed} cannot reach precision {a.target_precision} at any "
              f"threshold on this corpus. Drop these fields or improve the extractor; "
              f"do not lower the target.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
