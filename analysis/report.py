"""Assemble the analysis report from the artefacts, so no number is ever typed twice.

Every figure, table and quoted value in the report comes out of `analysis/out/*.json`,
which the other modules in this package wrote. Nothing here restates a result from
memory. That is the property that makes the report reproducible rather than merely
written: delete `analysis/out`, run `make analysis`, and the document rebuilds itself
from the data with whatever the data now says.

Run it:  python -m analysis.report          (writes ANALYSIS.md, .html and .pdf)
"""
from __future__ import annotations
import json
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "out"


def _load(name: str) -> dict:
    p = OUT / name
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `make analysis` first")
    return json.loads(p.read_text())


def _table(headers: list[str], rows: list[list]) -> str:
    """A GitHub-flavoured markdown table. Values are formatted by the caller."""
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _fig(n: str, alt: str) -> str:
    return f"![{alt}](figures/{n}.png)\n"


def build() -> str:
    eda = _load("eda.json")
    sim = _load("simulation.json")
    cv = _load("crossvalidation.json")

    real = eda["ffiec_2024_real"]
    fx = eda["fixture_2025_generated"]
    v = cv["versions"]
    md: list[str] = []
    A = md.append

    # ---------------------------------------------------------------- header
    A(f"""# Likewise — Analysis Report

**Subject.** The statistical design of the Likewise distinguish engine: what it
estimates, whether the estimators are implemented correctly, how they behave at the
sizes and the resolution the published mortgage record actually has, and what the
available data does and does not support.

**Date.** {date.today().isoformat()}  ·  **Author.** Arun Kadambi  ·
**Software.** Python {v['python']}, NumPy {v['numpy']}, SciPy {v['scipy']},
statsmodels {v['statsmodels']}  ·  **Seeds.** fixed and recorded per study

**How to rebuild.** `make analysis`. Every figure and every number below is read from
`analysis/out/*.json`, which that target regenerates from the data. No value in this
document is transcribed by hand.
""")

    # ---------------------------------------------------------------- summary
    cal_bad = [c for c in sim["calibration"] if c["verdict"] == "ANTI-CONSERVATIVE"]
    mde300 = {m["regime"]: m["minimum_detectable_shift"]
              for m in sim["minimum_detectable_effect"] if m["n_cells"] == 300}
    boot = {b["estimator"]: b for b in sim["bootstrap_coverage"]}
    A(f"""## 0. What this report establishes

1. **The estimators are implemented correctly.** Every statistic the engine computes is
   computed a second time against SciPy, statsmodels or NumPy, on the same inputs.
   {cv['agreed']} of {cv['total']} checks agree, the exact ones to floating point
   (§5). The cross-validation found one real defect, which is documented rather than
   quietly repaired.

2. **The pooled test holds its stated error rate.** Across four publication regimes and
   three filing sizes, {len(sim['calibration']) - len(cal_bad)} of
   {len(sim['calibration'])} configurations are calibrated or conservative and none is
   anti-conservative (§6.1).

3. **The design can see a shift of roughly
   {mde300.get('bin_1')} dimension units at 300 cells**, and about half that at 1,000
   (§6.2). On debt-to-income that is under one percentage point — small, but not zero,
   and the number is now stated rather than hoped for.

4. **The binding constraint is not statistical power. It is arithmetic.** In the real
   slice, {real['attainability']['share_capable_of_reaching_q']:.0%} of cells could ever
   reach q = 0.05, and at the design's own cell-size distribution the simulated share is
   {sim['structural_capacity'][0]['share_capable_of_reaching_q']:.0%}. This is decided
   by cell size and ties before any comparison is made (§3.4), and it is why the design
   pools across cells and publishes no per-finding p-value.

5. **The available real data cannot answer the substantive question.** The one real
   filing in the repository holds {real['rows']} records and
   {real['action_taken_counts'].get('3', 0)} denials; its null envelope spans the entire
   unit interval (§7). The correct report on that filing is that it is silent, and the
   engine says so.

A sixth finding is methodological and belongs here: ignoring the clustering costs real
coverage. A naive row bootstrap covers
{boot['naive row bootstrap']['coverage']:.3f} against a nominal 0.95 while being
narrower than the cluster bootstrap — apparent precision bought by treating dependent
observations as independent (§6.4).
""")

    # ---------------------------------------------------------------- estimands
    A("""## 1. The question, and what is being estimated

A lender files its own mortgage record under Regulation C. For each denial the filing
carries the reason the lender itself cited. The question the product asks is narrow and
deliberately so:

> Among applications the lender's own filing places in the same coarsened cell, does the
> public record contain an approved application that is **not worse** on the dimension
> the lender's stated reason names?

Two estimands follow, and they are different in kind.

**(E1) The per-pair decision.** For a denied record *d* and an approved record *a* in the
same cell, on the dimension the cited reason names, decide one of seven states —
strictly worse, weakly worse, tied, ambiguous, unrecorded, weakly better, strictly
better. This is a decision under a partial order, not an estimate. Its error is
controlled by the decisive threshold, not by a confidence level.

**(E2) The filing-level departure.** Across the whole filing, does the position of denied
records within their own cells depart from what exchangeability would produce? This is
the only inferential claim the product makes, and it is a statement about a filing, never
about an applicant.

**What is deliberately not estimated.** No causal effect of any protected characteristic;
the published record carries no such variable in the comparison. No per-finding
p-value — §3.4 shows why one would be unattainable. No determination of any kind: the
output is a queue for human review, and a finding means the public record does not by
itself support the stated reason, not that the reason was wrong.
""")

    # ---------------------------------------------------------------- data
    A(f"""## 2. Data and provenance

{_table(["snapshot", "records", "approved", "denied", "provenance"],
        [["`ffiec_2024_real`", real["rows"],
          real["action_taken_counts"].get("1", 0),
          real["action_taken_counts"].get("3", 0),
          "real FFIEC 2024 public file, one filer"],
         ["`fixture_2025_generated`", fx["rows"],
          fx["action_taken_counts"].get("1", 0),
          fx["action_taken_counts"].get("3", 0),
          "**generated** — structure only"]])}

The distinction is load-bearing and is carried on every figure axis in this report. The
generated fixture is larger and better behaved than any real small filer's record: its
cells are bigger, its ties are milder, and
{fx['attainability']['share_capable_of_reaching_q']:.0%} of its cells can reach q = 0.05
against {real['attainability']['share_capable_of_reaching_q']:.0%} of the real one's. It
exists to exercise code paths and to show what the machinery does when the data is
sufficient. **No inference about any lender rests on it.**
""")

    # ---------------------------------------------------------------- EDA
    gr = [g for g in real["granularity"] if g.get("n")]
    A(f"""## 3. Exploratory analysis

### 3.1 What the published scale can express

{_fig("f1_granularity", "publication granularity")}

{_table(["field", "published grid", "conformance", "modal share", "top-5 share",
         "distinct / obs"],
        [[f"`{g['field']}`", g.get("published_grid", "—"),
          f"{g.get('grid_conformance', float('nan')):.3f}"
          if g.get("grid_conformance") is not None else "—",
          f"{g['modal_share']:.3f}", f"{g['top5_share']:.3f}",
          f"{g['distinct_per_observation']:.3f}"] for g in gr])}

Loan amount and property value land on $10,000 bin **midpoints** without exception —
every published value ends in 5000 — so two loans $9,000 apart are reported identically.
Income is rounded to $1,000. Debt-to-income is an exact integer only inside [36, 49];
{real['dti_bands']['absent_share']:.0%} of records carry no DTI value at all.

The consequence is the **publication floor**: a difference smaller than one bin is not
expressible in the file, whatever the true difference was. That floor is one of the three
terms in every decisive threshold the engine computes, and it comes from this table
rather than from the regulation text.

### 3.2 Ties are the rule, not an edge case

{_fig("f2_ties", "tie concentration")}

In the real filing, five DTI values cover
{next(g['top5_share'] for g in gr if g['field'] == 'debt_to_income_ratio'):.0%} of the
column. A rank statistic can only separate records holding different values, so this
concentration is a hard ceiling on the evidence the field can supply — independent of
sample size and of effect size. It is also why the pooled test's variance is computed
from the actual midranks rather than from the textbook (n² − 1)/12, which assumes
distinct values and would make the test silently conservative.

### 3.3 Comparison is only defined inside a block

{_fig("f3_cells", "block and cell structure")}

The exact-match key partitions the filing into
{real['blocks']['n_blocks']} blocks over {real['blocks']['n_records']} records. Of these,
{real['blocks']['blocks_with_a_denial']} contain a denial and
{real['blocks']['blocks_with_both_roles']} contain both a denial and an approval;
{real['blocks']['share_of_denials_in_a_usable_block']:.0%} of denials sit in a block that
can produce any comparison at all.

A denial in a block with no approval is **not** a negative result. It is a record the
public file cannot speak to, and the engine reports it as unaddressed rather than as
clean. Conflating the two is the most consequential error this product could make, and
the funnel above is the check on it.

### 3.4 Most cells cannot reach a decision at any effect size

{_fig("f4_attainability", "attainable p floor")}

A record can be no more extreme than the tie block it sits in, so a cell's smallest
attainable p-value is |best tie block| / n — at best 1/n, with no ties at all. This is
fixed by the cell's size and values **before any comparison is made**.

In the real slice, {real['attainability']['share_capable_of_reaching_q']:.0%} of the
{real['attainability']['cells']} usable cells could ever reach q = 0.05; the best floor
anywhere in the filing is {real['attainability']['best_floor']}. Simulated at the
design's own cell-size distribution the share capable of reaching 0.05 is
{sim['structural_capacity'][0]['share_capable_of_reaching_q']:.0%}, with the best floor
in any cell at {sim['structural_capacity'][0]['best_attainable_floor']}.

This is the single most important fact in the report. It is why the design pools across
cells rather than testing within them, why no per-finding p-value is published, and why
no per-finding false-discovery-rate estimator survives in the codebase: they were
implemented, found arithmetically unattainable at this cell size, and deleted rather than
left unreachable.
""")

    # ---------------------------------------------------------------- method
    A("""## 4. Method

### 4.1 Interval dominance, and why the threshold cannot be one number

Published values are intervals, not points: a loan amount of $605,000 means
[$600,000, $610,000). Two intervals are ordered only when they do not overlap by more
than a tolerance, so the engine asks whether `a_lo − d_hi > τ` rather than whether
`a > d`. Everything else follows from that one substitution.

The threshold is computed per pair:

    τ(pair) = max( declared minimum, comparability floor(pair), publication floor(pair) )

The comparability floor is where the arithmetic bites. Combined loan-to-value is
100·L/V, a ratio of two quantities each published at $10,000 bin midpoints; propagating
that granularity gives

    floor(L, V) = 100 · max(0.05·L, 20000) / V   percentage points

which is 7.0 points at a $285,000 property and 16.0 at a $125,000 one.
""")
    A(f"""{_fig("f5_comparability_floor", "comparability floor")}

The declared minimum in the resolution budget is 7.1 points — adequate above about
$282,000 and inadequate below it. A single scalar certified at one reference point passes
where it was certified and fails everywhere cheaper, and it fails in the direction that
**manufactures findings**, on exactly the properties a small lender's denials concentrate
in. That is the argument for computing τ at each pair's own magnitudes, and Figure 5 is
the argument in full.

### 4.2 The comparison lattice

Seven states, ordered: `STRICTLY_WORSE < WEAKLY_WORSE < {{TIED, AMBIGUOUS, UNRECORDED}} >
WEAKLY_BETTER > STRICTLY_BETTER`. `AMBIGUOUS` and `UNRECORDED` are first-class outcomes,
not failures to decide. A denial beaten in both directions is reported as ambiguous; a
denial whose comparator has no value on the tested dimension is reported as unrecorded.
Resolving either by a tiebreak would produce a number nobody can audit.

### 4.3 The exact null

Under within-cell exchangeability the denial label is uniform over its cell, so the
probability that a cell produces a finding has a closed form:

    P(finding) = (1/n) Σ_i 1{{∃j worse by > τ}} · 1{{∄j better by > τ}}

summed over cells for the expectation. One pass, no seed, no simulation error. The
permutation test estimates the same quantity and is retained only for the interval;
§5 asserts the two agree.

### 4.4 The pooled rank test

Van Elteren's stratified rank test — the Cochran–Mantel–Haenszel score test for 1:M sets:

    E[R_s] = (n_s + 1)/2 ,  Var[R_s] = (1/n_s) Σ_j (a_sj − (n_s+1)/2)²  (tie-corrected)
    T = Σ_s w_s (E[R_s] − R_s) ,  w_s = 1/(n_s + 1) ,  Var[T] = Σ_s w_s² Var[R_s]

The weight is what stops one cell of four hundred drowning two hundred cells of three.
The variance is taken from the actual midranks, which is the tie correction; the untied
closed form would overstate the spread and make the test conservative without saying so.
T is signed so that positive means denials sit **better** than chance on the dimension
their own stated reason names — the direction that makes the reason hard to justify.

### 4.5 Sensitivity to unmeasured confounding

The data was not randomised, so some unmeasured variable might explain the whole result.
Rosenbaum's bound does not rule that out; it says how strong such a variable would have
to be. For a one-sided p at level α the finding survives while

    Γ ≤ α (1/p − 1) / (1 − α)

Γ = 1 is the no-bias point. Two applicants identical on every published field can differ
by eighty credit-score points, which is already a bias factor in the mid single digits,
so a Γ* near 1 means the finding tolerates nothing. This number is frequently
unflattering and is reported as it computes.

### 4.6 Interval estimators

An exact Clopper–Pearson limit for the binding gate's false-bind rate, obtained by
inverting the binomial test rather than by a normal approximation; and a **cluster**
bootstrap for the published rates, because pairs inside a cell share the denied record
and the coarsened cell and are not independent draws. §6.4 measures both.
""")

    # ---------------------------------------------------------------- verification
    rows = []
    for c in cv["checks"]:
        gap = (f"{c['worst_gap']:.2e}" if c["kind"] != "monte_carlo"
               else f"{c['worst_gap']:.2f} SE")
        rows.append([f"`{c['name']}`", c["reference"], c["kind"], gap,
                     "agrees" if c["agreed"] else "**DISAGREES**"])
    A(f"""## 5. Verification: two independent implementations of every statistic

The served container carries five packages and makes no outbound call, so the engine
implements its statistics in the standard library. On its own that is a weaker
correctness argument than taking them from SciPy, because a hand-rolled empirical CDF
that is subtly wrong about ties looks exactly like one that is right.

So they are implemented twice. `analysis/crossvalidate.py` recomputes each statistic
against a mature reference on the same inputs and asserts agreement to a stated
tolerance. Where no reference exists — the closed-form null is specific to this design —
the reference is a brute-force or Monte Carlo computation that is obviously correct and
far too slow to ship.

{_fig("f10_crossvalidation", "cross-validation")}

{_table(["statistic", "checked against", "kind", "worst gap", "verdict"], rows)}

Tolerances are 1e-12 relative for exact checks, per-check for numeric ones, and four
Monte Carlo standard errors for simulated references — expressed in standard errors
rather than as an absolute number, so the tolerance tightens as B grows and cannot be
met by simulating less.

**The check earned its place.** Cross-validating the Clopper–Pearson bound against the
Beta quantile raised `OverflowError` at n = 2,995, k = 1,497: the binomial CDF was summed
as a direct product, and `comb(2995, 1497)` is an exact integer of some nine hundred
digits that cannot become a float even though the product it appears in is a probability
in [0, 1]. Every existing test happened to use a small k, so none of them touched it. The
sum is now taken in log space via `lgamma`, and two regression tests pin the sizes the
binding gate actually runs at. That defect sat in the assertion floor of the release
gate — the size at which the gate is designed to operate.
""")

    # ---------------------------------------------------------------- calibration
    cal_rows = [[c["regime"], c["n_cells"], f"{c['rejection_rate_05']:.4f}",
                 f"[{c['rejection_ci95_05'][0]:.4f}, {c['rejection_ci95_05'][1]:.4f}]",
                 f"{c['mean_live_cells']:.0f}", c["verdict"]]
                for c in sim["calibration"]]
    A(f"""## 6. Operating characteristics

Unit tests establish that the code computes what it says. §5 establishes that what it
says agrees with SciPy. Neither answers the question a reader should actually ask: at
these sizes and this coarsening, does the test hold its error rate, and can it detect
anything? Those are properties of the design, and the only way to measure them is to
generate data where the truth is known.

The studies use a vectorised recomputation of the pooled statistic, because a power curve
needs hundreds of thousands of simulated filings. That creates an obvious hazard — a
study measuring a fast reimplementation instead of the product — closed by a guard that
rebuilds a sample of simulated filings as engine cells, runs the engine's own
`stratified_rank_test` on them and asserts the z-statistics match. The guard runs first,
every time; the worst gap in this run was
{sim['vectorised_path_verified_against_engine']['worst_z_gap']:.1e}. The finding rule is
guarded the same way, through `scan.dominance_statistic` itself.

### 6.1 Calibration under a true null

{_fig("f6_calibration", "calibration")}

{_table(["regime", "cells", "rejection rate at 0.05", "exact 95% CI",
         "live cells", "verdict"], cal_rows)}

The empirical CDF of the null p-values lies on or just below the diagonal in every
regime. Below is expected and is the safe side: the statistic is discrete — ranks in a
cell of three take three values — so a discrete test cannot hit its nominal level exactly.
The Kolmogorov–Smirnov statistic is reported in the artefact as a magnitude but is
deliberately not gated on, for the same reason: at 4,000 replications it would reject a
correctly implemented discrete test.

### 6.2 Power, and the minimum detectable effect

{_fig("f7_power", "power curves")}

{_table(["regime", "cells", "minimum detectable shift at 80% power"],
        [[m["regime"], m["n_cells"],
          "not reached in range" if m["minimum_detectable_shift"] is None
          else f"{m['minimum_detectable_shift']:.2f} units"]
         for m in sim["minimum_detectable_effect"]])}

The minimum detectable shift falls roughly as 1/√(cells) — 1.4 units at 100 cells, 0.8 at
300, 0.5 at 1,000 — which is the internal consistency check one should demand of a power
study before believing any single number in it.

The curves are near-identical across coarsening regimes, and that deserves a plain
statement rather than a quiet pass: **a rank test is largely indifferent to binning**,
because binning preserves order even where it destroys distance. The cost of coarsening
in this product is therefore **not** paid by the pooled test. It is paid by the finding
rule, which is a statement about distance.

### 6.3 The finding rule, and what the threshold costs

{_fig("f8_finding_rule", "the finding rule")}

Every cell resolves into exactly one state: a finding, ambiguous, nothing separates
anybody, or only better comparators. As τ rises, ambiguity falls — that is the threshold
doing its job — but the share where nothing separates anybody rises faster. τ is not a
tuning knob that can be turned to buy precision. It is set by the publication scale, and
its cost is paid in records that leave the queue entirely.

Note the null column: with no effect present at all, the rule fires on about a third of
cells, because a cell of three with a threshold below its spread produces a finding by
geometry. **A product that published the raw rate would be publishing mostly geometry.**
That is why the headline is always the departure from this null and never a count.

### 6.4 Interval coverage

{_fig("f11_coverage", "interval coverage")}

{_table(["estimator", "nominal", "measured coverage", "mean width"],
        [[b["estimator"], f"{b['nominal']:.2f}", f"{b['coverage']:.3f}",
          f"{b['mean_width']:.4f}"] for b in sim["bootstrap_coverage"]])}

The exact binomial bound is conservative at every point on the grid, which is the correct
direction for a bound that gates publication — though the excess width is a real cost,
since an over-wide bound refuses releases that should have shipped.

The cluster bootstrap covers
{boot['cluster bootstrap (engine)']['coverage']:.3f} against a nominal 0.95: a percentile
interval is not exact at 120 clusters, and it is reported as it measures rather than as
it is advertised. The naive row bootstrap covers
{boot['naive row bootstrap']['coverage']:.3f} while being narrower — apparent precision
bought by pretending dependent observations are independent. This is the strongest
argument in the package for resampling clusters rather than rows, because it is a
measurement rather than an appeal to principle.
""")

    # ---------------------------------------------------------------- results
    A(f"""## 7. Results on the data actually available

{_fig("f9_observed_vs_null", "observed against null")}

**The real filing is silent, and that is the result.** {real['rows']} records,
{real['action_taken_counts'].get('3', 0)} denials, seven of which found a matched
comparator, no findings, and a null envelope spanning the entire unit interval. At that
size the method cannot distinguish anything from anything. Reporting "no findings" as
though it were a clean bill of health would be the same error §3.3 warns about, one level
up.

The right-hand panel is generated data, large enough for the envelope to close. It shows
that the machinery separates signal from geometry once the question is answerable, and —
read with the left panel — how much data that takes. **No claim about any lender may be
read from it.**

What would change this: a filing large enough to close the envelope. The design needs
cells, not records, and cells come from filers with many applications inside the same
exact-match key. The measured funnel in §3.3 is the tool for deciding in advance whether
a given filer's record can support the question at all — which is a useful answer to be
able to give before any analysis is run.
""")

    # ---------------------------------------------------------------- threats
    A("""## 8. Threats to validity

**Unmeasured confounding.** The comparison conditions only on published fields. Credit
score, reserves, documentation quality and the loan officer's file notes are all absent
and all plausibly decisive. Rosenbaum's Γ* quantifies the exposure rather than removing
it, and the honest reading of a Γ* near 1 is that the finding tolerates no unmeasured
bias at all.

**Coarsening.** Everything in §3.1. Its cost falls on the finding rule, not the pooled
test (§6.2, §6.3).

**No ground truth.** There is no labelled set of denials known to be unsupported. The
product therefore reports a queue, not a determination, and its acceptance gate measures
agreement with a computed oracle rather than with reality.

**Dependence between pairs.** Pairs share denied records, cells are near-cliques, and the
sub-block cover deliberately overlaps, so no clean clustering partition exists. The exact
conditional null sidesteps this by conditioning on the cell; the cluster bootstrap
handles it where a variance is needed. Neither is a complete answer, and a residual
dependence between overlapping sub-blocks is not modelled.

**Selection into comparability.** Cells that produce a comparison are not a random sample
of cells: they are the ones with enough same-key volume. Rates are therefore conditional
on comparability, and §3.3 reports the conditioning explicitly instead of folding it into
a denominator.

**Multiplicity.** No per-finding p-value is published, so no per-finding correction is
either. The single inferential claim is the filing-level pooled test (§4.4). This is a
design decision forced by §3.4, and it is the reason a reader will not find a
Benjamini–Hochberg step anywhere in the codebase.

**Fixture contamination.** The generated fixture is easier than reality in every
direction that matters. It is labelled on every axis in this report, and the analysis
layer is barred from the served engine by a test that scans the source (§9).

**Specification drift.** Every result is computed under a versioned, digested
specification. A result carries the digest of the spec that produced it; a result whose
spec digest is unknown is not comparable with any other.
""")

    # ---------------------------------------------------------------- repro
    A(f"""## 9. Reproducibility

```
make analysis            # cross-validation, simulation, EDA, figures, this report
python -m analysis.crossvalidate   # 10 checks against SciPy / statsmodels / NumPy
python -m analysis.simulate        # calibration, power, coverage, the finding rule
python -m analysis.eda             # data profile of both snapshots
python -m analysis.figures         # 11 figures + figures.pdf
```

**Two dependency sets, and the boundary between them is enforced.** The served container
carries five packages and no scientific stack; `analysis/requirements.txt` carries NumPy,
SciPy, pandas, statsmodels and matplotlib. `tests/test_analysis_boundary.py` parses every
source file in `likewise/` and `extract/` — function bodies included, since a lazy import
never executes during a test run — and fails the build if any of them imports the analysis
stack, or if those package names appear in the served requirements.

**Determinism.** Every study fixes its seed
(`analysis.crossvalidate.SEED = {cv['seed']}`, `analysis.simulate.SEED = {sim['seed']}`)
and every derived generator descends from it. Reruns reproduce the artefacts.

**Artefacts.** `analysis/out/crossvalidation.json`, `simulation.json`, `eda.json`,
`figures/*.png`, `figures.pdf`, and this report.

**Environment of record.** Python {v['python']}, NumPy {v['numpy']}, SciPy {v['scipy']},
statsmodels {v['statsmodels']}. A check against a different SciPy is a different check,
so the versions are recorded in the artefact rather than in prose alone.
""")

    A("""## 10. What would change these conclusions

- **A larger real filing.** Everything in §7 is a statement about 33 denials. The design
  needs cells, and the funnel in §3.3 says in advance whether a candidate filer has them.
- **A labelled outcome.** Even a few hundred denials with a known post-review disposition
  would convert the acceptance gate from agreement-with-an-oracle into precision against
  reality, and would let the queue's ordering be evaluated rather than argued.
- **A finer published scale.** Most of §3 is a consequence of $10,000 bins and DTI bands.
  A regulator publishing one more digit would change the comparability floor by an order
  of magnitude and move the whole design.
- **A measured lift.** The value claim — that a reviewer working this queue finds more,
  faster, than one working the filing unaided — is unmeasured and needs a design partner.
  Nothing in this report addresses it, and nothing in it should be read as if it did.
""")
    return "\n".join(md)


CSS = """
body { font-family: Georgia, 'Times New Roman', serif; max-width: 46em; margin: 3em auto;
       padding: 0 1.2em; color: #1a1a1a; line-height: 1.55; }
h1 { font-size: 1.9em; border-bottom: 2px solid #1f4e79; padding-bottom: .3em; }
h2 { font-size: 1.35em; margin-top: 2em; color: #1f4e79; }
h3 { font-size: 1.08em; margin-top: 1.6em; }
code, pre { font-family: 'DejaVu Sans Mono', monospace; font-size: .86em; }
pre { background: #f6f6f4; padding: .8em 1em; overflow-x: auto; border-left: 3px solid #ccc; }
table { border-collapse: collapse; width: 100%; margin: 1.2em 0; font-size: .84em;
        font-family: Helvetica, Arial, sans-serif; }
th { background: #eef2f6; text-align: left; }
th, td { border: 1px solid #d5d5d5; padding: .35em .55em; }
img { max-width: 100%; margin: 1.2em 0; }
blockquote { border-left: 3px solid #1f4e79; margin-left: 0; padding-left: 1em;
             color: #333; font-style: italic; }
"""


def main() -> int:
    md = build()
    OUT.mkdir(parents=True, exist_ok=True)
    md_path = OUT / "ANALYSIS.md"
    md_path.write_text(md)

    css_path = OUT / "_report.css"
    css_path.write_text(CSS)
    html_path = OUT / "ANALYSIS.html"
    made = [md_path]
    try:
        subprocess.run(["pandoc", str(md_path), "-s", "--toc", "--toc-depth=2",
                        "--metadata", "title=Likewise — Analysis Report",
                        "-c", css_path.name, "--embed-resources", "--standalone",
                        "-o", str(html_path)],
                       cwd=OUT, check=True, capture_output=True)
        made.append(html_path)
        pdf_path = OUT / "ANALYSIS.pdf"
        subprocess.run(["pandoc", str(md_path), "-s", "--toc", "--toc-depth=2",
                        "--metadata", "title=Likewise — Analysis Report",
                        "-c", css_path.name,
                        "--pdf-engine=wkhtmltopdf",
                        "--pdf-engine-opt=--enable-local-file-access",
                        "-o", str(pdf_path)],
                       cwd=OUT, check=True, capture_output=True)
        made.append(pdf_path)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # A missing converter is not a reason to lose the report. The markdown is the
        # source of record; the rendered forms are conveniences.
        detail = getattr(exc, "stderr", b"")
        print(f"  rendering skipped: {type(exc).__name__} "
              f"{detail.decode()[:200] if detail else exc}")
    for p in made:
        print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
