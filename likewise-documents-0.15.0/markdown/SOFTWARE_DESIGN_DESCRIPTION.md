# Likewise — Software Design Description

## Document control

| | |
| :--- | :--- |
| Document | Software Design Description (referred to internally as the TDD) |
| Product | Likewise |
| Version | 2.0 |
| Status | Baselined against software release v0.13.0 |
| Prepared by | Arun Kadambi |
| Date of issue | 10 September 2026 |
| Implements | Architecture Description v2.0 |
| Comparability specification in force | 1.4.0 |

### Revision history

| Version | Date | Author | Summary |
| :--- | :--- | :--- | :--- |
| 0.1 to 0.6 | Sep 2026 | A. Kadambi | Iterative drafts through design review |
| 0.7 | 7 Sep 2026 | A. Kadambi | Statistical rework following first contact with the national file |
| 1.0 | 10 Sep 2026 | A. Kadambi | Brought into line with the built system |
| 2.0 | 10 Sep 2026 | A. Kadambi | Restructured to IEEE 1016 design viewpoints |

---

## 1. Introduction

### 1.1 Purpose

This document describes how Likewise is built: its decomposition, its interfaces, the data it holds, the algorithms it runs and the statistical design behind them. It is written for an engineer who has to change something and needs to know what will break, and for a reviewer who has to decide whether the numbers mean anything.

### 1.2 Scope and context

The design subject is the whole of the Likewise software at release v0.13.0, including the optional extraction component that does not ship in the served image.

### 1.3 Design stakeholders and their concerns

IEEE 1016 asks that the concerns a design must address be stated rather than assumed. Four here.

An engineer changing the comparison needs to know which parts are load-bearing and which are incidental, because the difference is not visible from the code. A reviewer assessing the statistics needs each claim stated with its assumptions, so they can decide whether the assumption holds rather than whether the arithmetic is right. A security reviewer needs the disclosure boundary to be one place rather than a property to be verified everywhere. And whoever inherits this needs to know why particular things are done in an unobvious way, which is why this document records defects rather than only designs.

### 1.4 References

R1: IEEE Std 1016-2009, *Standard for Information Technology — Systems Design — Software Design Descriptions*. R2: Software Requirements Specification v2.0. R3: Architecture Description v2.0. R4: Rosenbaum, *Observational Studies*, 2nd ed. R5: van Elteren, "On the combination of independent two-sample tests of Wilcoxon", 1960.

### 1.5 Design languages

Prose, tables, and mathematical notation in-line. Structure is given by the IEEE 1016 viewpoints rather than by UML; the system is small enough that a component register and responsibility statements carry more than a diagram would.

---

## 2. Composition viewpoint

```
likewise/
  api.py          routes, credential scopes, error mapping
  core.py         grouping SQL, matcher, interval construction, dominance, midranks, power
  compare.py      the comparison lattice: one pair, one dimension
  precedent.py    admission where a prior decision governs
  binding_gate.py scoring rulings against a known-answer corpus
  stats.py        the pooled test, the exact null, the envelope, sensitivity bounds
  scan.py         sequencing, suppression, tripwires, the summary
  specs.py        load, validate, digest, the per-pair threshold
  egress.py       the sole serialisation boundary
  loader.py       layout detection, validation, normalisation, manifest
  store.py        get / put / create / list / uri
  paths.py        where mutable things live
  runtime.py      memory and thread limits from the environment
  schema.py       the internal record schema and sentinel mapping
  errors.py       structured failures
  web/            server-rendered pages over already-serialised artefacts

extract/          optional, offline. Nothing in likewise/ imports it
```

Roughly four thousand lines in the served engine. The technology is Python 3.10 or newer, FastAPI and Uvicorn, DuckDB embedded over columnar files, and frozen dataclasses over YAML for the specifications. There is no pandas, no numpy and no scipy anywhere in it.

That constraint is deliberate and worth defending, since it is unusual for anything statistical. Every routine here is standard-library arithmetic: the complementary error function for a normal tail, log-gamma terms for a binomial sum, bisection where a root is needed and ternary search where a minimum is. In exchange the served image stays small, its dependency surface stays auditable, and nothing in the numerical stack can change behaviour underneath the engine between releases. It was less painful than expected; the hardest piece was about twenty lines.

The constraint applies to the image and nowhere else, and the distinction is the point rather than a caveat. Every one of those routines is implemented a second time in `analysis/`, against SciPy, statsmodels and NumPy, and a check asserts the two agree on the same inputs before a release ships. The standard-library version is what serves; the reference version is what makes the standard-library version believable. Neither would be as good on its own: a hand-rolled empirical CDF that is subtly wrong about ties looks exactly like one that is right, and a SciPy call in a read-only container is a transitive surface nobody has audited.

It is not a hypothetical safeguard. The first run of the check raised `OverflowError` from the exact binomial bound at n = 2,995 with 1,497 failures — `math.comb(2995, 1497)` is an exact integer of some nine hundred digits, and Python will not convert it to a float even though the product it appears in is a probability in [0, 1]. The sum is now taken in log space. Every test in the suite had used a small failure count, so nothing in the suite could have reached it, and the sizes involved are precisely the ones the binding gate's assertion floor is built around.

---

## 3. Dependency viewpoint

The dependency graph is a layering, and the layering is what makes the disclosure guarantee enforceable.

`stats.py` depends on nothing but the standard library. It receives values and labels and has no way to see a record, which is why it can be tested from a list of numbers and why nothing in it can leak. `compare.py` sits at the same level: it knows what the record says about one pair on one dimension, and has no opinion about what should follow.

`core.py` depends on both, and adds the rule that turns comparisons into an outcome. `scan.py` depends on `core` and `stats` and owns sequencing, but no comparison logic of its own. `egress.py` sits across the top and is the only module permitted to serialise a finding; a contract test walks every registered route to check, and a static check fails the build if a renderer imports a raw record type directly.

The web package renders artefacts that have already passed through egress. It never sees a raw record, and each file in it says so.

Two packages sit outside this graph and depend on it in one direction only. `extract/` is optional and offline. `analysis/` holds the cross-validation, the simulation studies, the data profile and the figures; it imports `likewise` freely and is imported by nothing. The asymmetry is enforced by a source-level test rather than by convention, because the failure it prevents — a scientific package reaching the served image through an import inside a function body — is invisible to any check that only watches what executes.

---

## 4. Information viewpoint

### 4.1 Persistent structures

Snapshots are columnar files under an immutable identifier, with a manifest naming every file, its digest, and every record that was expected and did not arrive. Specifications are YAML, immutable once published, cited on findings by digest as well as version string.

Scan output is a findings file, a summary, a sweep, control results and a dispositions file, all under a scan identifier derived from the tuple of filer, year, specification digests and snapshot. A repeated run of the same tuple is the same scan.

### 4.2 Sentinels and exemptions

Lenders operating under the EGRRCPA partial exemption omit precisely the fields the reason engine needs, and the public file carries a literal `"Exempt"` string in the Data Browser export and a numeric code in the snapshot format. Both map to null at ingest, and exempt records are counted in their own denominator rather than disappearing into a general "no data" bucket. Nulls never match nulls anywhere in the system: two records that both lack a value are not alike on it, and the SQL construct that would treat them as alike is banned outright by a lint over the generated query text.

### 4.3 The denominator chain

Every rate the product publishes carries its denominator, and the chain is ordered and complete: records in scope, denials in scope, non-exempt, complete, with a matched comparator, testable by code, in an adequately powered group, with a finding. Each step names what it removed. A rate whose numerator and denominator were computed by different paths is the easiest way to publish a wrong number that looks right, and the chain exists so that they cannot drift.

---

## 5. Interface viewpoint

A REST surface under `/v1` and a server-rendered view under `/ui`, both from one process. Every route requires a credential; scopes are read and write.

The route that evaluates a caller-supplied pair rejects institution identifiers rather than masking them. Masking whatever a caller sends would turn the endpoint into a lookup oracle over its own pseudonymisation function, and because the filer panel is public and enumerable, a complete mask-to-identifier table could be assembled in about an hour. Input is restricted to an allow-list of published fields at published precision, and request bodies are excluded from logs, because the natural thing for a user to do is paste their own full-precision underwriting data into a service that has no classification for it.

Two routes refuse by design. Findings and the review queue both return a conflict status until a sensitivity sweep exists for that scan, on the grounds that a finding must not be shown without the curve that says whether its threshold was chosen to produce it.

---

## 6. Algorithm viewpoint: the decisive threshold

This is where a reader who wants to understand one thing about the system should start, because it decides everything downstream.

The question is how far apart two applications must be before the difference is real. It is not a statistical question; it is error propagation, and it has the same shape as any laboratory measurement. You cannot measure a difference finer than the resolution of your instrument, and when a quantity is derived from measured inputs, the uncertainties of those inputs propagate into it.

Three floors compete and the largest wins:

```
tau(pair) = max( declared minimum, comparability floor(pair), publication floor(pair) )
```

The declared minimum is a policy choice written into the signed specification. The publication floor is what the regulator's rounding alone implies. The comparability floor is the interesting one.

Combined loan-to-value is 100·L/V. The matcher admits pairs whose loan amounts differ by up to its own tolerance, and for a ratio that admitted slack propagates:

```
comparability floor(L, V) = 100 * max(0.05 * L, $20,000) / V     percentage points
```

which comes to 7.02 points at a $285,000 property, 11.43 at $175,000 and 16.00 at $125,000. Everything below roughly $282,000 in property value needs a larger gap than most applications ever exhibit, which means the method cannot speak there and should say so.

This was wrong for some time, and the way it was wrong is instructive. The threshold was certified at a single reference point and applied as a scalar, and it passed, because the reference sat about 0.08 points inside the boundary. The only real filer scanned at that stage was in San Diego County, where the median property value is around $805,000 and roughly one record in two hundred falls below the point where the certified value stops holding. One expensive market concealed a defect affecting most of the country, and it failed in the direction that manufactures findings in cheap markets, which is the direction that would eventually have looked like a result about protected classes.

The floors are evaluated at the minimum of the pair on each magnitude, because they decrease in the denominator and the smaller magnitude therefore gives the larger required gap. Choosing the mean would certify a threshold that the cheaper half of the pair does not support.

The ways of combining the three floors are a closed, named set rather than caller-supplied functions, for the same reason the specification is signed: a digest over an arbitrary function certifies nothing.

---

## 7. Logical viewpoint: the comparison lattice

One pair, one dimension, placed on a seven-element partial order:

```
STRICTLY_WORSE < WEAKLY_WORSE < { TIED, AMBIGUOUS, UNRECORDED } > WEAKLY_BETTER > STRICTLY_BETTER
```

A published value denotes an interval. Debt-to-income below 20 per cent denotes the range from zero to twenty; an integer *k* inside the reported window denotes *k* plus or minus a half; "50 to 60 per cent" denotes that closed range; anything above 60 denotes an unbounded range. With a threshold τ, one interval dominates another only when it lies wholly beyond it by more than τ.

The two directional margins are not negatives of one another. Their sum is minus the combined width of the two intervals, which means the relation is asymmetric in a way that point comparison never is. A metamorphic test asserts that identity exactly, and asserts plain inversion only where the comparison is resolved. The test was written the naive way first; it passed for weeks, and it passed only because the specification it ran against declared no interval widths at all.

The three unordered elements are kept distinct, and the distinction is inert in the lending product and load-bearing outside it. A tie means the order is identified and the two records sit at the same value. An ambiguity means the intervals overlap and the record does not order the pair. Unrecorded means the record does not speak to the dimension at all. Under flagging, all three produce nothing and could safely be one value; under a rule where a prior decision binds, a tie is the strongest possible reason to bind and silence is a reason not to, so collapsing them would make an exact match indistinguishable from an absence of data.

One consequence of interval dominance does not go away and belongs in any honest description of the product. A denial reported above 60 per cent debt-to-income has no upper bound, so nothing can be shown to be worse than it; a denial in the 50-to-60 band needs a comparator above 61 and none exists. About 81.5 per cent of debt-to-income denials are therefore structurally incapable of producing a finding, at any sample size, under any correct rule. Debt-to-income is the largest denial reason in the country.

---

## 8. Algorithm viewpoint: dominance and the reason engine

Four clauses over the per-dimension comparisons, evaluated as a conjunction rather than scored.

First, no tested dimension may be decisively better. Second, at least one must be decisively worse beyond its own pair threshold. Third, at least one dimension must actually have been informative, which rules out a finding assembled entirely from comparisons that said nothing. Fourth, no residual-risk dimension may show the comparator strictly better beyond tolerance.

Income and loan amount are residual-risk dimensions carrying declared directions rather than membership conditions. Loan amount is excluded from directional treatment for collateral denials, and the reason is arithmetic: loan-to-value is 100·L/V, so a comparator admitted for borrowing more at the same property value would produce a collateral finding by division alone.

Multi-code resolution is conservative. A denial citing any reason the public record cannot test is untestable as a whole, because reasons are first-sufficient, unranked and non-exhaustive, and the claim "the public record does not support the reason you cited" is only defensible when every cited reason was examined. This creates an incentive that runs the wrong way, in that a lender adding untestable codes lowers its own finding rate, so reason composition is published per filer.

Polarity is declared per dimension and validated at load. Collateral tests loan-to-value and property value, whose polarities are opposite; a single global sign convention inverts one of them and manufactures findings from stronger collateral.

---

## 9. Algorithm viewpoint: the statistical design

### 9.1 Groups, ranks and attainable power

Groups are blocks of a partition rather than neighbourhoods, and the distinction is not pedantic. A symmetric tolerance is not transitive, so the set of records within tolerance of a given denial is a neighbourhood of that denial, and permuting a label inside a neighbourhood asserts an exchangeability that does not hold. Groups are therefore defined by bucket identity over the matched fields, using a lossless overlapping cover, which restores a genuine equivalence relation and with it exact exchangeability.

The p-value is the empirical distribution function rather than a rank divided by *n*: the count of group members at or beyond the observation, over *n*, with a floor at 1/*n*. This is exact under arbitrary ties and identical to rank/*n* when values are distinct. Ties are the rule here rather than an edge case, because the tested dimensions are published at bin resolution, and the rank form understates: a group of ten with a five-way tie at the best value reports 0.30 where the true probability is 0.50.

The smallest achievable p-value is a property of the tie structure, not of the group size. A group of twenty whose ten lowest values are identical cannot report below 0.5 however strong the effect, so the power check compares that floor to the target level and marks the group as unable to reach it. Such groups are reported with their rank and margin, counted in their own denominator, and are not findings.

### 9.2 The null

For a group with values *v₁…vₙ* and threshold τ, the probability of a finding under within-group exchangeability is

```
P = (1/n) * SUM over i of  [ 1 if some j is worse than i by more than tau ]
                          * [ 1 if no   j is better than i by more than tau ]
```

Summed across groups, this is the exact expected number of findings, computed in one pass with no replicate count, no seed and no wall-clock exposure. A randomisation test is also run, because the closed form gives a mean and the tripwire wants an interval as well, and a test asserts the two agree within Monte Carlo error. That agreement is the strongest single check on either of them.

The reference distribution is built over every matched, testable denial, before the dominance filter and before suppression. Suppression governs disclosure, not inference. A null assembled from groups that had already produced a finding is conditioned on the event under test, and rejects at close to certainty on data with no signal in it whatsoever. That defect survived a full test suite, a mutation gate at 100 per cent and an architectural review, and was found only when somebody generated data with nothing in it and asked what the pipeline said.

### 9.3 What is claimed, and what is not

Per-finding significance is abandoned, and the estimators that would have produced it were deleted rather than left switched off. The reason is arithmetic. Inside a family of *m* hypotheses, a false-discovery threshold needs a group of roughly 1/(q·f), which is about a hundred at conventional settings. The median matched group here holds three. A per-finding q-value would be decoration on a test that cannot fire, and worse, it would look exactly like the thing it is not.

What the data supports is a claim about the filer. Pooled across every matched group, do this filer's denials sit better than chance on the dimension their own stated reason names? Hundreds of tiny groups, each uninformative alone, answer that. The instrument is a pooled stratified rank test, van Elteren's (R5), equivalently the Cochran-Mantel-Haenszel score test for one-to-many matched sets:

```
E[R_s]   = (n_s + 1) / 2
Var[R_s] = (1/n_s) * SUM over j of ( a_sj - (n_s + 1)/2 )^2      exact, tie-corrected
T        = SUM over s of  w_s * ( E[R_s] - R_s ),   w_s = 1 / (n_s + 1)
```

The variance is computed from the realised midranks rather than the textbook (n²−1)/12, which assumes distinct values; under ties the midranks have smaller spread, and using the untied form would overstate the variance and make the test quietly too conservative. The weight stops one group of four hundred drowning two hundred groups of three. The statistic is signed so that a positive value means denials sit better than chance on their own stated dimension, which is the direction that would make the stated reason hard to justify.

Stated exactly, the claim is: *across this filer's denials, the dimension the filer's own stated reason names does not order the decisions.* It is about a filer, never about an application.

One obstruction remains and does not go away. Reason codes are observed only on denied records and are caused by the record's own covariates, so any permutation of the label must move the reason code with it. The test therefore examines a composite hypothesis and cannot separate "denied the wrong application" from "cited the wrong reason".

### 9.4 Sensitivity

Rosenbaum's bound (R4) in closed form. For a one-sided p at level α, a finding survives a bias bound Γ exactly while Γ ≤ α(1/p − 1)/(1 − α).

Coarsening imposes a ceiling that no sample size removes. Once a dimension is reported on a discrete published scale, the smallest tie-exact p is the population share of its best level, so the ceiling is that same expression evaluated at that share. Measured: about 2.1 for debt-to-income over published bands, below 1 for loan-to-value at its own threshold, against a benchmark near 11 implied by credit score alone.

This is the number that decides what the product may claim, which is why it is also in clause 2.6 of the requirements rather than only here.

### 9.5 Negative controls

The publication gate. The identical engine is run against a reason the filer did not cite, with both arms restricted to pairs where both dimensions are informative, since otherwise the control cannot distinguish specificity from measurability and would pass for the wrong reason. Publication is blocked on failure and equally on an inconclusive result, because a gate that treats "the data could not tell" as a pass is not a gate.

---

## 10. Interface viewpoint: contracts

Every external serialisation of a finding, summary or control result passes through one module. This is enforced rather than asserted: a contract test walks every registered route and checks the response was produced by the serialiser, and a static check fails the build on a direct import of a raw record type into the API or a renderer.

Reproducibility is content identity over sorted logical rows at fixed numeric precision, not byte identity. Byte identity would additionally require pinned writer and codec versions and single-threaded writes, and would break across deployments anyway because the pseudonymisation key differs.

The content hash is not a determinism proof, and it is worth being precise about what it does. It certifies that a result was not edited after the fact. It is computed over the findings that were emitted, so two runs that selected different comparators simply produce two different hashes, and a reviewer holds only one of them. Determinism is established by the total ordering described in the architecture description and by tests that fail three ways when that ordering is removed.

---

## 11. State dynamics viewpoint: admission where a prior decision governs

The same comparison, asked a different question: does a prior adjudication govern the present case? This component is not on the lending path, and it exists because the error asymmetry inverts when the answer compels rather than suggests. Under flagging, a false positive costs a reviewer an hour with a file. Under a rule of precedence, a decision compelled by a precedent that does not govern is compelled, and its audit trail is accurate in every field.

The design consequence is an ordered status ladder in which silence outranks distinguishing: a premise the present case does not record is not a premise it is at least as strong on, it is a premise nobody established. Six mutually exclusive case outcomes keep the four ways of not binding apart rather than collapsing them into one empty set: nothing retrieved, everything distinguished, premise not established, admitted but not orderable, admitted but in conflict, and governed.

Ties in the authority order abstain rather than resolve. A ruling carries no score and no disposition, which a test enforces by reflecting over its fields. At zero tolerance the whole construction reduces exactly to boolean set containment, verified across all 256 combinations of an eight-factor premise.

---

## 12. Algorithm viewpoint: the binding acceptance gate

Whether the engine is fit to compel a decision, scored against a corpus whose correct answers are known by construction.

The gate is one-sided by design. A missed bind costs a reviewer a case they must decide themselves; a false bind compels a decision. So the gate bounds false binds and merely reports missed ones, since gating recall would trade the expensive error for the cheap one.

The bound is exact rather than approximate. Every bind is a Bernoulli trial, and from *k* failures in *n* trials the Clopper-Pearson upper limit is the largest rate for which observing *k* or fewer failures remains plausible at the chosen level, found by bisection on the binomial distribution function. At zero failures this reduces to 1 − α^(1/n), of which the familiar rule of three is the large-sample approximation; computing it exactly costs nothing, sharpens the floors slightly (the true minima are 299 and 2,995 rather than 300 and 3,000), and unlike the rule of three still returns a usable bound when there are failures.

Four conditions refuse. Evaluating on the cases the tolerances were fitted to is invalid, because that measures the fit. Any bind on a guard case fails at any sample size, because a guard is constructed so that the only correct behaviour is abstention. Too few binds returns inconclusive rather than pass, because perfect precision is trivially satisfiable by never binding at all, and for the same reason the reported bound is undefined rather than zero when nothing was bound. And a pass on an oracle written by whoever wrote the engine's reading of the rulebook is refused, because computed ground truth is a second program from the same source and a shared misreading reads as perfect precision; the independently authored arm is bounded on its own count, never pooled.

---

## 13. Resource viewpoint: evaluation

The suite holds 253 tests. Three techniques carry most of the weight, and none of them is unit testing.

Mutation testing runs a published catalogue of deliberate defects and measures how many the suite catches. The gate is 0.90 and the rate is 80 of 80. Publishing the catalogue matters twice: a kill rate against a private catalogue is unreviewable, and publishing it prevents the obvious way to game the measure, which is to write mutants you already know you catch.

Metamorphic testing asserts properties across the entire candidate set rather than on fixtures. Swapping the two sides inverts the margin where resolved and sums to minus the combined interval width where not; adding a constant to both property values changes no match; rounding both incomes to the published bin changes no outcome.

A true-null fixture generates data with no signal and asserts the machinery reports none. It is about thirty lines. It would have caught three of the five statistical defects on day one instead of week six, and the lesson is that a test suite which only ever sees data with something in it has not been tested either.

The linter is configured to find defects rather than impose a house style, on the reasoning that a gate firing on two hundred sites of deliberate formatting is a gate somebody switches off, and the real findings leave with it.

---

## 14. Composition viewpoint: the optional extraction component

Where a corpus arrives as prose rather than as a regulator's structured filing, something has to produce the typed record the engine consumes. That component exists, runs offline, and is never imported by the served engine.

The backbone survey, conducted in September 2026, returned a mostly negative headline: no new encoder architecture was released in 2026, and every 2026 encoder is a domain adaptation of an existing one. The default is a legally-domain-adapted checkpoint, held as a prior rather than a result, since token classification is unmeasured on it; the general-purpose original stays in the set as a control arm and the trainer reports the gap between them. A shorter-context model that measurably wins token classification under matched pretraining data is retained as a chunked comparison arm, because the long context is the reason it was not chosen and that reason should stay testable.

Silence is the safety property. Three statuses: observed emits a value, while abstained and absent both emit a null, and a null on a premise dimension is unrecorded, which under clause 11 breaks the bind rather than making it. An abstention may not carry its best guess, and the contract refuses at construction rather than trusting a convention. The two silent statuses stay distinct in the audit record even though the engine cannot tell them apart, because otherwise the extractor's own miss rate is unmeasurable against true absences.

The confidence floor is a governance object rather than a hyperparameter. It lives in a signed specification with its own validation rules, it is fitted for precision at a declared target rather than for a balanced score, and a floor of zero is refused rather than clamped, since zero makes the abstention path unreachable.

Scoring is by round trip: render records whose values are known into prose, extract them back, compare. The result is an upper bound and is stamped as one, because the renderer and the reader share a vocabulary and a real filing does not.

---

## 15. Stated limitations

Carried in the README and on every export.

The inferential claim is at scan level, not per finding. The permutation null tests a composite hypothesis and cannot separate a wrong decision from a wrongly cited reason. The sampling frame is anti-correlated with the risk it is meant to prioritise, being blind to thin markets, non-metro lending, the broker channel, manual underwriting and small or partially exempt filers. Roughly 81.5 per cent of debt-to-income denials cannot produce a finding. Sensitivity is bounded above by the coarsening at about 2.1 and below 1 depending on the dimension.

This is not a fair-lending finding, because the protected-class axis is excluded by design. It is not comparative file review as the Interagency Procedures define it; it contributes to two of that procedure's eight steps and replaces none of them. Collateral is not loan-to-value, and the code is a bucket for property events generally.

---

## Appendix A. Glossary

**Cell or group.** Applications matching exactly on the declared key and within the declared band on numeric fields.

**Coarsened.** Rounded or bucketed by the regulator before publication.

**Dominance.** One interval lying wholly beyond another by more than the applicable threshold.

**Guard case.** A case constructed so that the only correct behaviour is abstention.

**Midrank.** The average of the ranks a set of tied values jointly occupies.

**Tripwire.** A pre-registered band on a published headline, checked in both directions.

## Appendix B. Deferred

A pure-Python reference partition as a differential oracle against the generated SQL. A temporal validity predicate evaluated inside candidate generation rather than as a post-filter. Two-sided eligibility predicates. A closed-enumeration gate specification. Cross-filer indexing with common-support standardisation. Regression discontinuity at the conforming loan limit. Precision at *K* against lender-adjudicated verdicts, which requires a design partner.
