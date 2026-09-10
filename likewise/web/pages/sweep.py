"""Tolerance sensitivity sweep.

Findings as a function of every tolerance in the specification, drawn from sweep.json --
which the scan produces and stores beside the findings, so no finding can be presented
without it. The chart is inline SVG built by web.charts; this module owns the surrounding
table, and both read the stored points as they are.

It computes nothing. In particular, the refused points are refusals the startup gate
returned when the sweep re-ran it at each threshold, not values this page decided to
exclude.
"""
from __future__ import annotations

from ..charts import _sweep_chart
from ..format import (DIM_LABEL, e)
from ..layout import corners, page, tripwire_chip

# ---------------------------------------------------------------------------
# One block per dimension
# ---------------------------------------------------------------------------
def sweep_page(sid: str, rec: dict, summary: dict, sweep: dict) -> str:
    blocks = []
    for dim, block in sweep["dimensions"].items():
        trows = []
        # A refused threshold takes a spanning row saying it was refused and why. Left as
        # blank cells it would read as a threshold that produced no findings, which is
        # the opposite of a threshold the gate would not run at all.
        for p in block["points"]:
            cls = "on" if p.get("is_operating") else ("off" if "refused" in p else "")
            if "refused" in p:
                cells = ('<td class="mono">' + e(p["value"]) + '</td>'
                         '<td class="mono" colspan="5">refused at the startup gate — '
                         + e(p["refused"]) + "</td>")
            else:
                cells = ("".join('<td class="mono">' + e(v) + "</td>" for v in (
                    p["value"], p.get("matched_fraction"), p["matched"], p["candidates"],
                    p["post_fdr"], p.get("median_q")))
                    + '<td class="mono">' + e(", ".join(p.get("tripwires") or []) or "pass") + "</td>")
            trows.append('<tr class="' + cls + '">' + cells + "</tr>")
        blocks.append(f"""<div class="card blueprint" style="margin-bottom:20px">{corners()}
  <div style="display:flex;align-items:baseline;justify-content:space-between;gap:10px;
              flex-wrap:wrap;margin-bottom:14px">
    <div style="font:600 14px/1 var(--font-heading);letter-spacing:.04em">
      {e(DIM_LABEL.get(dim, dim).upper())} &nbsp;·&nbsp; FINDINGS AND MATCHED SHARE</div>
    <div class="mono muted" style="font-size:10.5px">— findings &nbsp;····· matched share
      &nbsp;▓ refused below granularity</div>
  </div>
  {_sweep_chart(dim, block)}
  <div class="scroll-x" style="margin-top:14px"><table class="data">
    <tr><th>THRESHOLD</th><th>MATCHED</th><th>MATCHED n</th><th>CANDIDATES</th><th>POST-FDR</th>
        <th>MEDIAN q</th><th>TRIPWIRE</th></tr>
    {''.join(trows)}
  </table></div>
</div>""")

    # The chart and the table carry the same points. The chart is what a reader takes in
    # and the table is what they can quote; a sensitivity claim shown only as a picture
    # is one nobody can check, which is why the JSON is linked from the page as well.
    body = f"""
<h1 class="page">Findings as a function of tolerance, for every tolerance in the specification.</h1>
<p class="lede">Produced as part of the scan and stored with it, so no finding can be presented
  without its sweep. The operating point is marked. The shaded region is where the threshold
  falls below what the FFIEC publishes, and those points are not low numbers — they are
  refusals, derived by re-running the startup gate at each point rather than drawn by hand.</p>
<div class="two">
  <div>{''.join(blocks)}</div>
  <div class="stack">
    <div class="card blueprint">{corners()}<h2 class="sec">CONTRACT</h2>
      <div class="mono muted" style="font-size:11px;line-height:1.75">
        trigger &nbsp;on scan completion<br>
        storage &nbsp;sweep.json beside findings<br>
        payload &nbsp;point[] × dimension[]<br>
        fields &nbsp;value · matched · testable · candidates · post_fdr · median_q · tripwires[]<br>
        route &nbsp;GET /v1/scans/{{id}}/sweep<br>
        guarantee &nbsp;the findings route 409s when the sweep is absent
      </div>
    </div>
    <div class="card tight"><h2 class="sec">SWEEP DIMENSIONS</h2>
      <div style="display:grid;gap:5px;font:12.5px/1.5 var(--font-body)">
        {''.join('<div style="display:flex;justify-content:space-between;padding:5px 0;'
                 'border-bottom:1px solid var(--color-divider)"><span>' + e(DIM_LABEL.get(d, d))
                 + '</span><span class="mono" style="font-size:11px">' + str(len(b['points']))
                 + ' points</span></div>' for d, b in sweep['dimensions'].items())}
      </div>
      <div class="mono muted" style="font-size:10.5px;margin-top:11px;line-height:1.55">Every
        tolerance in the specification gets a curve. A tolerance without a published sweep
        blocks release.</div>
    </div>
    <div class="card tight"><h2 class="sec">EXPORT</h2>
      <a class="btn btn-secondary block" href="/v1/scans/{sid}/sweep">Sweep JSON</a>
      <div class="mono muted" style="font-size:10.5px;margin-top:9px;line-height:1.55">The sweep
        ships with the operating point in every external deliverable.</div></div>
  </div>
</div>"""
    return page("Sweep", body, active="queue", sid=sid,
                crumb="Scans / " + sid + " / Sweep", chip=tripwire_chip(summary))


