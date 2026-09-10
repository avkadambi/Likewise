# The Method

Everything Likewise does statistically, and why.

**Part One assumes no mathematics.** If formulas are not your thing, read Part One and
stop — you will understand what the product claims, what it cannot claim, and why. Part Two
states the same things precisely for whoever implements or audits them.

| | |
| :--- | :--- |
| Document | Method reference |
| Product | Likewise |
| Author | Arun Kadambi |
| Date | 9 September 2026 |
| Specification in force | materiality 1.4.0 |

---

# Part One — Without mathematics

## 1. The question

Every year, mortgage lenders in the United States have to publish a record of every
application they received: whether they approved it, and for the ones they denied, a coded
reason. Anyone can download this. It is called the HMDA public file.

Likewise reads one lender's own filing and asks one question, once per denial:

> Among the applications this lender **approved**, is there one that looks the same as this
> denied application on everything the public record shows, and is **no better** on the
> specific thing the lender said it denied for?

If a lender denies an application "for collateral" and, in the same county and the same
loan programme, approves one with a *worse* loan-to-value ratio, that is worth a look.

That is the whole product. Everything below exists to make that question mean something.

## 2. Why it is harder than it sounds

Four problems, and each one shapes a design decision you will meet in the code.

**The published numbers are deliberately blurred.** The regulator rounds them to protect
borrowers' privacy. Loan amounts and property values are published at the midpoint of a
$10,000 bin. Incomes are rounded to the nearest $1,000. Debt-to-income is an exact number
only between 36% and 49%; outside that window the file just says "over 60%".

So when two records look different, you have to ask whether they *are* different or whether
the rounding invented the gap. And the answer depends on how big the numbers are: a $10,000
bin barely moves the loan-to-value ratio on an $800,000 house and moves it enormously on a
$125,000 one. This is why the product computes a different "how big does a difference have
to be" threshold for **every single pair**, rather than using one number.

**The file does not contain what actually decides a mortgage.** No credit score, no
reserves, no employment history, no appraisal narrative. Two applications that look
identical to this engine can be obviously different to an underwriter. This is why no
individual result is ever presented as a conclusion, and why the engine reports a number
(§8) saying exactly how much hidden difference it would take to explain a result away.

**Comparing things is trickier than it looks.** If you say "compare this denial to every
approval within 10% of its income", you have built a group *around that one record*. The
approvals in it may not be within 10% of each other. That sounds pedantic and it is not —
the entire statistical argument depends on the records in a group being interchangeable,
and in a group built around one of them they are not. Groups are built a different way (§3).

**Only the lender's own file is in view.** The comparison is not against the market. It
asks whether the filing is consistent *with itself*. That is a narrower claim and it is
deliberate: it needs no assumption about anything the file does not carry.

## 3. How it works, in order

**Grouping.** Put applications into groups where every member is genuinely comparable —
same county, same loan purpose, same occupancy, same lien position, and similar income and
loan size. Group membership never depends on which record you started from.

**Comparing.** Within a group, take each denial and compare it against the approvals on the
dimension the lender's own stated reason names. Because published values are blurred, the
comparison is between *ranges* rather than points. If the ranges overlap, the honest answer
is "the public record does not say which is worse", and that is a real answer, not a
missing one.

**Deciding.** A denial is flagged only if some approval is clearly worse on the cited
reason — clearly meaning by more than that pair's own threshold — and no approval is better
on the other things that matter.

**Ranking.** Flagged denials are put in an order for a human to work through. The order is a
triage order. It is not a ranking by confidence, and it deliberately carries no
significance score.

**Checking.** Two checks run before anything is published. The **sweep** re-runs everything
across a range of threshold values and publishes the curve, so anyone can see whether the
result only exists at one convenient setting. The **controls** re-run the identical engine
against a reason the lender did *not* cite; if it fires just as often on the placebo, the
engine is detecting noise and nothing is published.

## 4. What the result means, and what it does not

**A single flagged denial means:** on the public record alone, this lender approved
something comparable that was no better on the reason they gave for this denial. Go read the
file.

**It does not mean** discrimination, a violation, or even a mistake. It is not a claim about
the applicant. Something outside the public record may explain it completely, and usually
will.

The only *statistical* claim the product makes is made once per lender, over all their
denials at once: *across this filer's denials, the dimension their own stated reason names
does not order the decisions.* That is a statement about a filing, not about an application.

Three things follow, and they are in the product, not the small print:

- Every result carries `evidentiary_status: screening_hypothesis` in the data.
- No result carries a p-value or a significance score, because none is defensible per pair.
- Every scan publishes which parts of the lender's book the method **cannot see** (§11).

## 5. The uncomfortable finding

When the corrected method was run, results came out *below* what pure chance would produce.
That means the lenders' stated reasons order their decisions **more** consistently than
random relabelling would — the opposite of what the product was built expecting.

Read that carefully, because two very different conclusions are available and only one is
supported:

- **Supported:** the public record mostly supports lenders' stated reasons.
- **Not supported:** inconsistent underwriting does not happen.

The second does not follow, and §8 explains why with a number: the regulator's rounding
destroys the resolution needed to see it. You would get this same result from a scrupulous
lender and a careless one alike. Absence of evidence, and the engine can say precisely why
the evidence would be absent either way.

That distinction is the single most important thing to understand about this product.

---

# Part Two — Precisely

## 6. The estimand

This is not an estimate of whether a lender discriminates, nor of whether any individual
denial was wrong, nor a model of underwriting read through its residuals. What is measured:

> Among a lender's denials, on how many does the public record itself fail to support the
> stated reason — in the sense that an application the same lender approved, matched on
> everything the public record shows, was not better on that reason?

This is a statement about the internal consistency of a filing. It is well defined without
any assumption about unobserved credit quality, which is the entire reason for choosing it.

## 7. Matching, not modelling

The obvious approach — fit a denial model on the published fields and look at large
residuals — is rejected for three reasons.

**A fitted comparator set defeats the protected-class exclusion invisibly.** Likewise never
loads race or ethnicity. That protection is *syntactic*: it checks field names. A propensity
model or learned ranker over the permitted features (income, loan type, automated
underwriting system, conforming-limit flag, channel, occupancy, geography) is a learned
proxy for race, and a good one. The exclusion would be violated in substance while passing
every test written to enforce it.

**Exchangeability is defined by the cell.** The inferential argument (§11) rests on
permuting outcome labels within a group of interchangeable applications. If group membership
is a function of a model fitted on the outcome, the null becomes conditional on an estimated
object, and the design is back to needing unconfoundedness — the assumption it exists to
avoid.

**The claim must be checkable by the lender.** They must be able to reproduce or rebut a
result from the published specification and the public file. "Given the vendor's model" is
not checkable by anyone outside the vendor.

Comparability is therefore **declarative**: a signed, versioned, digest-cited specification,
never fitted. A learned re-ranker was considered and rejected outright rather than deferred —
it could only affect ordering, ordering is exactly what the labelling census is powered to
validate, and a component that cannot be evaluated is proxy risk with no measured benefit.

## 8. Cells, not neighbourhoods

A tolerance relation — "within ±10%" — is symmetric but **not transitive**. Defining a
comparison group as "everything within tolerance of this denial" builds a *neighbourhood*,
not an equivalence class: two approvals in it may not be within tolerance of each other.
Permuting the outcome label inside a neighbourhood asserts something false.

Cells are therefore defined by **bucket identity** over the exact-match key and the banded
numeric fields, using a lossless overlapping cover. Cells are blocks of a partition;
membership does not depend on the starting record. This restores a genuine equivalence
relation and with it exact within-cell exchangeability.

**Measured cost of the key.** On the 2025 national file the key as specified matches 69.4%
of testable denials with 34.4% in a cell of ten or more; the numeric bands take that to
20.8% and 2.5%.

**A counter-intuitive property.** A cell exists only if it contains both a denial and an
approval, so the matched set is *selected on* within-cell heterogeneity in the unobserved
index. With observed covariates fully controlled, the entire outcome difference must be
carried by what is unobserved. Conditional on surviving selection, adding observed controls
**concentrates** unobserved confounding rather than diluting it. The key is therefore
justified by measured matching cost and post-treatment reasoning, never by "more controls is
more rigorous".

**Enforced since specification 1.4.0:** a tested dimension may not appear in the blocking
key, the exact-match set or the bands (validation rule 8). Matching a dimension and then
testing it are contradictory operations. The design had asserted this for some time and
nothing checked it.

## 9. The comparison lattice

Each dimension places a pair on a chain:

```
STRICTLY_WORSE < WEAKLY_WORSE < {TIED, AMBIGUOUS, UNRECORDED} > WEAKLY_BETTER > STRICTLY_BETTER
```

Not being ordered is three answers, not one, and the distinction only becomes load-bearing
under a rule of precedence:

| | Meaning |
| :--- | :--- |
| `TIED` | the order IS identified — the records sit at the same value |
| `AMBIGUOUS` | the published intervals overlap, so the record does not order them |
| `UNRECORDED` | the record does not speak to this dimension at all |

Under flagging all three fail the existential strict clause and nothing is emitted, so
collapsing them is harmless. Where a prior decision *governs*, a tie is the strongest
possible a-fortiori bind while a silence is a premise nobody established — and an
implementation that reads them as one value binds in both cases. See
[reference/PRECEDENCE.md](../docs/PRECEDENCE.md).

`STRICTLY_WORSE` means the *approved* record is worse than the denied one by more than the
pair's threshold — the direction that makes the stated reason hard to justify.

A published value maps to the interval it actually denotes:

```
<20%      → [0, 20)          integer k → [k−0.5, k+0.5]
20%-<30%  → [20, 30)         50%-60%   → [50, 60]
30%-<36%  → [30, 36)         >60%      → (60, ∞)
```

With `higher_is_worse` and threshold τ, for approved `[a_lo, a_hi]` and denied
`[d_lo, d_hi]`:

```
strictly worse    ⟺  a_lo − d_hi > τ
strictly better   ⟺  d_lo − a_hi > τ
weakly worse      ⟺  0 < a_lo − d_hi ≤ τ
weakly better     ⟺  0 < d_lo − a_hi ≤ τ
otherwise             unordered — TIED if both are the same point, else AMBIGUOUS
margin             =  a_lo − d_hi
```

**A rank-based alternative was rejected.** Comparing published bands by ordinal rank makes
far more debt-to-income denials "usable", but one rank step is 1 point inside 36–49 and 10
points at `[50, 60]`. A rank rule would declare `50%-60%` against `>60%` decisive when the
true difference might be 0.02 points — exempting the largest denial reason in the country
from the resolution budget, which is the single safeguard the design rests on.

**What interval dominance concedes.** A denial at `>60%` has `d_hi = ∞` and can never be
dominated. One at `50%-60%` needs a comparator with `a_lo > 61`, and none exists. **About
81.5% of debt-to-income denials are structurally incapable of producing a result**, at any
sample size, under any correct rule. Debt-to-income is the largest denial reason in the
country at roughly 32% of all denials. This is a limitation of the data and no recode
changes it.

**Incomparability is reported, never absorbed** (`report_incomparable` in the
specification). Folding it into "no finding" would report a silence as an absence of a
problem.

## 10. Resolution: the per-pair threshold

For a ratio of two binned quantities the comparability floor is

```
floor(L, V) = 100 · max(0.05·L, $20,000) / V     percentage points
```

7.02 points at the original reference (L = $270,000, V = $285,000), **11.43 at
V = $175,000, 16.00 at V = $125,000**. A declared threshold of 7.1 points is violated for
every pair below roughly **$282,000 in property value**.

This was live and invisible for a specific reason worth recording: the only real filer
scanned during the build was in San Diego, median property value $805,000, where 0.5% of
records fall below the boundary. One expensive market concealed a defect affecting most of
the country — and the direction is adverse, manufacturing results preferentially in
low-value markets, which would look like a protected-class result while being an artefact.

The applied threshold is therefore

```
τ(pair) = max( declared_minimum , comparability_floor(pair) , publication_floor(pair) )
```

evaluated at the pair's own magnitudes and emitted on the result. The specification value is
a declared *minimum*, not the operative number.

Two further corrections belong here. **An unmatched dependency contributes unbounded slack,
not zero** — the original gate zeroed any dependency absent from the control set, which
created a perverse incentive where *removing* a field made the gate easier to pass. And **the
publication floor applies only to a dimension declared derived**; for a reported ratio the
binning of the components does not propagate.

Since 1.4.0 the composition is a **named resolution model** (`strictest`, `declared_only`,
`publication_only`) selected in the budget specification. A closed set rather than a callable,
deliberately: an arbitrary function in a signed artifact is neither reviewable nor comparable
by digest.

All of it is enforced at the **startup gate**, which validates against the loaded snapshot's
property-value deciles and refuses to bind the port on failure.

## 11. Inference

### Two failures, in opposite directions

**The null was built from the wrong cells.** The reference distribution was assembled only
from cells that had already produced a result. Under a true null the reported p came out at
or below 0.05 with probability **1.00** at cell size 4, 0.60 at 6, 0.27 at 10.

**Per-finding false-discovery control is arithmetically unattainable.** Cell power was
tested as `1/n ≤ q`, the condition for a *single* test. Inside a family of size *m* the
requirement is `n ≥ 1/(q·f)` for Benjamini–Hochberg, `H_m/(q·f)` for Benjamini–Yekutieli —
n ≥ 100 or ≥ 800 at q = 0.10, f = 0.10, against a median cell of three. Simulated under a
*perfect* alternative at n = 12 and m ≈ 450, both returned **zero** discoveries.

One channel could not fail to reject; the other could not reject.

### The correction

**The null is built over every matched, testable denial** — before the dominance filter,
before disclosure suppression. Suppression governs disclosure, not inference.

**The expectation is computed exactly.** For a cell with values *v₁…vₙ* and threshold τ:

```
P_H0(finding in this cell) = (1/n) · Σᵢ 1{∃j: v_j worse than v_i by > τ}
                                      · 1{∄j: v_j better than v_i by > τ}
```

Summed over cells this is the exact expected count under within-cell exchangeability, in one
O(Σn²) pass — no replicate count, no seed, no wall-clock exposure. An adaptive permutation
still runs to supply the interval, and a test asserts the two agree to within Monte Carlo
error, which is what makes the permutation path checkable rather than merely trusted.

**Per-finding significance is abandoned**, and the estimators were deleted rather than left
as an unreachable fallback. Results carry margin, margin ratio, midrank, cell size, block
degree, geography level and Γ\* as a prioritisation.

**The inferential instrument is a pooled stratified rank test** — van Elteren, equivalently
the Cochran–Mantel–Haenszel score test for 1:M matched sets:

```
E[R_s]   = (n_s + 1) / 2
Var[R_s] = (1/n_s) · Σ_j ( a_{s,j} − (n_s + 1)/2 )²          exact, tie-corrected
T        = Σ_s w_s ( E[R_s] − R_s ),      w_s = 1 / (n_s + 1)
```

Cells of size 2 and 3 contribute, which is where the power comes from. Simulated power to
detect a 0.10 excess at one-sided α = 0.05 is **0.79 at 400 cells of size 3** and **0.92 at
400 cells of size 11**, against essentially zero filers under the per-finding design.

Since 1.4.0 this statistic has a **tripwire**. Before that, the only claim the product makes
was published and read by nothing.

### Ranks and p-values within a cell

The p-value is the **empirical CDF**, not the rank over n:

```
p = #{ j : v_j ≤ v_obs } / n              (higher_is_worse)
```

Exact under arbitrary ties, identical to `rank/n` when values are distinct. The shipped
implementation returned `rank/n` from a *midrank*, anticonservative under ties — and ties are
the common case here. A cell of ten with a five-way tie reported 0.30 against a true 0.50.

The attainable minimum is a property of the **tie structure**, not of n:
`min_p = (size of the best tie block)/n`. A cell of forty in which everything is tied has no
power at all.

Ranks are computed on values **coarsened to the pair's own threshold**. Ranking to 0.001
points while declaring 7.1 the smallest measurable difference lets a denial reach rank 1 on
an ordering the design says is not a measurement.

### One obstruction that does not go away

Denial reason codes are observed **only on denied records**, so any label permutation must
carry the reason code with the label — and reason codes are *caused by* the record's own
covariates. The test therefore addresses a composite hypothesis and **cannot separate
"denied the wrong application" from "cited the wrong reason"**.

## 12. Sensitivity to unmeasured confounding

The standing objection to any matched-pair result is that the two applicants differed on
something unobserved. Rosenbaum's Γ turns it into a number.

For midrank *r* in a cell of *n* under bias bound Γ, the worst-case one-sided p is
`Γr/(Γr + n − r)`. Inverting at level α:

```
Γ* = α (1/p − 1) / (1 − α)
```

At α = 0.10: p = 0.10 → **Γ\* = 1.00**; p = 0.05 → 2.11; p = 0.02 → 5.44; p = 0.01 → 11.0.

**Every result at the old power floor of n = 10 had Γ\* = 1.00** — no robustness to any
unmeasured bias at all. Γ\* = 5 requires a cell of at least 46.

Coarsening imposes a ceiling no sample size removes. Once a dimension is coarsened to a
discrete published scale, the smallest tie-correct p is the population share *f* of the best
level:

```
Γ_max = α (1/f − 1) / (1 − α)
```

**≈ 2.1 for debt-to-income over the published bands, and below 1 for loan-to-value coarsened
to its own threshold.**

Γ\* is published per result; **Γ_max is a property of the specification and is checked at the
startup gate** — a dimension below the benchmark is not testable and the service refuses to
start.

**Calibrating the benchmark.** Under a normal-latent model `d = √2·Φ⁻¹(AUC)`. With an
observed AUC near 0.70 on published fields against a full-information underwriting benchmark
near 0.88, the unobserved component contributes ≈1.49 SD — Γ ≈ 11. Two applications identical
on every published field and 80–100 FICO points apart is unremarkable.

**If Γ_max sits below the benchmark for both testable codes at honest resolution, that is the
finding**, and it belongs at the top of the product document.

## 13. Negative controls

**The primary control is a paired discordance test.** Let *b* be denials where the cited
dimension fires and the placebo does not, *c* the reverse; exact binomial on `b/(b+c) > 0.5`.
This replaced a ratio control that substituted a literal constant for a bootstrap draw
whenever the placebo rate was zero — so that constant, not the data, set the bound the
the gate read.

**Both arms are restricted to pairs where both dimensions are informative.** Loan-to-value is
adjudicable on 96.3% of collateral-code denials, debt-to-income on 5.1% of matched pairs
under the numeric rule; without the restriction the control cannot distinguish specificity
from measurability and passes for the wrong reason.

**A second placebo holds measurability fixed by construction:** permute the *cited reason
code* within a stratum from that stratum's empirical distribution and re-run the identical
engine.

**Controls run pooled nationally.** "Powered" was coded as n ≥ 30; the honest requirement is
~118 per arm unpaired or ~68 discordant pairs paired. A validity check is not a per-filer
claim.

## 14. Coverage — the limitation that shapes everything

A cell exists only where a filer has volume in one geography × key combination. The method
is therefore structurally blind to thin markets, non-metropolitan lending, the broker
channel, manual underwriting, small filers and partially exempt filers — **precisely where
underwriting discretion is largest**.

The sampling frame is anti-correlated with the risk it is meant to prioritise. Every scan
publishes a coverage profile — matched fraction and result rate by county-volume decile,
automated-underwriting presence, submission channel, loan purpose and complete-case status —
so a buyer is told which half of their book cannot be seen.

Related: under the EGRRCPA partial exemption, insured depositories and credit unions below
the origination thresholds omit denial reason, loan-to-value, debt-to-income and property
value — every input the reason engine uses.

## 15. Validation

**A true-null fixture.** Labels assigned uniformly at random within cells must produce a
uniform p-value distribution. Thirty lines, and it would have caught three of the five
defects above on day one.

**Mutation testing** against a published, pre-registered catalogue at a kill rate ≥ 0.90 —
published, because a kill rate against a private catalogue is unreviewable. Every mutant is
drawn from a real defect in this project's history.

**Metamorphic properties.** Swapping approved and denied inverts the margin sign wherever the comparison is resolved, and flips the outcome. Where it is not resolved the reported margin is a slack rather than a dominance, and the two directions sum to minus the combined interval width -- an exact identity, asserted as one. Adding a constant to both
property values changes nothing; rounding both incomes to the published bin changes no
outcome.

**Generative tests** over randomly drawn inputs: tolerance symmetry, antisymmetry of the
lattice, p-value bounds, monotonicity of Γ\*.

**The label instrument is public-record rebuttal, not comparability.** A labeller sees both
full rows and answers one question with a forced justification: *naming a specific field, is
there a difference visible in the published record and outside the matched field list that a
fair-lending examiner would accept as a legitimate reason for the different outcome?* Two
labellers independently, disagreements to a blinded third adjudicator. **Gwet's AC1** is the
primary agreement statistic rather than Cohen's κ, which is tunable by sample choice — and
the gate sits on the boundary arm where prevalence is engineered near 0.5, because AC1 has
the opposite failure at low prevalence.

## 16. Known limits

- The inferential claim is scan-level, not per-result.
- The permutation null addresses a composite hypothesis and cannot separate "denied the wrong
  application" from "cited the wrong reason".
- The sampling frame is anti-correlated with the risk it prioritises (§14).
- About 81.5% of debt-to-income denials cannot produce a result at any sample size (§9).
- Sensitivity is bounded above by the coarsening — Γ_max ≈ 2.1 and < 1 (§12).
- Same-applicant resubmission may be unidentified rather than filtered.
- Collateral is not loan-to-value; denial reasons are first-sufficient, unranked and
  non-exhaustive; income is not fully commensurable across a pair; reason-coding is gameable.
- A deterministic wrong answer reproduces perfectly. Reproducibility is a property of the
  pipeline, not a quality result.

## 17. Open questions

**Protected-class analysis is excluded**, which forecloses any fair-lending claim. The method
is correct under every resolution of that question and a guard prevents accidental
introduction.

The most informative thing available without relaxing the exclusion is a **proxy-strength
diagnostic**: fit a classifier predicting a protected attribute from the permitted feature
set and publish *only its AUC*. That measures how much protected-class information the key
already carries without using any of it to decide anything. It requires loading attributes
the pipeline currently refuses at ingest, so it is a policy decision.

**A regression discontinuity** at the conforming loan limit, at 80% loan-to-value and at the
qualified-mortgage threshold is a real quasi-experiment on free public data. One field
currently in the key — the conforming-limit flag — is a deterministic function of loan
amount, county, units and year, so it adds nothing already matched on *and* deletes precisely
the pairs that straddle the limit. Removing it is scheduled.
