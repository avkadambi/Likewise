"""Inline SVG charts. No chart library, and no client-side rendering: the page is
served post-egress and stays legible with scripting off.

Two charts, both drawn from the stored post-egress artifacts: the tolerance sweep and
the permutation null. This module owns the geometry -- axes, scales, the marks -- and
nothing else. It computes no statistic; both functions are handed a block that the scan
or the sweep already produced.
"""
from __future__ import annotations
import math

from .format import (DIM_LABEL, e)

# ---------------------------------------------------------------------------
# The tolerance sweep
# ---------------------------------------------------------------------------
def _sweep_chart(dim: str, block: dict) -> str:
    """Findings and matched share against the dimension's threshold. Points the startup
    gate refused are drawn as a shaded region rather than as values, because a threshold
    below publication granularity is not an operating choice."""
    pts = block["points"]
    W, L, R, T, B = 900, 60, 20, 20, 250
    xs = [p["value"] for p in pts]
    lo, hi = min(xs), max(xs)
    span = (hi - lo) or 1.0

    def px(v):
        return L + (W - L - R) * (v - lo) / span

    # Both vertical scales are set from the points that were NOT refused. A refused point
    # has no findings count to speak of, and letting one into the maximum would squash
    # the operating curve against the axis. Two fallbacks, for two different empties: the
    # `or [1]` covers a sweep where every point refused, the trailing `or 1` a maximum
    # that came out zero. Either would divide by zero in py() below.
    ok = [p for p in pts if "refused" not in p]
    fmax = max([p["candidates"] for p in ok] or [1]) or 1
    mmax = max([(p.get("matched_fraction") or 0) for p in ok] or [1]) or 1

    def py(v, vmax):
        return B - (B - T) * (v / vmax if vmax else 0)

    parts = ['<svg viewBox="0 0 900 300" class="chart" role="img" aria-label="'
             + e(DIM_LABEL.get(dim, dim)) + ' sweep">']
    # The refused region is drawn first, as a shaded band up to the highest refused
    # threshold, so the curve is painted over it rather than under it. Refused points are
    # not plotted as low values: a threshold below what the regulator publishes is not a
    # setting that produces few findings, it is a setting the startup gate will not run.
    refused = [p for p in pts if "refused" in p]
    if refused:
        edge = max(p["value"] for p in refused)
        parts.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="#d4d4d7" opacity=".55"/>'
                     % (L, T, max(0.0, px(edge) - L), B - T))
        parts.append('<text x="%.1f" y="%d" font-family="ui-monospace,Menlo,monospace" '
                     'font-size="10" fill="#5d5d60" transform="rotate(90 %.1f %d)">'
                     'REFUSED — BELOW GRANULARITY</text>' % (L + 6, T + 16, L + 6, T + 16))
    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#1d1f20"/>' % (L, B, W - R, B))
    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#1d1f20"/>' % (L, T, L, B))
    for frac in (0.25, 0.5, 0.75):
        y = B - (B - T) * frac
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#b7b7ba" '
                     'stroke-dasharray="3 4"/>' % (L, y, W - R, y))
    if ok:
        parts.append('<polyline fill="none" stroke="#5980a6" stroke-width="2.5" points="'
                     + " ".join("%.1f,%.1f" % (px(p["value"]), py(p["candidates"], fmax))
                                for p in ok) + '"/>')
        parts.append('<polyline fill="none" stroke="#2b2b2d" stroke-width="1.4" '
                     'stroke-dasharray="2 5" points="'
                     + " ".join("%.1f,%.1f" % (px(p["value"]),
                                               py(p.get("matched_fraction") or 0, mmax))
                                for p in ok) + '"/>')
    # The operating point is marked and labelled with its own numbers. It is the answer
    # to the first question an informed reader asks -- whether the threshold was chosen
    # to produce the result -- so it is drawn on the curve rather than stated beside it.
    op = next((p for p in pts if p.get("is_operating")), None)
    if op and "refused" not in op:
        x = px(op["value"])
        parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#1d2d3d" '
                     'stroke-width="1.6"/>' % (x, T, x, B))
        parts.append('<circle cx="%.1f" cy="%.1f" r="5" fill="#1d2d3d"/>'
                     % (x, py(op["candidates"], fmax)))
        # The callout is clamped inside the right margin, so an operating point near the
        # high end of the sweep does not put its own label off the canvas.
        bx = min(x + 10, W - R - 200)
        parts.append('<rect x="%.1f" y="%d" width="196" height="42" fill="#f2f2f3" '
                     'stroke="#1d2d3d"/>' % (bx, T + 6))
        parts.append('<text x="%.1f" y="%d" font-family="ui-monospace,Menlo,monospace" '
                     'font-size="12" fill="#1d2d3d">OPERATING POINT %s</text>'
                     % (bx + 9, T + 23, e(op["value"])))
        parts.append('<text x="%.1f" y="%d" font-family="ui-monospace,Menlo,monospace" '
                     'font-size="12" fill="#1d2d3d">%d findings · matched %s</text>'
                     % (bx + 9, T + 39, op["candidates"],
                        e(op.get("matched_fraction"))))
    for p in pts:
        parts.append('<text x="%.1f" y="%d" font-family="ui-monospace,Menlo,monospace" '
                     'font-size="11" fill="#5d5d60" text-anchor="middle">%s</text>'
                     % (px(p["value"]), B + 18, e(p["value"])))
    parts.append('<text x="%d" y="%d" font-family="ui-monospace,Menlo,monospace" font-size="11" '
                 'fill="#5d5d60">%s — %s</text>'
                 % (L, B + 38, e(DIM_LABEL.get(dim, dim).upper()),
                    e((block.get("kind") or "").replace("_", " ").upper())))
    parts.append("</svg>")
    return "".join(parts)




# ---------------------------------------------------------------------------
# The permutation null
# ---------------------------------------------------------------------------
def _null_chart(nullj: dict) -> str:
    """The permuted distribution with the observed statistic marked.

    The bars are a normal curve fitted to the stored mean and 95% interval, not the
    permutation histogram itself -- the summary carries the moments, not the draws. The
    OBSERVED line and the figures in the callout are the real numbers; the shape behind
    them is an illustration of where they sit.
    """
    # An absent null is stated in words rather than drawn as an empty axis. It means no
    # matched cell reached the power floor, which is a finding about the scan.
    if not nullj:
        return ('<div class="mono muted" style="font-size:11.5px">No permutation null: no '
                "matched cell reached the power floor on this scan.</div>")
    mean = float(nullj.get("null_mean") or 0.0)
    lo, hi = (nullj.get("null_ci95") or [mean, mean])
    obs = float(nullj.get("observed") or 0.0)
    xmax = max(hi, obs, mean) * 1.35 or 1.0
    W, L, R, T, B = 900, 50, 20, 20, 180

    def px(v):
        return L + (W - L - R) * min(1.0, v / xmax)

    # 3.92 is the width of a 95% interval in standard deviations (2 x 1.96), so this
    # recovers the spread from the interval the summary stored. Floored above zero
    # because a degenerate null -- every permutation identical -- would divide by it.
    sd = max((float(hi) - float(lo)) / 3.92, 1e-9)
    bars = []
    for i in range(28):
        x0 = xmax * i / 28.0
        x1 = xmax * (i + 1) / 28.0
        mid = (x0 + x1) / 2
        h = math.exp(-0.5 * ((mid - mean) / sd) ** 2)
        bars.append((px(x0), px(x1), h))
    hmax = max(b[2] for b in bars) or 1.0
    parts = ['<svg viewBox="0 0 900 220" class="chart" role="img" '
             'aria-label="Permutation null with observed statistic marked">']
    for x0, x1, h in bars:
        ht = (B - T) * h / hmax
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#d4d4d7"/>'
                     % (x0, B - ht, max(1.0, x1 - x0 - 2), ht))
    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#1d1f20"/>' % (L, B, W - R, B))
    parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#1d2d3d" stroke-width="2"/>'
                 % (px(obs), T + 6, px(obs), B + 12))
    bx = min(px(obs) + 12, W - R - 250)
    parts.append('<rect x="%.1f" y="%d" width="248" height="42" fill="#f2f2f3" stroke="#1d2d3d"/>'
                 % (bx, T + 6))
    parts.append('<text x="%.1f" y="%d" font-family="ui-monospace,Menlo,monospace" font-size="12" '
                 'fill="#1d2d3d">OBSERVED %s</text>' % (bx + 9, T + 23, e(obs)))
    parts.append('<text x="%.1f" y="%d" font-family="ui-monospace,Menlo,monospace" font-size="12" '
                 'fill="#1d2d3d">null mean %s · 95%% [%s, %s]</text>'
                 % (bx + 9, T + 39, e(mean), e(lo), e(hi)))
    parts.append('<text x="%d" y="%d" font-family="ui-monospace,Menlo,monospace" font-size="11" '
                 'fill="#5d5d60">DOMINANCE FINDING RATE PER PERMUTATION →</text>' % (L, B + 34))
    parts.append("</svg>")
    return "".join(parts)


