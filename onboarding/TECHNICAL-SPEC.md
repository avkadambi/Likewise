# Likewise — Technical Specification

| | |
| :--- | :--- |
| Document | Technical specification |
| Product | Likewise |
| Author | Arun Kadambi |
| Date | 9 September 2026 |
| Status | Current |
| Related | MODELS.md for the statistics, ARCHITECTURE.md for components |

Interfaces, schemas, algorithms and evaluation. The statistical reasoning lives in
MODELS.md and is not repeated here.

---

## 1. Modules

```
likewise/
  api.py       routes, auth, error mapping, HTML route wiring
  web/         server-rendered views over stored post-egress artifacts
                 format.py    plain-language numbers, labels, verdicts
                 layout.py    page shell, nav, banners
                 charts.py    inline SVG, no chart library
                 pages/       one module per screen
  core.py      blocking SQL, matcher, intervals, midranks, cell power
  compare.py   the comparison lattice
  precedent.py admission under a rule of precedence
  stats.py     exact null, pooled stratified rank test, sensitivity
  scan.py      orchestration, suppression, tripwire evaluation
  specs.py     load, validate, digest, startup gate, resolution models
  loader.py    CSV → internal schema → Parquet, streaming
  egress.py    the sole serialisation boundary
  schema.py    the internal record schema
  store.py     get / put / create / list / uri
  paths.py     where mutable things live
  runtime.py   engine memory and thread budget
  errors.py    structured, machine-readable failures
```

About 3,300 lines in the engine, a server-rendered view split across a small package, and
roughly 800 lines of command-line tools.

## 2. Ingest

### Layout detection

Three layouts, recognised from the header row alone. See PIPELINE.md §3 for the table; the
unit difference between Snapshot (income in thousands) and Data Browser (dollars) is part of
detection rather than a downstream correction, because it is exactly the kind of thing that
produces a plausible wrong answer.

### Streaming conversion

Conversion is a DuckDB projection over a CSV scan, not a Python loop, so memory does not
scale with the file. Two details learned the hard way:

- DuckDB's default `temp_directory` is `.tmp` **relative to the working directory**. In a
  read-only container that is unwritable, so it is set explicitly.
- `store_rejects` does not materialise under a projection plan, so ragged-row detection
  cannot rely on it. The loader **reconciles row counts** — physical rows scanned against
  rows produced — and a mismatch is a refusal with the counts in the payload.

`convert()` is the same mapping in plain Python, kept as the readable reference. A
differential test drives both over real files and asserts identical records including
`record_key` digests. **If you change one, change the other** — the reference exists so a
reviewer can check the mapping without reading generated SQL, and it is worthless the moment
it drifts.

### Normalisation

Partial-exemption sentinels — the literal `"Exempt"` in the Data Browser, numeric `1111` in
the Snapshot — and `"NA"` map to null. Exempt records get their own denominator rather than
being silently dropped.

**Census tract is dropped**, not filtered: no intermediate Parquet can carry it, and a test
greps every curated schema for the field.

## 3. The specification

Three files, all digested and cited on every result.

**`specs/materiality/<version>.yaml`** — population, blocking key and bands,
`exact_match_required`, control features, residual-risk dimensions with declared directions,
suspected-resubmission signature, disclosure floor, comparison policy, statistics parameters,
tripwires.

**`specs/reasons/<version>.yaml`** — the reason testability map, with per-dimension polarity
declared. Collateral tests loan-to-value and property value, whose polarities are opposite; a
single global sign convention inverts one and manufactures results from stronger collateral.

**`specs/budget/<version>.json`** — per dimension: granularity, whether reported or derived,
what it depends on, the reported half-width, published bands, the declared decisive threshold
and its written basis, and the named resolution model.

### Validation rules

Nine, all checked before the port is bound. PIPELINE.md §3 has the table. Two notes:

Rule 5 exists because a band narrower than the matcher tolerance silently drops pairs the
matcher would accept, and the hole was concentrated at low incomes — which is exactly where
results concentrate.

Rules 8 and 9 encode invariants the design had asserted for some time with nothing checking
them. Both held by inspection; neither was enforced.

### Resolution models

`pair_threshold` composes up to four candidate floors — the declared policy minimum, the
comparability floor propagated from matched fields, the publication floor from binning, and
the dimension's own granularity — into the threshold that decides one pair.

The composition is a **named model** selected in the budget:

| Model | Composition | When |
| :--- | :--- | :--- |
| `strictest` | `max(declared, comp, pub, gran)` | Default. Correct whenever a dimension is downstream of matched fields |
| `declared_only` | `max(declared, gran)` | No algebraic dependence on any matched field |
| `publication_only` | `max(declared, pub, gran)` | Tested but not matched on, and not derived from anything that is |

A closed set rather than a callable, deliberately: an arbitrary function in a signed artifact
is neither reviewable nor comparable across versions by digest. Adding a model is a code
change with a review; choosing one is a specification change with a rationale.

## 4. The comparison lattice

`compare.py` places a pair on the lattice per dimension. MODELS §9 states the
semantics. Two implementation notes:

`Comparison.outcome` projects the lattice onto the legacy three-valued outcome the wire
format and the web view speak. `Comparison.order` is the finer statement, and it separates
"the intervals overlap so the record does not order them" from "they do not overlap but the
gap is under the pair's own floor". Both project to `below_resolution` and they are not the
same fact.

`unresolved()` is the constructor for a dimension the record cannot speak to at all — a null
on either side, or a value outside the window the regulator reports numbers in.

## 5. The matcher and reason engine

All deltas computed with no early return. Symmetric relative tolerance with a stated
reference side, so `match(a, b) == match(b, a)`. Per-dimension declared polarity. An explicit
empty-conjunction guard, because a conjunction over an empty set is true and would otherwise
silently become "not supported".

**The tested dimension is not tolerance-matched.** Dominance replaces the tolerance there,
and rule 8 now enforces the separation.

The dominance clauses, evaluated over the lattice:

1. **Weak dominance** on the tested dimension.
2. **Strictness at resolution** — the difference exceeds the pair's own threshold, not merely
   has the right sign.
3. **Residual risk not better** — the comparator is not strictly better, beyond tolerance, on
   any residual-risk dimension.
4. The conjunction is **non-empty**.

Clauses 2 and 3 are separate quantifiers on purpose: universal weak dominance, plus
existential strict dominance at resolution.

**Multi-code policy** is read from the specification (`comparison.multi_code_policy`) rather
than implied. `conservative` — the shipped value — makes a denial citing any untestable code
untestable as a whole. `any_testable` exists as a declared alternative and changes the
estimand; it is not a tuning knob.

## 6. Statistics

`stats.py` holds four things. MODELS §11–12 gives the derivations.

**`exact_expected_findings(cells)`** — the closed-form expectation under within-cell
exchangeability, one O(Σn²) pass, no replicate count and no seed. A test asserts it agrees
with the permutation estimate to within Monte Carlo error, which is what makes the
permutation path checkable rather than merely trusted.

**`permutation_null(...)`** — supplies the interval. Adaptive: starts at `B_initial`, doubles
to `B_max`, and stops early once the interim p is outside a factor of three of the decision
threshold. All three parameters come from the specification. In practice scans terminate at
the initial count.

**`stratified_rank_test(cells)`** — van Elteren, the only inferential claim the product
makes. Cells of two and three contribute; cells below two and zero-variance cells are
excluded and the result reports `z: None` rather than a number.

**`rank_p_value` / `min_attainable_p` / `gamma_star` / `gamma_max`** — the within-cell
quantities. `rank_p_value` is the empirical CDF with an explicit `1/n` floor: a p-value of
zero would make Γ\* unbounded.

There is no per-finding multiplicity correction, because there are no per-finding p-values to
correct. Both FDR estimators were implemented, neither was reachable from any code path, and
both were removed rather than left as a fallback that could not be invoked.

## 7. Schemas

### Result

```json
{
  "finding_id": "fnd_...", "scan_id": "scn_...", "rank": 1,
  "evidentiary_status": "screening_hypothesis",
  "significance": "none_attached_see_scan_level_test",
  "analysis_status": "confirmatory",
  "reason_outcome": "not_supported_by_public_record",
  "stated_reason_codes": [4],
  "record_ref": { "approved": "rec_...", "denied": "rec_..." },

  "rank_in_cell": 3.5, "cell_size": 14, "cell_power": "adequate",
  "min_attainable_p": 0.21, "gamma_star": 2.11,
  "margin_ratio": 4.2, "informative_dimension_count": 1,
  "block_degree": 13, "k_cohort": 11, "geo_level": "county",

  "tested": [ { "dimension": "...", "direction": "higher_is_worse",
                "order": "strictly_worse", "delta": 0.4,
                "decisive_threshold": 7.1, "within": true,
                "margin": -0.4, "outcome": "not_supported" } ],
  "bands": { "income": "80k-90k", "property_value": "275k-300k" },
  "county_code": "12345",
  "spec_digests": { }, "snapshot_id": "...", "pseudonym_key_version": 1
}
```

Fields carrying a decision:

- **No `q_value`.** `significance` states this explicitly in a field the renderer cannot drop.
- **`decisive_threshold` is per pair**, not per dimension.
- **`rank_in_cell` is a midrank** and therefore fractional. On bin-published dimensions ties
  are the normal case.
- **`margin` and `margin_ratio` are bucketed** to multiples of the dimension's own threshold
  before serialisation.
- **`order`** is the lattice position; `outcome` is its three-valued projection.
- **`informative_dimension_count`** exposes how many dimensions actually decided it. Because
  below-resolution dimensions are excluded and matching already forces both property values
  inside tolerance, collateral-code results are in practice decided by loan-to-value alone.
  Publishing the count means a two-dimension conjunction cannot be advertised while a
  histogram shows 95% single-dimension.

### Summary

The ordered denominator chain (PIPELINE.md §5) plus: `denials_incomparable`,
`findings_below_power_floor`, the coverage profile, `exact_null`, `scan_level_test`,
`control_results`, `margin_ratio_median`, `informative_dim_histogram`,
`block_degree_distribution`, `cell_size_distribution`, `cell_concentration_index`,
`content_hash`, `tripwire_breached`, `wall_time_by_stage`, and every digest.

`wall_time_by_stage` separates ingest, blocking, matching, reason, **statistics** and egress.
The statistical stage is where wall-clock risk first appears and it is instrumented from the
first commit rather than after the first timeout.

## 8. API

PIPELINE.md §4 has the route table and the three design decisions embedded in it.

**Latency budget.** p95 ≤ 500 ms on `/v1/pairs/evaluate` warm, budgeted as: specification
lookup from memory ≤ 5 ms, delta computation ≤ 20 ms, reason evaluation ≤ 20 ms,
serialisation ≤ 50 ms, framework overhead ≤ 100 ms. Cold start is out of budget and reported
separately.

## 9. Evaluation

### The label instrument

The label originally budgeted for does not exist: comparability given the public record is a
deterministic function of the specification, and comparability in fact needs a credit file
nobody here will have.

**Replaced with public-record rebuttal.** The labeller sees both records' full rows — not
only the matched fields — and answers one question with a forced justification:

> Naming a specific field, is there a difference visible in the published record and
> **outside** the matched field list that a fair-lending examiner would accept as a
> legitimate reason for the different outcome?
> `rebutted` (name the field and both values) · `not_rebutted` · `cannot_tell`

Excluded by name, not by judgment: `total_loan_costs`, `origination_charges`,
`discount_points`, `lender_credits`, `interest_rate`, `rate_spread`. These are populated only
for originations, are perfectly collinear with the outcome, and would rebut every pair.

**Adjudication.** Two labellers independently; disagreements to a blinded third adjudicator.
Agreement statistics on **pre**-adjudication labels, rebuttal rate on **post**-adjudication,
and which is which stated wherever a number appears. A rebuttal field that recurs is a field
that belongs in the matching key — the instrument feeds the pipeline.

### Reliability

**Gwet's AC1 as primary**, with a bootstrap interval, rather than Cohen's κ. κ is tunable by
the sample choice: at natural prevalence 0.05 with raw agreement 0.95, κ = 0.47 and a good
instrument fails a 0.60 gate; at boundary-oversampled prevalence 0.50 with agreement 0.80,
κ = 0.60 exactly and a worse instrument passes.

AC1 has the opposite failure at low prevalence — at agreement 0.90 and prevalence 0.05,
AC1 = 0.889 while a process indistinguishable from "always answer not-rebutted" clears the
gate. So **the gate sits on the boundary arm**, where prevalence is engineered near 0.5, with
a floor on positive-class specific agreement.

Intra-rater: a one-week washout re-label at n = 60, not 30. At n = 30 the AC1 interval
half-width is 0.14, so a point-estimate gate is a noise gate.

### Mutation testing

Kill rate ≥ 0.90 against a **published, pre-registered** catalogue; guard items 100%.
Published, because a kill rate against a private catalogue is unreviewable.

Guard items are written by a non-implementer from the specification documents only, never
from the engine, each carrying author, date and the bug class it witnesses.

Current: 52 entries, 52 killed, one recorded equivalent with its proof.

### Metamorphic properties

Swapping approved and denied inverts the margin sign wherever the comparison is resolved, and flips the outcome. Where it is not resolved the reported margin is a slack rather than a dominance, and the two directions sum to minus the combined interval width -- an exact identity, asserted as one. Adding a
constant to both property values does not change `matched`. Rounding both incomes to the
published bin changes no outcome. A null in a tested dimension lands in the incomplete bucket
and never in results.

## 10. Reproducibility

`content_hash` is a canonical hash over sorted logical rows at fixed numeric precision. The
guarantee is **content identity, not byte identity**. A CI test asserts two runs of the same
scan produce the same hash.

A deterministic wrong answer reproduces perfectly. This is a reproducibility property, not a
quality result.

## 11. Deferred

- **Geography hierarchy.** County, then MSA/MD, then state crossed with a coarse
  property-value stratum for non-metropolitan records, with `geo_level` on every result and
  the null stratified by level. A flat switch to MSA/MD was rejected: 14.9% of records fall
  into a single non-metropolitan catch-all spanning 1,973 counties.
- **`conforming_loan_limit` removal.** It is a deterministic function of loan amount, county,
  units and year, so it adds nothing beyond fields already in the key *and* deletes precisely
  the pairs that straddle the limit — which is the regression discontinuity worth running.
- **Snapshot as a third loader layout** at national scale.
- **Proxy-strength diagnostic** (MODELS §17), which is a policy decision rather than an
  engineering one.
- **Cross-filer index** with common-support standardisation.
- **Precision@K on lender verdicts**, which is not measurable without a design partner.
