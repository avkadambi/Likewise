"""Finding detail: one denial, one approved comparator, side by side.

The page a reviewer works from, and the one place the product asks somebody to act. It
is built entirely from the post-egress finding, so the two records appear as disclosure
bands and pseudonymous references -- the renderer has no access to the underlying rows
and could not print a raw value if a reviewer asked for one.

This module owns the layout and the wording. It owns no judgement: the verdict, the
margins, the rank and the power all arrive computed, and the disposition the reviewer
records is written by the API route, not here.
"""
from __future__ import annotations

from ..format import (DIM_LABEL, DISPOSITIONS, VERDICT,
                     claim, e, fmt_margin, gap_short, ordinal,
                     strength)
from ..layout import blocked_banner, corners, page, tripwire_chip

# ---------------------------------------------------------------------------
# The two files, side by side
# ---------------------------------------------------------------------------
def _delta_table(f: dict) -> str:
    """Three columns on desktop; one card per dimension below 840px. The grouping is in
    the markup (a .drow per dimension) so the transposition is a stylesheet change rather
    than a second renderer -- 2e's rule that the mobile view is not a second serialisation
    route applies to the markup as well as to egress."""
    # Three groups of rows in a fixed order: the dimensions the denial reason NAMES, then
    # the remaining banded dimensions, then what the two files are identical on. The
    # order is the argument the page is making -- what was cited, what else is visible,
    # and what was held constant -- so it does not depend on the data.
    bands = f.get("bands", {})
    named = set()
    out = ['<div class="deltas">',
           '<div class="drow hd"><div></div>'
           '<div><div class="kicker">DENIED</div>'
           '<div style="font:600 14px/1.2 var(--font-heading)">'
           + e(f["record_ref"]["denied"]) + '</div></div>'
           '<div><div class="kicker">APPROVED</div>'
           '<div style="font:600 14px/1.2 var(--font-heading)">'
           + e(f["record_ref"]["approved"]) + '</div></div></div>']
    for t in f.get("tested", []):
        d = t["dimension"]
        named.add(d)
        thr, oc = t.get("decisive_threshold"), t.get("outcome")
        # Each named dimension states its own threshold in the sentence beside it. A gap
        # inside the floor is explicitly said to decide NOTHING -- neither for the filer
        # nor against them -- because a row showing a difference with no verdict attached
        # reads as a small piece of evidence.
        if oc == "not_supported":
            why = ("Past the " + fmt_margin(d, thr).lstrip("+") + " that the published data "
                   "can actually resolve, so the gap is real.")
        elif oc == "below_resolution":
            why = ("Inside the " + fmt_margin(d, thr).lstrip("+") + " floor set by how coarsely "
                   "this field is published, so it decides nothing either way.")
        else:
            why = "The approved file is not worse on this dimension."
        out.append(
            '<div class="drow named">'
            '<div><div style="font:600 14px/1.3 var(--font-body)">' + e(DIM_LABEL.get(d, d))
            + '</div><div class="mono" style="font-size:10.5px;color:var(--color-accent-800);'
              'margin-top:2px">NAMED BY THE REASON</div></div>'
            '<div><span class="celllabel">Denied</span><span class="num">'
            + e(bands.get(d, "band withheld")) + '</span></div>'
            '<div><span class="celllabel">Approved</span><span class="num">'
            + e(gap_short(d, t)) + '</span>'
            '<div style="font:12px/1.4 var(--font-body);color:var(--color-accent-800);'
            'margin-top:2px">' + e(why) + '</div></div></div>')
    # The unnamed banded dimensions say "matched, not an advantage" rather than showing
    # the approved file's own band: these are the control features, held inside tolerance
    # by the matcher, and printing a second band would invite a comparison the match
    # already declared immaterial.
    for d, b in sorted(bands.items()):
        if d in named:
            continue
        out.append(
            '<div class="drow">'
            '<div><div style="font:600 14px/1.3 var(--font-body)">' + e(DIM_LABEL.get(d, d))
            + '</div></div>'
            '<div><span class="celllabel">Denied</span>'
            '<span style="font:15px/1.3 var(--font-body)">' + e(b) + '</span></div>'
            '<div><span class="celllabel">Approved</span>'
            '<span class="muted" style="font:13px/1.4 var(--font-body)">inside the control '
            'tolerance — matched, not an advantage</span></div></div>')
    out.append(
        '<div class="drow wide"><div><div style="font:600 14px/1.3 var(--font-body)">'
        'Identical on</div></div>'
        '<div style="grid-column:span 2"><div style="font:13.5px/1.55 var(--font-body)">'
        'County ' + e(f.get("county_code")) + ' · loan purpose · lien position · occupancy · '
        'loan type · automated-underwriting result · co-applicant presence · filing year. '
        'The only thing that differs is the answer: <b>denied</b> against '
        '<b>originated</b>.</div></div></div>')
    out.append('</div>')
    return "".join(out)


# ---------------------------------------------------------------------------
# Strength, in words and in figures
# ---------------------------------------------------------------------------
def _null_words(summary: dict) -> str:
    """The permutation null as a sentence a reviewer can act on.

    The null is a property of the SCAN, not of this pair, and the sentence says so by
    naming the rate across the scan rather than a figure attached to the finding.
    """
    n = summary.get("null") or {}
    if not n:
        return ("The permutation null was not computed for this scan — no matched cell "
                "reached the power floor, so there is nothing to compare a rate against.")
    side = "below" if n.get("direction") == "below_null" else "above"
    return ("We reshuffled the outcomes inside each matched group " + str(n.get("B"))
            + " times. Across this scan the reshuffled data produced findings at a rate of "
            + str(n.get("null_mean")) + ", against " + str(n.get("observed"))
            + " observed — " + side + " the null.")


def _stats_line(f: dict) -> str:
    """Everything numeric about the finding, on one line, behind a <details>.

    Folded away rather than omitted: the reviewer the page addresses does not need it,
    and the reviewer's counsel does. Every value is printed as stored, including
    "not computed" where a quantity was not -- an absent figure is itself a fact about
    the scan.
    """
    p = f.get("rank_p_value")
    parts = []
    if p is not None:
        parts.append("p(rank) %.4g" % p)
    parts += [
        "rank_in_cell %s/%s" % (f.get("rank_in_cell"), f.get("cell_size")),
        "q (%s) %s" % (f.get("q_value_by") or "not computed", f.get("q_value")),
        "margin_ratio %s" % f.get("margin_ratio"),
        "block_degree %s" % f.get("block_degree"),
        "k-cohort %s" % f.get("k_cohort"),
        "informative dimensions %s" % f.get("informative_dimension_count"),
        "cell power %s" % f.get("cell_power"),
    ]
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
def finding_page(sid: str, rec: dict, summary: dict, f: dict, disp: dict,
                 reasons: dict, controls: dict | None, pos: int, total: int,
                 nxt: str | None) -> str:
    label, code = VERDICT.get(f.get("reason_outcome"), ("Reviewed", ""))
    s_label, _ = strength(f)          # the meter bar belongs to the queue row, not here
    codes = f.get("stated_reason_codes") or []
    rlabel = reasons.get(codes[0], {}).get("label", "the stated reason") if codes else "—"
    dims = ", ".join(DIM_LABEL.get(t["dimension"], t["dimension"]).lower()
                     for t in f.get("tested", [])) or "no published dimension"
    cell_size = f.get("cell_size") or 0
    rank_txt = ordinal(int(f.get("rank_in_cell") or 1)).capitalize() + " of " + str(cell_size)
    spec_v = rec.get("spec_version", "")
    fid = f["finding_id"]
    # An unscored pair gets an arithmetic explanation, not the scan's null: the reason it
    # is unscored is a property of ITS cell -- the smallest p-value a cell of that size
    # can produce cannot clear the threshold -- and quoting the scan-wide null instead
    # would answer a question the reader did not ask.
    if s_label == "Not scored":
        strength_words = (
            "This cell holds %d comparable approved files. The smallest p-value a cell of "
            "that size can produce is 1 in %d, which cannot clear the false-discovery "
            "threshold however extreme the gap looks. Being the worst of a small group is "
            "not evidence, so the pair is listed and left unscored." % (cell_size, cell_size or 1))
    else:
        strength_words = _null_words(summary)
    next_btn = ('<a class="btn btn-ghost" href="/ui/scans/' + sid + '/findings/' + e(nxt or "")
                + '">Next →</a>') if nxt else ""
    recorded = ""
    if disp.get("verdict"):
        recorded = ('<div class="mono muted" style="font-size:10.5px;margin-top:9px">Recorded '
                    + e(disp.get("recorded_at")) + " by " + e(disp.get("principal")) + "</div>")
    # Three verdicts, rendered from DISPOSITIONS so the wording and the accepted values
    # cannot drift apart -- the API validates against the same three keys. "Can't tell
    # yet" is one of them: a reviewer who cannot decide has somewhere to put that, rather
    # than leaving the pair silently undisposed.
    opts = "".join(
        '<label><input type="radio" name="verdict" value="' + k + '"'
        + (" checked" if disp.get("verdict") == k else "")
        + '><span class="dot"></span><span><b>' + e(t)
        + '</b><br><span class="muted" style="font-size:12px">' + e(sub)
        + "</span></span></label>"
        for k, (t, sub) in DISPOSITIONS.items())

    # Two columns. The left is the case: the claim, the two files, and how strong it is.
    # The right is the work: what to check in the filer's own system, the form that
    # records the answer, and the provenance block. The order matters -- the reviewer
    # reads the claim before being asked to judge it, and the "IMPORTANT" note stating
    # that this is not a finding of discrimination sits with the instructions rather than
    # at the foot of the page, where it would be read after the decision.
    body = f"""
{blocked_banner(controls, summary)}
<div style="display:flex;align-items:center;gap:16px;margin:14px 0;flex-wrap:wrap">
  <a class="mono" href="/ui/scans/{sid}/queue">← Back to queue</a>
  <span class="spacer"></span>
  <span class="mono muted" style="font-size:11.5px">Pair {pos} of {total} to review</span>
  {next_btn}
</div>
<div class="two">
  <div class="stack">
    <div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:9px;flex-wrap:wrap">
        <span class="tag tag-accent" style="font-size:11.5px">{e(label)}</span>
        <span class="mono dim" style="font-size:11px">{e(code)} · {e(fid[4:12])} · {e(s_label.lower())}</span>
      </div>
      <h1 class="page" style="margin-top:0">{e(claim(f, reasons))}</h1>
      <p class="lede">Reason code {e(codes[0] if codes else '—')} &mdash; {e(rlabel.lower())}
        &mdash; points at {e(dims)}. The approved file is not better than the denied file on
        anything else the public record shows. That is what makes this pair worth a look.</p>
    </div>

    <div class="card blueprint" style="padding:0">{corners()}
      <div style="padding:16px 20px;border-bottom:1px solid var(--color-divider);display:flex;
                  align-items:baseline;justify-content:space-between;gap:10px;flex-wrap:wrap">
        <div style="font:600 16px/1 var(--font-heading);letter-spacing:.03em">THE TWO FILES, SIDE BY SIDE</div>
        <div class="mono muted" style="font-size:11px">shaded rows are what the denial reason names</div>
      </div>
      <div class="scroll-x">{_delta_table(f)}</div>
      <div class="mono muted" style="font-size:10.5px;line-height:1.6;padding:11px 20px;
           border-top:1px solid var(--color-divider)">
        Values render as the disclosure band, not the raw figure — egress bands every published
        financial field before it leaves the process. The margin and the threshold
        beside it are what decide the finding.</div>
    </div>

    <div class="card">
      <h2 class="sec">HOW STRONG IS THIS, AND WHY</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:22px;margin-top:12px">
        <div><div style="font:600 20px/1.15 var(--font-heading);margin-bottom:5px">{e(rank_txt)}</div>
          <div class="muted" style="font:12.5px/1.5 var(--font-body)">{cell_size} approved files
            were comparable. This is where the denied file sits among them on the dimension the
            reason names.</div></div>
        <div><div style="font:600 20px/1.15 var(--font-heading);margin-bottom:5px">{e(s_label)}</div>
          <div class="muted" style="font:12.5px/1.5 var(--font-body)">{e(strength_words)}</div></div>
        <div><div style="font:600 20px/1.15 var(--font-heading);margin-bottom:5px">Screening, not proof</div>
          <div class="muted" style="font:12.5px/1.5 var(--font-body)">Evidentiary status
            {e(f.get('evidentiary_status'))}; analysis status {e(f.get('analysis_status'))}.
            A finding is a prioritised place to look, not a determination.</div></div>
      </div>
      <details><summary>Show the statistics</summary>
        <div class="mono muted" style="font-size:11px;line-height:1.7">{e(_stats_line(f))}</div>
      </details>
    </div>
  </div>

  <div class="stack">
    <div class="card blueprint">{corners()}
      <h2 class="sec">WHAT TO CHECK</h2>
      <p class="muted" style="font:12px/1.5 var(--font-body);margin:0 0 12px">Three steps in your
        own origination system. Then record what you found.</p>
      <ol style="margin:0;padding-left:18px;font:12.5px/1.55 var(--font-body)">
        <li style="margin-bottom:10px"><b>Pull both files.</b>
          {e(f['record_ref']['denied'])} and {e(f['record_ref']['approved'])}, filing year
          {e(rec['activity_year'])}.</li>
        <li style="margin-bottom:10px"><b>Look for what HMDA doesn't publish.</b> Credit score,
          employment history, reserves, a co-signer, appraisal notes, loan term, prepayment
          terms. Any one of these can legitimately explain the difference.</li>
        <li><b>Decide whether the {e(rlabel.lower())} reason still stands</b> once you can see
          everything.</li>
      </ol>
      <div style="border-top:1px solid var(--color-divider);margin-top:15px;padding-top:13px">
        <div class="kicker">IMPORTANT</div>
        <p style="font:12px/1.55 var(--font-body);margin:0">Likewise cannot see any of those
          fields. It has not found discrimination &mdash; it has found two records that will look
          identical to an examiner. If your file has the answer, this is a five-minute check.
          If it doesn't, that is the finding.</p>
      </div>
    </div>

    <form class="card blueprint" id="what-did-you-find" method="post"
          action="/ui/scans/{sid}/findings/{e(fid)}/disposition">{corners()}
      <h2 class="sec">WHAT DID YOU FIND?</h2>
      <div class="opts">{opts}</div>
      <textarea class="input" name="note" rows="3"
        placeholder="What you checked, and where. Saved with your name and the date.">{e(disp.get('note') or '')}</textarea>
      <button class="btn btn-primary blueprint block" style="margin-top:11px" type="submit">{corners()}Save and go to next pair</button>
      {recorded}
    </form>

    <div class="card tight">
      <details open><summary>How this pair was matched</summary>
        <div class="mono muted" style="font-size:11px;line-height:1.75">
          matching standard &nbsp;<a href="/ui/spec?v={e(spec_v)}">v{e(spec_v)}</a><br>
          reason map &nbsp;{e(f['spec_digests'].get('reasons', '')[:20])}…<br>
          publication snapshot &nbsp;{e(f.get('snapshot_id'))}<br>
          method locked &nbsp;{e(rec.get('preregistration_digest'))}<br>
          pseudonym key &nbsp;version {e(f.get('pseudonym_key_version'))}<br>
          identities &nbsp;removed before display
        </div>
      </details>
      <div class="muted" style="font:11.5px/1.5 var(--font-body);margin-top:10px">Everything above
        is quotable. <a href="/ui/scans/{sid}/sweep">See how the answer changes</a> if the
        matching tolerance moves.</div>
    </div>
  </div>
</div>
<div class="stick">
  <a class="btn btn-secondary" href="/ui/scans/{sid}/queue">Later</a>
  <a class="btn btn-primary blueprint" href="#what-did-you-find">{corners()}Record what you found</a>
</div>
"""
    return page("Finding", body, active="queue", sid=sid, chip=tripwire_chip(summary))


