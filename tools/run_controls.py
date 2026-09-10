"""Negative controls, persisted as a product output rather than printed.

Each control states its expected rate BEFORE the run. Without that, a pass is merely
non-significant rather than informative -- the architect review's P2 item.
"""
from __future__ import annotations
import argparse, glob, json, math, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import duckdb
from collections import defaultdict
from likewise import specs, scan, core, stats
from likewise import paths
from likewise.store import open_store


def nz(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-id", required=True)
    ap.add_argument("--store", default=None)
    a = ap.parse_args()

    store = open_store(a.store or paths.store_root())
    rec = store.get_json(f"scans/{a.scan_id}/scan.json")
    spec = specs.load(version=rec["spec_version"])
    files = sorted(glob.glob(
        paths.parquet_glob(rec["curated_snapshot"], rec["activity_year"], rec["lei"])))

    con = scan.configure(duckdb.connect())
    pop = spec.raw["population"]
    cur = con.execute(core.candidate_sql(spec), {
        "files": files, "approved": pop["approved_actions"], "denied": pop["denied_actions"]})
    cols = [d[0] for d in cur.description]
    cand = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    pairs = []
    for row in cand:
        ar = {k[2:]: nz(v) for k, v in row.items() if k.startswith("a_")}
        dr = {k[2:]: nz(v) for k, v in row.items() if k.startswith("d_")}
        for k in spec.exact_match:
            ar.setdefault(k, row.get(f"blk_{k}"))
            dr.setdefault(k, row.get(f"blk_{k}"))
        m = core.match(ar, dr, spec)
        if not m.matched or m.incomplete:
            continue
        codes = [nz(row.get(f"d_denial_reason_{i}")) for i in (1, 2, 3, 4)]
        pairs.append((row, ar, dr, [int(c) for c in codes if c is not None]))

    def by_cluster(fn):
        out = defaultdict(list)
        for row, ar, dr, codes in pairs:
            v = fn(row, ar, dr, codes)
            if v is not None:
                out[row["blk_county_code"]].append(v)
        return out

    def defeated(ar, dr, codes):
        return 1 if core.evaluate(ar, dr, codes, spec).outcome \
            == "not_supported_by_public_record" else 0

    def cited(row, ar, dr, codes):
        return defeated(ar, dr, [4]) if 4 in codes else None

    def placebo_uncited(row, ar, dr, codes):
        return defeated(ar, dr, [1]) if (4 in codes and 1 not in codes) else None

    def placebo_parity(row, ar, dr, codes):
        return int(hash(row["denied_key"]) % 2 == 0) if 4 in codes else None

    rng = random.Random(3)

    def approved_approved(row, ar, dr, codes):
        if 4 not in codes:
            return None
        x, y = (ar, dr) if rng.random() < 0.5 else (dr, ar)
        return defeated(x, {**y, "action_taken": 3}, [4])

    def reversed_outcome(row, ar, dr, codes):
        return defeated(dr, ar, codes) if codes else None

    controls = []
    primary = stats.ratio_control(by_cluster(cited), by_cluster(placebo_uncited))
    pr = primary.as_dict()
    controls.append({
        "name": "Uncited-dimension placebo", "primary": True,
        "description": "Run the survival test against a dimension the denial reason does not "
                       "name. A defeated verdict here is the pipeline firing on noise.",
        "expected": "cited ÷ placebo ≥ %s" % pr.get("min_ratio"),
        "observed": pr.get("rate"), "ci95": pr.get("ci95"),
        "n": pr.get("n"), "powered": pr.get("powered"),
        "gate": pr.get("gate"), "detail": pr})

    for name, fn, desc, expected, gate_fn in [
        ("Reversed-outcome control", reversed_outcome,
         "Swap the denied and approved roles. Dominance findings should collapse to the "
         "null rate.", "≤ 0.05", lambda r: r <= 0.05),
        ("Parity placebo", placebo_parity,
         "A dimension with no underwriting content whatever. Anything other than a coin "
         "flip means the machinery, not the data, is producing the pattern.",
         "0.45 – 0.55", lambda r: 0.45 <= r <= 0.55),
        ("Approved–approved", approved_approved,
         "Pair two approved records and label one of them denied at random. The reason "
         "engine should find nothing.", "≤ 0.10", lambda r: r <= 0.10),
    ]:
        R = by_cluster(fn)
        n = sum(len(v) for v in R.values())
        r = (sum(sum(v) for v in R.values()) / n) if n else None
        lo, hi = stats.cluster_bootstrap_ci(R, B=500) if n else (None, None)
        controls.append({
            "name": name, "primary": False, "description": desc, "expected": expected,
            "observed": None if r is None else round(r, 4),
            "ci95": None if lo is None else [round(lo, 4), round(hi, 4)],
            "n": n, "powered": n >= 30,
            "gate": "not_computable" if r is None else ("pass" if gate_fn(r) else "fail")})

    mut = None
    if os.path.exists("data/store/mutation.json"):
        mut = json.load(open("data/store/mutation.json"))
        controls.append({
            "name": "Mutation kill rate", "primary": False,
            "description": "A pre-registered bug catalogue injected into the pipeline; the "
                           "share caught by the test suite. Catalogue published in the repo.",
            "expected": "≥ 0.90", "observed": mut.get("rate"), "ci95": None,
            "n": mut.get("total"), "powered": True,
            "gate": "pass" if (mut.get("rate") or 0) >= 0.90 else "fail"})

    failed = [c["name"] for c in controls if c["gate"] == "fail"]
    # The control gate is a PASS requirement, not a "did not fail" requirement. An inconclusive or
    # uncomputable primary control blocks publication exactly as a failing one does:
    # not knowing whether the pipeline fires on noise is not evidence that it does not.
    primary_gate = controls[0]["gate"]
    blocked = bool(failed) or primary_gate != "pass"
    summary = store.get_json(f"scans/{a.scan_id}/summary.json")
    out = {"scan_id": a.scan_id, "generated": time.time(), "controls": controls,
           "failed": failed, "publication_blocked": blocked,
           "primary_gate": primary_gate,
           "null": summary.get("null"),
           "gate_note": "The control gate. Findings remain viewable and dispositionable when a control "
                        "fails; external publication does not."}
    store.put_json(f"scans/{a.scan_id}/controls.json", out)
    print(json.dumps({"failed": failed, "publication_blocked": blocked,
                      "controls": [{k: c[k] for k in ("name", "observed", "gate")}
                                   for c in controls]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
