"""Run one scan and persist it into the store the web view and the API both read.

A scan is a pure function of (filer, year, specification versions, snapshot). The scan_id
is derived from that tuple, so re-running an identical tuple overwrites the same record
rather than accumulating near-duplicate runs.
"""
from __future__ import annotations
import traceback
import argparse, glob, hashlib, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from likewise import specs, scan
from likewise import paths
from likewise.egress import Egress
from likewise.errors import SpecError
from likewise.store import open_store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lei", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--snapshot", required=True, help="curated snapshot directory name")
    # Defaults to the version IN FORCE. A pinned default here meant the CLI ran a
    # standard the service no longer served, and the disagreement was invisible
    # because both labelled their output honestly with the version they used.
    ap.add_argument("--spec-version", default=specs.IN_FORCE)
    ap.add_argument("--label", default="")
    ap.add_argument("--store", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    files = sorted(glob.glob(
        paths.parquet_glob(a.snapshot, a.year, a.lei)))
    if not files:
        print(f"no parquet under snapshot={a.snapshot} year={a.year} lei={a.lei}", file=sys.stderr)
        return 2

    try:
        spec = specs.load(version=a.spec_version)
    except SpecError as e:
        e.emit_and_exit()

    tup = f"{a.lei}|{a.year}|{a.spec_version}|{spec.snapshot_id}|{a.snapshot}"
    sid = "scn_" + hashlib.sha256(tup.encode()).hexdigest()[:16]
    store = open_store(a.store or paths.store_root())
    eg = Egress(bytes.fromhex(os.environ["LIKEWISE_PSEUDONYM_KEY"])
                if os.environ.get("LIKEWISE_PSEUDONYM_KEY")
                else b"dev-key-not-for-production!!!!!!", key_version=1)

    prereg = os.environ.get("LIKEWISE_PREREG")
    rec = {"scan_id": sid, "status": "running", "lei": a.lei, "activity_year": a.year,
           "snapshot_id": spec.snapshot_id, "curated_snapshot": a.snapshot,
           "label": a.label, "image_digest": "sha256:dev",
           "spec_version": a.spec_version, "spec_digests": spec.digests,
           "pseudonym_key_version": 1,
           "preregistration_digest": prereg or "unset",
           "analysis_status": "confirmatory" if prereg else "exploratory",
           "started_at": time.time(), "deadline": time.time() + 45 * 60,
           "finished_at": None, "superseded_by": None, "error": None}
    store.put_json(f"scans/{sid}/scan.json", rec)

    try:
        res = scan.run(files, spec, lei=a.lei, year=a.year, scan_id=sid,
                       analysis_status=rec["analysis_status"])
    except SpecError as exc:
        # A structural refusal is a result, not a crash. It is stored with its full
        # payload so the specification screen can render the refusal verbatim.
        rec.update(status="refused", finished_at=time.time(),
                   error=exc.kind, refusal=exc.payload())
        store.put_json(f"scans/{sid}/scan.json", rec)
        print(f"REFUSED {exc.kind}", file=sys.stderr)
        print(json.dumps(exc.payload(), indent=2), file=sys.stderr)
        return 78
    except Exception as exc:
        # Broad on purpose: this is the CLI boundary and the scan record must be written
        # whatever happened. The traceback goes to stderr rather than into the record --
        # a stored repr() alone has sent more than one debugging session in circles.
        rec.update(status="failed", finished_at=time.time(), error=repr(exc))
        store.put_json(f"scans/{sid}/scan.json", rec)
        print(f"scan failed: {exc!r}", file=sys.stderr)
        traceback.print_exc()
        return 1

    summary = eg.summary(res["summary"])
    store.put_json(f"scans/{sid}/summary.json", summary)
    store.put_json(f"scans/{sid}/findings.json", [eg.finding(f, spec) for f in res["findings"]])
    rec.update(status="complete", finished_at=time.time())
    store.put_json(f"scans/{sid}/scan.json", rec)

    if not a.quiet:
        c = summary["counts"]
        print(f"{sid}  {a.label or a.lei} FY{a.year}  spec {a.spec_version}")
        for k in ("records_in_scope", "denials_in_scope", "denials_non_exempt",
                  "denials_with_matched_comparator", "denials_testable_by_code_marginal",
                  "untestable_code_present", "untestable_below_resolution",
                  "denials_with_dominating_comparator", "denials_with_finding",
                  "findings_below_power_floor", "suppressed_k"):
            print(f"  {k:38} {c.get(k)}")
        print(f"  scan-level test {json.dumps(summary.get('scan_level_test'))}")
        print(f"  null {json.dumps(summary.get('null'))}")
        for t in summary.get("tripwire_breaches", []):
            print(f"  TRIPWIRE {json.dumps(t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
