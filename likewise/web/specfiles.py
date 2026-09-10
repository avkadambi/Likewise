"""Reading the specification directory for the version history screen.

The one place in the web package that touches the filesystem, and it reads only the
versioned specification files -- never a scan, a finding or a stored artifact. It parses
no policy out of them either: the loader in specs.py owns what a specification MEANS,
and this owns only the four fields the history screen prints.
"""
from __future__ import annotations

import yaml

# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------
def read_versions(spec_dir: str) -> list[dict]:
    """Version history with the written rationale every version must carry. The rationale is a
    comment block in the specification file itself, so it cannot drift from the file it
    explains."""
    import pathlib
    out = []
    for f in sorted(pathlib.Path(spec_dir).glob("*.yaml")):
        blob = f.read_text()
        raw = yaml.safe_load(blob)
        # The rationale is read out of the file's own comment block rather than a YAML
        # key, so it cannot be edited without touching the specification it explains.
        # The marker names the version, so a file that gained a rationale for a version
        # it is not cannot supply one here.
        marker = "# v%s rationale" % raw["version"]
        rationale = ""
        if marker in blob:
            after = blob.split(marker, 1)[1]
            lines = [after.split("\n", 1)[0].lstrip(" ")]
            # The block ends at the first line that is not a comment. A rationale is a
            # run of comment lines and nothing else, so this cannot swallow settings that
            # happen to follow it.
            for ln in after.split("\n")[1:]:
                if not ln.startswith("#"):
                    break
                lines.append(ln.lstrip("# ").rstrip())
            rationale = " ".join(x for x in lines if x).strip()
            if rationale.startswith("("):
                rationale = rationale.split(").", 1)[-1].strip() or rationale
        out.append({"version": raw["version"], "author": raw.get("author", ""),
                    "effective_date": raw.get("effective_date", ""),
                    "rationale": rationale})
    # Files are read in sorted order and the list is reversed, so the newest version is
    # first -- which is the one the screen marks as in force.
    out.reverse()
    return out
