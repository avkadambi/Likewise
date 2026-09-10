"""Review queue: the prioritised list, one row per finding.

Everything on this page came out of findings.json and summary.json, both written
post-egress: bands rather than values, pseudonymous references rather than record keys.
The renderer never sees a raw record, and it owns no ordering or scoring of its own --
findings arrive ranked by the scan and are shown in that order.
"""
from __future__ import annotations

from ..format import (DIM_LABEL, DISPOSITIONS, VERDICT,
                     claim, e, gap_words, ordinal,
                     strength, verdict_counts)
from ..layout import blocked_banner, corners, page, tripwire_chip

# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
def queue_page(sid: str, rec: dict, summary: dict, findings: list[dict],
               dispositions: dict, reasons: dict, controls: dict | None,
               tab: str, limit: int, offset: int) -> str:
    c = summary.get("counts", {})
    total = len(findings)
    done = sum(1 for f in findings if dispositions.get(f["finding_id"], {}).get("verdict"))
    v = verdict_counts(c)
    untestable, den = v["untestable"], v["non_exempt"]

    # Underpowered is tested BEFORE the disposition, so a pair from a cell that cannot
    # reach the FDR threshold never appears in "needs a decision" -- sending a reviewer
    # into their origination system over a pair the statistics cannot score is the waste
    # this bucketing exists to prevent. Such a pair is still listed, in its own tab.
    def bucket(f):
        d = dispositions.get(f["finding_id"], {}).get("verdict")
        if f.get("cell_power") == "underpowered":
            return "unscored"
        return "reviewed" if d else "needs"

    need = sum(1 for f in findings if bucket(f) == "needs")
    # Filtered, never re-sorted. Findings arrive in the rank order the scan fixed, and
    # the page states that the order is repeatable; sorting here would make that false.
    shown = [f for f in findings if tab == "all" or bucket(f) == tab]
    nxt = next((f for f in findings if bucket(f) == "needs"), None)

    tabs = [("needs", "Needs a decision", need), ("reviewed", "Reviewed", done),
            ("unscored", "Not enough to compare",
             sum(1 for f in findings if bucket(f) == "unscored")),
            ("all", "All findings", total)]
    tabhtml = "".join(
        f'<a class="seg-opt" style="{"background:var(--color-accent);color:var(--color-bg)" if tab == k else ""}"'
        f' href="/ui/scans/{sid}/queue?tab={k}">{e(l)}&nbsp;&nbsp;{n}</a>'
        for k, l, n in tabs)

    rows = "".join(finding_row(sid, f, dispositions.get(f["finding_id"], {}), reasons)
                   for f in shown[offset:offset + limit])
    # An empty tab says so and points back at the counts, rather than rendering nothing.
    # A blank page reads as a page that failed to load; the counts above it are the whole
    # answer for this scan and the sentence says that.
    if not shown:
        rows = ('<div class="card"><p class="lede" style="margin:0">Nothing in this tab. '
                'The counts above are the whole story for this scan.</p></div>')

    pager = ""
    # Offset paging over a fixed order, and the link carries the tab: the underlying list
    # does not change between requests, so an offset means the same thing on the second
    # page as on the first.
    if offset + limit < len(shown):
        pager = (f'<a class="mono" href="/ui/scans/{sid}/queue?tab={tab}'
                 f'&offset={offset + limit}">Load more →</a>')

    # The body is laid out in four parts, in this order: the blocked/tripwire banner, a
    # two-column head that pairs the headline count with the untestable panel, the tab
    # strip, and the rows. The untestable panel sits BESIDE the headline rather than
    # below the rows on purpose -- a queue that showed only what it found would invite a
    # reader to take the findings for the whole picture, and those denials are not
    # cleared, they are unseen.
    return page("Review queue", f"""
{blocked_banner(controls, summary)}
<div class="two">
  <div>
    <h1 class="page">{need} {'pair' if need == 1 else 'pairs'} still need your decision</h1>
    <p class="lede">Each pair is one denied application and one approved application that
      look the same on everything the public record shows &mdash; but got opposite answers.
      Your job is to check each pair against your own file and say whether the denial
      reason holds.</p>
    <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
      <div style="flex:1;min-width:240px;max-width:420px">
        <div class="meter"><i style="width:{(done / total * 100) if total else 0:.0f}%"></i></div>
        <div class="mono muted" style="font-size:11px;margin-top:6px">{done} of {total}
          reviewed &nbsp;·&nbsp; {e(rec.get('label') or rec['lei'])} FY{rec['activity_year']}</div>
      </div>
      {f'<a class="btn btn-primary blueprint" href="/ui/scans/{sid}/findings/{nxt["finding_id"]}">{corners()}Review next pair</a>' if nxt else ''}
    </div>
  </div>
  <div class="card blueprint">{corners()}
    <h2 class="sec">WHAT THIS QUEUE CANNOT TELL YOU</h2>
    <p style="font:12.5px/1.55 var(--font-body);margin:0 0 9px">
      {untestable:,} of the {den:,} denials in this filing can't be tested at all.
      {v['no_comparator']:,} have no comparable approved file anywhere in the portfolio;
      {v['untestable_code']:,} name a reason the public record does not carry;
      {v['untestable_resolution']:,} name one it carries too coarsely to separate the pair.
      None of them are cleared. They are unseen.</p>
    <a class="mono" href="/ui/scans/{sid}/coverage">See the full coverage breakdown →</a>
  </div>
</div>

<div style="display:flex;align-items:center;gap:10px;padding:11px 0;margin:16px 0;
            border-top:1px solid var(--color-divider);border-bottom:1px solid var(--color-divider);
            flex-wrap:wrap">
  <span class="seg scroll-x">{tabhtml}</span>
  <span class="spacer"></span>
  <span class="muted" style="font-size:12.5px">Strongest evidence first</span>
</div>

{rows}
<div style="display:flex;justify-content:space-between;padding-top:16px;font-size:12.5px"
     class="muted">
  <span>Showing {min(limit, max(0, len(shown) - offset))} of {len(shown)} &nbsp;{pager}</span>
  <span class="mono" style="font-size:11px">Order is fixed and repeatable ·
    matched using <a href="/ui/spec?v={e(rec.get('spec_version'))}">standard
    v{e(rec.get('spec_version'))}</a></span>
</div>
""", active="queue", sid=sid, chip=tripwire_chip(summary))


# ---------------------------------------------------------------------------
# One row
# ---------------------------------------------------------------------------
def finding_row(sid: str, f: dict, disp: dict, reasons: dict) -> str:
    label, code = VERDICT.get(f.get("reason_outcome"), ("Reviewed", ""))
    s_label, s_frac = strength(f)
    unscored = s_label == "Not scored"
    tested = f.get("tested", [])
    # The row shows ONE dimension: the unsupported one if there is one, otherwise the
    # first tested. A row that listed every tested dimension would bury the thing the
    # denial reason actually names among the ones it does not.
    decisive = next((t for t in tested if t.get("outcome") == "not_supported"), None) \
        or (tested[0] if tested else None)
    bands = f.get("bands", {})

    # The denied side prints the disclosure band and the approved side prints the gap in
    # words. Two bands side by side would invite the reader to subtract them, and the
    # difference between two bands is not the margin that decided the finding.
    if decisive:
        d = decisive["dimension"]
        gap_text = gap_words(d, decisive)
        pair = f"""<div class="pair">
  <div><div class="kicker">DENIED · {e(f['record_ref']['denied'])}</div>
    <div style="font:13px/1.5 var(--font-body)">{e(DIM_LABEL.get(d, d))}
      <b>{e(bands.get(d, 'band withheld'))}</b></div></div>
  <div><div class="kicker" style="color:var(--color-accent-800)">APPROVED ·
      {e(f['record_ref']['approved'])}</div>
    <div style="font:13px/1.5 var(--font-body)">{e(DIM_LABEL.get(d, d))}
      <b>{e(gap_text)}</b></div></div>
</div>"""
    else:
        pair = ""

    note = ""
    if disp.get("verdict"):
        note = (f'<div style="font:12.5px/1.5 var(--font-body)" class="muted">Your note, '
                f'{e(disp.get("recorded_at", ""))}: "{e(disp.get("note") or "no note")}"</div>')

    tag_reviewed = (f'<span class="tag tag-neutral" style="font-size:11px">You reviewed this '
                    f'— {e(DISPOSITIONS.get(disp["verdict"], ("recorded",))[0].rstrip("."))}'
                    f'</span>') if disp.get("verdict") in DISPOSITIONS else ""

    # The right-hand rail carries the strength verdict and the only link into the detail
    # page. An unscored pair gets no meter bar at all -- a bar at any width would imply a
    # score was computed and came out low, when none was computed.
    rail = f"""<div class="rail">
  <div class="kicker">HOW STRONG IS THIS?</div>
  <div style="font:600 22px/1.1 var(--font-heading);margin-bottom:7px;
       {'color:var(--color-neutral-500)' if unscored else ''}">{e(s_label)}</div>
  {'' if unscored else f'<div class="meter" style="height:9px;margin-bottom:6px"><i style="width:{s_frac * 100:.0f}%"></i></div>'}
  <div class="muted" style="font:12px/1.5 var(--font-body);margin-bottom:12px">
    {('Listed for completeness. Excluded from the significance test — being the worst of '
      'a very small group is not evidence.') if unscored else
     f'The {ordinal(int(f.get("rank_in_cell") or 1))} comparison out of {f.get("cell_size", 0)} similar files.'}
  </div>
  <a class="btn btn-secondary block" href="/ui/scans/{sid}/findings/{e(f['finding_id'])}">Open and review</a>
</div>"""

    return f"""<div class="card blueprint frow">{corners()}
  <div class="grid">
    <div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:9px;flex-wrap:wrap">
        <span class="tag tag-accent" style="font-size:11px">{e(label)}</span>
        <span class="mono dim" style="font-size:10.5px">{e(code)} · {e(f['finding_id'][4:12])}</span>
        {tag_reviewed}
      </div>
      <h3>{e(claim(f, reasons))}</h3>
      {pair}
      <div class="muted" style="font:12.5px/1.5 var(--font-body)">
        Matched exactly on county, loan purpose, lien position, occupancy, loan type,
        automated-underwriting result and co-applicant presence; loan amount and income
        within the published control tolerance.</div>
      {note}
    </div>
    {rail}
  </div>
</div>"""


