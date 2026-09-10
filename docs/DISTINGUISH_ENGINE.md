# The Distinguish Engine

Making the comparison kernel serve both the lending instantiation and the Digital
Judiciary's distinguishing gate.

| | |
| :--- | :--- |
| Document | Design exploration |
| Author | Arun Kadambi |
| Date | 9 September 2026 |
| Status | Design exploration. Sections 2 and 3 describe behaviour verified against the running code and covered by tests; the rest is proposal, and says so where it matters. |
| Related | METHOD.md, DESIGN.md, `tests/test_dj_generalisation.py` |

---

## 1. The two systems are the same object at different points in the design space

The Digital Judiciary specifies:

```
cov(r, c)         = |premise(r) ∩ facts(c)| / |premise(r)|
Candidates(c)     = { r ∈ S : prov(r) ∈ rules(c), cov(r,c) ≥ θ, ¬lapsed(r) }
distinguish(r, c) holds iff premise(r) ⊄ facts(c)
Survivors(c)      = { r ∈ Candidates(c) : ¬distinguish(r, c) }
```

Likewise does:

```
blocking          → a candidate set, filtered by key equality and numeric bands
matcher           → the pair is comparable or it is not
dominance         → the comparator is worse on the tested dimension, or it is not
```

Set them side by side and the correspondence is exact:

| Digital Judiciary | Likewise | Shared object |
| :--- | :--- | :--- |
| `Candidates(c)`, `cov ≥ θ` | blocking key + bands | cheap retrieval over a large store |
| `distinguish(r, c)` | dominance clauses | the gate that decides admission |
| `premise(r)` | the denial's cited reason dimensions | the per-record subset under test |
| `facts(c)` | the comparator's published values | the subject's attribute assignment |
| tolerance vector `m` | the materiality specification | the parameter neither system can fit |
| `Survivors(c)` | matched, dominating comparators | what survives both stages |

Both are **two-stage compositions of a cheap retrieval and an expensive gate, over a
partial assignment of magnitudes to dimensions, parameterised by a tolerance nobody can
learn from outcomes.** That is one engine, and it is already built.

The dimensional reformulation the programme wants — `distinguish_m`, admitting when the
present case is no worse than the premise *by more than a stated tolerance* — is what this
repository has been doing to mortgage denials for its whole life.

## 2. The coherence result is already mechanised here

This is the substantive finding, and it runs from the engineering back to the theory.

The formal obstacle to the dimensional gate is that retrieval–gate coherence stops being
free. Under boolean containment, `¬distinguish` and `cov = 1` are the same condition
written twice, so retrieval provably cannot discard what the gate would admit. Under a
tolerant gate the identity is severed: a record can survive the gate while scoring below
the retrieval threshold, and retrieval silently loses precedent the gate would have
admitted. Where a retrieval miss compels a decision and produces a written justification
for it, that is not a missed reference — it is a decision made without its controlling
record, and the rationale trail truthfully reports a consulted set that never contained it.

The coherence condition is `¬distinguish_m(r,c) ⟹ sim(r,c) ≥ θ`.

**Likewise enforces it at specification load, in two complementary rules, each with a CI
fixture that violates it.** Neither was written with the judiciary in mind; both were
forced by defects in the lending instantiation, which is the more interesting provenance.

**Rule 8 — the tested dimension is never in the retrieval key.** A dimension under test may
not appear in the blocking key, the exact-match set or the bands. Retrieval therefore
cannot filter on the dimension the gate examines, so for tested dimensions the coherence
condition holds vacuously.

This is the θ = 0 repair applied *selectively*. Rather than dropping the retrieval
threshold to zero everywhere — which costs retrieval volume that grows with the store —
only the tested dimensions are exempted, and every other dimension keeps its filter. The
cost is bounded by the size of the tested set, which is small and per-record.

**Rule 5 — where retrieval does filter, the band must cover the tolerance.** For dimensions
retrieval legitimately narrows on, coherence is not free and is bought explicitly: the
retrieval band must be at least as wide as the tolerance the gate will apply to the same
field, on both the relative and absolute terms.

That is the tolerance-aligned repair, checked mechanically. Rule 5's own comment, written
long before this comparison was drawn, names the same failure the coherence result names:

> *"Otherwise blocking silently discards pairs the matcher would have accepted, and the
> loss is invisible: it happens before anything is counted."*

**Rule 9 — the band must be strictly wider than the tolerance.** Flush with it, retrieval
removes every pair the gate could fire on: the gate is live in the code and dead in effect.
Coherence in the weak sense holds and the composition is still useless.

Together these are a hybrid the formal treatment does not enumerate: **exemption on tested
dimensions, alignment on filtered ones, strictness on the residual set — all three verified
at load rather than argued per deployment.** `tests/test_dj_generalisation.py` constructs
the coherence witness on the real comparison function and then shows the rules refuse the
configuration that permits it.

## 3. What transfers unchanged

Verified executably, not asserted:

**The reduction.** With boolean dimensions and zero tolerance, the interval comparison
reproduces set containment exactly — checked over all 256 combinations of a four-factor
premise against a four-factor fact pattern. This is the compatibility result that makes a
dimensional gate an extension rather than a replacement, and it means no disposition
already recorded under the boolean gate is reopened by adopting the engine.

**Absolute provisions.** τ(p) = 0 is the ordinary zero-tolerance case on the same code
path. Absolute and ordinary provisions differ by a declared tolerance, not by a second
engine.

**The per-record tested set.** Likewise already derives the dimensions under test from the
*record*, not from a global list: a denial's cited reason codes select them. `dims(premise(r))`
is the same mechanism with a different name.

**Incomparability as a first-class answer.** A dimension the present case does not record is
not a dimension on which the case is weaker. Treating silence as absence converts every
incomplete record into a distinguished one — for a gate that compels a decision, the
expensive direction of error.

**The gate-margin instrumentation.** The empirical question — how many discards turn on a
single dimension, the finest margin a boolean vocabulary can express — needs the
per-dimension comparison recorded on every discard. `TestedDim` already carries dimension,
direction, margin, applied threshold, outcome and lattice position. Measuring the margin
distribution across the worlds is reading a field, not building an instrument.

**The tolerance as a governed object.** The programme's argument is that the tolerance is
outcome-determining, not derivable from the rules, not learnable from outcomes without
circularity, and therefore constitutional. Likewise's specification mechanism is that
argument implemented: versioned files, immutable once published, a named author and a
written rationale per version, digest-cited on every result, validated at load, refused if
invalid, and rendered on their own screen. What the theory asks for as a norm, this
enforces as a gate.

## 4. What the judiciary records demand that lending records do not

Five real differences. None is deep; all are seams that must be cut deliberately.

### 4.1 The comparison is against a reference, not between peers

Likewise compares an *approved* record to a *denied* one — two applications of the same
kind. The gate compares a *present case* to a *precedent's premise*, and the premise is not
a case: it is the position at which a holding rested, together with the direction favouring
the winning side.

Same shape, and the numbers read oppositely. `evaluate(approved, denied, …)` becomes
`evaluate(reference, subject, …)` with the side declared per dimension rather than implied
by an argument name. The test suite already pins that the comparison is directional and
that swapping the side inverts the verdict exactly.

**Cost: a rename and a declared field.** Not a redesign.

### 4.2 Temporal validity

`Candidates(c)` carries `¬lapsed(r)`. A precedent has a life, and whether it is available
depends on when the present case arrives. Likewise has no analogue — a filing year is a
closed world and every record is contemporaneous.

This is the one genuinely new requirement. The engine needs an **as-of predicate on the
reference**, evaluated against the subject's own position in time, and it has to be part of
the candidate stage rather than a post-filter, or the coherence property is broken from a
new direction: a lapsed record removed after the gate has already influenced what the gate
saw.

**Cost: a new stage, small but load-bearing.** It should be specified before it is built.

### 4.3 Eligibility is two-sided

The Docket holds declined and no-provision-engaged cases. They are never precedent, never
controlling, never admitted. But they are still cases, and they still belong in
denominators.

Likewise has the same shape without having named it: purchased loans and preapproval
requests are in scope for population counts but are not underwriting decisions and must not
serve as comparators. Both need **two predicates, not one**: eligible-as-subject and
eligible-as-reference, declared in the specification and reported separately in the
denominator chain.

### 4.4 The outcome is a vector, and discordance is a declared predicate

Likewise hardcodes outcome discordance as approved ≠ denied. A disposition is richer —
disposition type, charge or decline, rating, route.

But note what does *not* change: `distinguish` tests the **premise against the facts**, not
the outcome. The outcome only enters when asking whether two comparable cases were treated
differently. So the seam is clean: the comparison machinery is untouched, and outcome
discordance becomes a declared predicate over an outcome vector rather than a boolean on
one field.

### 4.5 The stratification key

`(filer, filing year)` becomes `(provision, rulebook version)` or `(world, corpus
revision)`. The pooled stratified rank test works unchanged — it is indifferent to what
defines a stratum. Scan identity, which is currently a digest of filer, year, specification
and snapshot, becomes a digest of the judiciary's equivalent tuple.

## 5. The largest available quality win: there is an oracle

This is the thing worth reorganising around.

Likewise's honest limitation is that **the core value claim is not evaluated**. The estimand
that matters is lift — P(rebutted | flagged) ÷ P(rebutted | random matched testable) — and at
the current label budget its interval spans "worse than random" to "five times better". There
is no ground truth in a public mortgage filing, and no budget buys one.

The judiciary corpora have **computed ground truth by construction**: one chronological pass
against a reference engine produces the label, and a second independent script replays and
must reproduce it. The disposition the oracle says should have obtained is a *field on the
record*.

That converts the unmeasurable into the measured:

| Quantity | Lending | Judiciary |
| :--- | :--- | :--- |
| Precision of the gate | Unmeasurable at any affordable label budget | Directly computable against the oracle |
| Recall against admissible precedent | Unmeasurable | Directly computable |
| Coherence violations in practice | Provable at load, unobservable at runtime | Countable per run |
| Effect of a tolerance change on disposition | A sensitivity surface | A confusion matrix |

**Recommendation: build the oracle path first, before any of §4.** An engine whose error
rate can be measured is a different engineering proposition from one whose cannot, and every
subsequent design choice gets cheaper to evaluate. It also lets the sweep report something
much stronger than a curve of counts — the curve of *disposition changes* against the
tolerance, which is the quantity the constitutional argument actually rests on.

The corpus discipline supplies a second gift: **guard items**, cases engineered to look like
a violation and not be one. Likewise's negative controls approximate this with a placebo
dimension, and admit the approximation. Labelled near-misses are strictly better — they
measure over-blocking directly, which a placebo arm can only bound.

## 6. What must not transfer

Three things I would argue against carrying over, and one framing.

**Rosenbaum's Γ into a synthetic corpus.** Γ bounds how much unmeasured confounding a
result could survive. In a generated world there is no unmeasured confounding: the
data-generating process is known, so the confounding can be *computed* rather than bounded.
Transplanting Γ would produce a number that looks like the lending one, invites the same
reading, and means nothing. The synthetic instantiation should report the oracle-disagreement
rate and mark Γ `not_applicable: generated_corpus`.

For **real** court records the reverse holds, and hard. Γ_max is already ≈ 2.1 for
debt-to-income and below 1 for loan-to-value here, against a benchmark near 11 from the AUC
gap. Real case records have more unobserved determinants of outcome, not fewer — plea
negotiation, victim cooperation, defence quality, everything in the file that is not a
field. Two cases matched on statute, jurisdiction and prior-record category can differ on
facts that dominate the sentence entirely. **The sensitivity ceiling gets worse, and no
sample size lifts it.** That belongs in the limitations of any real-records instantiation
from day one, not discovered later.

**Free-text embeddings anywhere near the primary inference.** The argument is the same one
that keeps a fitted matcher out of the lending engine, and it is stronger here. The
protected-class exclusion is syntactic — it checks field names. An embedding of a fact
narrative is a proxy for everything in the narrative, including every protected attribute,
and it would pass every test written to enforce the exclusion while violating it in
substance. Controlled, auditable fact-pattern fingerprints as declared ordinal dimensions
are fine and are exactly what the dimensional reformulation wants. Embeddings are not, and
"auxiliary only" is a boundary that erodes.

**Any claim of admissibility.** The lending instantiation stamps every result
`screening_hypothesis` and refuses to attach a per-result significance value. A judicial
instantiation needs that discipline more, not less: "these two cases are alike and were
treated differently" reads as an allegation about a named decision-maker. Explainable and
auditable — every clause that fired, every threshold applied, the sensitivity bound, the
consulted set — yes. Admissible, no. The two are often conflated and the conflation is
where this class of system does harm.

**And the disclosure machinery stays, even though synthetic worlds do not need it.** Banding,
margin bucketing, k-anonymity over the emitted attribute set and keyed pseudonymisation are
unnecessary against a generated corpus. They are essential the moment a real docket is
loaded, and a component removed for a synthetic instantiation will not be rebuilt correctly
under deadline for the real one. Make the disclosure policy **pluggable and declared**, with
`none` as an explicit, recorded choice that appears on every export — never absent.

## 7. Extraction: now is the moment, and here are the seams

I argued against extracting a domain-agnostic library while there was one working domain and
one hypothetical. That objection is now resolved: there is a concrete second domain with a
specified gate, a defined record object and a corpus discipline. Extracting on speculation
produces an interface shaped by the domain you have; extracting against two real domains
produces one shaped by the difference.

The difference is now nameable. Everything in §4, plus:

```
distinguish/                     the kernel — no domain vocabulary anywhere
  compare.py                     the five-valued lattice          (exists, unchanged)
  resolution.py                  named resolution models          (exists, in specs.py)
  gate.py                        clause evaluation over comparisons
  cells.py                       partition blocks, midranks, power (exists, in core.py)
  inference.py                   exact null, pooled test, envelope (exists, as stats.py)
  spec.py                        load, validate, digest, gate rules (exists, as specs.py)
  eligibility.py                 subject / reference predicates    NEW
  validity.py                    as-of predicates                  NEW
  egress.py                      pluggable disclosure policy       (exists, needs the seam)

instantiations/
  lending/                       reason codes, HMDA layouts, publication granularity
  judiciary/                     provisions, factors, intake routes, the oracle path
```

**What must be true of the extraction, or it is not worth doing.** The safety properties are
the parts most easily lost: egress exclusivity, k-anonymity over the emitted set, the
protected-class guard, the sweep requirement, publication-granularity enforcement. Split the
engine and every one of them becomes something a second caller can forget to configure. The
extraction is only correct if those move into the kernel as **required, declared policy with
no default** — a caller that does not choose is refused, rather than one that quietly gets
`none`.

The validation rules move with them. Rules 5, 8 and 9 are the coherence property; they are
not lending-specific and they are the most valuable thing the kernel carries.

## 8. Sequence

Ordered by value per unit of risk, and deliberately front-loading the measurement.

1. **The oracle path.** An optional expected-disposition column, confusion counts in the
   summary, and the sweep reporting disposition changes rather than count changes. Nothing
   else is worth doing before the engine's error rate is observable. §5.
2. **Reference/subject with a declared side**, replacing approved/denied. A rename and a
   spec field; it unblocks everything downstream. §4.1
3. **Two-sided eligibility predicates**, with separate reporting in the denominator chain.
   §4.3
4. **Outcome discordance as a declared predicate** over an outcome vector. §4.4
5. **A judiciary specification and a minimal worked corpus slice**, run end to end through
   the existing engine. This is the point at which the correspondence stops being an
   argument and becomes a result — and where the gate-margin distribution falls out for
   free.
6. **Temporal validity.** Specify before building; it is the one stage with no analogue and
   it can break coherence from a new direction. §4.2
7. **Extraction**, against two working instantiations rather than one and a plan. §7

Steps 1 to 4 are small and are worth doing for the lending instantiation on their own
merits, which is the property to look for: if a generalisation step only pays off in the
second domain, it is being done too early.

## 9. What would change my mind

Stated so this document can be wrong in a checkable way.

- **If the boolean gate's discards are not concentrated at the single-dimension margin at
  corpus scale**, the case for a dimensional reformulation weakens considerably, and the
  coherence work stands on its own rather than as a means to it. The reported 31 of 33 is
  one instantiation; the measurement at scale is step 5.
- **If the judiciary's retrieval is not in fact score-thresholded** in the executed build the
  way the specification describes, the coherence result binds differently and the repair may
  already be present for a different reason. The specification and the shipped retrieval
  score have diverged once before in this programme's own reporting; that is worth checking
  against the code rather than the prose.
- **If tolerances turn out to be per-provision rather than per-dimension**, the resolution
  model needs a second index and the specification shape changes more than §7 assumes.
