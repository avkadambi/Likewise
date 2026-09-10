"""Tolerance sensitivity sweep.

Produced with the scan and stored beside its findings, so no finding can be presented
without its sweep. Each point is a full re-load of the specification through the startup
gate, which means a point whose threshold falls below publication granularity REFUSES
rather than returning a number -- that refusal is the shaded region on the chart, and it
is derived rather than drawn.
"""
from __future__ import annotations
import argparse, copy, json, os, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import glob
import yaml
from likewise import specs, scan
from likewise import paths
from likewise.errors import SpecError
from likewise.store import open_store

# dimension -> points. Chosen to straddle each dimension's comparability floor, so the
# curve shows where measurement stops being possible, not just where counts change.
DECISIVE_POINTS = {
    "combined_loan_to_value_ratio": [0.5, 1.0, 2.0, 4.0, 7.1, 10.0, 14.0],
    "debt_to_income_ratio":         [0.5, 1.0, 2.0, 4.0],
    "property_value":               [2500.0, 5000.0, 10000.0, 20000.0],
}
CONTROL_POINTS = {
    "loan_amount": [0.01, 0.025, 0.05, 0.10],
    "income":      [0.01, 0.025, 0.05, 0.10],
}


def _write(dirpath, mver, mat, bud):
    with open(f"{dirpath}/materiality/{mver}.yaml", "w") as fh:
        yaml.safe_dump(mat, fh, sort_keys=False)
    with open(f"{dirpath}/budget/{mat['budget']}.json", "w") as fh:
        json.dump(bud, fh, indent=2, sort_keys=True)


def point(tmp, mver, mat, bud, files, lei, year, quick_B):
    _write(tmp, mver, mat, bud)
    try:
        sp = specs.load(tmp, version=mver)
    except SpecError as e:
        return {"refused": e.kind, "failures": e.failures}
    try:
        res = scan.run(files, sp, lei=lei, year=year, scan_id="scn_sweep",
                       analysis_status="exploratory")
    except SpecError as e:
        return {"refused": e.kind, "failures": e.failures}
    c = res["summary"]["counts"]
    qs = sorted(f["q_value"] for f in res["findings"] if f.get("q_value") is not None)
    return {
        "matched": c["denials_with_matched_comparator"],
        "matched_fraction": (round(c["denials_with_matched_comparator"] / c["denials_non_exempt"], 4)
                             if c.get("denials_non_exempt") else None),
        "testable": c["denials_testable_by_code_marginal"],
        "candidates": c["denials_with_finding"],
        "post_fdr": c["findings_after_fdr"],
        "median_q": round(qs[len(qs) // 2], 4) if qs else None,
        "tripwires": [t["tripwire"] for t in res["summary"].get("tripwire_breaches", [])],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-id", required=True)
    ap.add_argument("--store", default=None)
    ap.add_argument("--specs", default="specs")
    a = ap.parse_args()

    store = open_store(a.store or paths.store_root())
    rec = store.get_json(f"scans/{a.scan_id}/scan.json")
    lei, year = rec["lei"], rec["activity_year"]
    mver = rec["spec_version"]
    files = sorted(glob.glob(
        paths.parquet_glob(rec["curated_snapshot"], year, lei)))

    base = specs.load(a.specs, version=mver)
    tmp = tempfile.mkdtemp(prefix="likewise-sweep-")
    shutil.copytree(a.specs, tmp, dirs_exist_ok=True)
    quick_B = base.raw["statistics"].get("permutation_B_initial", 200)

    operating = {
        "combined_loan_to_value_ratio":
            base.budget.raw["dimensions"]["combined_loan_to_value_ratio"]["decisive_threshold"],
        "debt_to_income_ratio":
            base.budget.raw["dimensions"]["debt_to_income_ratio"]["decisive_threshold"],
        "property_value":
            base.budget.raw["dimensions"]["property_value"]["decisive_threshold"],
        "loan_amount": base.raw["control_features"]["loan_amount"]["tolerance"],
        "income": base.raw["control_features"]["income"]["tolerance"],
    }

    out = {"scan_id": a.scan_id, "spec_version": mver, "snapshot_id": base.snapshot_id,
           "generated": time.time(), "operating_point": operating, "dimensions": {}}

    for dim, pts in DECISIVE_POINTS.items():
        rows = []
        for v in pts:
            mat, bud = copy.deepcopy(base.raw), copy.deepcopy(base.budget.raw)
            bud["dimensions"][dim]["decisive_threshold"] = v
            r = point(tmp, mver, mat, bud, files, lei, year, quick_B)
            r["value"] = v
            r["is_operating"] = (v == operating[dim])
            rows.append(r)
            print(f"  {dim} {v}: {json.dumps({k: r[k] for k in r if k != 'failures'})}")
        out["dimensions"][dim] = {"kind": "decisive_threshold",
                                  "unit": base.budget.raw["dimensions"][dim]["unit"],
                                  "granularity": base.budget.raw["dimensions"][dim]["granularity"],
                                  "points": rows}

    for feat, pts in CONTROL_POINTS.items():
        rows = []
        for v in pts:
            mat, bud = copy.deepcopy(base.raw), copy.deepcopy(base.budget.raw)
            mat["control_features"][feat]["tolerance"] = v
            r = point(tmp, mver, mat, bud, files, lei, year, quick_B)
            r["value"] = v
            r["is_operating"] = (v == operating[feat])
            rows.append(r)
            print(f"  {feat} {v}: {json.dumps({k: r[k] for k in r if k != 'failures'})}")
        out["dimensions"][feat] = {"kind": "control_tolerance", "unit": "relative",
                                   "granularity": None, "points": rows}

    shutil.rmtree(tmp, ignore_errors=True)
    store.put_json(f"scans/{a.scan_id}/sweep.json", out)
    print(f"sweep -> scans/{a.scan_id}/sweep.json  "
          f"({sum(len(d['points']) for d in out['dimensions'].values())} points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
