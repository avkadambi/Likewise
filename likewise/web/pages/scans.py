"""Scan list and launch form.

One card per scan, built from the stored scan record and its post-egress summary -- the
filer appears as the first characters of its identifier and nothing here reads a curated
row. The module owns the card and the form; it does not launch anything, and the write
scope it is told about only decides whether the form is drawn at all. The route enforces
the scope again on submission.
"""
from __future__ import annotations

from ..format import (e)
from ..layout import corners, page

# ---------------------------------------------------------------------------
# One card per scan
# ---------------------------------------------------------------------------
def scans_page(rows: list[dict], spec_versions: list[str], can_write: bool) -> str:
    cards = []
    for r in rows:
        rec, summary = r["scan"], r.get("summary") or {}
        c = summary.get("counts", {})
        sid = rec["scan_id"]
        status = rec.get("status")
        den = c.get("denials_non_exempt") or c.get("denials_in_scope") or 0
        matched = c.get("denials_with_matched_comparator") or 0
        untest = (c.get("untestable_code_present") or 0) + (c.get("untestable_below_resolution") or 0)
        pct = lambda n, d: ("%.1f%%" % (100.0 * n / d)) if d else "—"

        # A refused scan gets a card of its own and a link to the verbatim payload. It is
        # not hidden and it is not shown with zeroed counts: a refusal is a result, and a
        # row of zeros would read as a scan that found nothing.
        if status == "refused":
            fails = (rec.get("refusal") or {}).get("failures") or []
            detail = ("Refused before scanning — "
                      + (fails[0].get("field", "") if fails else "")
                      + " is determined by the outcome")
            cards.append(
                '<div class="card" style="opacity:.72;margin-bottom:10px">'
                '<div class="mono dim" style="font-size:10px">' + e(sid) + " · FILER "
                + e(rec["lei"][:8]) + " · FY" + e(rec["activity_year"]) + "</div>"
                '<div style="font:600 15px/1.2 var(--font-heading);margin:3px 0">'
                + e(rec.get("label") or "—") + "</div>"
                '<div class="mono muted" style="font-size:11px">' + e(detail) + "</div>"
                '<div style="margin-top:8px"><span class="tag tag-outline" style="font-size:10px">'
                'REFUSED</span> <a class="mono" href="/ui/spec?v=' + e(rec.get("spec_version", ""))
                + '&refused=' + e(sid) + '">See the refusal →</a></div></div>')
            continue

        # A breached tripwire replaces the COMPLETE badge rather than sitting beside it.
        # The two together would let a reader take the completion as the headline and the
        # breach as a footnote.
        badge = ('<span class="tag" style="font-size:10px;background:var(--color-neutral-800);'
                 'color:#fff">TRIPWIRE ×' + str(len(summary.get("tripwire_breaches") or []))
                 + "</span>") if summary.get("tripwire_breaches") else \
                '<span class="tag tag-accent" style="font-size:10px">COMPLETE</span>'
        cards.append(f"""<a class="card blueprint" style="margin-bottom:10px;display:grid;
   grid-template-columns:1fr 118px 118px 118px 110px;gap:18px;align-items:center;
   text-decoration:none;color:inherit" href="/ui/scans/{sid}/queue">{corners()}
  <div>
    <div class="mono dim" style="font-size:10px">{e(sid)} · FILER {e(rec['lei'][:8])} · FY{e(rec['activity_year'])}</div>
    <div style="font:600 16px/1.2 var(--font-heading);margin:3px 0">{e(rec.get('label') or rec['lei'])}</div>
    <div class="mono" style="font-size:10.5px;color:var(--color-accent-700)">
      spec v{e(rec.get('spec_version'))} · snapshot {e(rec.get('snapshot_id'))} ·
      {e(c.get('records_in_scope', 0)):} records</div>
  </div>
  <div><div class="kicker">FINDINGS</div><div style="font:600 21px/1 var(--font-heading)">{c.get('denials_with_finding', 0)}</div></div>
  <div><div class="kicker">MATCHED</div><div style="font:600 21px/1 var(--font-heading)">{pct(matched, den)}</div></div>
  <div><div class="kicker">UNTESTABLE</div><div style="font:600 21px/1 var(--font-heading)">{pct(untest, den)}</div></div>
  <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-start">{badge}
    <span class="mono dim" style="font-size:10px">{e(rec.get('analysis_status'))}</span></div>
</a>""")

    # ---------------------------------------------------------------------------
    # The launch form
    # ---------------------------------------------------------------------------
    # A read-scope session is told the panel exists and why it cannot use it, rather than
    # being shown a page with a hole in it. The alternative -- rendering the form and
    # letting the post fail -- teaches the operator the wrong thing about their session.
    launch = ""
    if can_write:
        vers = "".join('<option value="' + e(v) + '">' + e(v) + "</option>" for v in spec_versions)
        launch = f"""<form class="card blueprint" method="post" action="/ui/scans">{corners()}
  <h2 class="sec">NEW SCAN</h2>
  <div class="field" style="margin-bottom:10px"><label>Filer LEI</label>
    <input class="input" name="lei" placeholder="paste LEI — hashed before it leaves the process"></div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
    <div class="field"><label>Filing year</label><input class="input" name="year" value="2024"></div>
    <div class="field"><label>Spec version</label><select class="input" name="spec">{vers}</select></div>
  </div>
  <div style="border:1px solid var(--color-divider);padding:10px;margin-bottom:12px;
              background:var(--color-accent-100)">
    <div class="mono" style="font-size:10px;color:var(--color-accent-800);line-height:1.6">
      RESOLVED AT SUBMIT<br>publication snapshot &nbsp;from the chosen spec<br>
      reason map &nbsp;from the chosen spec<br>pre-registration digest &nbsp;computed server-side</div>
  </div>
  <button class="btn btn-primary blueprint block" type="submit">{corners()}Queue scan</button>
  <p class="muted" style="font:11px/1.5 var(--font-body);margin:10px 0 0">Write scope. The read
    session cannot reach this panel.</p>
</form>"""
    else:
        launch = ('<div class="card"><h2 class="sec">NEW SCAN</h2><p class="muted" '
                  'style="font:12px/1.5 var(--font-body);margin:0">Launching a scan needs write '
                  'scope. This session holds read scope only.</p></div>')

    body = f"""
<div class="two">
  <div>
    <h1 class="page">Scans</h1>
    <p class="lede muted" style="font-size:12.5px">A scan is a pure function of filer, year,
      specification version and publication snapshot. Re-running an identical tuple returns the
      existing run rather than recomputing, and findings never migrate across specification
      versions — a new version means a new scan.</p>
    {''.join(cards) or '<div class="card">No scans yet.</div>'}
  </div>
  <div class="stack">{launch}</div>
</div>"""
    return page("Scans", body, active="scans")


