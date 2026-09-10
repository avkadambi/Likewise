"""Load CSV filings from the drop folder into a curated snapshot.

    python3 tools/load.py                      # everything in data/inbox
    python3 tools/load.py --file path/to.csv   # one named file
    python3 tools/load.py --and-scan           # load, then scan, sweep and controls

A snapshot is one filer-year. The snapshot id defaults to a name derived from the filing
year and today's date, so re-loading the same filing on the same day overwrites rather
than accumulating near-duplicate snapshots.
"""
from __future__ import annotations
import argparse, glob, json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from likewise import loader, paths, specs
from likewise.errors import SpecError

INBOX = paths.inbox()


def _spec(version: str):
    return specs.load(version=version)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", default=INBOX)
    ap.add_argument("--file", action="append", default=[],
                    help="load these files instead of scanning the inbox")
    ap.add_argument("--header", default=None,
                    help="a file whose first line supplies the column names, for "
                         "rows-only exports that arrive without a header")
    ap.add_argument("--snapshot", default=None, help="snapshot id (default: derived)")
    # Defaults to the version IN FORCE. A pinned default here meant the CLI ran a
    # standard the service no longer served, and the disagreement was invisible
    # because both labelled their output honestly with the version they used.
    ap.add_argument("--spec-version", default=specs.IN_FORCE)
    ap.add_argument("--label", default="", help="human name shown on the scan list")
    ap.add_argument("--manifest", default=None,
                    help="JSON file of provenance facts merged into the snapshot manifest "
                         "(source, retrieval method, known gaps). The coverage screen "
                         "renders it.")
    ap.add_argument("--internal-data", action="store_true",
                    help="accept data that is NOT at publication granularity; the snapshot "
                         "is stamped non-public and every scan on it says so")
    ap.add_argument("--archive", action="store_true",
                    help="move loaded files to data/inbox/loaded/ on success")
    ap.add_argument("--and-scan", action="store_true",
                    help="run scan, sweep and controls on the new snapshot")
    a = ap.parse_args()

    paths = a.file or sorted(p for p in glob.glob(os.path.join(a.inbox, "*.csv")))
    if not paths:
        print(f"nothing to load: put a .csv in {a.inbox}/ "
              f"(start from docs/templates/likewise_lar_template.csv)", file=sys.stderr)
        return 2

    try:
        spec = _spec(a.spec_version)
    except SpecError as e:
        e.emit_and_exit()

    print(f"loading {len(paths)} file(s) from {a.inbox}")
    for p in paths:
        print(f"  {os.path.basename(p)}")

    snapshot_id = a.snapshot or f"filing_{time.strftime('%Y-%m-%d')}"
    try:
        got = loader.load(paths, spec.snapshot, snapshot_id,
                          allow_nonconforming=a.internal_data, header_file=a.header)
    except SpecError as e:
        print(f"\nREFUSED: {e.kind}\n", file=sys.stderr)
        json.dump(e.payload(), sys.stderr, indent=2, sort_keys=True)
        sys.stderr.write("\n")
        return 78

    extra = json.load(open(a.manifest)) if a.manifest else {}
    extra.setdefault("source", "operator drop folder")
    extra.update({
        "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "public_record": got["granularity_conforming"],
        "public_record_note": (
            "Values conform to the publication granularity the resolution budget assumes."
            if got["granularity_conforming"] else
            "LOADED WITH --internal-data. These values are NOT at publication granularity, "
            "so the resolution budget does not describe this snapshot and no margin on it "
            "should be read against a published bin width."),
    })
    wrote = loader.write_manifest(got, snapshot_id, extra=extra)

    print(f"\nloaded {got['rows_written']} rows  layout={got['layout']}  "
          f"filer={got['lei']}  year={got['activity_year']}")
    print(f"  duplicates dropped   {got['duplicates_dropped']}")
    print(f"  sentinels normalised {got['normalisation_causes']}")
    print(f"  publication granularity: "
          f"{'conforms' if got['granularity_conforming'] else 'NON-PUBLIC (stamped)'}")
    for f, r in sorted(got["granularity_report"].items()):
        if r.get("conforming") is not None and r.get("n"):
            print(f"    {f:32} {r['conforming']}/{r['n']}  {r['expected']}")
    print(f"  parquet   {got['parquet']}")
    print(f"  manifest  {wrote['manifest']}")

    if a.archive:
        dest = os.path.join(a.inbox, "loaded")
        os.makedirs(dest, exist_ok=True)
        for p in paths:
            os.replace(p, os.path.join(dest, os.path.basename(p)))
        print(f"  archived  {dest}/")

    cmd = [sys.executable, "tools/run_scan.py", "--lei", got["lei"],
           "--year", str(got["activity_year"]), "--snapshot", snapshot_id,
           "--spec-version", a.spec_version, "--label", a.label or snapshot_id]
    if not a.and_scan:
        print("\nnext:\n  " + " ".join(cmd))
        return 0

    print("\n--- scan ---")
    if subprocess.run(cmd).returncode not in (0,):
        return 1
    import hashlib
    sid = "scn_" + hashlib.sha256(
        f"{got['lei']}|{got['activity_year']}|{a.spec_version}|{spec.snapshot_id}|"
        f"{snapshot_id}".encode()).hexdigest()[:16]
    print("\n--- sweep (findings are not servable without it) ---")
    subprocess.run([sys.executable, "tools/run_sweep.py", "--scan-id", sid])
    print("\n--- controls: the publication gate ---")
    subprocess.run([sys.executable, "tools/run_controls.py", "--scan-id", sid])
    print(f"\ndone. make serve, then http://127.0.0.1:8080/ui/scans/{sid}/queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
