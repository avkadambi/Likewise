"""Page shell: navigation, banners, chips, and the one place a <html> document is
assembled. Kept separate from the pages so a change to the chrome cannot silently
change what a page states.

This module owns the frame: the document, the nav, and the three pieces of chrome that
carry a limitation from the scan onto every screen (the blocked banner, the tripwire
chip, the corner marks). It owns no content -- it is handed a `body` string that a page
has already built, and it never reads a finding.
"""
from __future__ import annotations

from .format import (e)

# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------
NAV = [("queue", "Review queue"), ("scans", "Scans"),
       ("spec", "How pairs are matched"), ("controls", "Checks & limits")]


def page(title: str, body: str, active: str = "", crumb: str = "",
         chip: str = "", sid: str = "") -> str:
    """The only place an <html> document is assembled.

    `body` arrives already escaped by the page that built it -- everything variable in
    the shell itself goes through e(). Two stylesheets and no script: the view is served
    post-egress and has to stay legible and complete with scripting off, so there is
    nothing here to fetch a value the server did not already print.
    """
    links = "".join(
        f'<a class="{"on" if k == active else ""}" href="{_navhref(k, sid)}">{e(v)}</a>'
        for k, v in NAV)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · Likewise</title>
<link rel="stylesheet" href="/static/industry.css">
<link rel="stylesheet" href="/static/app.css">
</head><body>
<header class="top">
  <a class="brand" href="/ui/">LIKEWISE</a>
  <nav class="nav-links">{links}</nav>
  <span class="spacer"></span>
  {f'<span class="crumb">{e(crumb)}</span>' if crumb else ''}
  {chip}
  <span class="mono dim" style="font-size:11px">Names and addresses are never shown</span>
</header>
<main class="wrap">{body}</main>
</body></html>"""


def _navhref(k: str, sid: str) -> str:
    # Two of the four destinations are scan-scoped and two are not. With no scan in hand
    # the scoped links fall back to /ui/, which redirects to a live scan or to the scan
    # list -- a nav item that led to a URL with an empty scan id would 404.
    if k == "scans":
        return "/ui/scans"
    if k == "spec":
        return "/ui/spec"
    if not sid:
        return "/ui/"
    return {"queue": f"/ui/scans/{sid}/queue", "controls": f"/ui/scans/{sid}/controls"}[k]


# ---------------------------------------------------------------------------
# Chrome that carries a limitation
# ---------------------------------------------------------------------------
def corners() -> str:
    """Four empty elements the stylesheet draws the blueprint corner marks on."""
    return ('<i class="corner tl"></i><i class="corner tr"></i>'
            '<i class="corner bl"></i><i class="corner br"></i>')


def tripwire_chip(summary: dict) -> str:
    # Rendered into the header of every scan-scoped page, so a breached tripwire is
    # visible from the finding the reader happens to be on rather than only from the
    # coverage screen they may never open. Empty string when nothing breached: no chip
    # at all, rather than a chip reading zero.
    n = len(summary.get("tripwire_breaches") or [])
    if not n:
        return ""
    return (f'<span class="tag mono" style="background:var(--color-neutral-800);color:#fff">'
            f'TRIPWIRE ×{n}</span>')


def blocked_banner(controls: dict | None, summary: dict) -> str:
    """A failed control constrains the product, visibly, and the banner travels with the
    findings into every view.

    Three separate limitations are collected into one banner: a blocked publication, each
    breached tripwire, and an exploratory run. They are additive rather than exclusive --
    a scan can be all three at once, and stating only the first would understate it.
    """
    bits = []
    if controls and controls.get("publication_blocked"):
        g = controls.get("primary_gate") or "did not pass"
        why = {"fail": "failed its gate",
               "inconclusive": "returned an inconclusive result — too few comparable pairs "
                               "to distinguish the cited dimension from an uncited one",
               "not_computable": "could not be computed at all on this scan"}.get(
                   g, "did not pass (" + str(g) + ")")
        bits.append("<b>External publication is blocked on this scan.</b> The "
                    "uncited-dimension placebo " + why + ", so the findings are usable for "
                    "internal review and disposition only. The primary control must pass, not "
                    "absence of failure.")
    for t in summary.get("tripwire_breaches") or []:
        bits.append(f'Tripwire <span class="mono">{e(t.get("tripwire"))}</span> '
                    f'{e(t.get("breach"))}'
                    + (f' at {e(t.get("value"))} against {e(t.get("bound"))}.'
                       if t.get("value") is not None else "."))
    if summary.get("analysis_status") == "exploratory":
        bits.append("This scan ran without a pre-registration lock, so it is labelled "
                    "<b>exploratory</b> and every finding on it says so.")
    if not bits:
        return ""
    return '<div class="banner">' + "<br>".join(bits) + "</div>"


