# Design review record v3 — the distinguish engine and dual-domain reuse

Review received against 0.8.0. This record states what was accepted, what was rejected
and why, and what the review's own recommendations did not account for. Outcome: two
defects found and fixed in 0.8.1; the proposed package extraction deferred with a
sequencing argument.

## 1. Accepted as already satisfied

| Review item | Status in 0.8.0 |
| :--- | :--- |
| §2.4 Resolution models first-class, named, versioned | Already `RESOLUTION_MODELS` in `specs.py` — a closed set of three named models dispatched by `Budget.resolution_model()` |
| §3 priority 1, direction as a declared field | Already declared: `Tolerance.direction`, `PremiseDim.weaker_when`. The rename the review asks to "finish" was finished |
| §4 coherence witness as a permanent gate | Already in `tests/test_dj_generalisation.py`, already run by `make check`. No promotion needed |
| §6 gate must not become a scored similarity | Already enforced by a test reflecting over `Ruling`'s fields |

## 2. Accepted as real and unaddressed

- **§2.1 The extraction is genuinely unfinished.** Measured: `core.py` carries 24 sites of
  domain vocabulary; `_pair_cols()` hardcodes eleven HMDA column names; `candidate_sql()`
  hardcodes `action_taken`, `total_units` and `record_key`.
- **§2.5 A pure-Python reference partition.** Accepted, and stronger than stated: it is
  also a differential oracle against the SQL path, matching the conversion test that
  already exists.
- **§3 priority 2, temporal validity inside candidate generation.** Accepted on the
  review's own reasoning. A post-filter breaks Proposition 0: a lapsed record removed
  after the gate has seen it means the retrieval set and the admission set no longer
  correspond.
- **§3 priority 3, two-sided eligibility.** Accepted. It is already latent —
  `population.exclude_flags` plus the approved/denied action lists are a one-sided
  eligibility predicate that has not been named as one.

## 3. Rejected, with reasons

**The oracle cannot be built first.** The review's highest-ROI item is a chronological
oracle scored by a confusion matrix of disposition changes. That is the right instrument
and it was, at the time of review, unbuildable: `candidate_sql` carried no `ORDER BY`
while the scan read `comparators[0]`, broke two `max()` ties by arrival order, and walked
a seeded permutation stream across the null cells in build order — under
`preserve_insertion_order=false` on a multi-threaded build. A confusion matrix across
engine versions is meaningless while one version can disagree with itself.

Determinism precedes the oracle. Closed in 0.8.1.

**`inference.py` does not belong in the kernel.** The proposed package places the exact
null, the stratified rank test and the permutation machinery in a domain-free
`distinguish/`. They are not domain-free: they depend on the estimand being a rate over a
population of matched pairs drawn from one filer's filing. The judiciary instantiation
makes no such population claim — the review says so itself three sections later, when it
forbids transferring Rosenbaum Γ into a synthetic corpus. Putting inference in the kernel
would invite exactly the transfer the review prohibits. Inference belongs in the lending
adapter.

**`GateSpec` with string quantifiers is a new interpreter.** `universal: ["not
STRICTLY_BETTER"]` is a mini-language parsed at load time inside a signed artefact. This
is the same objection that rejected user-supplied resolution callables: a governance
artefact must be digest-comparable, and a string that is executed is not. The idea is
accepted; the encoding must be a closed enum of quantifier clauses, not free text.

**§2.3 has a dependency the review does not mention.** Collapsing the tested/residual
distinction into `GateSpec` is right in the kernel, but rule 9 — a residual band must be
strictly wider than its own tolerance — exists *because* residual dimensions are
quantified differently. Rule 9 has to move with the distinction or it silently stops
firing, which is the failure mode it was written to prevent.

## 4. What the review did not find

Both defects fixed in 0.8.1 were outside its scope, and both are of one shape: a default
that was correct when written, inherited by callers nobody revisited.

**The suite and the CLI ran a specification the service did not serve.** `specs.load()`
defaulted to the literal `"1.0.0"`. 0.8.0 fixed the service to name its version through
`load_in_force()` and left everything else: the shared test fixture (138 tests),
`tools/run_scan.py`, and `tools/load.py` pinned separately at 1.2.0. Between 1.0.0 and
1.4.0 the control features moved into residual risk, the bands widened to ±22%, and
thresholds became per-pair. Nothing failed, because every artefact honestly recorded the
version it had used — the versions simply disagreed, and no reader held two of them.

Pointing the suite at the specification in force exposed three tests that had stopped
testing what they claimed:

- The role-swap metamorphic property was **false**. Plain margin inversion holds for point
  values; under intervals the two directions sum to minus their combined width. It passed
  only because 1.0.0 declared no reported half-widths. Combined loan-to-value is published
  to three decimals, and the two margins differ by exactly 4 × 0.0005.
- The post-treatment guard was demonstrated on `initially_payable_to_institution`, which
  1.2.0 removed from the blocking key for exactly the reason the guard exists.
- The matcher's no-early-return guard had become vacuous: with `control_features` empty
  the loop it guards has nothing to be early about. A consequence worth recording —
  `MatchResult.deltas` is empty on every pair under the specification in force, so the
  delta-to-tolerance stratification cannot be built from it. The coarse numeric filter
  still runs, as the blocking bands, in SQL, before `match()` is reached.

**Replay was not deterministic.** Detailed in §3 above. `content_hash` could not detect it:
the hash certifies that a result was not edited afterwards, not that the same input
reproduces it.

## 5. Sequencing carried

1. Replay determinism — **done, 0.8.1**
2. Version governance — **done, 0.8.1**
3. Pure-Python reference partition (also the SQL differential oracle)
4. Temporal validity predicate inside candidate generation
5. Two-sided eligibility predicates
6. `GateSpec` with a closed quantifier enum, rule 9 moved with the distinction
7. Kernel extraction — comparison, resolution, gate, cells. Inference stays in the lending
   adapter
8. Chronological oracle harness

Verification at 0.8.1: 158 tests, mutation kill rate 62/62, ruff clean, specification
1.4.0 in force.
