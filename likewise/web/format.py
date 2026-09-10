"""Plain-language formatting: numbers, labels, verdicts, claim sentences.

Pure functions over the post-egress dictionaries. Nothing here reaches for a store, a
specification or a template -- which is what lets the queue and the detail page be
tested by asserting on values rather than on HTML fragments.

Everything this module is handed has already been through egress: bands, not values;
bucketed margins, not raw ones; pseudonymous references, not record keys. It owns how
those are worded and never what they are. It does no arithmetic on the underlying data
beyond turning stored counts into the three-way decomposition the screens state.
"""
from __future__ import annotations
import html, math
from typing import Any

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
# The product's words, in one place. The screens address a filer reviewing their own
# file, so an outcome is "The stated reason doesn't hold up" and not
# "not_supported_by_public_record"; the machine-readable code travels beside it for
# anyone quoting the finding. A dimension with no entry in DIM_LABEL falls back to its
# field name at the call site rather than being hidden.
REASONS_FALLBACK = {}

VERDICT = {
    "not_supported_by_public_record": ("The stated reason doesn't hold up", "DEFEATED"),
    "supported": ("The stated reason holds on the public record", "SURVIVES"),
    "untestable": ("Not enough to compare", "UNTESTABLE"),
}
DISPOSITIONS = {
    "holds":     ("The reason holds.", "Something outside the public record explains it"),
    "not_holds": ("The reason doesn't hold.", "Needs remediation"),
    "unclear":   ("Can't tell yet.", "Files aren't comparable, or I need more"),
}
DIM_LABEL = {
    "combined_loan_to_value_ratio": "Loan-to-value",
    "property_value": "Property value",
    "debt_to_income_ratio": "Debt-to-income",
    "income": "Income",
    "loan_amount": "Loan amount",
}
DIM_UNIT = {
    "combined_loan_to_value_ratio": "pp", "debt_to_income_ratio": "pp",
    "property_value": "usd", "income": "usd", "loan_amount": "usd",
}


# ---------------------------------------------------------------------------
# Escaping and numbers
# ---------------------------------------------------------------------------
def e(x: Any) -> str:
    """Escape anything on its way into markup.

    There is no template engine, so this is the only barrier between stored text and the
    response. quote=True because values land inside attributes as well as between tags,
    and None becomes the empty string so a missing field renders as nothing rather than
    as the word "None".
    """
    return html.escape("" if x is None else str(x), quote=True)


def money(v) -> str:
    # An em dash for absent, never "$0": a zero is a figure the record states and an
    # absence is the record not stating one, and these screens are about that difference.
    if v is None:
        return "—"
    return "$" + f"{abs(float(v)):,.0f}" if float(v) >= 0 else "-$" + f"{abs(float(v)):,.0f}"


def fmt_margin(dim: str, m) -> str:
    # NaN prints as "not comparable" rather than propagating into the page. It arrives
    # from a dimension the pair could not be compared on, which is a statement worth
    # making in words.
    if m is None or (isinstance(m, float) and math.isnan(m)):
        return "not comparable"
    # Percentage-point dimensions carry an explicit sign; currency goes through money(),
    # which formats the sign itself. Callers that want a magnitude strip the "+" after
    # taking abs() -- the sign is never removed from a signed figure.
    return f"{m:+.3g} pp" if DIM_UNIT.get(dim) == "pp" else money(m)


# ---------------------------------------------------------------------------
# The three-way decomposition
# ---------------------------------------------------------------------------
def verdict_counts(c: dict) -> dict:
    """Survives, defeated and untestable are three counts, never two.

    Untestable is counted in two distinct ways and both belong in it. A matched denial can
    be untestable because its reason names nothing the public record carries, or because
    the published values are too coarse to separate the pair. A denial with no comparator
    at all was never testable either -- it just failed earlier. Folding either into
    "survives" would report an absence of evidence as evidence of absence, which is the
    single failure mode this decomposition exists to prevent.
    """
    # Two denominators, kept apart on purpose. `nonx` is the non-exempt population, which
    # is what "untestable" is a share of; `matched` is what survives/defeated are shares
    # of. Every arithmetic result is floored at zero: these counts come from a stored
    # summary, and a negative count rendered into a sentence would read as a real number.
    nonx = c.get("denials_non_exempt") or c.get("denials_in_scope") or 0
    matched = c.get("denials_with_matched_comparator") or 0
    defeated = c.get("denials_with_finding") or 0
    untest_matched = (c.get("untestable_code_present") or 0) + \
                     (c.get("untestable_below_resolution") or 0)
    unmatched = max(0, nonx - matched)
    survives = max(0, matched - defeated - untest_matched)
    return {"non_exempt": nonx, "matched": matched, "defeated": defeated,
            "survives": survives, "untestable_matched": untest_matched,
            "no_comparator": unmatched, "untestable": untest_matched + unmatched,
            "untestable_code": c.get("untestable_code_present") or 0,
            "untestable_resolution": c.get("untestable_below_resolution") or 0}


# ---------------------------------------------------------------------------
# Saying how far apart the two files are
# ---------------------------------------------------------------------------
# Both functions print the MAGNITUDE and then say the direction in a word. The stored
# margin is signed on the dimension's own orientation, so "-8.8 pp" in front of a reader
# states the opposite of the finding; the first render review caught exactly that.
def gap_short(dim: str, t: dict) -> str:
    m, oc = t.get("margin"), t.get("outcome")
    if m is None or (isinstance(m, float) and math.isnan(m)):
        return "not comparable"
    mag = fmt_margin(dim, abs(m)).lstrip("+")
    return mag + {"not_supported": " worse", "below_resolution": " apart"}.get(oc, " better")


def gap_words(dim: str, t: dict) -> str:
    """How much worse the approved file is, in words. The stored margin is signed on the
    dimension's own orientation, and a bare minus sign in front of a percentage-point
    figure reads as the opposite of what it means."""
    m, thr, oc = t.get("margin"), t.get("decisive_threshold"), t.get("outcome")
    if m is None or (isinstance(m, float) and math.isnan(m)):
        return "not comparable on this dimension"
    mag = fmt_margin(dim, abs(m)).lstrip("+")
    if oc == "not_supported":
        return mag + " worse"
    if oc == "below_resolution":
        return mag + " apart — inside the " + fmt_margin(dim, thr).lstrip("+") + " floor"
    return mag + " better"


# ---------------------------------------------------------------------------
# Strength, rank and the claim sentence
# ---------------------------------------------------------------------------
def strength(f: dict) -> tuple[str, float]:
    """Wireframe 2b/2c's 'How strong is this?'. A cell that cannot reach the FDR
    threshold is not scored at all rather than scored low -- being the worst of one
    is not evidence, and a bar would imply it was."""
    if f.get("cell_power") == "underpowered" or (f.get("cell_size") or 0) < 2:
        return "Not scored", 0.0
    p = f.get("rank_p_value")
    # A finding with no p-value is unscored too. Substituting a default would put a bar
    # on the screen for a quantity that was never computed.
    if p is None:
        return "Not scored", 0.0
    # The bar is 1 - p, clamped. It is a presentation of the rank p-value and nothing
    # more -- the labels are cut points on that one number, not a second score.
    s = max(0.0, min(1.0, 1.0 - float(p)))
    return ("Strong" if s >= 0.80 else "Moderate" if s >= 0.50 else "Weak"), s


def ordinal(n: int) -> str:
    return {1: "best", 2: "2nd best", 3: "3rd best"}.get(n, f"{n}th best")


def claim(f: dict, reasons: dict) -> str:
    """The finding as a sentence, addressed to the filer. Wireframe 2c note 1."""
    codes = f.get("stated_reason_codes") or []
    label = reasons.get(codes[0], {}).get("label", "the stated reason") if codes else "the stated reason"
    inf = [t for t in f.get("tested", []) if t.get("outcome") == "not_supported"]
    # With no unsupported dimension there is nothing to assert, and the sentence says the
    # record settles nothing "either way" rather than implying the denial was sound. The
    # product's whole claim is about what the public record can and cannot show.
    if not inf:
        return (f"Denied for {label.lower()}, but nothing in the public record settles it "
                f"either way at this resolution.")
    d = inf[0]["dimension"]
    dl = DIM_LABEL.get(d, d).lower()
    worse = "worse" if inf[0].get("direction") == "higher_is_worse" else "weaker"
    return (f"You denied this application for {label.lower()}. You approved one with "
            f"{worse} {dl} in the same county.")


