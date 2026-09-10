#!/usr/bin/env python3
"""Assemble the document package: every document, plus the rendered pages.

Kept as a script rather than a shell one-liner for the same reason the onboarding pack
is a make target -- a distributable whose build lives only in somebody's shell history
cannot be rebuilt, and the first time that mattered here the onboarding pack's internal
links pointed at a directory that had never existed in the repository.

The rendered HTML and PDF are inputs, not outputs of this script: they are produced from
the two authored pages and passed in with --rendered. If that directory is absent the
pack still builds, without them, and says so.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

INDEX = """# Likewise — document set

Version {version} · comparability specification {spec} in force · Apache License 2.0

Everything here is documentation. The source is distributed separately as
`likewise-{version}.tar.gz`.

## Start here

| If you are | Read |
| :--- | :--- |
| A compliance officer, or anyone new to the idea | `rendered/one-denial-start-to-finish.pdf` — one denied application followed all the way through, with each statistical method explained from scratch |
| Looking for the shape of the system | `rendered/how-likewise-decides.pdf` — the eight pipeline stages, where each one refuses, and the two acceptance gates |
| Going to run it | `onboarding/INSTALL.md`, then `reference/USER_GUIDE.md` |
| Going to change it | `CONTRIBUTING.md` first. It is short, and every rule in it exists because breaking it produced a wrong answer that looked right |

Both rendered documents are included as HTML too, which is how they were authored and
where the diagrams are sharpest.

## reference/

| File | What it covers |
| :--- | :--- |
| `USER_GUIDE.md` | Every screen and every number, for anyone |
| `METHOD.md` | The statistics: matching, dominance, resolution, the single inferential claim, sensitivity, controls, and the collected limits |
| `DESIGN.md` | Architecture, schemas, contracts, testing, packaging |
| `OPERATIONS.md` | Deploying, configuring, backing up, troubleshooting |
| `PRECEDENCE.md` | Admission when a prior adjudication governs, and why silence must never bind |
| `DISTINGUISH_ENGINE.md` | Serving a second domain, and the retrieval–gate coherence property |
| `EXTRACTION.md` | Reading prose into a structured record, and how that reader is scored |
| `REVIEW_RECORD_V3.md` | An external design review: accepted, rejected, and what it missed |
| `likewise_lar_dictionary.csv` | Every input column, its allowed values, and what the engine uses it for |

## specifications/

The three formal documents, in Word and in their markdown source. They follow the
standards a reviewer will expect: ISO/IEC/IEEE 29148 for the requirements specification,
ISO/IEC/IEEE 42010 for the architecture description, IEEE Std 1016 for the software
design description.

## analysis/

`ANALYSIS.pdf` — the analysis report: what the engine estimates, whether the estimators
are implemented correctly, how the design behaves at the sizes and the resolution the
published record actually has, and what the available data does and does not support.
Eleven figures, all of them drawn from the JSON artefacts alongside them, which is why
nothing in the report is a number typed by hand.

Read section 0 first. It is five claims and where each is established.

## onboarding/

A guided reading order for someone joining the project:
`README.md` → `INSTALL.md` → `PRODUCT.md` → `MODELS.md` → `PIPELINE.md` →
`ARCHITECTURE.md` → `TECHNICAL-SPEC.md`. Its cross-references point at `../reference/`,
which is why the two directories travel together.

## Before showing anyone a result

`reference/METHOD.md` collects the limitations. Two of them decide how much weight a
result can carry, and both are in the walkthrough as well: only about one denial in five
has a comparable approved application, and the sensitivity bound is low enough that these
findings cannot support an enforcement action. They are a place to start reading files.
"""

RENDERED = {
    "how-likewise-decides.html": "how-likewise-decides.html",
    "one-denial-start-to-finish.html": "one-denial-start-to-finish.html",
    "how-likewise-decides.pdf": "how-likewise-decides.pdf",
    "one-denial-start-to-finish.pdf": "one-denial-start-to-finish.pdf",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rendered", default=None,
                    help="directory holding the rendered HTML and PDF pages")
    ap.add_argument("--out", default=None)
    ap.add_argument("--specs", default=None,
                    help="directory holding the three formal specification documents")
    a = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from likewise import __version__ as version
    from likewise.specs import IN_FORCE

    out = pathlib.Path(a.out or ROOT / f"likewise-documents-{version}.zip")
    stage = pathlib.Path(tempfile.mkdtemp()) / f"likewise-documents-{version}"
    for sub in ("reference", "onboarding", "rendered", "analysis", "analysis/figures",
                "specifications"):
        (stage / sub).mkdir(parents=True)

    for f in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE", "NOTICE"):
        shutil.copy2(ROOT / f, stage / f)
    for f in sorted((ROOT / "docs").glob("*.md")):
        shutil.copy2(f, stage / "reference" / f.name)
    for f in sorted((ROOT / "onboarding").glob("*.md")):
        shutil.copy2(f, stage / "onboarding" / f.name)
    dic = ROOT / "docs" / "templates" / "likewise_lar_dictionary.csv"
    if dic.exists():
        shutil.copy2(dic, stage / "reference" / dic.name)

    # The analysis package's own outputs. They are copied rather than regenerated: this
    # script assembles a distributable and must not silently produce a different result
    # from the one the author looked at. If `analysis/out` is absent the pack still
    # builds and says so, the same way it does for the rendered pages.
    aout = ROOT / "analysis" / "out"
    analysis_missing = []
    for name in ("ANALYSIS.pdf", "ANALYSIS.html", "ANALYSIS.md", "figures.pdf",
                 "crossvalidation.json", "simulation.json", "eda.json"):
        src_f = aout / name
        if src_f.exists():
            shutil.copy2(src_f, stage / "analysis" / name)
        else:
            analysis_missing.append(name)
    for f in sorted((aout / "figures").glob("*.png")):
        shutil.copy2(f, stage / "analysis" / "figures" / f.name)

    # The three formal specifications, in Word and in source, from wherever they are
    # authored. SPEC_DIR may be pointed elsewhere; the default is a sibling of the repo.
    spec_dir = pathlib.Path(a.specs) if a.specs else ROOT.parent / "specs-out"
    spec_missing = []
    if spec_dir.is_dir():
        for f in sorted(spec_dir.iterdir()):
            if f.suffix in (".docx", ".md") and f.name != "build.js":
                shutil.copy2(f, stage / "specifications" / f.name)
    else:
        spec_missing.append(str(spec_dir))

    missing = []
    if a.rendered:
        src = pathlib.Path(a.rendered)
        for want, name in RENDERED.items():
            hit = next((p for p in src.iterdir() if p.name == want), None)
            if hit is None:
                # tolerate the authored filenames the pages were written under
                alt = {"how-likewise-decides.html": "flow.html",
                       "one-denial-start-to-finish.html": "journey.html"}.get(want)
                cands = [p for p in src.iterdir()
                         if p.name == alt or (want.endswith(".pdf") and p.suffix == ".pdf"
                                              and want.split("-")[0] in p.name.lower())]
                hit = cands[0] if cands else None
            if hit is None:
                missing.append(want)
            else:
                shutil.copy2(hit, stage / "rendered" / name)
    else:
        missing = list(RENDERED)

    (stage / "INDEX.md").write_text(INDEX.format(version=version, spec=IN_FORCE))
    for label, items in (("analysis artefact", analysis_missing),
                         ("specification directory", spec_missing)):
        if items:
            print(f"NOTE: {len(items)} {label}(s) not found: {items}", file=sys.stderr)
    if missing:
        # Said out loud rather than shipped quietly incomplete.
        print(f"NOTE: {len(missing)} rendered file(s) not supplied: {missing}",
              file=sys.stderr)
        (stage / "rendered" / "README.md").write_text(
            "The rendered HTML and PDF pages were not included in this build.\n")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(stage.parent))
    n = len(zipfile.ZipFile(out).namelist())
    print(f"{out}  ({n} files, {out.stat().st_size // 1024} KB)")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
