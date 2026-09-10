# Admission Under a Rule of Precedence

The design record: what was decided, what was built, and what was deliberately not.

| | |
| :--- | :--- |
| Document | Design record |
| Author | Arun Kadambi |
| Date | 9 September 2026 |
| Method | Ten propositions worked through from five specialist perspectives — two on architecture, two on statistics, one on governance and domain — deliberately set in opposition to each other. These are perspectives taken in sequence by one author, not five reviewers, and nothing here is external sign-off. |
| Related | DISTINGUISH_ENGINE.md, `likewise/precedent.py`, `tests/test_precedent.py` |

---

## 1. The question

Today the engine finds comparable records to **flag** inconsistency: the output is "go look
at this file". A rule of precedence asks something else — a new case is checked for likeness
to a previous adjudication, and if it is alike enough, **the previous adjudication governs.**

The question was how to decide that two records are close enough for a prior adjudication to
bind. Ten propositions were put and worked through from each perspective in turn.

## 2. The ten propositions

All ten were adopted. Two drew an objection worth preserving, and both objections changed
what was built.

| | Proposition | Outcome |
| :--- | :--- | :--- |
| P1 | Bindingness is a partial-order test, never a scalar similarity crossing a threshold | Adopted |
| P2 | Add a third stage: controlling-precedent selection among admitted survivors | Adopted |
| P3 | A declared conflict rule is required; absent one, refuse rather than pick | Adopted |
| P4 | A-fortiori admission is a distinct, stronger status than tolerant admission | Adopted |
| P5 | Tolerances and thresholds are constitutional objects on the existing spec mechanism | Adopted |
| P6 | The error asymmetry inverts; abstention is a first-class outcome | Adopted |
| P7 | The coherence rules extend to the new controlling stage | Adopted |
| P8 | Retrieval similarity must be tolerance-aligned rather than a separate metric | Adopted, objection recorded |
| P9 | Build in-repo now rather than extracting a kernel first | Adopted |
| P10 | No scalar closeness score on a binding record | Adopted, objection recorded |

### The two objections

**P8 — the architecture perspective objected,** and the objection is structural rather than about
calibration. Aligning a scalar retrieval score keeps a threshold θ upstream of the gate; a
record retrieval never returns cannot bind, so under enforcement that θ *is* the bindingness
criterion, which is what P1 exists to forbid. The seat's alternative: rule 8 already removes
tested dimensions from retrieval entirely, and `core.boundary_sequence` builds a lossless
bucket cover from the tolerance itself — an index with a proof of recall and no threshold at
all. *"Adopt rule 8 and P8 has nothing left to align on; adopt P8 and you have preserved the
shape of the defect while fixing its calibration."*

Recorded because it is right about the direction of travel even though the proposition
carried.

**P10 — the statistical perspective objected,** on the ground that the honest object is not a
similarity but **Chebyshev slack in tolerance units**, `min_d (m_d − δ_d)/m_d`, which is
order-consistent with admission by construction. Suppressing it does not stop readers
building a proxy; it stops them building the correct one.

**Resolution adopted:** slack is implemented as `precedent.slack()` and is *not* a field on
the emitted `Ruling`. It is a diagnostic for a specification author asking "how close was
that", not a number printed beside a decision. Both positions are honoured and a test
enforces the boundary.

## 3. What emerged that was not among the ten

Four seats independently reached the same conclusion, which makes it the most important
outcome of the exercise.

> **Silence must never bind.**

A premise dimension the present case does not record is not a dimension on which the case is
at least as strong. It is a premise nobody established.

Under flagging this was harmless and the repository has a test asserting it is *correct*: an
unrecorded dimension produced a NaN margin, was excluded from the conjunction, failed the
existential strict clause, and nothing was emitted. The incompleteness was absorbed.

Under precedence the same record passes "not distinguished" and governs. Every field on the
resulting decision is accurate. The defect is that **"not shown weaker" was read as "shown at
least as strong"** — and where a retrieval miss compels a decision anyway, the failure is
self-concealing.

Two seats added the observation that makes it urgent: if gate discards really do concentrate
at the single-dimension margin, the modal case sits exactly on this boundary. The failure
would not be a tail. It would be the centre of the distribution.

## 4. Four defects the review found in the existing code

All four were reproduced against the running code before being fixed, and each is covered
by an entry in the mutation catalogue.

All four verified against the running code before acting on them.

### 4.1 The service was serving the wrong specification

`api.py` called `specs.load(spec_dir)` with no version. `load`'s signature defaults to
`"1.0.0"`, so **the running service served materiality 1.0.0** — unsigned, with no
`comparison` block — which meant `multi_code_policy`, a setting 1.4.0's own rationale calls
*"a specification decision with a version and a rationale, not a tuning knob"*, was being
supplied by a Python fallback in the engine.

A default argument is not a decision. Fixed by `specs.load_in_force()`, which names the
version in force in one place and **refuses to serve an unsigned specification**. Historical
versions stay loadable for replay, because a decision must be reproducible against the
standard in force when it was made; it is *serving* one that is refused.

### 4.2 An exact tie was marked unresolved

`resolved = order != INCOMPARABLE` meant two point values at the same place reported
`resolved=False`. Under precedence an exact tie is the **strongest a-fortiori bind there is**
— the present case matches the premise exactly — and it was indistinguishable from an overlap
and from a silence.

`INCOMPARABLE` was in fact three states collapsed into one:

| | Meaning | Under precedence |
| :--- | :--- | :--- |
| `TIED` | the order IS identified: the records sit at the same value | binds, a fortiori |
| `AMBIGUOUS` | published intervals overlap; the record does not order them | premise not established |
| `UNRECORDED` | the record does not speak to this dimension at all | premise not established |

Now three lattice elements. `TIED` is `resolved`; the other two are not. All three still
project to `below_resolution` in the legacy three-valued outcome, so nothing in the lending
instantiation changes.

### 4.3 Rule 5 was sound only for one reference side

Rule 5 compares the blocking band and the matcher tolerance as scalar coefficients. That
comparison holds only when the tolerance is evaluated at the *smaller* of the two magnitudes.
`Tolerance.reference` accepts `min`, `max` or `mean`, is read straight from YAML with
`v.get("reference")`, and **was never validated**. At `max` or `mean` the same coefficient
buys a wider absolute window than the band, and blocking drops pairs the matcher accepts —
the exact loss rule 5 exists to prevent, reintroduced through the reference side.

Every shipped specification happens to use `min`. Now **rule 11** requires it.

### 4.4 A vacuous tolerance passed the gate

A boolean dimension spans 1.0, so a tolerance of 1.0 admits every case regardless of the
factor. The dimension has not been loosened; it has stopped participating. The repository's
own test demonstrates this and the gate accepted it. Now **rule 10**: a tolerance at or above
a dimension's declared span is refused.

## 5. What was built

### `likewise/compare.py` — the lattice split

Seven elements rather than five. `TIED`, `AMBIGUOUS` and `UNRECORDED` replace the single
collapsed value, with `UNORDERED` as the named family so a caller can ask the question
without enumerating.

### `likewise/precedent.py` — admission, and four ways to abstain

**Per candidate**, an ordered status ladder. The order is the safety argument:

```
PREMISE_UNPROVEN  outranks  DISTINGUISHED  outranks  TOLERANT  outranks  A_FORTIORI
```

Silence first, because a premise nobody established cannot govern however favourable the
recorded dimensions look. A favourable dimension does not rescue an unestablished premise.

**Per case**, six mutually exclusive outcomes, so the counts sum to the docket by
construction:

| Outcome | Meaning |
| :--- | :--- |
| `GOVERNED` | a controlling precedent was found |
| `NO_CANDIDATES` | retrieval returned nothing |
| `ALL_DISTINGUISHED` | candidates existed; every one was distinguished on the merits |
| `PREMISE_NOT_ESTABLISHED` | the case is silent, or unsettled, on a premise dimension |
| `NO_CONTROLLING` | admitted, but the authority order is not total on the admitted set |
| `CONFLICT_UNRESOLVED` | admitted precedents disagree on disposition |

The four abstention causes are four different events. A naive implementation returns an empty
list for all of them and the audit trail cannot tell them apart.

**Ties in the authority order abstain rather than resolve.** Two precedents of equal standing
is a question for the constitution; picking one by sort position is precisely the failure this
module exists to avoid.

**`Ruling` carries no score and no disposition.** Enforced by a test that reflects over the
dataclass fields and refuses `score`, `similarity`, `confidence`, `closeness`, `probability`,
`disposition`, `p_value`, `gamma_star`, or any bare float. A future commit that adds a
closeness score to a decision record breaks a test rather than a norm.

That last one was argued for with a counter-example from this repository: `METHOD.md` states
that no field could imply per-finding significance, and `egress.py` publishes `rank_p_value`,
`gamma_star` and `min_attainable_p` on every finding beside a field that says none is
attached. **A caveat string failed at screening severity.** It will not hold beside an
enforced disposition.

### Validation rules 10 and 11

Eleven rules now, plus 1b. Both new ones carry CI fixtures that violate them.

### The order-consistency proof, mechanised

The admission region is a box: every dimension within its own tolerance. A weighted or
additive score has a halfspace for a superlevel set, and a halfspace is a box only in one
dimension. So **no weighted similarity can be made order-consistent with admission**, at any
weights, for any threshold.

`test_no_weighted_score_reproduces_the_admission_region` enumerates a 2-dimensional grid,
asserts that no weight/threshold pair reproduces the admission set, and asserts that the
Chebyshev minimum reproduces it exactly. It converts the argument into a failing assertion
the moment somebody adds a score.

## 6. The governance position, recorded in full

The fifth seat was asked to take a position on whether this class of system should enforce at
all, and did:

> **No. The correct output is:** *"controlling precedent r, on these premise dimensions, at
> these margins, under tolerance vector 1.4.0 / sha256:… — apply it or distinguish it in
> writing."*

Three grounds:

1. `premise(r)` is *the factors the holding rested on* — an interpretive judgment about a
   prior decision, made by whoever encoded it. The engine binds on an encoding of a holding,
   not on the holding, and nothing in the pipeline distinguishes "correctly extracted" from
   "extracted".
2. Precision is computable only against a computed oracle in a generated corpus. Precision
   earned synthetically does not license enforcement on a real docket, and the sensitivity
   ceiling on real records is already below what the effect needs.
3. Where a retrieval miss compels a decision, the rationale trail is **false by construction**
   on exactly the cases that matter: it truthfully reports a consulted set that never
   contained the controlling record.

A rebuttable duty to respond captures nearly all the consistency benefit at a fraction of the
legitimacy cost. Enforcement adds automation, not correctness.

**This is why `Ruling` has no disposition field.** The module surfaces a controlling
precedent. What a decision-maker owes one is a constitutional question, and the engine is not
the place it gets answered.

## 7. On fitting the tolerance

The review refined the standing argument rather than repeating it. Fitting `m` on dispositions
the system produced is fitting `m` on `m`. But the circularity is **not** present against an
oracle corpus, because the oracle disposition is computed by an independent reference engine
that never consults `m`. So the oracle measures a tolerance's *consequences* without
licensing its *choice*.

What follows procedurally: `m` stays declared, never fitted — but *not learnable* is not *not
accountable*.

> **No superseding tolerance version may be published without its disposition-delta:** how
> many recorded dispositions the change flips, in which direction, against the frozen oracle
> corpus, plus the alternatives considered and rejected.

"We chose 3.0" is not a rationale. "We chose 3.0; 2.0 flips 41 toward binding, 4.0 flips 12
away" is.

## 8. Named open items

Carried out of the review and recorded so they are not rediscovered. Three are now closed and
are kept here with what closing them changed, because an item that vanishes when it is
done takes its reasoning with it.

**The oracle path — BUILT.** `likewise/binding_gate.py`, `tools/run_binding_gate.py`.
The corpora carry computed ground truth, which makes precision and recall of a binding
decision directly measurable — unlike the lending instantiation, where the core value claim
is admitted to be unevaluable.

The gate as built: on a held-out corpus revision **not used for tolerance selection**, ≥300
oracle-verified binds bounding the false-bind rate at ≤1%; 3000 for an absolute provision.
**Guard items must be 100% abstained or distinguished — a single guard bind fails at any n.**
Below the n floor the verdict is *inconclusive*, never pass, because perfect precision is
satisfiable by never binding.

Three things came out different from the specification above, and all three are stricter.

*The bound is computed exactly rather than by the rule of three.* `clopper_pearson_upper`
solves the binomial CDF by bisection in the standard library. At zero failures it reproduces
the section's numbers — the true minimum floors are **299** and **2995**, so 300 and 3000 are
right and slightly conservative — and unlike the rule of three it still returns a bound when
there are failures, which makes a near miss legible instead of merely failed.

*Binding on the wrong precedent is a false bind, not an agreement.* Agreeing that
*something* governs is not agreeing. The verdict taxonomy separates `bind_agreed` from
`bind_wrong_precedent`, and both the latter and `false_bind` count against the bound.

*A pass on a self-authored oracle alone is refused, not merely annotated.* See the
independence item below.

**Replay determinism — CLOSED in 0.8.1.** `core.candidate_sql` had no `ORDER BY`, and
`scan.py` read `cell["comparators"][0]` in two places and took a `max()` whose ties broke by
arrival order, under `preserve_insertion_order=false` with two threads. `content_hash` is
order-independent over emitted findings and could not detect it. Now a total order on
`(denied_key, approved_key)` with declared tiebreaks; `tests/test_determinism.py` fails three
ways when the `ORDER BY` is removed.

**Temporal validity** — `¬lapsed(r)` — has no analogue here and can break coherence from a
new direction: a lapse filter is a retrieval filter while recency is an authority-ordering
attribute, so rule 8's analogue may forbid the composition. Specify before building.

**Rule 8's analogue may be unsatisfiable at scale.** `tested_dimensions` unions across every
testable code; in the judiciary that union is ⋃_r dims(premise(r)). Where premises span the
factor vocabulary, rule 8 leaves retrieval nothing to filter on and scale must come from the
provision index and the validity window alone. Better said now than discovered at corpus
scale.

**The oracle may not be independent of the engine — MITIGATED, and the mitigation is
refusable.** Computed ground truth is a second program written from the same rulebook, and
guard items are written by the same authors. A shared misreading of a provision reads as 100%
precision and is in fact measured agreement between two implementations of one error.

Every `OracleCase` declares an `arm`, and the independent arm is bounded **on its own count**
rather than pooled — on a worked run, 340 pooled binds bound the rate at 0.88% while the 43
independent ones bound it only at 6.7%, which is the number that should govern belief.

The mitigation as originally proposed was to report that arm separately. Reporting is not
enough: an arm that is only ever reported is the arm that is quietly left empty. The gate
therefore returns **`inconclusive`** when the independent arm is below its floor, with the
cause named. A pass on a self-authored oracle alone is not a pass.

What remains open is the *fraction*: `min_independent_binds` defaults to 1, which refuses an
empty arm but does not state how much independent authorship is enough. That is a governance
question, not an engineering one, and it should be settled in a specification rather than a
default.

**Rationale is scraped, not validated.** It is recovered by string-matching a comment inside
the YAML and enforced only by a web contract test, never by `specs._validate`. It should be a
required structured field carrying `supersedes`, `alternatives_rejected` and the
disposition-delta.

**There is no amendment channel.** The service has `read` and `write`; who may edit a
tolerance is governed by filesystem access. Proposed: an `amend` scope requiring two distinct
named principals, and a prohibition on the same principal amending a tolerance and disposing
of a case decided under it.
