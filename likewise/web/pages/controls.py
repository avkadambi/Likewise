"""Negative controls and the permutation null.

What the pipeline finds when there is nothing to find. Controls and nulls are a page in
the product and an API resource, not a notebook somebody ran once: each control carries
the rate it expected BEFORE the run, so a pass is informative rather than merely
non-significant.

The module renders controls.json and the stored null. It runs no control and computes no
statistic, and the publication gate it displays was decided by the run -- this page
states the consequence, it does not apply it.
"""
from __future__ import annotations

from ..charts import _null_chart
from ..format import (e)
from ..layout import corners, page, tripwire_chip

# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
def controls_page(sid: str, rec: dict, summary: dict, controls: dict | None) -> str:
    # No controls at all is its own page, and it says the scan is not publishable and
    # what to run. Rendering the findings-side chrome with an empty controls panel would
    # let an uncontrolled scan look like a controlled one that passed.
    if not controls:
        body = ('<h1 class="page">Checks &amp; limits</h1><div class="card"><p class="lede" '
                'style="margin:0">Controls have not been computed for this scan. A rate is not '
                'served without them, so nothing on this scan is publishable until they are: '
                '<span class="mono">make controls SCAN=' + e(sid) + "</span></p></div>")
        return page("Controls", body, active="controls", sid=sid, chip=tripwire_chip(summary))

    # One card per control, with the expected rate printed beside the observed one and
    # the primary control marked. Anything that is not "pass" -- including inconclusive
    # and not-computable -- is shown as its own word rather than folded into a FAIL, so a
    # control that could not be computed is not read as one that was and failed.
    rows = []
    for c in controls["controls"]:
        gate = c["gate"]
        tag = ('<span class="tag tag-accent" style="font-size:10px">PASS</span>' if gate == "pass"
               else '<span class="tag" style="font-size:10px;background:var(--color-neutral-800);'
                    'color:#fff">' + e(gate.upper()) + "</span>")
        prim = ('<span class="tag tag-outline mono" style="font-size:9.5px">PRIMARY</span> '
                if c.get("primary") else "")
        ci = ("  [%s, %s]" % tuple(c["ci95"])) if c.get("ci95") else ""
        rows.append(f"""<div class="card{' blueprint' if c.get('primary') else ''}"
     style="margin-bottom:11px{';border-color:var(--color-neutral-800)' if gate != 'pass' else ''}">
  {corners() if c.get('primary') else ''}
  <div style="display:grid;grid-template-columns:1fr 118px 128px 96px 92px;gap:16px;align-items:center">
    <div><div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap">
      {prim}<span style="font:600 15px/1.2 var(--font-heading)">{e(c['name'])}</span></div>
      <div class="muted" style="font:11.5px/1.5 var(--font-body);max-width:62ch">{e(c['description'])}</div></div>
    <div><div class="kicker">EXPECTED</div><div class="mono" style="font-size:14px">{e(c['expected'])}</div></div>
    <div><div class="kicker">OBSERVED</div><div class="mono" style="font-size:14px;font-weight:600">
      {e(c['observed'])}{e(ci)}</div></div>
    <div><div class="kicker">{'POWERED' if c.get('powered') is not None else 'N'}</div>
      <div class="mono" style="font-size:14px">{e(c.get('n'))}</div></div>
    <div>{tag}</div>
  </div>
</div>""")

    # The verdict panel lists what this scan may and may not be used for, line by line.
    # Internal review stays allowed when publication is blocked: the findings are still
    # worth a reviewer's time, and a block that hid them would push the work somewhere
    # with no controls at all.
    blocked = controls.get("publication_blocked")
    verdict = f"""<div class="card blueprint" style="border-color:var(--color-neutral-800)">{corners()}
  <h2 class="sec">WHAT THIS SCAN CANNOT CLAIM</h2>
  <p style="font:12.5px/1.6 var(--font-body);margin:0 0 11px">
    {'The primary control did not pass, so external publication is blocked. Findings remain viewable and dispositionable, and the banner follows them onto every finding page and every export.' if blocked else 'All controls passed. Publication is unblocked; every other stated limitation still applies.'}</p>
  <div class="mono muted" style="font-size:11px;line-height:1.7">
    {'blocked' if blocked else 'allowed'} &nbsp;external publication<br>
    {'blocked' if blocked else 'allowed'} &nbsp;customer-facing figures<br>
    allowed &nbsp;internal review and disposition<br>
    gate &nbsp;primary control must PASS, not merely fail to fail
  </div>
</div>"""

    body = f"""
<h1 class="page">What the pipeline finds when there is nothing to find.</h1>
<p class="lede">Controls and null summaries are API resources and a page in the product, not
  analysis notebooks. Each control states its expected rate before the run, so a pass is
  informative rather than merely non-significant.</p>
<div class="two">
  <div>
    {''.join(rows)}
    <div class="card blueprint" style="margin-top:20px">{corners()}
      <div style="display:flex;align-items:baseline;justify-content:space-between;gap:10px;
                  flex-wrap:wrap;margin-bottom:14px">
        <div style="font:600 14px/1 var(--font-heading);letter-spacing:.04em">PERMUTATION NULL</div>
        <div class="mono muted" style="font-size:10.5px">exact within cell · labels permuted,
          covariates held</div>
      </div>
      {_null_chart(controls.get('null') or summary.get('null'))}
      <div class="mono muted" style="font-size:11px;line-height:1.6;
           border-top:1px solid var(--color-divider);margin-top:14px;padding-top:11px">
        Read the null and the controls together; either alone is misleading. The null says
        whether the matched geometry alone would produce this many findings. The controls say
        whether the survival test fires on dimensions the denial never cited.</div>
    </div>
  </div>
  <div class="stack">
    {verdict}
    <div class="card tight"><h2 class="sec">PUBLISHED ARTEFACTS</h2>
      <div style="display:grid;gap:6px;font:12px/1.4 var(--font-body)">
        <div style="display:flex;justify-content:space-between"><span>Materiality specification</span>
          <a class="mono" href="/ui/spec">view</a></div>
        <div style="display:flex;justify-content:space-between"><span>Tolerance sweep</span>
          <a class="mono" href="/ui/scans/{sid}/sweep">view</a></div>
        <div style="display:flex;justify-content:space-between"><span>Coverage &amp; denominators</span>
          <a class="mono" href="/ui/scans/{sid}/coverage">view</a></div>
        <div style="display:flex;justify-content:space-between"><span>Controls JSON</span>
          <a class="mono" href="/v1/scans/{sid}/controls">view</a></div>
      </div>
      <div class="mono muted" style="font-size:10.5px;margin-top:10px;line-height:1.55">Addressable
        by URL and versioned with the release.</div></div>
  </div>
</div>"""
    return page("Checks & limits", body, active="controls", sid=sid,
                crumb="Controls / " + sid, chip=tripwire_chip(summary))


