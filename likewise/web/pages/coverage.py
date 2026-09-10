"""Coverage: the denominator chain and the coverage profile.

The screen that says what the product could NOT see. It renders the stored counts, the
tripwire breaches, the run budget and the snapshot manifest -- all of it already written
out by the scan and the loader. It computes no rate of its own beyond turning a count
into a share of the denominator named beside it, and it never reads a record.

This is also where the load-time stamps surface: a snapshot that is not the published
record, and a known, non-random gap in what was loaded. Both travel from the manifest,
because a limitation stated once at load time and nowhere afterwards is a limitation the
reader never sees.
"""
from __future__ import annotations

from ..format import (DIM_LABEL, e, verdict_counts)
from ..layout import corners, page, tripwire_chip

# ---------------------------------------------------------------------------
# What a breached tripwire means
# ---------------------------------------------------------------------------
# Written out in full, next to the breach, rather than left as a metric name. A tripwire
# fires on a number nobody outside the project can interpret; the sentence is what makes
# it actionable, and where the likeliest explanation is an error in this software it says so.
TRIPWIRE_MEANING = {
    "matched_fraction": ("Tolerances may be too loose for the pairs to be comparable, or too "
                         "tight for any pair to survive. Investigate before citing any finding "
                         "from this scan."),
    "not_supported_rate": ("The defeated share is outside the band the specification says is "
                           "plausible. A high rate is more likely an error here than a lender's "
                           "misconduct; a rate of zero usually means the test never fired."),
    "median_margin_ratio": ("Margins are close to the publication floor, so the findings are "
                            "being decided by rounding rather than by lending."),
    "cited_over_placebo": ("The cited dimension is not firing more often than an uncited one. "
                           "That is the specificity check failing."),
}


# ---------------------------------------------------------------------------
# The denominator chain
# ---------------------------------------------------------------------------
def coverage_page(sid: str, rec: dict, summary: dict, controls: dict | None,
                  manifest: dict | None) -> str:
    c = summary.get("counts", {})
    total = c.get("denials_in_scope") or 0
    nonx = c.get("denials_non_exempt") or 0
    matched = c.get("denials_with_matched_comparator") or 0
    # Each row states the denominator it is a share OF. Testability and matching are both
    # marginals over the non-exempt population -- testability is deliberately not
    # conditioned on matching -- so chaining them as if each nested inside the last would
    # produce a share above 100% and a bar that lies.
    steps = [
        ("Denials, all reasons", None, c.get("denials_in_scope", 0), "all denials", total),
        ("Non-exempt", "EGRRCPA nulls dropped", nonx, "all denials", total),
        ("Testable reason", "marginal over non-exempt, not conditioned on matching",
         c.get("denials_testable_by_code_marginal", 0), "non-exempt denials", nonx),
        ("Matched", "marginal over non-exempt: at least one comparator in cell",
         matched, "non-exempt denials", nonx),
        ("Dominance candidate", "matched and testable, and the comparator dominates",
         c.get("denials_with_finding", 0), "matched denials", matched),
        ("Survives FDR", "Benjamini-Yekutieli, within scan",
         c.get("findings_after_fdr", 0), "dominance candidates",
         c.get("denials_with_finding", 0)),
    ]
    rows = ['<div class="chain"><div class="h"><span class="kicker">STEP</span>'
            '<span class="kicker">SHARE OF ITS OWN DENOMINATOR</span>'
            '<span class="kicker">COUNT</span>'
            '<span class="kicker">OF ALL DENIALS</span></div>']
    # Each row carries its OWN denominator, and the bar is a share of that. Measuring
    # every row against the same total would draw a marginal that is not nested inside
    # the previous step as though it were, and the bar would then be a picture of a
    # relationship the counts do not have. The second figure is the share of all denials,
    # printed as a number rather than a bar for the same reason.
    for name, sub, n, den_name, den in steps:
        share = (100.0 * n / den) if den else 0.0
        of_total = (100.0 * n / total) if total else 0.0
        sub_txt = (sub + " · " if sub else "") + "of " + den_name
        rows.append('<div class="r"><span style="font:600 13px/1.3 var(--font-body)">'
                    + e(name) + '<div class="mono dim" style="font-size:10px;'
                    'font-weight:400">' + e(sub_txt) + '</div></span>'
                    '<div class="bar"><i style="width:' + ("%.1f" % min(100.0, share))
                    + '%"></i></div>'
                    '<span class="mono" style="font-size:13px">' + format(n, ",") + "</span>"
                    '<span class="mono muted" style="font-size:12px">'
                    + ("%.1f%%" % of_total) + "</span></div>")
    rows.append("</div>")

    # ---------------------------------------------------------------------------
    # Survives, defeated, untestable
    # ---------------------------------------------------------------------------
    # Three tiles, never two, and the paragraph beneath them states the identity that
    # makes the decomposition checkable: survives + defeated + untestable-among-matched
    # equals matched. Untestable is drawn against the non-exempt population and says so
    # on the tile, because it is the one figure whose denominator differs.
    v = verdict_counts(c)
    verdicts = f"""<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
      gap:16px;margin-top:22px">
  <div class="card blueprint">{corners()}<div class="kicker">SURVIVES</div>
    <div style="font:600 30px/1 var(--font-heading);margin:5px 0 4px">{v['survives']:,}</div>
    <div class="mono muted" style="font-size:11px">of {v['matched']:,} matched</div></div>
  <div class="card blueprint">{corners()}<div class="kicker">DEFEATED</div>
    <div style="font:600 30px/1 var(--font-heading);margin:5px 0 4px">{v['defeated']:,}</div>
    <div class="mono muted" style="font-size:11px">of {v['matched']:,} matched</div></div>
  <div class="card blueprint" style="border-color:var(--color-neutral-700)">{corners()}
    <div class="kicker">UNTESTABLE</div>
    <div style="font:600 30px/1 var(--font-heading);margin:5px 0 4px">{v['untestable']:,}</div>
    <div class="mono muted" style="font-size:11px">of {v['non_exempt']:,} non-exempt ·
      its own denominator</div></div>
</div>
<p class="muted" style="font:12px/1.6 var(--font-body);max-width:80ch">
  Untestable is drawn against non-exempt, not against matched, and it is never folded into
  either of the other two. {v['no_comparator']:,} denials had no comparable approved file at
  all; {v['untestable_code']:,} matched but name a reason the public record cannot carry;
  {v['untestable_resolution']:,} matched and name a testable reason whose published values
  are too coarse to separate the pair. Survives, defeated and untestable-among-matched sum
  to the matched count exactly &mdash; {v['survives']:,} + {v['defeated']:,} +
  {v['untestable_matched']:,} = {v['matched']:,}.</p>"""

    tw = []
    for t in summary.get("tripwire_breaches") or []:
        name = t.get("tripwire")
        val = t.get("value")
        head = e(name) + " — " + (("%s against a bound of %s" % (val, t.get("bound")))
                                  if val is not None else e(t.get("breach")))
        tw.append('<div style="border-left:3px solid var(--color-neutral-800);padding-left:11px;'
                  'margin-bottom:12px"><div style="font:600 13px/1.35 var(--font-body)">'
                  + head + '</div><div class="mono muted" style="font-size:11px;line-height:1.55;'
                  'margin-top:4px">' + e(TRIPWIRE_MEANING.get(name, "")) + "</div></div>")
    if not tw:
        tw.append('<div class="mono muted" style="font-size:11.5px">No tripwire breached on '
                  "this scan.</div>")

    # Stages sorted by descending cost, so the run budget answers "what took the time"
    # without the reader adding anything up.
    stages = summary.get("wall_time_by_stage") or {}
    budget = "".join(
        '<div style="display:flex;justify-content:space-between"><span>' + e(k)
        + '</span><span class="mono">' + ("%.2fs" % v) + "</span></div>"
        for k, v in sorted(stages.items(), key=lambda kv: -kv[1]))

    # ---------------------------------------------------------------------------
    # Where this data came from
    # ---------------------------------------------------------------------------
    # The provenance block is omitted entirely when there is no manifest, rather than
    # rendered with blanks: a panel of empty fields reads as a claim that the questions
    # were asked and came back empty.
    prov = ""
    if manifest:
        rows_p = []
        for key, label in (("source", "source"), ("filer_name_public", "filer"),
                           ("geography", "geography"), ("retrieved", "retrieved"),
                           ("loaded_at", "loaded"), ("layout", "layout")):
            if manifest.get(key):
                rows_p.append(e(label) + " &nbsp;" + e(manifest[key]))
        rows_p.append("rows &nbsp;" + e(manifest.get("rows_written")))
        if manifest.get("duplicates_dropped"):
            rows_p.append("duplicates dropped &nbsp;" + e(manifest["duplicates_dropped"]))
        comp = manifest.get("completeness") or {}
        if comp.get("universe_rows"):
            rows_p.append("of a universe of &nbsp;" + e(comp["universe_rows"]))

        banners = []
        # A snapshot loaded with --internal-data is stamped once, at load, and the stamp
        # travels with it. Every screen that shows a margin against a published bin width
        # is wrong about this snapshot, and saying so here is cheaper than a footnote on
        # each of them.
        if manifest.get("public_record") is False:
            banners.append('<div class="banner"><b>This snapshot is not the published '
                           'record.</b><br>' + e(manifest.get("public_record_note", "")) +
                           "</div>")
        if comp.get("known_gap_rows"):
            banners.append(
                '<div class="banner"><b>' + e(comp["known_gap_rows"]) + " records are "
                "missing from this snapshot and they are not missing at random.</b><br>"
                + e(comp.get("known_gap_definition", "")) + '<br><span class="muted">'
                + e(comp.get("known_gap_effect", "")) + "</span></div>")

        gran = manifest.get("granularity_report") or {}
        gr = []
        # Per-field conforming/total from the load, printed for every field that had
        # something to check. A field whose values are not all at publication granularity
        # is set in bold rather than dropped -- this is the evidence behind the bin widths
        # every other screen quotes.
        for f, r in sorted(gran.items()):
            if r.get("conforming") is None or not r.get("n"):
                continue
            ok = r["conforming"] == r["n"]
            gr.append('<div style="display:flex;justify-content:space-between;gap:10px">'
                      '<span>' + e(DIM_LABEL.get(f, f)) + '</span><span class="mono"'
                      + ("" if ok else ' style="font-weight:700"') + ">"
                      + e(r["conforming"]) + "/" + e(r["n"]) + "</span></div>")
        gran_block = ""
        if gr:
            gran_block = ('<div class="mono muted" style="font-size:10.5px;line-height:1.7;'
                          'border-top:1px solid var(--color-divider);margin-top:11px;'
                          'padding-top:10px">ROWS AT PUBLICATION GRANULARITY</div>'
                          '<div style="font:11.5px/1.7 var(--font-body)">'
                          + "".join(gr) + "</div>")

        prov = ('<div class="card tight"><h2 class="sec">WHERE THIS DATA CAME FROM</h2>'
                '<div class="mono muted" style="font-size:11px;line-height:1.7">'
                + "<br>".join(rows_p) + "</div>" + gran_block
                + "".join(banners) + "</div>")

    body = f"""
<h1 class="page">Coverage</h1>
<p class="lede">Every rate this product publishes carries its denominator. The chain below is
  ordered, and each step names what it removed and why.</p>
<div class="two">
  <div>
    {''.join(rows)}
    {verdicts}
  </div>
  <div class="stack">
    <div class="card blueprint" style="border-color:var(--color-neutral-800)">{corners()}
      <h2 class="sec">TRIPWIRES</h2>
      {''.join(tw)}
      <div class="mono muted" style="font-size:10.5px;line-height:1.6;
           border-top:1px solid var(--color-divider);padding-top:11px">
        A high defeated rate is more likely an error here than a lender's misconduct. Any headline
        above its tripwire is re-derived and independently replayed before it appears in any
        deliverable.</div>
    </div>
    <div class="card tight">
      <h2 class="sec">RUN BUDGET</h2>
      <div style="display:grid;gap:7px;font:11.5px/1.4 var(--font-body)">{budget}
        <div style="display:flex;justify-content:space-between;border-top:1px solid var(--color-divider);
             padding-top:7px;font-weight:600"><span>Total</span>
          <span class="mono">{('%.2fs' % summary.get('wall_time_s', 0))}</span></div>
      </div>
    </div>
    <div class="card tight">
      <h2 class="sec">REPRODUCIBILITY</h2>
      <div class="mono muted" style="font-size:11px;line-height:1.7">
        findings hash &nbsp;{e((summary.get('content_hash') or '')[:26])}…<br>
        sort &nbsp;deterministic<br>
        inputs &nbsp;filer · year · spec · snapshot<br>
        re-run &nbsp;returns the same scan id<br>
        egress key &nbsp;version {e(rec.get('pseudonym_key_version'))}
      </div>
    </div>
    {prov}
  </div>
</div>"""
    return page("Coverage", body, active="queue", sid=sid,
                crumb="Scans / " + sid + " / Coverage", chip=tripwire_chip(summary))


