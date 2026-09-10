#!/usr/bin/env python3
"""Score a corpus of rulings against its oracle, and apply the binding acceptance gate.

Takes rulings as data rather than running the engine itself. Retrieval, the provision
index and the authority order are corpus-specific and live in whatever produced the
rulings; the gate only needs the decision and what the oracle expected. That seam also
means a run can be re-scored under a changed gate without re-running the engine, which is
the difference between a gate and a thing nobody checks twice.

Two JSONL inputs, joined on `case_id`.

  --oracle   {"case_id": "w1-c0007", "expected": "governed",
              "expected_controlling": "p-114", "guard": false,
              "arm": "engine", "absolute": false}

  --rulings  {"case_id": "w1-c0007", "outcome": "governed", "controlling": "p-114"}

`arm` is "engine" for expectations written by whoever wrote the engine's reading of the
rulebook, and "independent" for those written by someone who did not. The gate refuses to
return `pass` on the engine arm alone: computed ground truth is a second program from the
same rulebook, and a shared misreading of a provision reads as perfect precision.

Exit status is 0 only on `pass`. `inconclusive` and `invalid` are not passes.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from likewise import binding_gate as bg
from likewise.precedent import Ruling


def _jsonl(path: str) -> list[dict]:
    return [json.loads(x) for x in pathlib.Path(path).read_text().splitlines() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oracle", required=True)
    ap.add_argument("--rulings", required=True)
    ap.add_argument("--tolerance-selection", default=None,
                    help="JSONL or newline-delimited case ids used to fit the tolerances")
    ap.add_argument("--min-binds", type=int, default=300)
    ap.add_argument("--min-binds-absolute", type=int, default=3000)
    ap.add_argument("--min-independent-binds", type=int, default=1)
    ap.add_argument("--target-false-bind-rate", type=float, default=0.01)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    cases = [bg.OracleCase(
        case_id=r["case_id"], expected=r["expected"],
        expected_controlling=r.get("expected_controlling"),
        guard=bool(r.get("guard", False)), arm=r.get("arm", bg.ENGINE_ARM),
        provision=r.get("provision"), absolute=bool(r.get("absolute", False)))
        for r in _jsonl(a.oracle)]

    rulings = {}
    for r in _jsonl(a.rulings):
        rulings[r["case_id"]] = Ruling(r["outcome"], cause=r.get("cause"),
                                       controlling=r.get("controlling"))

    missing = [c.case_id for c in cases if c.case_id not in rulings]
    if missing:
        # Not skipped. A case the engine produced no ruling for is a case the gate cannot
        # score, and dropping it silently shrinks the denominator in the engine's favour.
        print(f"no ruling for {len(missing)} oracle case(s): {missing[:5]}"
              f"{' ...' if len(missing) > 5 else ''}", file=sys.stderr)
        return 2

    fitted: list[str] = []
    if a.tolerance_selection:
        for line in pathlib.Path(a.tolerance_selection).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            fitted.append(json.loads(line)["case_id"] if line.startswith("{") else line)

    rep = bg.evaluate(cases, lambda c: rulings[c.case_id],
                      tolerance_selection_cases=fitted,
                      min_binds=a.min_binds, min_binds_absolute=a.min_binds_absolute,
                      target_false_bind_rate=a.target_false_bind_rate, alpha=a.alpha,
                      min_independent_binds=a.min_independent_binds)

    text = json.dumps(rep.as_dict(a.alpha), indent=2)
    print(text)
    if a.report:
        pathlib.Path(a.report).write_text(text + "\n")
    return 0 if rep.verdict == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
