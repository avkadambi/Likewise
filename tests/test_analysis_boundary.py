"""The analysis layer must never become a dependency of the served engine.

`analysis/` exists so the statistics can be checked against SciPy, statsmodels and
NumPy, and so the study figures can be drawn. None of that belongs in a container that
has to stay small, start fast and make no outbound call. The separation is only real if
it is enforced, so it is enforced here rather than described in a README: if an import
of `analysis` -- or of any scientific package -- ever appears in `likewise/` or
`extract/`, this test fails and the release does not ship.

The check is a source scan rather than an import hook because it has to catch an import
sitting inside a function body, which never executes during a test run and so would be
invisible to any runtime check.
"""
from __future__ import annotations
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVED = ("likewise", "extract")

# The analysis stack, by top-level module name. `torch` is absent from this list on
# purpose: `extract.backends` imports it lazily and the extraction stage is not part of
# the served image either, which is a separate boundary with its own test.
FORBIDDEN = {"analysis", "numpy", "scipy", "pandas", "statsmodels", "matplotlib",
             "sklearn", "seaborn"}


def _modules_imported_by(path: Path) -> set[str]:
    """Every top-level module name imported anywhere in one file, function bodies included."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # A relative import (level > 0) cannot reach out of the package, so it can
            # never be one of the forbidden top-level names.
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def _served_sources() -> list[Path]:
    return sorted(p for pkg in SERVED for p in (ROOT / pkg).rglob("*.py"))


def test_the_served_packages_import_nothing_from_the_analysis_stack():
    offenders = {}
    for src in _served_sources():
        bad = _modules_imported_by(src) & FORBIDDEN
        if bad:
            offenders[str(src.relative_to(ROOT))] = sorted(bad)
    assert not offenders, (
        "the served engine must not depend on the analysis stack; "
        f"found {offenders}")


def test_the_scan_looks_at_a_real_and_non_empty_set_of_files():
    """A boundary test that scans nothing passes for the wrong reason."""
    srcs = _served_sources()
    assert len(srcs) >= 15, f"only {len(srcs)} served source files found"
    assert any(p.name == "stats.py" for p in srcs)


def test_the_scan_would_actually_catch_a_violation(tmp_path: Path):
    """The detector, tested on a file that does violate the rule -- including the case
    that motivated a source scan, an import hidden inside a function body."""
    f = tmp_path / "sample.py"
    f.write_text("import math\n\n\ndef go():\n    import numpy as np\n    return np\n")
    assert "numpy" in _modules_imported_by(f)
    f.write_text("from scipy import stats\n")
    assert "scipy" in _modules_imported_by(f)
    f.write_text("from . import core\n")
    assert not _modules_imported_by(f) & FORBIDDEN


@pytest.mark.parametrize("pkg", SERVED)
def test_the_served_requirements_name_none_of_the_analysis_stack(pkg: str):
    """The dependency list is the other half of the same boundary: a package that is not
    installed in the image cannot be imported from it, whatever the source says."""
    req = (ROOT / "requirements.txt").read_text().lower()
    for name in sorted(FORBIDDEN - {"analysis"}):
        assert name not in req, f"{name} must not appear in the served requirements"
