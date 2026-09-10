# Likewise — The Method

How the statistics work, why they are shaped this way, and what they can and cannot
support. Each section opens in plain language and then states the thing precisely.

Companion documents: [USER_GUIDE.md](USER_GUIDE.md) for using the product,
[DESIGN.md](DESIGN.md) for the software.

---

## 1. The estimand — what is actually being measured

Start with what this method is *not* measuring, because it disciplines everything else.

It does not estimate whether a lender discriminates. It does not estimate whether any
individual denial was wrong. It does not fit a model of the lender's underwriting and
look at residuals.

It measures one thing:

> Among a lender's denials, on how many does the **public record itself** fail to support
> the reason the lender gave — in the sense that an application the same lender approved,
> matched on everything the public record shows, was **not better** on that reason?

This is a statement about the *consistency of a filing with itself*. It requires no
assumption about unobserved credit quality to be well defined, which is the entire reason
for choosing it. Every method decision below follows from wanting an estimand that stays
meaningful when the confounders are unknowable.

## 2. Why matching, and not a model

The obvious approach is to fit a denial model on the published fields and look at large
residuals. Likewise deliberately does not do this, for three reasons.

**A fitted comparator set defeats the protected-class exclusion, and does so invisibly.**
Likewise never loads race or ethnicity. That protection is *syntactic* — it checks field
names. A propensity model or a learned ranker over the permitted features (income, loan
type, automated-underwriting system, conforming-limit flag, channel, occupancy, geography)
is a learned proxy for race, and a good one. The exclusion would be violated in substance
while passing every test written to enforce it.

**Exchangeability is defined by the cell.** The whole inferential argument (§7) rests on
being able to permute outcome labels *within* a group of genuinely interchangeable
applications. If group membership is itself a function of a model fitted on the outcome,
the null becomes conditional on an estimated object, and the design is back to needing
unconfoundedness — the assumption this design exists to avoid.

**The claim has to be checkable by the lender.** A lender must be able to reproduce or
rebut a finding from the published specification and the public file. "Given the vendor's
model" is not a claim anyone outside the vendor can check.

So comparability is **declarative**: a signed, versioned, digest-cited specification, never
fitted, never tuned to make a result look better. A learned re-ranker was considered and
rejected outright rather than deferred: it could only affect ordering, ordering is exactly
what the labelling census is powered to validate, and a component that cannot be evaluated
is proxy risk with no measured benefit.

## 3. Matching: cells, not neighbourhoods

### The plain version

To compare a denial against approvals, you first need a group of approvals that are "the
same kind of application". Likewise builds that group by requiring exact agreement on a set
of categorical fields (loan type, purpose, occupancy, lien status, geography, and so on)
and closeness on a set of numeric fields (income, loan amount, property value).

### The precise version, and a subtlety that matters

A tolerance relation — "within ±10%" — is **symmetric but not transitive**. If you define a
comparison group as *"everything within tolerance of this denial"*, you have built a
**neighbourhood** of that denial, not an equivalence class. Two approvals in that
neighbourhood may not be within tolerance of each other. Permuting the outcome label inside
a neighbourhood asserts something false: it assumes the records are interchangeable, and
they are not, because the group was constructed around one of them.

Likewise therefore defines cells by **bucket identity** over the exact-match key and the
banded numeric fields, using a lossless overlapping cover. Cells are blocks of a partition.
Membership does not depend on which record you started from. That restores a genuine
equivalence relation and with it exact within-cell exchangeability.

### What is in the key, and what was taken out

The key is chosen for comparability, and its cost is measured rather than asserted. On the
2025 national file, the key as specified matches 69.4% of testable denials with 34.4% in a
cell of ten or more; the numeric bands take that to 20.8% and 2.5%.

Two changes are worth recording because the reasoning generalises.

**Amortisation-family fields were removed.** `amortization`, `interest_only_payment`,
`balloon_payment` and `negative_amortization` cost nothing measurable in matching, and
their rare non-default values mark loans whose terms were changed *during processing* to
save a deal — which is downstream of the application. Matching on a post-treatment variable
is circular.

**Adding exact-match fields does not always reduce confounding.** This is the
counter-intuitive one. A cell exists only if it contains both a denial and an approval, so
the matched set is *selected on* within-cell heterogeneity in the unobserved index. With
the observed covariates fully controlled, the entire outcome difference must be carried by
what is unobserved. Conditional on surviving selection, adding observed controls
**concentrates** the unobserved confounding rather than diluting it. This is why the key is
justified by measured matching cost and post-treatment reasoning, not by "more controls is
more rigorous".

**Geography is hierarchical.** County first, then MSA/MD, then state crossed with a coarse
property-value stratum for non-metropolitan records. The level used is recorded on every
finding as `geo_level`, the null is stratified by level, and coarser levels are caveated. A
flat switch to MSA/MD was proposed and rejected: 14.9% of records fall into a single
non-metropolitan catch-all spanning 1,973 counties, and property value is a *tested*
dimension for the collateral code — so a comparator drawn from a different collateral
market would dominate by construction.

**Post-treatment fields are diagnosed per field, not globally.** A field whose values are
determined by the outcome cannot be matched on. But a global rule is the wrong instrument
in both directions: a strict disjointness test misses *partial* separation (denials 90% at
one value, approvals 5%) which then silently draws the whole matched set from a 5% sliver;
and with many small filers, chance disjointness is common enough that a strict test would
spuriously refuse roughly a third of them. So each field gets a diagnostic computed on the
analysis population: outcome association, overlap coefficient, a permutation p-value for
disjointness *given that filer's own sample size*, and the share of denials retained. It
refuses per field, with a reason.

## 4. Dominance: a partial order, not a tolerance

### The plain version

Once you have a denial and a set of comparable approvals, you ask whether any approval was
*worse* on the reason cited. "Worse" has to mean worse by enough to be a real difference,
and it has to mean worse without being better on something else that matters.

### The precise version

Dominance is stated as four clauses, kept separate on purpose:

1. **Weak dominance** on the tested dimension.
2. **Strictness at resolution** — the difference must exceed the decisive threshold for
   that pair, not merely have the right sign.
3. **Residual risk not better** — the comparator must not be strictly better, beyond
   tolerance, on any residual-risk dimension.
4. The conjunction must be **non-empty** — a finding cannot be produced by a vacuous
   `all()` over zero dimensions.

Crucially, the tested dimension is **not** tolerance-matched. Matching a dimension and then
testing it are contradictory operations. Dominance replaces the tolerance on the tested
dimension.

### Interval comparison

Published values are coarsened, and some are bands rather than numbers. Comparing a band to
a number as if both were points is wrong. Every published value maps to the interval it
actually denotes:

```
<20%      → [0, 20)          integer k → [k−0.5, k+0.5]
20%-<30%  → [20, 30)         50%-60%   → [50, 60]
30%-<36%  → [30, 36)         >60%      → (60, ∞)
```

With `higher_is_worse` and threshold τ, for approved interval `[a_lo, a_hi]` and denied
`[d_lo, d_hi]`:

```
approved strictly worse beyond τ   ⟺  a_lo − d_hi > τ
approved strictly better beyond τ  ⟺  d_lo − a_hi > τ
otherwise                          ⟹  below_resolution — the order is not identified
margin                             =  a_lo − d_hi
```

This reduces exactly to the numeric rule inside the reported integer window, needs no new
dimension type, keeps the threshold in its declared unit, and is correct at every boundary:
`49` against `50%-60%` yields 0.5 points and is **not** decisive at τ = 1.0; `43` against
`>60%` yields 16 points and is.

**A rank-based alternative was considered and withdrawn.** Comparing published bands by
ordinal rank looks attractive because it makes far more debt-to-income denials "usable".
But one rank step is 1 point inside 36–49 and 10 points at `[50, 60]`, so a rank rule would
declare `50%-60%` against `>60%` decisive when the true difference might be 0.02 points —
exempting the largest denial reason in the country from the resolution budget, which is the
single safeguard the whole design rests on.

**What interval dominance concedes, and the rank rule hid.** A denial at `>60%` has
`d_hi = ∞` and can never be dominated. A denial at `50%-60%` needs a comparator with
`a_lo > 61`, and none exists. **About 81.5% of debt-to-income denials are structurally
incapable of producing a finding**, at any sample size, under any correct rule. Debt-to-
income is the largest denial reason in the country, at roughly 32% of all denials. The
public record replaces the number with a band precisely where a lender would cite it. That
is a limitation of the data, and no recode changes it.

## 5. Resolution: why the threshold is per pair

### The plain version

How small a difference counts as real depends on how big the numbers are. The published
loan amount is a $10,000 bin midpoint. On an $800,000 house, that binning moves the
loan-to-value ratio by about a percentage point. On a $125,000 house, it moves it by
sixteen. One threshold for the whole country is therefore wrong nearly everywhere.

### The precise version

For a ratio of two binned quantities, the comparability floor is

```
floor(L, V) = 100 · max(0.05·L, $20,000) / V     percentage points
```

At the original reference (L = $270,000, V = $285,000) this is 7.02 points. At
V = $175,000 it is 11.43. At V = $125,000 it is 16.00. A declared threshold of 7.1 points
is violated for every pair below roughly **$282,000 in property value**.

This defect was live and invisible for a specific reason worth recording: the only real
filer scanned during the build was in San Diego, median property value $805,000, where 0.5%
of records fall below the boundary. One expensive market concealed a defect affecting most
of the country. The direction is adverse — findings are manufactured preferentially in
low-value markets, which will look like a protected-class result while being an artefact.

The applied threshold is therefore

```
τ(pair) = max( declared_minimum , comparability_floor(pair) , publication_floor(pair) )
```

evaluated at the pair's own magnitudes and emitted on the finding. The value in the
specification becomes a declared *minimum*, not the operative number.

Two further corrections belong here.

**An unmatched dependency contributes unbounded slack, not zero.** The original gate
skipped any dependency absent from the control set, reasoning that an unmatched field
"contributes no matching slack". The reverse is true. Property value is not a control
feature, so its contribution was silently zeroed — and a within-cell property-value spread
of $50,000 moves loan-to-value by 16.6 points. Worse, it created a perverse incentive:
*removing* a field from the control set made the gate easier to pass. An unmatched
dependency now contributes its empirical within-cell spread, or fails the gate.

**The publication floor applies only to a dimension declared derived.** For a *reported*
loan-to-value ratio, the $10,000 binning of the components does not propagate — the lender
reports the ratio of the true quantities, not the ratio of the bins.

All of this is enforced at the **startup gate**: the service validates the specification
against the loaded snapshot's property-value deciles and refuses to bind its port if a
declared threshold is finer than the data can resolve.

## 6. Ranking inside a cell

### The plain version

Inside a cell, sort the applications by the tested dimension and see where the denial
lands. If the denial sits at the good end while approvals sit at the bad end, that is the
signal.

### The precise version

**The p-value is the empirical CDF, not the rank over n.** For `higher_is_worse`:

```
p = #{ j : v_j ≤ v_obs } / n
```

This is exact under arbitrary ties and identical to `rank/n` when values are distinct. The
midrank is retained for display only.

Why this matters: the shipped implementation returned `rank/n` computed from a *midrank*,
which is anticonservative under ties — and ties are the common case here, not the
exception. In a cell of ten with a five-way tie at the best value, the reported p was 0.30
against a true 0.50. Understated by a factor of 1.7.

**The attainable minimum p is a property of the tie structure, not of n.**

```
min_p = (size of the best tie block) / n
```

Cell power is computed from the realised multiset, not from cell size. A cell of forty in
which everything is tied has no power at all, and reporting it as adequate because n ≥ 10
is simply wrong.

**Ranks are computed on values coarsened to the pair's own decisive threshold.** Ranking
loan-to-value to 0.001 points while declaring 7.1 points the smallest measurable difference
lets a denial reach rank 1 on an ordering the design says is not a measurement. Coarsening
collapses most cells to two or three levels. That collapse is the honest answer, not a
defect in the fix.

## 7. The inferential claim, and why it sits at scan level

This is the most important section in the document.

### Two things went wrong, in opposite directions

**The null was built from the wrong cells.** The reference distribution was assembled only
from cells that had *already produced a finding* — downstream of both the dominance filter
and disclosure suppression. Under a true null (labels assigned uniformly within cells), the
reported p came out at or below 0.05 with probability **1.00** at cell size 4, 0.60 at 6,
and 0.27 at 10. Nominal is 0.05. The scan-level channel had close to 100% type-I error.

**Per-finding false-discovery control is arithmetically unattainable.** Cell power was
tested as `1/n ≤ q`, which is the condition for a *single* test. Inside a family of size
*m*, the requirement is `n ≥ 1/(q·f)` for Benjamini–Hochberg or a permutation FDR, and
`H_m/(q·f)` for Benjamini–Yekutieli, where `H_m = ln m + γ`. At q = 0.10 and an expected
true-positive fraction f = 0.10, that is n ≥ 100 or n ≥ 800 — against a power floor of 10.
Simulated under a *perfect* alternative at n = 12 and m ≈ 450, both estimators returned
**zero** discoveries. The per-finding channel had close to 0% power.

Read together: one channel could not fail to reject, the other could not reject.

### The correction

**The null is built over every matched, testable denial** — before the dominance filter,
before suppression. Suppression governs disclosure, not inference.

For the primary statistic no Monte Carlo is required. For a cell with values *v₁…vₙ* and
threshold τ, the exact within-cell probability of producing a finding under the null is

```
P_H0(finding in this cell) = (1/n) · Σᵢ 1{∃j: v_j > v_i + τ} · 1{∄j: v_j < v_i − τ}
```

Summed over cells, this gives the exact expected finding count under within-cell
exchangeability in a single O(Σn²) pass — no replicate count, no seed, no wall-clock
exposure.

**Per-finding significance is abandoned.** Findings carry no q-value, and the schema no
longer has a field that a renderer could use to imply one. What they carry is a
prioritisation: margin, margin ratio, midrank, cell size, block degree, geography level and
Γ\*.

**The inferential instrument becomes a pooled stratified rank test** — van Elteren,
equivalently the Cochran–Mantel–Haenszel score test for 1:M matched sets — calibrated by
the same permutation:

```
E[R_s]   = (n_s + 1) / 2
Var[R_s] = (1/n_s) · Σ_j ( a_{s,j} − (n_s + 1)/2 )²          exact, tie-corrected
T        = Σ_s w_s ( E[R_s] − R_s ),      w_s = 1 / (n_s + 1)
```

Cells of size 2 and 3 contribute — which is where the power comes from, since those cells
are the bulk of the matched set. Simulated power to detect a 0.10 excess at one-sided
α = 0.05 is **0.79 at 400 cells of size 3** and **0.92 at 400 cells of size 11**, against
essentially zero filers under the per-finding design.

### The claim, stated exactly

> Across this filer's denials, the dimension the filer's own stated reason names does not
> order the decisions.

It is a scan-level claim about a filer. It is not a claim about an application.

### One obstruction that does not go away

Denial reason codes are observed **only on denied records**, so any label permutation must
carry the reason code along with the label — and reason codes are *caused by* the record's
own covariates. The permutation therefore tests a composite hypothesis and **cannot
separate "denied the wrong application" from "cited the wrong reason"**. This is stated in
the limitations and on the scan record; it is not fixable within this data.

## 8. Sensitivity to unmeasured confounding

### The plain version

The obvious objection to any matched-pair result is: *the two applicants differed on
something you can't see.* Rosenbaum's Γ turns that objection into a number. Γ = 3 means "an
unmeasured factor would have to make one applicant three times more likely to be denied
before this result dissolves". You then ask whether such a factor is plausible.

### The precise version

For midrank *r* in a cell of *n* under a bias bound Γ, the worst-case one-sided p is
`Γr / (Γr + n − r)`. Inverting at level α:

```
Γ* = α (1/p − 1) / (1 − α)
```

At α = 0.10: p = 0.10 → **Γ\* = 1.00**; p = 0.05 → 2.11; p = 0.02 → 5.44; p = 0.01 → 11.0.

**Every finding at a power floor of n = 10 had Γ\* = 1.00 — no robustness to any unmeasured
bias whatsoever.** Γ\* = 5 requires a cell of at least 46.

Coarsening imposes a ceiling that no sample size removes. Once a dimension is coarsened to
a discrete published scale, the smallest tie-correct p is the population share *f* of the
best level:

```
Γ_max = α (1/f − 1) / (1 − α)
```

This is approximately **2.1 for debt-to-income over the published bands**, and **below 1
for loan-to-value coarsened to its own decisive threshold**.

Both quantities are required outputs. **Γ\* is published on every finding.** **Γ_max is a
property of the specification and is checked at the startup gate**: a dimension whose Γ_max
falls below the benchmark is not testable at the chosen level, and the service refuses to
start rather than producing findings that cannot survive any unmeasured confounding at all.

**Calibrating the benchmark.** Under a normal-latent model, `d = √2·Φ⁻¹(AUC)`. With an
observed AUC around 0.70 on the published fields against a full-information underwriting
benchmark near 0.88, the unobserved component contributes roughly 1.49 standard deviations
— that is Γ ≈ 11. Two applications identical on every published field and 80–100 FICO
points apart is unremarkable, and that alone is Γ in the mid single digits.

If Γ_max sits below the benchmark for both testable codes at honest resolution, **that is
the finding**, and it belongs at the top of the product document rather than in a footnote.

## 9. Negative controls

A control answers the question the p-value cannot: *does this engine fire specifically on
the cited reason, or on anything?*

**The primary control is a paired discordance test, not a ratio.** The original ratio
control substituted a literal constant for a bootstrap draw whenever the placebo rate was
zero — so that constant, not the data, determined the bound the gate read
on. It is replaced by: let *b* be denials where the cited dimension fires and the placebo
does not, *c* the reverse; exact binomial on `b/(b+c) > 0.5`. Stable, no confidence-interval
hack, and more powerful.

**Both arms are restricted to pairs where both dimensions are informative.** Otherwise the
arms use dimensions with radically different availability — loan-to-value is adjudicable on
96.3% of collateral-code denials, debt-to-income on 5.1% of matched pairs under the numeric
rule — and the control cannot distinguish specificity from measurability. It would pass for
the wrong reason.

**A second placebo holds measurability fixed by construction:** permute the *cited reason
code* across denials within a stratum, drawing from that stratum's own empirical reason
distribution, and re-run the identical engine. This breaks the reason-to-dimension link
while preserving every correlation in the data.

**Controls run pooled nationally, not per scan.** "Powered" was originally coded as
n ≥ 30; the honest requirement is about 118 per arm unpaired, or 68 discordant pairs
paired. A validity check is not a per-filer claim, and 563,148 testable denials nationally
solves the power problem outright.

## 10. Multiplicity, and the sweep

There is no per-finding multiplicity correction, because there are no per-finding
p-values to correct. Had one been kept it would have had to be **Benjamini–Yekutieli**,
valid under arbitrary dependence at a cost of `H_m = ln m + γ`, rather than
Benjamini–Hochberg, which is not valid under this dependence structure and silently
multiplies the rejection count. Both estimators were implemented, neither was reachable
from any code path, and both were removed rather than left as a fallback that could not
be invoked.

**The selection problem is stated rather than hidden.** Every coverage-related
configuration change in this design was chosen on the national file by comparing candidates
on matched and powered fraction — which is the denominator of the headline. That is model
selection with an unstated degrees-of-freedom cost, on the population the product will be
sold against.

The discipline: **select on one filing year, freeze and sign, run confirmatory on the
next.** Where the newer year must be used for selection, every scan of it is labelled
`exploratory` and says so on every finding. **The full selection grid — every configuration
tried, not only the winner — is part of the pre-registration artefact**, so the search space
is auditable rather than asserted.

And the sweep is a hard requirement at the API: findings are not servable without the
exceedance curve across the tolerance grid, with the null recomputed at each grid point. A
reader must be able to see whether the threshold was chosen to produce the result.

## 11. Coverage — the limitation that shapes everything

A comparison cell exists only where a filer has volume in one geography × key combination.
So the method is structurally blind to thin markets, non-metropolitan lending, the broker
channel, manual underwriting, small filers, and partially exempt filers.

That is precisely where underwriting discretion is largest. **The sampling frame is
anti-correlated with the risk it is meant to prioritise.** Every scan therefore publishes a
coverage profile — matched fraction and finding rate by county-volume decile, automated-
underwriting presence, submission channel, loan purpose and complete-case status, plus the
effective relative window by income and loan-amount decile — so a buyer is told which half
of their book the product cannot see.

Related: under the EGRRCPA partial exemption, insured depositories and credit unions below
the origination thresholds omit denial reason, loan-to-value, debt-to-income and property
value — every input the reason engine uses. The addressable panel is the non-exempt subset,
and exempt records get their own denominator rather than being quietly dropped.

## 12. Validation

**A true-null fixture.** A synthetic scan with labels assigned uniformly at random within
cells must produce a p-value distribution indistinguishable from uniform. It is about thirty
lines of test code, and it would have caught three of the five defects above on the first
day. It is now a standing test.

**Mutation testing against a published catalogue.** A kill-rate gate of 0.90 against a
pre-registered, published list of mutants — published, because a kill rate against a
private catalogue is unreviewable. The mutants are drawn from real defects in this
project's own history: flip a direction; `<` → `<=` in the resolution test; swap the
approved and denied keys; drop the minimum-absolute floor from the band; negate a margin;
`all()` → `any()`; `min` → `max` as the tolerance reference; delete the empty-conjunction
guard; break midranks to an arbitrary tie-break; drop the cell-power floor.

**Metamorphic properties over the full candidate set.** Swapping approved and denied
inverts the margin sign wherever the comparison is resolved, and flips the outcome. Where
it is not resolved the margin reported is a slack -- how far the pair is from being
orderable -- and slack does not invert: measured across the same two intervals, the two
directions sum to minus their combined width. The test asserts that identity exactly.

That distinction is not pedantry. The property was originally written as plain inversion
on every pair and held only because every reported half-width was zero in the
specification the suite was running; combined loan-to-value is published to three
decimals, and under the standard in force the two margins differ by exactly four times
that half-width. Adding a constant to both property values changes nothing. Rounding both
incomes to the published bin changes no outcome. A null in a tested dimension lands in the
incomplete bucket and never in findings.

**The label instrument is public-record rebuttal, not comparability.** A labeller sees both
records' full rows — not only the matched fields — and answers one question with a forced
justification: *naming a specific field, is there a difference visible in the published
record and outside the matched field list that a fair-lending examiner would accept as a
legitimate reason for the different outcome?* Two labellers independently; disagreements go
to a blinded third adjudicator. Agreement statistics are computed on pre-adjudication
labels and rebuttal rates on post-adjudication labels, and which is which is stated wherever
a number appears. A rebuttal field that recurs is a field that belongs in the matching key —
the instrument feeds the pipeline.

Gwet's AC1 is the primary agreement statistic rather than Cohen's κ, because κ is tunable by
the sample choice: at natural prevalence 0.05 with raw agreement 0.95, κ = 0.47 and a good
instrument fails a 0.60 gate; at boundary-oversampled prevalence 0.50 with agreement 0.80,
κ = 0.60 exactly and a worse instrument passes. AC1 has the opposite failure at low
prevalence, so the agreement gate is applied on the **boundary arm**, where prevalence is
engineered near 0.5.

## 13. Known limits, collected

- **The inferential claim is scan-level, not per-finding.** A finding is a place to look.
- **The permutation null tests a composite hypothesis** and cannot separate "denied the
  wrong application" from "cited the wrong reason".
- **The sampling frame is anti-correlated with the risk it prioritises** (§11).
- **About 81.5% of debt-to-income denials cannot produce a finding**, at any sample size,
  under any correct rule (§4).
- **Sensitivity to unmeasured confounding is bounded above by the coarsening** — Γ_max ≈ 2.1
  for debt-to-income, below 1 for loan-to-value at its own threshold (§8).
- **Same-applicant resubmission may be unidentified rather than filtered.** Once the
  blocking key is accounted for, the exclusion signature reduces to "identical property
  value, same income bin", which fires on legitimate pairs and deletes the best-matched
  comparisons in the scan. Whether it carries information is measured against
  approved-to-approved pairs in the same blocks, where resubmission cannot explain a match,
  and published as a ratio rather than assumed.
- **Collateral is not loan-to-value**; denial reasons are first-sufficient, unranked and
  non-exhaustive; income is not fully commensurable across the pair; reason-coding is
  gameable.
- **A deterministic wrong answer reproduces perfectly.** Reproducibility is a property of
  the pipeline, not a quality result.

## 14. Open questions

**Protected-class analysis is excluded**, which forecloses any fair lending claim. The
method is correct under every resolution of that question, and there is an explicit guard so
that no code path introduces a protected-class feature by accident.

The most informative thing that could be done without relaxing the exclusion is a
**proxy-strength diagnostic**: fit a classifier predicting a protected attribute from the
permitted feature set and publish *only its AUC*. That measures how much protected-class
information the matching key already carries, without using any of it to decide anything,
and it directly answers the concern that findings will be geographically distributed in a
way that looks like a protected-class result. It requires loading attributes the pipeline
currently refuses at ingest, so it is a policy decision rather than an engineering one.

**A regression discontinuity at the conforming loan limit, at 80% loan-to-value, and at the
qualified-mortgage threshold** is a real quasi-experiment available on free public data.
Notably, one field currently in the key — the conforming-limit flag — is a deterministic
function of loan amount, county, units and year, so it adds nothing beyond fields already
matched on *and* deletes precisely the pairs that straddle the limit. Removing it is
scheduled.
