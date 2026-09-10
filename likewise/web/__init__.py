"""Server-rendered web view.

The renderer reads the SAME post-egress artifacts the API serves -- summary.json,
findings.json, sweep.json, controls.json -- and never touches a raw Finding. That is
what keeps the s10.1 exclusivity contract true at every width: the mobile layout is a
stylesheet, not a second serialisation route.

Two places this build knowingly departs from the drawn frames, both because the drawn
frame would breach a constraint the implementation already holds:

  * The frames show the two records' exact values (78.2% against 84.6%). Egress bands
    every published financial field before it leaves the process, so what renders here
    is the band, the margin and the decisive threshold. Un-banded display of a filer's
    own portfolio is a live policy question; it is not a
    thing the renderer may decide on its own.
  * The frames say "same census tract". The geography ceiling in force is the county:
    census tract is dropped at ingest so no downstream code can emit it.

This module was one 1,364-line file. It is a package now, split by responsibility, and
the public surface is unchanged: api.py and every test still call `web.queue_page(...)`.

Deliberately NOT a template engine. Jinja2 was proposed and rejected: it adds a runtime
dependency, and more importantly a second place where a value can be interpolated into a
response. The exclusivity contract is enforced by a static check over this package plus a
route walk over the rendered output; a template directory is a hole in the first half of
that, for a readability gain that splitting the file already delivers.

What this package owns: markup. What it does NOT own: reading, computing or deciding.
It opens no file, holds no credential and calls no store -- api.py loads the stored
artifacts and passes them in. A page is a pure function of what it was handed, which is
why the tests can render one from a dictionary.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# The public surface
# ---------------------------------------------------------------------------
# Re-exported so callers keep saying `web.queue_page(...)`. The split into modules was a
# readability change and was not allowed to be an interface change: api.py and every test
# import from this package alone, so a further split moves names in here and nowhere
# else. The two chart builders keep their private names and are left out of __all__:
# the pages that draw them import from .charts directly, and nothing outside the package
# is meant to.
from .charts import _null_chart as _null_chart
from .charts import _sweep_chart as _sweep_chart
from .format import (DIM_LABEL, DIM_UNIT, DISPOSITIONS, REASONS_FALLBACK, VERDICT,
                     claim, e, fmt_margin, gap_short, gap_words, money, ordinal,
                     strength, verdict_counts)
from .layout import NAV, blocked_banner, corners, page, tripwire_chip
from .pages.controls import controls_page
from .pages.coverage import TRIPWIRE_MEANING, coverage_page
from .pages.finding import finding_page
from .pages.queue import finding_row, queue_page
from .pages.scans import scans_page
from .pages.spec import spec_page
from .pages.sweep import sweep_page
from .specfiles import read_versions

# Explicit, and sorted, so a name that quietly stops being exported shows up as a
# one-line diff rather than as an import error somewhere else.
__all__ = [
    "DIM_LABEL", "DIM_UNIT", "DISPOSITIONS", "NAV", "REASONS_FALLBACK",
    "TRIPWIRE_MEANING", "VERDICT", "blocked_banner", "claim", "controls_page",
    "corners", "coverage_page", "e", "finding_page", "finding_row", "fmt_margin",
    "gap_short", "gap_words", "money", "ordinal", "page", "queue_page",
    "read_versions", "scans_page", "spec_page", "strength", "sweep_page",
    "tripwire_chip", "verdict_counts",
]
