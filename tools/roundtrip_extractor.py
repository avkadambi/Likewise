#!/usr/bin/env python3
"""Score an extractor against ground truth the corpus already carries.

Renders records whose field values are known by construction into prose, extracts them
back, and compares. Produces two things:

  * a report with the acceptance gate applied, and
  * the labelled readings `calibrate_extractor.py` needs, which normally require a human
    reading every document.

Input is JSONL, one structured record per line, with `record_key` and the fields:

    {"record_key": "w1-c0007", "prior_category": "III", "offence_level": 22}

`--absent` and `--guard` name fields to withhold or to write in a guard style. A guard
puts the value in the prose while the record does not carry it, so the only correct
behaviour is silence and any assertion is a hallucination by construction.

Run WITHOUT --checkpoint to exercise the harness against the deterministic backend: the
numbers mean nothing about any model, and the report says so, but the pipeline, the gate
and the readings loop all run.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from extract import roundtrip as rt
from extract import spec as espec
from extract.abstain import Calibration
from extract.backends import (DeterministicBackend, LiteralMatchBackend,
                              TransformersBackend)
from extract.runner import extract_one


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", required=True, help="structured records, JSONL")
    ap.add_argument("--fields", required=True, help="comma-separated field names")
    ap.add_argument("--absent", default="", help="fields the prose omits")
    ap.add_argument("--guard", default="", help="fields written in a guard style")
    ap.add_argument("--checkpoint", default=None,
                    help="fine-tuned head; omitted means a baseline backend")
    ap.add_argument("--baseline", default="literal",
                    choices=("literal", "deterministic"),
                    help="which backend to use when no checkpoint is given")
    ap.add_argument("--specs", default="specs")
    ap.add_argument("--spec-version", default=None)
    ap.add_argument("--train-fraction", type=float, default=0.6)
    ap.add_argument("--min-assertions", type=int, default=300)
    ap.add_argument("--target-precision", type=float, default=0.98)
    ap.add_argument("--floor", type=float, default=None,
                    help="uniform floor, when the specification carries none yet")
    ap.add_argument("--report", default=None, help="write the report JSON here")
    ap.add_argument("--readings", default=None, help="write labelled readings JSONL here")
    a = ap.parse_args()

    fields = [f.strip() for f in a.fields.split(",") if f.strip()]
    absent = [f.strip() for f in a.absent.split(",") if f.strip()]
    guard = [f.strip() for f in a.guard.split(",") if f.strip()]
    records = [json.loads(x) for x in
               pathlib.Path(a.records).read_text().splitlines() if x.strip()]
    if not records:
        print("no records", file=sys.stderr)
        return 2

    sp = espec.load(a.specs, version=a.spec_version)
    cal = sp.calibration
    if cal is None:
        if a.floor is None:
            print("the specification carries no floors; pass --floor to score an "
                  "uncalibrated extractor, or calibrate it first", file=sys.stderr)
            return 2
        cal = Calibration(corpus_id="roundtrip", temperature=1.0, aggregation="min",
                          floors=dict.fromkeys(fields, a.floor),
                          target_precision=a.target_precision, fitted_n=0)

    if a.checkpoint:
        backend = TransformersBackend(sp.backbone.name, checkpoint=a.checkpoint)
    elif a.baseline == "literal":
        backend = LiteralMatchBackend()
    else:
        backend = DeterministicBackend()

    train_styles, eval_styles = rt.split_styles(a.train_fraction)
    scored = []
    for i, rec in enumerate(records):
        style = eval_styles[i % len(eval_styles)]
        # Guards only where the style is a guard style: a guard field written plainly is
        # simply a field, and would be scored as one.
        g = guard if style in rt.GUARD_STYLES else []
        rendering = rt.render(rec, fields, style, absent=absent, guard_fields=g)
        ex = extract_one(rendering.prose, rendering.record_key, fields, backend, sp, cal)
        scored.extend(rt.score(ex, rendering))

    rep = rt.report(scored, train_styles=train_styles,
                    min_assertions=a.min_assertions,
                    target_precision=a.target_precision)
    out = rep.as_dict()
    out["backend"] = backend.identity()
    if not a.checkpoint:
        out["WARNING"] = (f"{a.baseline} baseline, not a trained model: these numbers "
                          "are evidence about the harness, not about any extractor you "
                          "would deploy")

    text = json.dumps(out, indent=2)
    print(text)
    if a.report:
        pathlib.Path(a.report).write_text(text + "\n")
    if a.readings:
        n = rt.write_readings(scored, a.readings)
        print(f"\n{n} labelled readings -> {a.readings}", file=sys.stderr)

    return 0 if rep.gate["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
