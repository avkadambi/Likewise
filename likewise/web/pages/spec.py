"""The comparability specification in force.

The page that answers the first question an informed reviewer asks: whether the
thresholds were chosen to produce the result. It prints the loaded specification, the
version history with each version's written rationale, and -- when a scan was refused --
that refusal's payload verbatim.

Read-only, and the only page in the web view that is not built from a scan artifact.
Changing a specification is a pull request against the specification repository; nothing
here can edit one, and the module makes no policy decision of its own. The one number it
derives is the comparability floor, which it asks specs.py to compute.
"""
from __future__ import annotations
import json

from ...specs import DEFAULT_GATE_REFERENCE, comparability_floor
from ..format import (DIM_LABEL, e)
from ..layout import corners, page

# ---------------------------------------------------------------------------
# The dimension table
# ---------------------------------------------------------------------------
def spec_page(spec, versions: list[dict], active_v: str, refusal: dict | None,
              scans_on_version: list[dict]) -> str:
    m, b = spec.raw, spec.budget.raw
    gran = spec.snapshot["publication_granularity"]
    floors = {}
    for fld in b["dimensions"]:
        try:
            floors[fld] = comparability_floor(spec, fld, DEFAULT_GATE_REFERENCE)[0]
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            # Rendered as "—". A dimension whose floor cannot be evaluated at the
            # reference is shown as unknown rather than as zero, which would read as
            # "no floor applies" -- the opposite of the truth.
            floors[fld] = None

    def row(name, role, tol, field):
        g = gran.get(field, {})
        gtxt = ("%s %s" % (g.get("width"), g.get("unit", ""))).strip() if g else "—"
        dim = b["dimensions"].get(field)
        check = "not a budgeted dimension"
        if dim:
            thr = dim["decisive_threshold"]
            # The binding floor is whichever is larger: how coarsely the field is published,
            # or how much slack the matcher's own tolerances propagate into it. For a ratio
            # of two binned quantities the second dominates by three orders of magnitude,
            # and checking only against the first flatters the specification.
            floor = max(dim.get("granularity") or 0.0, floors.get(field) or 0.0)
            if floors.get(field):
                gtxt += " · comparability floor %.3g" % floors[field]
            mult = (thr / floor) if floor else float("inf")
            check = (("pass · %.3g× the binding floor" % mult) if mult >= 1
                     else "FAIL · tighter than the binding floor")
        return ('<tr><td style="font-weight:600">' + e(name) + '</td><td class="mono">'
                + e(role) + '</td><td class="mono">' + e(tol) + '</td><td class="mono">'
                + e(gtxt) + '</td><td class="mono" style="color:var(--color-accent-800)">'
                + e(check) + "</td></tr>")

    # Every role a field can hold gets a row, in a fixed order: tested, control, residual
    # risk, blocking band. A field holding two roles gets two rows: the table is a census
    # of what the specification does with each field, and one row per field would have to
    # choose which of its roles to show.
    rows = []
    for f, d in b["dimensions"].items():
        rows.append(row(DIM_LABEL.get(f, f), "tested",
                        "dominance · decisive at %s" % d["decisive_threshold"], f))
    for f, cf in m.get("control_features", {}).items():
        rows.append(row(DIM_LABEL.get(f, f), "control set",
                        "±%g %s" % (cf["tolerance"], cf.get("unit", "relative")), f))
    for f, rr in m.get("residual_risk", {}).items():
        rows.append(row(DIM_LABEL.get(f, f), "residual risk",
                        "±%g %s" % (rr["tolerance"], rr.get("unit", "")), f))
    for f in sorted(spec.raw.get("blocking", {}).get("band", {})):
        band = spec.raw["blocking"]["band"][f]
        rows.append(row(DIM_LABEL.get(f, f), "blocking band",
                        "±%g rel, floor %s" % (band["relative"], band.get("min_absolute")), f))

    # ---------------------------------------------------------------------------
    # A refusal, verbatim
    # ---------------------------------------------------------------------------
    # The stored payload is printed as JSON with sorted keys -- the same object CI
    # asserts against -- rather than paraphrased. A refusal explained in prose is a
    # refusal the reader cannot check against the artifact.
    ref_html = ""
    if refusal:
        ref_html = f"""<div class="card blueprint" style="border-color:var(--color-neutral-800);
      margin-top:20px">{corners()}
  <h2 class="sec">SCAN REFUSED — STRUCTURED ERROR, VERBATIM</h2>
  <p style="font:12px/1.55 var(--font-body);margin:0 0 10px;max-width:84ch">A specification that
    cannot produce a comparison is refused before any record is read, and the process exits
    non-zero rather than returning an empty result that looks like a clean bill of health.
    This is the payload from that refusal — the same object CI asserts against.</p>
  <pre class="err">{e(json.dumps(refusal, indent=2, sort_keys=True))}</pre>
</div>"""

    # ---------------------------------------------------------------------------
    # Version history and the scans on this version
    # ---------------------------------------------------------------------------
    # Each version shows its author, its effective date and its written rationale. A
    # version with no rationale recorded says so in place of it: an empty entry would let
    # an unexplained change pass as an explained one.
    vhtml = []
    for v in versions:
        colour = "var(--color-accent)" if v["version"] == active_v else "var(--color-neutral-300)"
        vhtml.append('<div style="border-left:3px solid ' + colour + ';padding-left:11px;'
                     'margin-bottom:13px"><div class="mono" style="font-size:11.5px;font-weight:600">v'
                     + e(v["version"]) + (" · in force" if v["version"] == active_v else "")
                     + '</div><div class="mono dim" style="font-size:10.5px;margin:3px 0 5px">'
                     + e(v.get("author", "")) + " · " + e(v.get("effective_date", "")) + "</div>"
                     '<div style="font:11.5px/1.5 var(--font-body)">' + e(v.get("rationale") or
                     "No written rationale recorded for this version.") + "</div></div>")

    shtml = "".join(
        '<div style="display:flex;justify-content:space-between;gap:10px"><a class="mono" href="/ui/scans/'
        + e(s["scan"]["scan_id"]) + '/queue">' + e(s["scan"]["scan_id"][:16])
        + '</a><span class="mono muted">'
        + str((s.get("summary") or {}).get("counts", {}).get("denials_with_finding", 0))
        + " findings</span></div>"
        for s in scans_on_version) or '<div class="mono muted">None on this version.</div>'

    body = f"""
<div class="two">
  <div>
    <div style="display:flex;align-items:center;gap:9px;margin:20px 0 7px;flex-wrap:wrap">
      <span class="tag tag-accent mono" style="font-size:10.5px">IN FORCE</span>
      <span class="mono" style="font-size:12px">v{e(spec.version)}</span>
      <span class="mono dim" style="font-size:11px">{e(m.get('author'))} ·
        {e(m.get('effective_date'))} · validated against {e(spec.snapshot_id)}</span>
    </div>
    <h1 class="page" style="margin-top:0">The comparability standard is a file, not a setting.</h1>
    <p class="lede">No statute defines materiality numerically. A 0.4 percentage point
      loan-to-value difference is the entire case in some files and rounding noise in others.
      This document is under version control, changed only by a new version with a written
      rationale and a named author, and cited by digest on every finding. It is not fitted.</p>
    <div class="scroll-x"><table class="data">
      <tr><th>DIMENSION</th><th>ROLE</th><th>TOLERANCE</th><th>PUBLICATION GRANULARITY</th><th>LOAD CHECK</th></tr>
      {''.join(rows)}
    </table></div>
    {ref_html}
    <div style="margin-top:20px">
      <h2 class="sec">SIBLING POLICY CONSTANTS</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px">
        <div class="card tight"><div style="font:600 13px/1.3 var(--font-body)">Disclosure cohort</div>
          <div class="mono" style="font-size:11.5px;margin-top:5px">k ≥ {e(m['disclosure']['k_min'])},
            geography ceiling {e(m['disclosure']['geography_ceiling'])}</div>
          <div class="mono muted" style="font-size:10.5px;margin-top:5px;line-height:1.5">Cohort is
            defined over the attributes an adversary would use to re-identify a borrower, not over
            the full internal blocking key. Cohorting on the whole key gives a median of one and
            suppresses everything without adding protection.</div></div>
        <div class="card tight"><div style="font:600 13px/1.3 var(--font-body)">Post-treatment guard</div>
          <div class="mono" style="font-size:11.5px;margin-top:5px">disjointness, no threshold</div>
          <div class="mono muted" style="font-size:10.5px;margin-top:5px;line-height:1.5">An
            exact-match field whose denial values and approval values do not intersect is
            determined by the outcome. Blocking on it is provably empty, so the scan refuses
            rather than reporting no comparators.</div></div>
      </div>
    </div>
  </div>
  <div class="stack">
    <div class="card blueprint">{corners()}
      <h2 class="sec">VERSION HISTORY</h2>
      {''.join(vhtml)}
      <div class="mono muted" style="font-size:10.5px;line-height:1.6;
           border-top:1px solid var(--color-divider);padding-top:11px">Read-only in the web view.
        Changes arrive by pull request against the specification repository.</div>
    </div>
    <div class="card tight"><h2 class="sec">SCANS ON THIS VERSION</h2>
      <div style="display:grid;gap:7px;font:11.5px/1.4 var(--font-body)">{shtml}</div>
      <div class="mono muted" style="font-size:10.5px;margin-top:9px;line-height:1.5">Findings never
        migrate across specification versions. A new version means a new scan.</div></div>
    <div class="card tight" style="background:var(--color-accent-100);border-color:var(--color-accent-600)">
      <div class="kicker" style="color:var(--color-accent-800)">WHY THIS SCREEN EXISTS</div>
      <p style="font:11.5px/1.55 var(--font-body);margin:0;color:var(--color-accent-900)">The first
        question an informed reviewer asks is whether the threshold was chosen to produce the
        result. This page and the sweep are the answer, and both are addressable by URL so
        counsel can cite them.</p>
    </div>
  </div>
</div>"""
    return page("Specification", body, active="spec")


