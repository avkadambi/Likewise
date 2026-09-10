"""Mutation harness. Release gate: kill rate >= 0.90.

A pass RATE over a handful of hand-built fixtures is not a rate, and it makes deleting
the failing item a valid fix. This measures whether the suite detects real, catalogued
defects instead.
"""
import json, os, pathlib, shutil, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tests.mutants import CATALOGUE

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _purge_bytecode():
    """Same-length replacements (`<=` -> `<`, `all(` -> `any(`) leave file size and
    often the mtime second unchanged, so CPython serves a stale .pyc and the mutation
    silently never runs -- reporting a kill that did not happen. A harness that
    spuriously reports kills is worse than no harness."""
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def run_suite() -> bool:
    _purge_bytecode()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    # -m "not slow" drops the multi-megabyte scaling test. It costs ~40s per mutant and
    # no catalogue entry depends on it: the cheap companion test covers the same setting.
    r = subprocess.run([sys.executable, "-B", "-m", "pytest", "tests/", "-q", "-x",
                        "-m", "not slow", "--no-header", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    return r.returncode == 0


SNAPSHOT = ROOT / ".mutation-snapshot"


def _snapshot_sources() -> list[pathlib.Path]:
    return sorted({ROOT / e[1] for e in CATALOGUE})


def restore_any_leftover() -> list[str]:
    """Put back anything an interrupted run left mutated.

    The finally block that restores a source file does not survive SIGKILL, and the outer
    process here is often a timeout. A run cut short in the middle leaves one mutation
    applied to the working tree, where it is invisible: the next `make test` fails on an
    unrelated-looking assertion and the file looks hand-edited. This happened -- M15 was
    found sitting in specs.py, turning the strictly-greater comparison Rule 3 depends on
    into a non-strict one. Restoring first, and warning loudly, costs one file read each.
    """
    if not SNAPSHOT.is_dir():
        return []
    restored = []
    for src in _snapshot_sources():
        keep = SNAPSHOT / src.relative_to(ROOT)
        if keep.is_file() and keep.read_bytes() != src.read_bytes():
            src.write_bytes(keep.read_bytes())
            restored.append(str(src.relative_to(ROOT)))
    return restored


def take_snapshot():
    if SNAPSHOT.is_dir():
        shutil.rmtree(SNAPSHOT)
    for src in _snapshot_sources():
        dst = SNAPSHOT / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main():
    leftover = restore_any_leftover()
    if leftover:
        print("RESTORED from an interrupted previous run: " + ", ".join(leftover))
        print("  Re-run any result produced since that run: the working tree was mutated.")
        _purge_bytecode()
    take_snapshot()
    try:
        return _main()
    finally:
        again = restore_any_leftover()
        if again:
            print("restored on exit: " + ", ".join(again))
        shutil.rmtree(SNAPSHOT, ignore_errors=True)


def _main():
    assert run_suite(), "baseline suite must be green before mutating"
    killed, survived, inapplicable, equivalent = [], [], [], []
    for entry in CATALOGUE:
        mid, rel, find, repl, prov = entry[:5]
        kind = entry[5] if len(entry) > 5 else "defect"
        p = ROOT / rel
        original = p.read_text()
        if find not in original:
            inapplicable.append((mid, prov)); continue
        if kind == "equivalent":
            equivalent.append((mid, prov)); continue
        try:
            p.write_text(original.replace(find, repl, 1))
            os.utime(p, (time.time() + 1, time.time() + 1))   # force mtime change
            (killed if not run_suite() else survived).append((mid, prov))
        finally:
            p.write_text(original)          # guaranteed restoration
    total = len(killed) + len(survived)
    rate = len(killed) / total if total else 0.0
    print("=" * 78)
    print(f"MUTATION KILL RATE  {len(killed)}/{total} = {rate:.2%}   gate >= 90%   "
          f"{'PASS' if rate >= 0.90 else 'FAIL'}")
    print("=" * 78)
    if survived:
        print("\nSURVIVED (the suite does not detect these):")
        for mid, prov in survived: print(f"  {mid}  {prov}")
    if equivalent:
        print("\nEQUIVALENT (proved behaviour-preserving; excluded from the rate):")
        for mid, prov in equivalent: print(f"  {mid}  {prov}")
    if inapplicable:
        print("\nNOT APPLICABLE (pattern absent -- catalogue drift, fix the entry):")
        for mid, prov in inapplicable: print(f"  {mid}  {prov}")
    assert run_suite(), "suite must be green after restoration"
    os.makedirs("data/store", exist_ok=True)
    with open("data/store/mutation.json", "w") as fh:
        json.dump({"killed": len(killed), "total": total, "rate": round(rate, 4),
                   "survived": [m for m, _ in survived],
                   "equivalent": [m for m, _ in equivalent],
                   "inapplicable": [m for m, _ in inapplicable]}, fh, indent=2)
    return 0 if rate >= 0.90 else 1


if __name__ == "__main__":
    sys.exit(main())
