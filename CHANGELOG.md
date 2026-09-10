# Changelog

## 0.14.0 — 10 September 2026

The statistics are now implemented twice, and the design's operating characteristics are
measured rather than assumed. A new `analysis/` package, barred from the served image by a
test, holds the second implementation, the simulation studies, the data profile, eleven
figures and a reproducible report.

### One defect, found by the cross-validation on its first run

`clopper_pearson_upper` summed the binomial CDF as a direct product of `math.comb(n, i)`
and the powers of p. At n = 2,995 with 1,497 failures — the size the binding gate's
assertion floor is built around — `comb(2995, 1497)` is an exact integer of some nine
hundred digits, and Python raises `OverflowError` converting it to a float, although the
product it appears in is a probability in [0, 1]. The sum is now taken in log space via
`lgamma`, agreeing with `scipy.stats.beta.ppf` to 7e-15 across the whole grid.

Every test in the suite had used a small failure count, so nothing in the suite could have
reached it. Two regression tests now pin the sizes the gate actually runs at, and a third
asserts the returned limit really is the root of `P(X <= k | n, p) = alpha`.

### `analysis/crossvalidate.py` — ten statistics, two implementations each

| Statistic | Checked against |
| :--- | :--- |
| `rank_p_value` | statsmodels ECDF, right-continuous so ties are counted the same way |
| `min_attainable_p` | exhaustive enumeration of every label placement |
| `core.midranks` | `scipy.stats.rankdata(method='average')`, plus the rank-sum identity |
| `stratified_rank_test` | NumPy variance and `scipy.stats.norm.sf` |
| the normal approximation | the exact conditional permutation null, simulated |
| `exact_expected_findings` | NumPy simulation driven through `scan.dominance_statistic` |
| `clopper_pearson_upper` | `scipy.stats.beta.ppf` **and** `statsmodels.proportion_confint` |
| `gamma_star` | Brent root-finding on Rosenbaum's worst-case bound |
| `abstain.fit_temperature` | `scipy.optimize.minimize_scalar`, Bounded |
| `cluster_bootstrap_ci` | NumPy cluster bootstrap over twelve independent seeds |

Tolerances are 1e-12 relative for exact checks and four Monte Carlo standard errors where
the reference is simulated — stated in standard errors so the tolerance tightens as B
grows and cannot be met by simulating less.

### `analysis/simulate.py` — what the design can and cannot do

Calibration under a true null across four publication regimes and three filing sizes:
twelve of twelve configurations calibrated or conservative, none anti-conservative. Power
against effect size, cell count and coarsening, with the minimum detectable shift falling
as 1/sqrt(cells) — 1.4 units at 100 cells, 0.8 at 300, 0.5 at 1,000. Coverage of the exact
binomial bound, conservative at every grid point. Coverage of the cluster bootstrap
against the naive row bootstrap, which covers 0.858 against a nominal 0.95 while being
narrower.

Two results are worth reading before the code. At the design's own cell sizes **no cell
can reach q = 0.05** — the best attainable p in any simulated cell is 1/8, decided by size
and ties before any comparison is made. And under a true null the finding rule still fires
on about a third of cells, because a small cell with a threshold below its spread produces
a finding by geometry; a raw rate would be mostly geometry.

The studies use a vectorised recomputation of the pooled statistic, guarded by a check
that rebuilds simulated filings as engine cells and asserts the z-statistics match. The
finding rule is guarded the same way, through `scan.dominance_statistic` itself.

### `analysis/eda.py`, `figures.py`, `report.py`

A data profile of both snapshots — publication grid, tie concentration, block and cell
structure, attainability — and eleven figures drawn only from the artefacts. The real
FFIEC slice and the generated fixture are labelled apart on every axis, because the
fixture is easier than reality in every direction that matters: 71% of its cells could
reach q = 0.05 against 18% of the real one's.

`ANALYSIS.md/.html/.pdf` is assembled from the JSON artefacts, so no number in it is typed
by hand. `make analysis` rebuilds all of it.

### The boundary is enforced, not described

`tests/test_analysis_boundary.py` parses every source file in `likewise/` and `extract/`,
function bodies included — a lazy import never executes during a test run and would be
invisible to a runtime check — and fails the build if any of them imports numpy, scipy,
pandas, statsmodels, matplotlib, sklearn or `analysis`, or if those names appear in the
served requirements. The suite is 249 tests.

### Documents

The requirements specification, architecture description and design description now state
the two-tier dependency story rather than only the short list, and carry three new
acceptance criteria: every published statistic agrees with an independent reference; the
pooled test is never anti-conservative; the minimum detectable effect and interval
coverage are measured and published.

## 0.13.0 — 10 September 2026

A documentation pass over the source. **No executable code changed** — verified by
parsing every file at the previous tag and at HEAD, stripping docstrings from both trees
and comparing the ASTs. 1,303 lines added, all of them comment or docstring.

### Every module says what it owns and what it does not

Twenty plumbing and presentation modules gained banner comments dividing them into named
sections, and a module docstring stating the boundary. The renderers in `web/` now say in
each file that they only ever see stored, post-egress artefacts.

### The mathematics is named where it is applied

The nine modules that carry mathematical content gained an orientation block listing every
model implemented in that file, in plain terms, before any code — and inline notes at each
formula explaining not just what it computes but why that form rather than the obvious
alternative:

- **`stats.py`** — the empirical CDF as an exact p-value and why ties make it not one
  line; Rosenbaum sensitivity and what Γ actually bounds; the van Elteren / CMH pooled
  rank test and why a median cell of three makes it necessary; Fisher's randomisation
  test and the adaptive draw budget; the closed form that removes the seed; the cluster
  bootstrap behind the publication gate.
- **`core.py`** — blocking as a matched design and what it buys and costs; interval
  arithmetic and why a partial order is the honest object; midranks; the attainability
  floor that is not a power calculation.
- **`specs.py`** — error propagation, stated as such. Why a threshold certified at one
  reference magnitude fails everywhere cheaper, in the direction that manufactures
  findings.
- **`binding_gate.py`** — Clopper–Pearson by bisection, and why the rule of three is its
  large-*n* approximation at *k*=0.
- **`compare.py`**, **`precedent.py`** — order theory: the box-shaped admission region,
  Chebyshev slack as the only order-consistent scalar, reduction to boolean containment
  at zero tolerance.
- **`extract/abstain.py`** — temperature scaling, ternary search on a unimodal NLL, and a
  precision-constrained threshold rather than an F1 optimisation.
- **`scan.py`**, **`extract/roundtrip.py`** — k-anonymity ordering, two-sided tripwires,
  and why an undefined precision is reported as undefined.

### A gate caught the documentation

The SQL lint scans this codebase's own string content for null-equating join operators.
It failed on a new module docstring in `core.py` that named the forbidden operator while
explaining why it is forbidden. The prose was reworded rather than the gate weakened.

### Verification

242 tests · mutation kill rate 78/78 · ruff clean · ASTs identical to 0.12.0.

---

## 0.12.0 — 10 September 2026

Publication readiness. No behaviour changed; the suite, the gates and the specification
in force are all as they were in 0.11.0.

### Licensed

**Apache License 2.0**, with a `NOTICE`. Apache rather than MIT for two reasons specific
to this kind of tool: it carries an explicit patent grant, which a compliance function's
own counsel looks for before adopting anything that touches lending decisions, and it
obliges a distributor to state what they changed, which suits a project whose whole
posture is that the standard a result was judged under must be nameable.

Every runtime dependency was checked rather than assumed — duckdb, fastapi and PyYAML are
MIT, uvicorn is BSD-3-Clause, python-multipart is Apache-2.0 — so either licence would
have been compatible. HMDA data is published by the United States government and is not
subject to copyright; the `NOTICE` says so.

### The documents made fit for an outside reader

- **The `measured` markers are gone.** They were an internal convention separating claims
  verified against running code from proposals. The distinction matters to an outside
  reader too, so it is now carried in plain wording rather than a private notation.
- **Twenty-eight dangling pointers removed.** References to a technical design, a solution
  design, numbered wireframes and numbered acceptance criteria — none of which travel with
  this repository — replaced by what each one actually meant.
- **`PRECEDENCE.md` reframed.** It described a five-member panel with vote tallies (5/5,
  4/5) and named dissenters. Published, that reads as five people having reviewed and
  signed off. That is not what happened: it was ten propositions worked through from five
  specialist perspectives by one author. The propositions, the outcomes and both
  objections are unchanged; only the implied external review is gone.

### Distributables

`make onboarding-pack` builds the joiner pack. Two rendered documents ship alongside the
source as PDFs: the system reference and the plain-language walkthrough.

---

## 0.11.0 — 9 September 2026

The binding acceptance gate — `likewise/binding_gate.py`. `PRECEDENCE.md` §8 specified it
in words and nothing implemented it: `admit` and `rule` had unit tests showing they do what
they were written to do, and nothing established that what they were written to do is right
on a corpus.

### One-sided, deliberately

A missed bind costs a reviewer a case they must decide themselves. A **false bind** compels
a decision from a precedent that does not govern, and its audit trail is accurate in every
field, so nothing downstream can catch it. The gate bounds false binds and merely *reports*
missed ones; gating recall would trade the expensive error for the cheap one.

### Three things came out stricter than the specification

- **The bound is exact, not the rule of three.** `clopper_pearson_upper` solves the
  binomial CDF by bisection in the standard library — no scipy, consistent with the rest of
  the engine. At zero failures it reproduces §8's floors and sharpens them: the true minima
  are **299** and **2995**, so 300 and 3000 were right and slightly conservative. Unlike the
  rule of three it returns a bound when there *are* failures, which makes a near miss
  legible rather than merely failed.
- **Binding on the wrong precedent is a false bind.** Agreeing that *something* governs is
  not agreeing. `bind_wrong_precedent` is separated from `bind_agreed` and counts against
  the bound.
- **A pass on a self-authored oracle alone is refused.** §8 named the independence risk —
  computed truth is a second program from the same rulebook, so a shared misreading reads
  as perfect precision — and proposed reporting the independent arm separately. Reporting
  is not enough: an arm that is only ever reported is the arm quietly left empty. Below its
  floor the verdict is `inconclusive`, with the cause named.

  The arm is bounded on its own count, never pooled. On a worked run: 340 pooled binds bound
  the rate at 0.88%, while the 43 independent ones bound it only at 6.7% — which is the
  number that should govern belief.

### The traps it refuses

| Condition | Verdict |
| :--- | :--- |
| Cases used to fit the tolerances also used to evaluate them | `invalid` |
| Any bind on a guard case | `fail`, at any *n* |
| Fewer binds than the floor (3000 where an absolute provision is present) | `inconclusive` |
| Independent arm below its floor | `inconclusive` |
| False-bind upper bound ≤ target | `pass` |

`false_bind_upper` returns `None` on zero binds, never `0.0` — an engine that abstains on
the whole docket has a false-bind rate of zero and is useless.

Six verdicts, not four: `abstain_agreed` and `abstain_diverged` stay apart, because the six
case outcomes exist so that "nothing retrieved" and "everything distinguished" do not
collapse into one empty set. A run whose abstentions are all correct for the wrong reason
passes the gate and is still telling you something.

### The demonstration

Built on the real `admit` and `rule`, not a mock. A case silent on a premise dimension has
one correct outcome, `PREMISE_NOT_ESTABLISHED`. A permissive `rule` — one that reads a
missing value as "no worse", which is the natural implementation and exactly what the status
ladder forbids — binds instead. The guard catches it and the gate fails. The correct engine
still binds across the whole admission ladder (`a_fortiori` at and below the premise,
`tolerant` inside tolerance, `distinguished` beyond it), so the demonstration shows both
halves rather than rewarding an engine that never binds.

### Also

`PRECEDENCE.md` §8 rewritten from specification to record: the oracle path marked **built**,
replay determinism **closed**, oracle independence **mitigated** — with the remaining open
question named, which is what *fraction* of independent authorship is enough. That is a
governance question and belongs in a specification, not in a default.

### Verification

242 tests · mutation kill rate 78/78 · ruff clean.

---

## 0.10.0 — 9 September 2026

The round-trip harness: measuring an extractor against ground truth the corpus already
carries. The engine is untouched again — materiality 1.4.0, no tolerance or band moved.

### The goal 0.9.0 did not state

0.9.0 built the constraint system around an extractor without settling what would feed it.
Both corpora are already structured: HMDA by the regulator, the judiciary corpora by their
generator. The generator is also the answer. Its records carry **computed** ground truth,
so rendering one into prose and extracting it back gives a measured accuracy with no human
labelling — and adjudicated truth is the one input `calibrate_extractor.py` cannot
synthesise.

### An upper bound, stated as one

The renderer and the extractor share a vocabulary; a real filing was written by someone who
had never seen the renderer. Every report carries that as a field, not a footnote — the
same discipline that marks Rosenbaum's Γ `not_applicable: generated_corpus` rather than
transplanting a number that looks like the lending one.

### Seven verdicts

Three extractor statuses against two truth states do not collapse into right and wrong.
`wrong` and `hallucinated` are the expensive errors — each puts a value the record does not
support in front of the gate. Every silence is cheap. The headline is **assertion
precision**, never F1, which would average the expensive error against the cheap one.

### The gate, and the trap it avoids

Mirrors the binding gate in `PRECEDENCE.md` §8: perfect precision is trivially satisfiable
by never speaking, so `assertion_precision` is `None` rather than `1.0` on zero assertions,
and the gate returns `inconclusive` below an assertion floor.

- **A style in both splits returns `invalid`.** If the evaluation styles were trained on,
  the number is memorisation. The extraction analogue of the held-out corpus revision that
  tolerance selection may not touch.
- **One guard assertion fails at any n.** Guard records put the value in the prose while
  the record does not carry it — "is *not* severe", "counsel asserted … which the court did
  not reach", "in the cited matter". Silence is the only correct behaviour. Guard styles
  are held out of training; a guard the extractor was trained on is not a guard.
- **Only assertions become labelled readings.** A silence is the absence of a reading, not
  a wrong one; feeding silences to a threshold fitter as negatives pushes the floor *down*.

### The guards are shown to have teeth

`LiteralMatchBackend` — find the label, take what follows — is accurate on plain prose and
correctly silent on genuinely absent fields. On the guard styles it asserts confidently and
wrongly. Measured on the shipped harness: 120 guard assertions, gate `fail`, assertion
precision 0.73.

The instructive part is *how* it fails. Its confidence stays high on the guards, so **a
confidence floor does not rescue an extractor from a representational blind spot** — the
floor governs uncertainty a model can express and is silent about errors it cannot see.
That is why the gate reads guard assertions directly rather than trusting calibration to
have caught them.

### Verification

214 tests · mutation kill rate 72/72 · ruff clean.

---

## 0.9.0 — 9 September 2026

An optional offline extraction stage, `extract/`, that reads prose records into the same
structured form the engine already consumes. Nothing in the engine changed: materiality
1.4.0 is still in force, no tolerance or band moved, and `likewise/` still runs on five
wheels.

### Why a model, and only here

HMDA arrives structured — that is the comparability argument, not a convenience. A court
record arrives as prose, and something has to produce the typed dimension vector the gate
consumes. The gate itself stays symbolic: admission is a box, and no learned score has
super-level sets that are boxes in more than one dimension.

### Backbone survey, September 2026

**No new encoder architecture was released in 2026.** Every 2026 encoder is a domain
adaptation of ModernBERT, so the choice was among checkpoints rather than designs.

Default is `caselaw-modernbert-large` — ModernBERT-large continued-pretrained on 8.3M US
court opinions, Apache-2.0, 8192 context. It is a **prior, not a result**: token
classification has not been measured on that checkpoint, `modernbert-large` is kept in the
set as the control arm, and `tools/train_extractor.py --control` trains both identically
and prints the gap.

Two findings shaped the set, and neither is a headline benchmark. ModernBERT's advantage
over DeBERTaV3 is largely *data*, not architecture — under matched pretraining data
DeBERTaV3 wins token classification by about 1.4 F1 — so `deberta-v3-large` stays as a
chunked comparison arm rather than being written out. And the ModernBERT tokenizer
prepends whitespace on a plain call, costing about 1.7 F1 on CoNLL; `add_prefix_space` is
recorded per backbone and asserted by a test.

### Silence is the safety property

Three statuses. `OBSERVED` emits the value; `ABSTAINED` and `ABSENT` both emit `None`, and
a `None` on a premise dimension is `UNRECORDED` — which outranks distinguishing and breaks
the bind. An extractor that is unsure produces silence, and silence never binds. This is
what 0.8.0's `UNRECORDED` split was for, built before anything produced silences.

- `FieldValue` refuses at construction to let a silent field carry a value.
- `ABSTAINED` and `ABSENT` stay distinct in the audit even though the engine cannot tell
  them apart, or the extractor's own miss rate is unmeasurable against true absences.
- An uncalibrated field gets no default floor. A borrowed threshold is this design's
  characteristic failure.

### The floor is governance, not a hyperparameter

`specs/extraction/1.0.0.yaml`, signed and versioned like every other standard here, with
seven gate rules. E4 refuses a floor of zero rather than clamping it: zero is not a lenient
threshold, it is the absence of one, and it makes the abstention path unreachable.

Floors are fitted **for precision at a declared target, never for F1** — a missed field
abstains, which is cheap; a hallucinated one binds, which is not. `calibrate_extractor.py`
exits non-zero and says to drop a field that cannot reach the target, rather than lowering
it. Calibration carries the corpus it was fitted on, because encoder confidence collapses
under domain shift: error-detection AUROC 0.922 in-domain against 0.633 out, with
calibration error 0.36–0.41. No published calibration numbers exist for any candidate
backbone at all.

### The engine keeps its five dependencies

torch is 555 MB of wheel against DuckDB's 21.5, before a checkpoint of 300 MB to 1.6 GB.
Extraction runs offline in its own virtualenv (`make extract-env`) and produces a snapshot;
`likewise/` never imports a model runtime, and a test asserts that over every file in the
package. `extract` itself imports no heavy dependency — the whole pipeline, abstention and
provenance included, is exercised in the suite with a seeded deterministic backend and no
weights.

### Verification

196 tests · mutation kill rate 67/67 · ruff clean.

---

## 0.8.1 — 9 September 2026

Two defects, both of the same shape: a default that was correct when it was written,
inherited by callers nobody revisited. No matching rule, tolerance or band changed.

### The suite and the command line ran a specification the service did not serve

`specs.load()` defaulted to the literal string `"1.0.0"`. 0.8.0 fixed the service to name
its version through `load_in_force()` and left every other caller on the default: the
shared test fixture, so 138 of the tests validated materiality 1.0.0; `tools/run_scan.py`,
so `make scan` produced findings under 1.0.0; and `tools/load.py`, pinned separately at
1.2.0. Between 1.0.0 and 1.4.0 the control features moved into residual risk, the blocking
bands widened to ±22%, and decisive thresholds became per-pair — so this was not a stale
label, it was a different comparability standard.

Nothing failed, because every artefact recorded the version it had actually used. The
versions simply disagreed, and no reader had two of them side by side.

`version=None` now means the version in force. Replay is unaffected: naming a version
explicitly is what a replay does. Two tests enforce it, one of them linting `tools/` for
`--spec-version` defaults.

Pointing the suite at the specification in force surfaced three tests that had stopped
testing what they claimed:

- **The role-swap metamorphic property was false.** "Swapping approved and denied inverts
  every margin" holds for point values. Under intervals the two directions sum to minus
  their combined width, and combined loan-to-value is published to three decimals. It
  passed only because 1.0.0 declared no reported half-widths. The property is now stated
  in two parts — exact inversion where the comparison is resolved, an exact width identity
  where it is not — and both are asserted without a tolerance.
- **The post-treatment guard was demonstrated on a field no longer in the key.** 1.2.0
  removed `initially_payable_to_institution` from the blocking key for exactly the reason
  the guard exists, after which the test constructed a separation on a field nothing
  matched on and asserted a refusal that could no longer occur. It now asserts its field
  is in the exact-match set before using it.
- **The matcher's no-early-return guard had become vacuous.** With the control set empty
  the loop it guards has nothing to be early about. It is driven from 1.0.0 explicitly,
  with the reason recorded, and a new test states the live consequence: under the
  specification in force `MatchResult.deltas` is empty on every pair, so the
  delta-to-tolerance stratification cannot be built from it. The coarse numeric filter
  still runs — as the blocking bands, in SQL, before `match()` is reached.

### Replay was not deterministic

`core.candidate_sql` carried no `ORDER BY`, while the scan reads `comparators[0]` to
decide the untestable cause and seed the reference distribution, breaks ties in two
`max()` calls, and walks a seeded permutation stream across the null cells in the order
they were built. The connection sets `preserve_insertion_order=false` and the build is
multi-threaded, so the same input could produce a different null and a different reported
comparator. `content_hash` cannot detect this — it is computed over the findings that were
emitted, and certifies that a result was not edited afterwards, not that the same input
would produce it again.

- `ORDER BY denied_key, approved_key` — total, on a pair unique per row. Ordering on the
  denial alone would leave exactly the ties that matter.
- Both `max()` calls carry a declared tiebreak. Ties are not rare: comparators identical
  on the tested dimension all share one margin, and which is reported decides what a
  reviewer opens first.
- `tests/test_determinism.py` asserts the query declares a total order, that it survives a
  reversed physical row order, and that a whole scan over reversed input is identical
  field for field. Removing the `ORDER BY` fails three of the four.

This was the blocker on the oracle work named in `docs/PRECEDENCE.md` §8. A confusion
matrix of disposition changes across engine versions means nothing while one version can
disagree with itself.

### Verification

158 tests · mutation kill rate 62/62 · ruff clean.

---

## 0.8.0 — 9 September 2026

Specification **1.4.0** in force. No tolerance, band or key membership changed: every
result under 1.3.0 is a result under 1.4.0.

### The engine serves a second question

`likewise/precedent.py` — admission when a prior decision **governs** rather than being
flagged. The error asymmetry inverts there: a false flag costs a reviewer an hour with a
file, while a decision governed by a wrongly-admitted precedent is compelled and its audit
trail is accurate in every field.

- An ordered status ladder in which **silence outranks distinguishing**. A premise
  dimension the present case does not record is not one the case is at least as strong on;
  it is a premise nobody established.
- Six mutually exclusive case outcomes, so the four abstention causes — nothing retrieved,
  everything distinguished, premise not established, admitted-but-not-orderable — stay
  distinguishable rather than collapsing into one empty set.
- Ties in the authority order **abstain rather than resolve**.
- `Ruling` carries no score and no disposition, enforced by a test that reflects over its
  fields.

`likewise/compare.py` — the unordered element split into `TIED`, `AMBIGUOUS` and
`UNRECORDED`. An exact tie was previously marked unresolved, making the strongest possible
a-fortiori bind indistinguishable from a silence. All three still project to
`below_resolution`, so the lending instantiation is unchanged.

### Defects fixed

- **The service was serving materiality 1.0.0.** `specs.load()`'s version argument
  defaults and `api.py` never passed one, so `multi_code_policy` — which 1.4.0's own
  rationale calls a versioned decision rather than a tuning knob — came from a Python
  fallback. `specs.load_in_force()` names the version once and refuses to serve an unsigned
  specification. Historical versions stay loadable for replay.
- **An exact tie was marked unresolved** (see above).
- **Rule 5 was sound for only one reference side.** Its scalar band-versus-tolerance
  comparison holds only when the tolerance is evaluated at the smaller magnitude;
  `Tolerance.reference` accepts `min`, `max` or `mean` and was never validated.
- **A vacuous tolerance passed the gate.** At or above a dimension's span a tolerance
  switches the dimension off rather than loosening it.

### Validation rules

Eleven now, plus 1b. New:

| Rule | Requirement |
| :--- | :--- |
| 10 | A tolerance is below its dimension's own declared span |
| 11 | A banded relative tolerance declares its reference side, and it is `min` |

### Documentation

- `docs/PRECEDENCE.md` — the design record: the ten propositions, both objections, the four
  defects, and the named open items.
- `docs/DISTINGUISH_ENGINE.md` — the correspondence with a second domain's gate.
- `onboarding/` updated throughout.

### Verification

151 tests · mutation kill rate 59/59 · ruff clean.

---

## 0.7.0 — 8 September 2026

Specification 1.3.0. Composable comparison lattice, named resolution models, gate rules 8
and 9, the exact closed-form null, and the onboarding pack.

- **Rule 8** — a tested dimension may not appear in the blocking key, the exact-match set
  or the bands. Matching a dimension and then testing it are contradictory operations.
- **Rule 9** — a residual-risk band must be strictly wider than its own tolerance, or
  blocking removes every pair the residual clause could fire on.
- The exact expected-finding count implemented as a closed form; a test asserts it agrees
  with the permutation to within Monte Carlo error.
- Per-finding FDR estimators deleted rather than left unreachable.
- A tripwire on the pooled scan-level test — the only inferential claim the product makes,
  and nothing read it.
- Container path defects: `api.py` and `loader.py` bypassed `paths.py`, and the
  `Containerfile` never set `LIKEWISE_DATA`.
- `ruff` wired into `make check` and `install.sh`; `pyproject.toml` added.
- `web.py` split into a package. No template engine.

## 0.6.0 and earlier

Statistical rework following first contact with the full national file: the permutation
null rebuilt over every matched testable denial, per-finding significance abandoned in
favour of a pooled stratified rank test, interval dominance, per-pair decisive thresholds,
and Rosenbaum sensitivity per finding and per specification.
