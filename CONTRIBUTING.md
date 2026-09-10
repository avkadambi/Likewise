# Contributing

Read this before changing anything under `likewise/`. Most of it is about a handful of
rules that are load-bearing rather than stylistic — each one is here because breaking it
produced a wrong answer that looked right.

## Before you push

```
make check        # lint + the full suite
make mutate       # the release gate; a couple of minutes
```

Do **not** run `make mutate` while you are editing. The harness rewrites source files in
place and restores them from a snapshot taken when it started, so an edit made mid-run is
silently reverted and a concurrent test run reports failures that have nothing to do with
your change. This has cost real time twice.

## The rules that are not negotiable

### Specifications are never fitted

`specs/` is a comparability standard: signed, versioned, cited by digest on every
finding. It is configuration with legal weight, not hyperparameters.

Changing a tolerance means a **new version file** with a written rationale and a named
author. It is never tuned to make a result look better, and never adjusted because a scan
produced an inconvenient number. If a threshold looks wrong, the argument for changing it
belongs in the rationale, in the file, where a lender can read it and rebut it.

The startup gate enforces eleven validation rules over every version and refuses to bind
the port if any fails. A gate nobody has watched fail is a gate nobody has tested, so
`tests/test_specs_gate.py` deliberately violates each rule and asserts the refusal.

### Egress is the only way out

Every external serialisation of `Finding`, `Summary`, `ControlResult` or `NullSummary`
goes through `likewise/egress.py`. No other module may build a JSON response, an HTTP
body, an export file or a log line containing those types.

This is enforced, not requested: a contract test walks every registered route, a static
check fails the build on a direct import of a raw dataclass into a renderer, and a
serialiser test asserts no response exposes a raw institution identifier, a census tract,
a record key or a per-application raw value.

The leak that motivated it passed the original test: the exact margin was published at
six decimal places beside four banded quasi-identifiers, and the test checked *key names*.
A near-unique pair identifier is not a key name.

### Null never matches null

`IS NOT DISTINCT FROM` is banned in SQL by a lint test, unconditionally, rather than by a
maintained list of susceptible fields — a maintained list drifts. The same rule applies in
Python: two records that both *lack* a value are not two records that agree. The
resubmission signature broke this and quietly dropped pairs from every denominator but its
own; see `_resub_signature` and the tests that pin it.

### Mutable paths resolve through `paths.py`

The code is read-only at `/app` in a container while everything mutable is a volume at
`/data`. A hardcoded `data/curated` works in exactly one of the two environments and fails
*silently* in the other — the UI lists zero snapshots rather than raising. A lint test
rejects hardcoded mutable paths anywhere under `likewise/`.

### The dual conversion path must stay in step

`loader.py` converts CSV to Parquet twice: once as a DuckDB projection (the fast path,
which is what runs) and once as `convert()` in plain Python (the readable reference).
A differential test drives both over real files and asserts identical records, including
`record_key` digests.

If you change one, change the other. The reference exists so a reviewer can check the
mapping without reading generated SQL, and it is worthless the moment it drifts.

### There is one specification version default, and it is `IN_FORCE`

`specs.load(version=None)` loads `specs.IN_FORCE`. Do not reintroduce a literal version
as a default anywhere — not in a function signature, not in an `argparse` default, not in
a test fixture. `specs.load()` used to default to `"1.0.0"`, and every caller that did not
pass a version inherited it: the whole test suite through its shared fixture,
`tools/run_scan.py`, and for a while the service. The result was a product that tested and
scanned under one comparability standard while serving another, with nothing failing,
because each artefact honestly recorded the version it had used and no reader held both.

A replay names its version explicitly; that is what makes it a replay. Everything else
takes what is in force. Two tests enforce this, and one of them lints `tools/` for
`--spec-version` defaults.

### Findings are not servable without a sweep

`GET /v1/scans/{id}/findings` and the web review queue both return 409 when a scan has no
sweep. There is no flag to bypass it. The first question any informed reader asks is
whether the threshold was chosen to produce the result, and the exceedance curve is the
answer.

### Tripwires are two-sided

A headline rate above *or below* its band triggers full re-derivation. A surprisingly
large not-supported rate is far more likely to be a defect here than a lender's
misconduct — and the characteristic failure of this design produces zero, so a
suspiciously clean result gets the same scrutiny.

## Testing culture

The habit worth keeping: **write the test for the defect that already happened.** Most of
the suite is exactly that, and the docstrings say which defect. When you fix something,
leave behind a test that names it and fails without the fix — verify that it fails, don't
assume.

Five kinds of test carry most of the weight:

| Kind | Where | What it catches |
| :--- | :--- | :--- |
| True-null fixture | `test_true_null.py` | Machinery that cannot fail to find something. It would have caught three of the five statistical defects on day one |
| Differential | `test_loader.py` | The fast path drifting from the readable reference |
| Metamorphic | `test_metamorphic.py` | Swap approved and denied, shift both property values, round both incomes — the invariants that must hold whatever the data |
| Generative | `test_generative.py` | Algebraic properties over randomly drawn inputs: symmetry, antisymmetry, p-value bounds. Fixed seed, no Hypothesis dependency |
| Contract | `test_egress_contract.py`, `test_web_contract.py` | The rules above, enforced rather than documented |

## The mutation gate

`tools/mutate.py` applies each entry in `tests/mutants.py` to the source, runs the suite,
and records whether anything noticed. The gate is a kill rate ≥ 0.90.

The catalogue is **published**, because a kill rate against a private catalogue is
unreviewable. Every entry is drawn from a real defect in this project's history, which is
what stops it being gamed with mutants that only test what already works.

When you add a guard, add a mutant that removes it. When you move code, update the
entry's file path — a mutant whose pattern has drifted out of the source is scored as
inapplicable, which quietly narrows the gate without anyone noticing. A test asserts the
catalogue has no duplicate ids and that every entry still applies; six entries were listed
twice for a while, so the printed rate described a different experiment from the one in
the file.

An **equivalent** mutant — one provably behaviour-preserving — is recorded as such with
the proof, and excluded from the rate rather than deleted.

## Lint

`ruff`, configured in `pyproject.toml` to find defects rather than impose a house style.
The rule set is deliberately narrow: pyflakes, bugbear, a few ruff correctness rules. A
gate that fires on 200 sites of deliberate formatting is a gate somebody switches off, and
the real findings go with it.

It has already earned its place — it caught an undefined name, a spec key that had quietly
become dead configuration, and a `zip()` that would have truncated candidate rows in
silence.

## Style

The engine is dense on purpose and heavily commented on *why*, not *what*. Comments
explain the decision and, where it matters, the alternative that was rejected and the
reason. When you change a decision, change the comment that defends it.

No pandas, numpy or scipy. The statistics are the standard library plus DuckDB aggregates,
and the permutation machinery is a `GROUP BY` over a shuffled label column. Adding one of
those libraries is a design change, not a convenience, and needs an argument.

## Where things are

```
likewise/
  api.py        routes, auth, error mapping
  web/          server-rendered views, one module per screen
  core.py       blocking SQL, matcher, dominance, midranks
  stats.py      exact null, pooled rank test, sensitivity
  scan.py       orchestration, suppression, tripwires
  specs.py      load, validate, digest, startup gate
  loader.py     CSV -> internal schema -> Parquet
  egress.py     the sole serialisation boundary
  paths.py      where mutable things live
  runtime.py    engine memory and thread budget, from the environment
```

`docs/DESIGN.md` covers the architecture, `docs/METHOD.md` the statistics and why they are
shaped that way.
