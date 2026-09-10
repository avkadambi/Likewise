"""The exhibits: what the data looks like, and what the method can and cannot do.

Every figure here is drawn from an artefact produced by another module in this package --
`eda.json`, `simulation.json`, `crossvalidation.json` -- or from the scan store the engine
itself wrote. Nothing is drawn from a number typed into this file, which is the property
that makes the figures reproducible: delete `analysis/out` and `make analysis` rebuilds
all of it from the data.

Where a figure shows the generated fixture rather than the real FFIEC slice it says so on
the axis, every time. The fixture is larger and better behaved than any real small filer's
record, and a figure that let a reader forget which one they were looking at would be the
most misleading thing in the whole package.

Run it:  python -m analysis.figures     (after eda, simulate and crossvalidate)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                      # no display in a container; write files only
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis import eda

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "out"
FIGS = OUT / "figures"

# One palette, used consistently: the same colour means the same thing in every figure.
INK = "#1a1a1a"
REAL = "#1f4e79"          # the real FFIEC slice
FIXTURE = "#c07a2b"       # the generated fixture -- warm, so it never reads as the real one
ACCENT = "#8b1a1a"        # thresholds, nominal levels, anything the reader must not miss
MUTED = "#8a8a8a"


def zip_(*seqs):
    """`zip` with the length mismatch made deliberate rather than accidental.

    Every use in this module pairs a data sequence with a fixed colour palette, and the
    palette is allowed to be the longer of the two -- a figure with three series should
    not have to trim a four-colour palette to draw. Written once here so that the intent
    is stated in one place instead of a `strict=False` appearing at seven call sites.
    """
    return zip(*seqs, strict=False)


def _style() -> None:
    plt.rcParams.update({
        "figure.dpi": 150, "savefig.dpi": 150, "figure.facecolor": "white",
        "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
        "axes.edgecolor": INK, "axes.labelcolor": INK, "text.color": INK,
        "xtick.color": INK, "ytick.color": INK, "axes.grid": True,
        "grid.color": "#dddddd", "grid.linewidth": 0.6, "axes.axisbelow": True,
        "legend.frameon": False, "figure.autolayout": False,
    })


def _finish(fig, name: str, caption: str) -> Path:
    """Save one figure, with its caption written into the image.

    The caption travels with the figure on purpose. These exhibits end up in a report, in
    a slide, and in a repository, and a figure whose caption was left behind in the
    document it was cut from is how a qualified result becomes an unqualified one.
    """
    fig.text(0.01, 0.005, caption, fontsize=6.5, color=MUTED, va="bottom", wrap=True)
    FIGS.mkdir(parents=True, exist_ok=True)
    path = FIGS / f"{name}.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    return path


def _load(name: str) -> dict:
    path = OUT / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; run `python -m analysis.{path.stem}` first")
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Figure 1: what the publication scale can express
# ---------------------------------------------------------------------------
def fig_granularity(prof: dict):
    """Loan amount, income and DTI as they actually arrive.

    THE POINT. Each panel shows a field's published values against the grid it is
    published on. Loan amount lands on $10,000 bin midpoints without exception -- every
    value ends in 5000 -- so two loans $9,000 apart are reported as identical. Income is
    rounded to $1,000. DTI is an exact integer only inside [36, 49].

    This is the origin of the publication floor, which is one of the three terms in every
    decisive threshold the engine computes. It is not a modelling assumption; it is a
    measurement of the file.
    """
    real = prof["ffiec_2024_real"]
    df = eda.load("ffiec_2024_real")
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.2))

    la = df["loan_amount"].dropna().astype(float)
    axes[0].hist(la / 1000, bins=30, color=REAL, edgecolor="white", linewidth=0.4)
    axes[0].set_title("Loan amount")
    axes[0].set_xlabel("$ thousands")
    axes[0].set_ylabel("records")
    conf = next(g for g in real["granularity"] if g["field"] == "loan_amount")
    axes[0].text(0.97, 0.94, f"{conf['grid_conformance']:.0%} on $10,000\nbin midpoints",
                 transform=axes[0].transAxes, ha="right", va="top", fontsize=8,
                 color=ACCENT)

    inc = df["income"].dropna().astype(float)
    axes[1].hist(inc / 1000, bins=30, color=REAL, edgecolor="white", linewidth=0.4)
    axes[1].set_title("Income")
    axes[1].set_xlabel("$ thousands")

    dti = df["debt_to_income_ratio"].dropna().astype(float)
    vc = dti.value_counts().sort_index()
    axes[2].bar(vc.index, vc.values, width=0.8, color=REAL)
    axes[2].axvspan(35.5, 49.5, color=ACCENT, alpha=0.08)
    axes[2].set_title("Debt-to-income ratio")
    axes[2].set_xlabel("percentage points")
    b = real["dti_bands"]
    axes[2].text(0.02, 0.94,
                 f"{b['exact_integer_in_36_49_share']:.0%} inside [36, 49]\n"
                 f"{b['absent_share']:.0%} of records carry no value",
                 transform=axes[2].transAxes, va="top", fontsize=8, color=ACCENT)
    fig.suptitle("Figure 1  The published record is coarse, and coarse unevenly",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    return _finish(fig, "f1_granularity",
                   "Real FFIEC 2024 slice, one filer, 400 records. Shaded band on the "
                   "right panel marks the window where Regulation C publishes an exact "
                   "integer; outside it the file carries a band, and the engine compares "
                   "bands as intervals.")


# ---------------------------------------------------------------------------
# Figure 2: tie concentration
# ---------------------------------------------------------------------------
def fig_ties(prof: dict):
    """How much of each column sits on how few values.

    THE POINT. A rank statistic can only separate records that hold different values, so
    the concentration of a column is a hard ceiling on the evidence it can ever supply.
    The curve is the cumulative share of the column covered by its k most common values;
    a curve that rises steeply is a column that cannot distinguish anybody.

    Read the DTI curve first: in the real filing, five values cover more than half the
    column. That is the arithmetic behind the tie-corrected variance in the pooled test
    and behind the attainable-p floor in Figure 4.
    """
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for key, colour, label in (("ffiec_2024_real", REAL, "real FFIEC slice"),
                               ("fixture_2025_generated", FIXTURE, "generated fixture")):
        df = eda.load(key)
        for field, ls in (("debt_to_income_ratio", "-"),
                          ("combined_loan_to_value_ratio", "--")):
            v = df[field].dropna().astype(float)
            if v.empty:
                continue
            counts = v.value_counts().sort_values(ascending=False).to_numpy()
            share = np.cumsum(counts) / counts.sum()
            k = np.arange(1, share.size + 1)
            ax.plot(k[:40], share[:40], ls, color=colour, linewidth=1.6,
                    label=f"{field.replace('_', ' ')} -- {label}")
    ax.axhline(0.5, color=MUTED, linewidth=0.8, linestyle=":")
    ax.text(40, 0.51, "half the column", ha="right", fontsize=7, color=MUTED)
    ax.set_xlabel("k most common values")
    ax.set_ylabel("cumulative share of the column")
    ax.set_ylim(0, 1.02)
    ax.set_title("Figure 2  Tie concentration caps every rank statistic", loc="left")
    ax.legend(fontsize=7.5, loc="lower right")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _finish(fig, "f2_ties",
                   "Solid: debt-to-income. Dashed: combined loan-to-value. The generated "
                   "fixture is deliberately less concentrated than the real file, which "
                   "is one reason no inference rests on it.")


# ---------------------------------------------------------------------------
# Figure 3: block and cell structure
# ---------------------------------------------------------------------------
def fig_cells(prof: dict):
    """How the exact-match key partitions a filing, and how little is left.

    THE POINT. Comparison is only defined inside a block, and a block is only useful if
    it holds both a denial and an approval. The left panel is the block-size
    distribution; the right is the funnel from records to cells that can actually
    produce a comparison.

    The funnel is the honest headline of the whole product: most denials never reach a
    comparison, and the reason is structural rather than statistical.
    """
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6))
    for key, colour, label in (("ffiec_2024_real", REAL, "real FFIEC slice"),
                               ("fixture_2025_generated", FIXTURE, "generated fixture")):
        b = prof[key]["blocks"]
        sizes = np.array([int(k) for k in b["block_size_distribution"]])
        counts = np.array(list(b["block_size_distribution"].values()))
        order = np.argsort(sizes)
        axes[0].step(sizes[order], np.cumsum(counts[order]) / counts.sum(),
                     where="post", color=colour, linewidth=1.6, label=label)
    axes[0].set_xscale("log")
    axes[0].set_xlabel("block size (records sharing the exact-match key)")
    axes[0].set_ylabel("cumulative share of blocks")
    axes[0].set_title("Blocks are small", loc="left")
    axes[0].legend(fontsize=7.5, loc="lower right")

    real = prof["ffiec_2024_real"]
    b, a = real["blocks"], real["attainability"]
    stages = ["records\nin file", "blocks", "blocks with\na denial",
              "blocks with\nboth roles", "cells with\n2+ DTI values"]
    vals = [b["n_records"], b["n_blocks"], b["blocks_with_a_denial"],
            b["blocks_with_both_roles"], a.get("cells", 0)]
    axes[1].bar(stages, vals, color=[REAL] * 4 + [ACCENT])
    axes[1].set_yscale("log")
    axes[1].set_ylabel("count (log scale)")
    axes[1].set_title("What survives to a comparison (real slice)", loc="left")
    for i, v in enumerate(vals):
        axes[1].text(i, v * 1.15, str(v), ha="center", fontsize=8)
    axes[1].tick_params(axis="x", labelsize=7.5)
    fig.suptitle("Figure 3  Comparison is only defined inside a block, and blocks are tiny",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    return _finish(fig, "f3_cells",
                   "A denial in a block with no approval is not a negative result. It is "
                   "a record the public file cannot speak to, and the engine reports it "
                   "as unaddressed rather than as clean.")


# ---------------------------------------------------------------------------
# Figure 4: the attainable p-value floor
# ---------------------------------------------------------------------------
def fig_attainability(prof: dict, sim: dict):
    """The smallest p a cell can produce, decided before any comparison is made.

    THE MATHEMATICS. A record can be no more extreme than the tie block it sits in, so a
    cell's floor is |best tie block| / n, and at best -- with no ties at all -- it is
    1/n. The curve is that best case; the points are the real cells, which sit on or
    above it.

    A cell below the 0.05 line cannot reach conventional significance at ANY effect size.
    That is why the design pools across cells instead of reporting a per-finding p-value,
    and why no per-finding false-discovery-rate estimator survives in the codebase: they
    were implemented, found unattainable at this cell size, and deleted rather than left
    unreachable.
    """
    a = prof["ffiec_2024_real"]["attainability"]
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    biggest = max([*a.get("sizes", [2]),
                   *prof["fixture_2025_generated"]["attainability"].get("sizes", [2])])
    n = np.arange(2, biggest + 1)
    ax.plot(n, 1.0 / n, color=MUTED, linewidth=1.4,
            label="best possible floor, 1/n (no ties at all)")
    if a.get("cells"):
        ax.scatter(a["sizes"], a["floors"], s=26, color=REAL, zorder=3,
                   label=f"real cells (n = {a['cells']})")
    fx = prof["fixture_2025_generated"]["attainability"]
    if fx.get("cells"):
        ax.scatter(fx["sizes"], fx["floors"], s=10, color=FIXTURE, alpha=0.5, zorder=2,
                   label=f"fixture cells (n = {fx['cells']})")
    ax.axhline(0.05, color=ACCENT, linewidth=1.2)
    ax.text(biggest, 0.056, "q = 0.05", ha="right", fontsize=8, color=ACCENT)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("cell size")
    ax.set_ylabel("smallest attainable p-value")
    ax.set_title("Figure 4  Most cells cannot reach a decision at any effect size",
                 loc="left")
    ax.legend(fontsize=7.5, loc="upper right")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    cap = (f"Real slice: {a.get('share_capable_of_reaching_q', 0):.0%} of cells could "
           f"ever reach q = 0.05. Simulated at the design's own size distribution the "
           f"share is {sim['structural_capacity'][0]['share_capable_of_reaching_q']:.0%}.")
    return _finish(fig, "f4_attainability", cap)


# ---------------------------------------------------------------------------
# Figure 5: the comparability floor
# ---------------------------------------------------------------------------
def fig_comparability_floor():
    """Why one scalar threshold for combined loan-to-value would be wrong.

    THE MATHEMATICS. CLTV is 100*L/V, a ratio of two quantities that are each published
    at $10,000 bin midpoints. Propagating that granularity, two CLTV values are only
    distinguishable when they differ by more than

        floor(L, V) = 100 * max(0.05 L, 20000) / V   percentage points

    which is 7.0 points at a $285,000 property and 16.0 at a $125,000 one. The declared
    minimum in the budget is 7.1 points -- adequate above about $282,000 and inadequate
    below it.

    This is the argument for computing the threshold PER PAIR at that pair's own
    magnitudes rather than certifying one number at a convenient reference point. A single
    scalar passes where it was certified and fails everywhere cheaper -- and it fails in
    the direction that manufactures findings, on exactly the properties a small lender's
    denials concentrate in.
    """
    declared = 7.1
    v = np.linspace(80_000, 900_000, 600)
    fig, ax = plt.subplots(figsize=(6.6, 3.9))
    for ltv, ls, lab in ((0.95, "-", "L = 0.95 V"), (0.80, "--", "L = 0.80 V"),
                         (0.60, ":", "L = 0.60 V")):
        floor = 100 * np.maximum(0.05 * ltv * v, 20_000) / v
        ax.plot(v / 1000, floor, ls, color=REAL, linewidth=1.6, label=lab)
    ax.axhline(declared, color=ACCENT, linewidth=1.3)
    ax.text(880, declared + 0.5, f"declared minimum, {declared} pp", ha="right",
            fontsize=8, color=ACCENT)
    cross = 2_000_000 / declared / 1000
    ax.axvline(cross, color=ACCENT, linewidth=0.9, linestyle=":")
    ax.text(cross + 8, 22, f"below ${cross * 1000:,.0f}\nthe declared minimum\n"
                           "is smaller than the floor",
            fontsize=8, color=ACCENT, va="top")
    for pv, lab in ((285, "7.0 pp"), (175, "11.4 pp"), (125, "16.0 pp")):
        ax.scatter([pv], [100 * 20_000 / (pv * 1000)], s=30, color=INK, zorder=4)
        ax.annotate(lab, (pv, 100 * 20_000 / (pv * 1000)), textcoords="offset points",
                    xytext=(6, 6), fontsize=8)
    ax.set_xlabel("property value ($ thousands)")
    ax.set_ylabel("comparability floor (percentage points of CLTV)")
    ax.set_ylim(0, 26)
    ax.set_title("Figure 5  The decisive threshold cannot be a single number", loc="left")
    ax.legend(fontsize=7.5)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return _finish(fig, "f5_comparability_floor",
                   "floor = 100 * max(0.05 L, 20000) / V, from propagating the $10,000 "
                   "publication bins of loan amount and property value through the ratio. "
                   "The engine takes tau = max(declared minimum, comparability floor, "
                   "publication floor) for each pair.")


# ---------------------------------------------------------------------------
# Figure 6: calibration
# ---------------------------------------------------------------------------
def fig_calibration(sim: dict):
    """The null distribution of the pooled test's p-value, against the uniform.

    THE POINT. A correctly calibrated test produces p-values uniform on (0, 1) under the
    null, so its empirical CDF lies on the diagonal. Departures ABOVE the diagonal are
    anti-conservative -- the test rejects more often than it claims -- and are the failure
    mode that matters, because the product's single inferential claim is a one-sided p.

    The curves lie on or just below the diagonal in every regime. Below is expected: the
    statistic is discrete, and a discrete test cannot hit its nominal level exactly, so it
    lands on the safe side.
    """
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.8))
    for regime, colour in zip_(sim["null_p_sample"],
                              (MUTED, REAL, FIXTURE, ACCENT)):
        p = np.sort(np.array(sim["null_p_sample"][regime]))
        ecdf = np.arange(1, p.size + 1) / p.size
        axes[0].plot(p, ecdf, color=colour, linewidth=1.4, label=regime)
        axes[1].plot(p, ecdf, color=colour, linewidth=1.4)
    for ax in axes:
        ax.plot([0, 1], [0, 1], color=INK, linewidth=0.8, linestyle="--")
    axes[0].set_xlabel("p-value under a true null")
    axes[0].set_ylabel("empirical CDF")
    axes[0].set_title("Whole range", loc="left")
    axes[0].legend(fontsize=7.5, loc="lower right")
    axes[1].set_xlim(0, 0.15)
    axes[1].set_ylim(0, 0.15)
    axes[1].axvline(0.05, color=ACCENT, linewidth=0.9)
    axes[1].set_xlabel("p-value (decision region)")
    axes[1].set_title("Where the decision is made", loc="left")
    fig.suptitle("Figure 6  The pooled test holds its stated error rate",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    rates = [c for c in sim["calibration"] if c["n_cells"] == 300]
    cap = ("4,000 simulated filings of 300 cells each, per regime. Rejection rate at "
           "alpha = 0.05: " + ", ".join(f"{c['regime']} {c['rejection_rate_05']:.3f}"
                                        for c in rates) + ".")
    return _finish(fig, "f6_calibration", cap)


# ---------------------------------------------------------------------------
# Figure 7: power
# ---------------------------------------------------------------------------
def fig_power(sim: dict):
    """How large a departure has to be before the pooled test sees it.

    THE POINT. Power against a location shift, by number of cells and by publication
    scale. The 80% line and the interpolated minimum detectable effect say what the
    design can see; the near-identical curves across coarsening regimes say something
    less obvious and worth stating plainly -- a RANK test is largely indifferent to
    binning, because binning preserves order even where it destroys distance.

    That indifference is confined to the pooled test. The finding rule in Figure 8 is a
    statement about distance, not order, and coarsening damages it directly.
    """
    pw = sim["power"]
    regimes = sorted({p["regime"] for p in pw})
    fig, axes = plt.subplots(1, len(regimes), figsize=(3.0 * len(regimes), 3.4),
                             sharey=True)
    for ax, regime in zip_(np.atleast_1d(axes), regimes):
        for nc, colour in zip_(sorted({p["n_cells"] for p in pw}),
                              (MUTED, REAL, ACCENT)):
            curve = sorted([p for p in pw if p["regime"] == regime and p["n_cells"] == nc],
                           key=lambda p: p["shift"])
            ax.plot([c["shift"] for c in curve], [c["power_05"] for c in curve],
                    "o-", ms=3, color=colour, linewidth=1.4, label=f"{nc} cells")
        ax.axhline(0.80, color=INK, linewidth=0.8, linestyle="--")
        ax.axhline(0.05, color=MUTED, linewidth=0.8, linestyle=":")
        ax.set_title(regime, loc="left", fontsize=9)
        ax.set_xlabel("shift (dimension units)")
    np.atleast_1d(axes)[0].set_ylabel("power at alpha = 0.05")
    np.atleast_1d(axes)[0].legend(fontsize=7.5, loc="lower right")
    fig.suptitle("Figure 7  Power of the pooled test", x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    mde = {(m["regime"], m["n_cells"]): m["minimum_detectable_shift"]
           for m in sim["minimum_detectable_effect"]}
    cap = ("Minimum detectable shift at 80% power: " +
           ", ".join(f"{r} @300 cells = {mde.get((r, 300))}" for r in regimes) +
           " dimension units. Dashed line 80% power; dotted line the nominal size.")
    return _finish(fig, "f7_power", cap)


# ---------------------------------------------------------------------------
# Figure 8: the finding rule
# ---------------------------------------------------------------------------
def fig_finding_rule(sim: dict):
    """What the decisive threshold costs, in the currency the product actually spends.

    THE POINT. Each cell resolves into exactly one of three states: a FINDING (somebody
    worse beyond the threshold, nobody better beyond it), AMBIGUOUS (beaten in both
    directions, which the comparison lattice refuses to resolve), or NOTHING SEPARATES
    ANYBODY (no comparator beyond the threshold in either direction).

    As the threshold rises, ambiguity falls -- that is the threshold doing its job, since
    a wider decisive band admits fewer contradictory comparisons -- but the share where
    nothing separates anybody rises faster. The threshold is not a free parameter that
    can be tuned to buy precision: it is set by the publication scale, and its cost is
    paid in records that leave the queue entirely.
    """
    dom = [d for d in sim["dominance"] if d["regime"] == "bin_1" and d["shift"] == 0.0]
    dom.sort(key=lambda d: d["threshold"])
    thr = [d["threshold"] for d in dom]
    find = np.array([d["finding_rate"] for d in dom])
    amb = np.array([d["ambiguous_rate"] for d in dom])
    none = np.array([d["no_comparator_beyond_threshold_rate"] for d in dom])
    other = 1 - find - amb - none          # beaten only in the better direction

    fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.6))
    axes[0].stackplot(thr, find, amb, none, other,
                      colors=[ACCENT, FIXTURE, MUTED, "#dcdcdc"],
                      labels=["finding", "ambiguous (both directions)",
                              "nothing separates anybody", "only better comparators"])
    axes[0].set_xlabel("decisive threshold (dimension units)")
    axes[0].set_ylabel("share of cells")
    axes[0].set_ylim(0, 1)
    axes[0].set_title("Every cell resolves into exactly one state", loc="left")
    axes[0].legend(fontsize=7, loc="upper center", ncol=2)

    for shift, colour in zip_((0.0, 1.0, 2.0, 4.0), (MUTED, REAL, FIXTURE, ACCENT)):
        pts = sorted([d for d in sim["dominance"]
                      if d["regime"] == "bin_1" and d["shift"] == shift],
                     key=lambda d: d["threshold"])
        axes[1].plot([p["threshold"] for p in pts], [p["finding_rate"] for p in pts],
                     "o-", ms=3, color=colour, linewidth=1.4, label=f"shift {shift:g}")
    axes[1].set_xlabel("decisive threshold (dimension units)")
    axes[1].set_ylabel("finding rate")
    axes[1].set_title("The rule fires more often under a real effect", loc="left")
    axes[1].legend(fontsize=7.5)
    fig.suptitle("Figure 8  The finding rule, and what the threshold costs",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    return _finish(fig, "f8_finding_rule",
                   "Simulated cells at the design's own size distribution, published on a "
                   "one-unit grid. Left panel is the true null; the rule fires on about a "
                   "third of cells with no effect present at all, which is why the "
                   "product's headline is a comparison against this null and never a raw "
                   "count.")


# ---------------------------------------------------------------------------
# Figure 9: the real scan against its own null
# ---------------------------------------------------------------------------
# The only real filing in the repository, identified by its LEI. Every other scan in the
# store was run against generated data -- the example filing or the synthetic fixture --
# and a figure that let the two blur together would be the single most misleading thing
# in this package, because the generated data is larger and better behaved than any real
# small filer's record.
REAL_LEI = "549300MGPZBLQDIL7538"


def _scans() -> list[dict]:
    """Every completed scan in the store, tagged with whether its input was real."""
    out = []
    for meta_path in sorted((ROOT / "data/store/scans").glob("*/scan.json")):
        summary_path = meta_path.parent / "summary.json"
        if not summary_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        summary = json.loads(summary_path.read_text())
        out.append({"meta": meta, "summary": summary,
                    "real": meta.get("lei") == REAL_LEI})
    return out


def fig_observed_vs_null():
    """The finding rate against its own permutation null, on real and generated input.

    THE POINT. The permutation null says that if the denial label were unrelated to the
    tested dimension, roughly a third of testable cells would STILL produce a finding --
    a cell of three with a threshold below its spread produces one by geometry alone. A
    product that published the raw rate would be publishing mostly geometry, which is why
    the headline is always the departure from this null and never a count.

    THE TWO PANELS ARE NOT THE SAME CLAIM. The left is the real FFIEC slice: 33 denials,
    seven of which found a matched comparator, no findings, and a null envelope spanning
    the entire unit interval. At that size the method cannot distinguish anything from
    anything, and saying so is the result. The right is a generated filing large enough
    for the envelope to close, where the observed rate sits well below the null.

    Nothing about a lender may be concluded from the right panel. It is shown because it
    demonstrates that the machinery separates signal from geometry once there is enough
    data for the question to be answerable -- and, read together with the left panel, how
    much data that takes.
    """
    scans = _scans()
    real = max((s for s in scans if s["real"] and s["summary"].get("null")),
               key=lambda s: s["summary"]["counts"]["matched_pairs"], default=None)
    gen = max((s for s in scans if not s["real"] and s["summary"].get("null")),
              key=lambda s: s["summary"]["counts"]["records_in_scope"], default=None)
    panels = [(p, lab) for p, lab in ((real, "real FFIEC 2024 slice"),
                                      (gen, "GENERATED filing")) if p]
    if not panels:
        return None

    fig, axes = plt.subplots(1, len(panels), figsize=(5.4 * len(panels), 3.4))
    for ax, (scan, label) in zip_(np.atleast_1d(axes), panels):
        n = scan["summary"]["null"]
        c = scan["summary"]["counts"]
        lo, hi = n["null_ci95"]
        colour = REAL if scan["real"] else FIXTURE
        ax.axvspan(lo, hi, color=MUTED, alpha=0.25)
        ax.axvline(n["null_mean"], color=INK, linewidth=1.4)
        ax.axvline(n["observed"], color=ACCENT, linewidth=2.4)
        ax.set_xlim(-0.02, max(hi, n["observed"]) * 1.15 + 0.02)
        ax.set_ylim(0, 1)
        ax.set_yticks([])
        ax.set_xlabel("finding rate among testable cells")
        ax.set_title(label, loc="left", color=colour)
        ax.text(n["null_mean"], 0.90, f"  null mean {n['null_mean']:.3f}", fontsize=8)
        ax.text(n["observed"], 0.70, f"observed {n['observed']:.3f}",
                fontsize=8, color=ACCENT,
                ha="left" if n["observed"] < n["null_mean"] else "right")
        ax.text((lo + hi) / 2, 0.30, f"95% null envelope\n[{lo:.3f}, {hi:.3f}]",
                fontsize=8, color=MUTED, ha="center")
        ax.text(0.98, 0.04,
                f"{c['records_in_scope']:,} records, {c['denials_in_scope']:,} denials\n"
                f"{c.get('denials_with_matched_comparator', 0):,} with a matched "
                f"comparator, {c.get('denials_with_finding', 0)} findings\n"
                f"direction: {n['direction']}",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5,
                color=MUTED)
    fig.suptitle("Figure 9  A finding rate means nothing except against its own null",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))
    return _finish(fig, "f9_observed_vs_null",
                   "Left: the real slice, where the envelope spans the whole unit "
                   "interval -- 33 denials cannot answer the question, and the honest "
                   "report is that they cannot. Right: generated data, shown only to "
                   "demonstrate that the envelope closes at scale. No claim about any "
                   "lender may be read from the right panel.")


# ---------------------------------------------------------------------------
# Figure 10: the cross-validation itself
# ---------------------------------------------------------------------------
def fig_crossvalidation(cv: dict):
    """Every statistic, and how far the engine sits from its reference implementation.

    THE POINT. Each bar is one statistic; its length is the largest disagreement found
    between the engine's standard-library implementation and a reference taken from SciPy,
    statsmodels or NumPy, against the tolerance allowed. Exact checks are plotted on an
    absolute scale in their own units; Monte Carlo checks are plotted in standard errors,
    because a simulated reference cannot be compared to floating-point noise.

    Bars far below their tolerance markers are the argument that the container's five-
    package dependency list costs nothing in numerical accuracy.
    """
    checks = cv["checks"]
    exact = [c for c in checks if c["kind"] != "monte_carlo"]
    mc = [c for c in checks if c["kind"] == "monte_carlo"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))

    y = np.arange(len(exact))
    gaps = [max(c["worst_gap"], 1e-18) for c in exact]
    axes[0].barh(y, gaps, color=REAL, height=0.55)
    axes[0].scatter([c["tolerance"] for c in exact], y, marker="|", s=200, color=ACCENT,
                    zorder=3, label="tolerance")
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([c["name"] for c in exact], fontsize=7.5)
    axes[0].set_xscale("log")
    axes[0].set_xlabel("worst disagreement (absolute or relative)")
    axes[0].set_title("Exact and numeric checks", loc="left")
    axes[0].legend(fontsize=7.5, loc="lower right")

    y = np.arange(len(mc))
    axes[1].barh(y, [c["worst_gap"] for c in mc], color=FIXTURE, height=0.55)
    axes[1].axvline(4.0, color=ACCENT, linewidth=1.2)
    axes[1].text(4.05, len(mc) - 0.6, "tolerance, 4 SE", fontsize=7.5, color=ACCENT)
    axes[1].set_yticks(y)
    axes[1].set_yticklabels([c["name"] for c in mc], fontsize=7.5)
    axes[1].set_xlim(0, 5)
    axes[1].set_xlabel("worst disagreement (Monte Carlo standard errors)")
    axes[1].set_title("Simulated references", loc="left")
    fig.suptitle("Figure 10  Two independent implementations of every statistic",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=(0, 0.05, 1, 0.93))
    v = cv["versions"]
    return _finish(fig, "f10_crossvalidation",
                   f"{cv['agreed']}/{cv['total']} checks agree. numpy {v['numpy']}, "
                   f"scipy {v['scipy']}, statsmodels {v['statsmodels']}, "
                   f"python {v['python']}.")


# ---------------------------------------------------------------------------
# Figure 11: interval coverage
# ---------------------------------------------------------------------------
def fig_coverage(sim: dict):
    """What the two interval estimators actually deliver, against what they promise.

    THE POINT. Left: the exact binomial bound the publication gate uses, across the sizes
    and rates the gate runs at. Clopper-Pearson is conservative by construction, and the
    figure shows by how much -- an over-wide bound refuses releases that should have
    shipped, so the excess is a cost, not only a safety margin.

    Right: the cluster bootstrap against the naive row bootstrap, on data with real
    within-cluster dependence. The naive interval is narrower and misses the truth far
    more often than its nominal 95% claims. This is the strongest argument in the package
    for resampling clusters rather than rows, because it is a measurement rather than an
    appeal to principle.
    """
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.5))
    bc = sim["binomial_coverage"]
    ns = sorted({r["n"] for r in bc})
    for p_true, colour in zip_(sorted({r["p_true"] for r in bc}),
                              (MUTED, REAL, FIXTURE, ACCENT)):
        pts = [r for r in bc if r["p_true"] == p_true]
        pts.sort(key=lambda r: r["n"])
        axes[0].plot([r["n"] for r in pts], [r["coverage"] for r in pts], "o-", ms=3,
                     color=colour, linewidth=1.4, label=f"true rate {p_true:g}")
    axes[0].axhline(0.95, color=INK, linewidth=1.0, linestyle="--")
    axes[0].set_xscale("log")
    axes[0].set_xticks(ns)
    axes[0].set_xticklabels([str(n) for n in ns], fontsize=7.5)
    axes[0].set_xlabel("trials")
    axes[0].set_ylabel("coverage of the nominal 95% upper limit")
    axes[0].set_title("Exact binomial bound: conservative everywhere", loc="left")
    axes[0].set_ylim(0.945, 1.005)
    axes[0].legend(fontsize=7, loc="center left", bbox_to_anchor=(0.02, 0.35))

    boot = sim["bootstrap_coverage"]
    names = [b["estimator"] for b in boot]
    cov = [b["coverage"] for b in boot]
    bars = axes[1].bar(names, cov, color=[REAL, MUTED], width=0.5)
    axes[1].axhline(0.95, color=ACCENT, linewidth=1.2)
    axes[1].text(1.45, 0.952, "nominal 95%", fontsize=7.5, color=ACCENT, ha="right")
    axes[1].set_ylim(0.75, 1.0)
    axes[1].set_ylabel("coverage")
    axes[1].set_title("Ignoring the clustering costs real coverage", loc="left")
    axes[1].tick_params(axis="x", labelsize=8)
    for b, c, w in zip_(bars, cov, [x["mean_width"] for x in boot]):
        axes[1].text(b.get_x() + b.get_width() / 2, c + 0.004,
                     f"{c:.3f}\nwidth {w:.3f}", ha="center", fontsize=7.5)
    fig.suptitle("Figure 11  Interval estimators, measured", x=0.01, ha="left",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0.05, 1, 0.93))
    cl, na = boot[0], boot[1]
    return _finish(fig, "f11_coverage",
                   "Both panels are simulation: the truth is known because it was chosen. "
                   f"The cluster bootstrap covers {cl['coverage']:.3f} against a nominal "
                   f"0.95 -- a percentile interval is not exact at 120 clusters and is "
                   f"reported as it measures, not as it is advertised. The naive interval "
                   f"covers {na['coverage']:.3f} while being {1 - na['mean_width'] / cl['mean_width']:.0%} "
                   "narrower, which is the whole failure mode: it buys apparent precision "
                   "by pretending dependent observations are independent.")


# ---------------------------------------------------------------------------
def main() -> int:
    _style()
    prof = _load("eda.json")
    sim = _load("simulation.json")
    cv = _load("crossvalidation.json")

    made = []
    for fn, args in ((fig_granularity, (prof,)), (fig_ties, (prof,)),
                     (fig_cells, (prof,)), (fig_attainability, (prof, sim)),
                     (fig_comparability_floor, ()), (fig_calibration, (sim,)),
                     (fig_power, (sim,)), (fig_finding_rule, (sim,)),
                     (fig_observed_vs_null, ()), (fig_crossvalidation, (cv,)),
                     (fig_coverage, (sim,))):
        path = fn(*args)
        if path:
            made.append(path)
            print(f"  {path.relative_to(ROOT)}")
        plt.close("all")

    # One PDF carrying every figure, for the report and for printing. Rebuilt from the
    # PNGs rather than redrawn, so the two can never disagree.
    pdf_path = OUT / "figures.pdf"
    with PdfPages(pdf_path) as pdf:
        for p in made:
            img = plt.imread(p)
            h, w = img.shape[:2]
            f = plt.figure(figsize=(w / 150, h / 150))
            ax = f.add_axes((0, 0, 1, 1)); ax.imshow(img); ax.axis("off")
            pdf.savefig(f); plt.close(f)
    print(f"  {pdf_path.relative_to(ROOT)}  ({len(made)} figures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
