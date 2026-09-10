# Likewise — Technical Design

The software: what the pieces are, how data moves through them, what each contract
guarantees, and why the unusual choices were made.

Companion documents: [USER_GUIDE.md](USER_GUIDE.md) for using the product,
[METHOD.md](METHOD.md) for the statistics, [OPERATIONS.md](OPERATIONS.md) for deployment.

---

## 1. Shape of the system

One process. No database server, no message queue, no cache, no object store, no cloud
account.

```
        CSV in data/inbox/
                │
                ▼
   ┌────────────────────────┐
   │  loader.py             │  layout detection, domain and granularity
   │  (streaming, in SQL)   │  validation, normalisation → Parquet
   └────────────┬───────────┘
                │  immutable snapshot prefix + manifest
                ▼
   ┌────────────────────────┐
   │  specs.py              │  load, validate (7 rules), digest,
   │  STARTUP GATE          │  refuse before binding the port
   └────────────┬───────────┘
                │
                ▼
   ┌────────────────────────┐      ┌──────────────┐
   │  scan.py               │◀────▶│  core.py     │  blocking SQL, matcher,
   │  orchestration         │      │              │  dominance, midranks
   │  suppression, tripwires│      ├──────────────┤
   │                        │◀────▶│  stats.py    │  exact null, pooled test,
   └────────────┬───────────┘      │              │  Γ*, Γ_max, envelope
                │                  └──────────────┘
                ▼
   ┌────────────────────────┐
   │  egress.py             │  THE SOLE SERIALISATION BOUNDARY
   │  banding, bucketing,   │  k-anonymity over the emitted attribute set
   │  pseudonymisation      │
   └────────────┬───────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
   api.py  /v1      web.py  /ui
```

About 3,200 lines of Python in the engine, a server-rendered web view split across a
small package, and roughly 800 lines of command-line tools.

The web view is deliberately **not** templated. A template engine was proposed and
rejected: it adds a runtime dependency, and a second place where a value can be
interpolated into a response — which is a hole in the static half of the egress
exclusivity check, for a readability gain that splitting the module already delivers.

## 2. Technology, and why

| Choice | Reason |
| :--- | :--- |
| Python 3.10+ (3.12 in the container) | 3.9 cannot parse `str \| None` in route annotations, which FastAPI evaluates at import |
| DuckDB, embedded over Parquet | An OLAP engine as a library. Nothing to install, start, or secure. Columnar scans over the national file without a server |
| FastAPI + Uvicorn | `/v1` routes and the `/ui` renderer, one ASGI app |
| Frozen dataclasses over YAML | Specifications are configuration with legal weight. Pydantic coerces `"1.0"` to `1.0` and fills defaults silently; a specification must fail loudly instead |
| **No pandas, numpy or scipy** | The statistics are standard-library plus DuckDB aggregates. The permutation machinery is a `GROUP BY` over a shuffled label column, not a library |

Five runtime packages: `duckdb`, `fastapi`, `uvicorn`, `PyYAML`, `python-multipart`. Two
more for tests: `pytest`, `httpx`. Everything installs as a pre-built wheel on macOS (Apple
silicon and Intel) and on Linux — no compiler, no Xcode, no Homebrew formula.

**The application makes no outbound network calls.** Data arrives as files in
`data/inbox/`; retrieving a filing from the CFPB HMDA Data Browser is a manual download
outside the process. The only external resource a rendered page reaches for is a web-font
stylesheet; if it is blocked, pages render in the system font stack and nothing else
changes.

## 3. Modules

```
likewise/
  api.py       routes, auth, error mapping, HTML route wiring
  web/         server-rendered views over stored post-egress artifacts:
                 format.py   plain-language numbers, labels, verdicts
                 layout.py   page shell, nav, banners
                 charts.py   inline SVG, no chart library
                 pages/      one module per screen
  core.py      blocking SQL, matcher, dominance, midranks, cell power
  stats.py     exact null, pooled stratified rank test, Γ, permutation envelope
  compare.py   the comparison lattice
  precedent.py admission under a rule of precedence; abstention causes
  scan.py      orchestration, suppression, tripwire evaluation
  specs.py     load, validate, digest, startup gate
  loader.py    CSV → internal schema → Parquet, streaming
  egress.py    the sole serialisation boundary
  schema.py    the internal record schema
  store.py     get / put / create / list / uri
  paths.py     data-root resolution from the environment
  runtime.py   engine memory and thread budget from the environment
  errors.py    structured, machine-readable failures
```

`store.py` is deliberately tiny: `get`, `put`, `create`, `list`, `uri`, with a local
filesystem backend. `create` is the only conditional operation, which is all the
concurrency control the design needs.

`paths.py` exists because the container runs with a read-only `/app` and a writable `/data`
volume. Every mutable location resolves from the environment (`LIKEWISE_DATA`,
`LIKEWISE_STORE`, `LIKEWISE_SPECS`) with sensible local defaults, so the same code runs from
a checkout and from an image with no conditional logic anywhere else.

## 4. Ingest

### Layout detection

Three input layouts are recognised from the header row alone:

| Layout | Distinguishing columns | Units |
| :--- | :--- | :--- |
| FFIEC Snapshot (national) | `combined_loan_to_value_ratio`, `denial_reason_1` | income in **thousands** |
| FFIEC Data Browser export | `loan_to_value_ratio`, `denial_reason-1` | income in dollars |
| Template | internal names | income in dollars |

The unit difference is the kind of thing that silently produces a plausible wrong answer,
so it is part of layout detection rather than a downstream correction.

### Streaming conversion

Conversion happens **inside DuckDB**, as a projection over a CSV scan, not in Python. Memory
does not scale with the file: `SET memory_limit` is a budget DuckDB honours rather than a
cliff it falls off. 512 MB is DuckDB's own floor for this pipeline.

Two details that were learned the hard way:

- DuckDB's default `temp_directory` is `.tmp` relative to the working directory. In a
  read-only container that is unwritable, so it is set explicitly to the system temp
  location.
- `store_rejects` does not materialise under a projection plan, so ragged-row detection
  cannot rely on it. Instead the loader **reconciles row counts**: physical rows scanned
  against rows produced. A mismatch is a refusal with the counts in the payload.

`convert()` in `loader.py` is the same mapping written as plain Python and kept as the
readable reference. A differential test drives both over real files and asserts they produce
identical records, record-key digests included, so the fast path cannot drift from the
legible one.

### Normalisation, and what is dropped

- EGRRCPA partial-exemption sentinels — the literal string `"Exempt"` in the Data Browser,
  the numeric `1111` in the Snapshot — and `"NA"` map to null. Exempt records get their own
  denominator rather than being silently dropped.
- **Census tract is dropped at ingest.** Not filtered downstream, dropped: no intermediate
  Parquet can carry it, and a test greps every curated schema for the field.

### What the loader refuses

The loader refuses rather than repairs, and every refusal prints a payload naming the rows
or columns:

- a ragged row — never padded, because a shifted column is exactly what that catches;
- a code outside its published domain;
- more than one filer or filing year in a snapshot;
- values not at publication granularity (see USER_GUIDE §5).

`--internal-data` overrides the granularity check and stamps the snapshot
`public_record: false`. The stamp travels onto every screen of every scan of that snapshot,
permanently.

## 5. The startup gate

`specs.py` validates the specification before anything else runs, and the service **exits
non-zero with a structured payload before binding the port** if it fails. A gate that has
never been observed failing is a gate nobody has tested, so there is a CI fixture that
deliberately violates each rule and asserts the failure.

Eleven rules:

| Rule | Requirement |
| :--- | :--- |
| 1 | Every dimension named by a testable reason code resolves to a granularity and a tolerance |
| 1b | No protected-class field appears in the key or the feature sets |
| 2 | Every budget entry referenced exists |
| 3 | Tolerance is **strictly** greater than granularity |
| 4 | The blocking key is a subset of the exact-match set |
| 5 | Every banded field is a control feature or a residual-risk dimension, and the band covers the matcher tolerance on **both** terms (relative and absolute) |
| 6 | Disclosure floor: `k_min ≥ 5`, geography ceiling is the county |
| 7 | Every tolerance carries a written rationale |
| 8 | A tested dimension may not appear in the key, the exact-match set or the bands |
| 9 | A residual-risk band is strictly wider than its own tolerance |
| 10 | A tolerance is below its dimension's own declared span, so the dimension still participates |
| 11 | A banded relative tolerance declares its reference side, and it is `min` |

Rules 8 and 9 are the retrieval-gate coherence property: a dimension the gate tests is
never one retrieval filters on, and where retrieval does filter the band must strictly
cover the tolerance. See [PRECEDENCE.md](PRECEDENCE.md) and
[DISTINGUISH_ENGINE.md](DISTINGUISH_ENGINE.md) §2.

Rule 10 refuses a tolerance at or above its dimension's span: that does not loosen the
dimension, it switches it off. Rule 11 exists because rule 5 compares band and tolerance
as scalar coefficients, which is sound only when the tolerance is evaluated at the smaller
of the two magnitudes — `reference` was read from YAML and never validated.

Rule 5 exists because a band narrower than the matcher tolerance silently drops pairs the
matcher would accept — and the hole was concentrated at low incomes, which is exactly where
findings concentrate.

Beyond the rules, the gate checks the resolution budget **across the loaded snapshot's
property-value deciles** rather than at a single reference point (METHOD §5), and refuses a
dimension whose Γ_max falls below the sensitivity benchmark (METHOD §8).

Specifications are signed, versioned and cited by digest on every finding. They are never
fitted and never tuned to make a result look better. Changing a tolerance produces a new
version with a written rationale and a named author.

## 6. Scan pipeline

```
blocking → candidates → matcher → reason engine → dominance
        → cells and midranks → k-suppression → egress
```

**Blocking.** Separate approved and denied relations, joined on the exact-match key, with a
value-range band predicate carrying a `min_absolute` floor, an explicit projection, and
overlapping log-ratio sub-blocking. Candidates are generated by a value-range band on the
sort key rather than a positional window, with the record key appended as the final sort
term: the leading sort field is published at bin midpoint and therefore heavily tied, and a
positional window over an unstable sort produced a candidate set that varied between runs
and truncated recall arbitrarily inside tie groups.

**Null matching is prohibited unconditionally.** `IS NOT DISTINCT FROM` is forbidden by a
SQL lint test rather than by a maintained list of susceptible fields, because a maintained
list drifts. A null on either side of an EGRRCPA-susceptible dimension unconditionally
breaks the exact match. SQL `USING` equality already rejects null on either side; the lint
keeps it that way.

**Matcher.** All deltas computed with no early return; symmetric relative tolerance with a
stated reference side; per-dimension declared polarity; `below_resolution` as a third
per-dimension value alongside within/outside; conservative multi-code resolution; and an
explicit empty-conjunction guard so a finding cannot be produced by `all()` over zero
dimensions.

**The tested dimension is not tolerance-matched.** Matching a dimension and then testing it
are contradictory operations; dominance replaces the tolerance there (METHOD §4).

**k-suppression happens before ranking**, and k-anonymity is computed over the **emitted**
attribute set rather than a hand-chosen subset. k-anonymity over a coarser set than what you
actually publish is not k-anonymity.

**Execution is synchronous**, at service concurrency 1 with a max-instances cap. A scan holds
one instance while API traffic scales to others. There is no separate job resource, so
max-instances is what bounds cost.

**Tripwires are two-sided.** A headline rate above *or below* its expected band triggers full
re-derivation and an independent replay. A surprisingly large not-supported rate is far more
likely to be a defect here than misconduct by a lender — and the characteristic failure mode
of this design produces zero, so a suspiciously clean result gets the same treatment.

## 7. Schemas

### Scan record

Filer, year, specification version, snapshot, digests, `preregistration_digest`,
`tripwire_breached`, and `analysis_status`. A scan whose specification post-dates its
pre-registration is `exploratory` and says so on every finding it produced.

### Finding

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
                "delta": 0.4, "decisive_threshold": 7.1, "within": true,
                "margin": -0.4, "outcome": "not_supported" } ],
  "bands": { "income": "80k-90k", "property_value": "275k-300k" },
  "county_code": "12345",
  "spec_digests": { }, "snapshot_id": "...", "pseudonym_key_version": 1
}
```

Notes on fields that carry design decisions:

- **No `q_value`.** Per-finding significance is abandoned (METHOD §7), and leaving the field
  present would invite a renderer to imply one. `significance` states this explicitly in a
  field the renderer cannot drop.
- **`decisive_threshold` is per pair**, not per dimension (METHOD §5).
- **`rank_in_cell` is a midrank** and therefore fractional. On bin-published dimensions, ties
  are the normal case.
- **`margin` and `margin_ratio` are bucketed** to multiples of the dimension's own threshold
  before serialisation. Published at six decimal places beside banded quasi-identifiers, the
  exact margin was very nearly a unique key for the pair: loan-to-value lives on a
  0.001-point grid roughly 2×10⁵ wide, and a 500-record cell has ~2.5×10⁵ ordered pairs. The
  original leak test checked key *names* and could not see it.
- **`informative_dimension_count`** exposes how many dimensions actually decided the outcome.
  Because below-resolution dimensions are excluded from the conjunction, and matching already
  forces both property values inside tolerance on a rounded field, collateral-code findings
  are in practice decided by loan-to-value alone. Publishing the count means a two-dimension
  conjunction cannot be advertised while a histogram shows 95% single-dimension.

### Summary

The denominator chain is an **ordered, required list**. Every element is present or the
summary is invalid:

```
records_in_scope
  → denials_in_scope
  → denials_non_exempt                   (denials_exempt_excluded)
  → denials_complete                     (excluded_incomplete_records)
  → denials_with_matched_comparator       (same_applicant_routed, suppressed_k)
  → denials_testable_by_code
  → denials_in_adequately_powered_cell    (cells_underpowered)
  → denials_with_dominating_comparator
  → denials_with_finding
```

Plus `denials_testable_by_code_marginal` (over **all** denials in scope, not conditioned on
matching — testability is a marginal, not a nested step), `findings_below_power_floor`, the
coverage profile, `null_mean`, `null_ci95`, the pooled test result, `control_results`,
`margin_ratio_median`, `informative_dim_histogram`, `block_degree_distribution`,
`cell_size_distribution`, `cell_concentration_index`, `content_hash`, `tripwire_breached`,
`wall_time_by_stage`, and every digest.

`wall_time_by_stage` separates ingest, blocking, matching, reason, **statistics** and egress.
The statistical stage is where wall-clock risk first appears, and it is instrumented from the
first commit rather than after the first timeout.

## 8. API

Base `/v1`, RFC 7807 error bodies. **Every route except `/health` requires a per-principal
bearer credential** — reads included.

| Method | Path | Scope |
| :--- | :--- | :--- |
| GET | `/health` | — |
| GET | `/v1/specs/{kind}` | read |
| POST | `/v1/scans` | write |
| POST | `/v1/scans/{id}/execute` | write |
| GET | `/v1/scans` | read |
| GET | `/v1/scans/{id}` | read |
| GET | `/v1/scans/{id}/findings` | read |
| GET | `/v1/scans/{id}/controls` | read |
| GET | `/v1/scans/{id}/null` | read |
| GET | `/v1/scans/{id}/sweep` | read |
| POST | `/v1/pairs/evaluate` | write |

**`/controls` and `/null` are product outputs, not analysis artefacts.** A rate is never
served without them: the findings route carries the null summary in its envelope.

**Findings are not servable without a sweep.** `GET /v1/scans/{id}/findings` and the web
review queue both return 409 when the scan has no sweep. A finding may not be presented
without the curve showing whether its threshold was chosen to produce it.

**`/pairs/evaluate` rejects institution identifiers; it does not redact them.** Redacting
caller-supplied input would make the endpoint an oracle over its own pseudonymisation
function — the filer panel is public and enumerable, so a complete mask-to-identifier table
would be buildable in about an hour. Input is restricted to an allowlist of published fields
at published precision; anything else is a 422. Request bodies are excluded from logs.

**Latency budget.** p95 ≤ 500 ms on `/v1/pairs/evaluate` on a warm instance, budgeted as:
specification lookup from memory ≤ 5 ms, delta computation ≤ 20 ms, reason evaluation
≤ 20 ms, serialisation ≤ 50 ms, framework overhead ≤ 100 ms. Cold start is out of budget and
reported separately. A CI test asserts the warm path.

## 9. The web view

`/ui` is server-rendered over the **same stored post-egress artefacts the API serves**. The
renderer never sees a raw `Finding`, so the exclusivity contract holds at every width: the
mobile layout is a stylesheet, not a second serialisation route, and a contract test asserts
the rendered HTML contains no forbidden key.

| Route | Shows |
| :--- | :--- |
| `/ui/scans` | Snapshots and scans, each labelled real or fixture |
| `/ui/scans/{id}/coverage` | The denominator chain and the coverage profile |
| `/ui/scans/{id}/queue` | The prioritised review queue |
| `/ui/scans/{id}/findings/{fid}` | One pair, with disposition capture |
| `/ui/scans/{id}/sweep` | The exceedance curve |
| `/ui/scans/{id}/controls` | The placebo comparison |
| `/ui/spec` | The comparability standard in force |

The session cookie carries the **same** bearer credential the API takes. That is the whole of
the web view's authentication surface: no second signing key, no second trust root, one place
to revoke.

Two places the implementation departs from the original interface design, both because the
drawn frame would breach a constraint held elsewhere:

- The frames show the two records' exact values. Egress bands every published financial
  field, so the view renders the band, the bucketed margin and the decisive threshold.
  Un-banded display of a filer's own portfolio is a live policy question, not something a
  renderer decides.
- The frames say "same census tract". The geography ceiling in force is the county, and
  census tract is dropped at ingest so no downstream code can emit it.

## 10. Egress exclusivity

**All external serialisation of `Finding`, `Summary`, `ControlResult` or `NullSummary` must
pass through `egress.py`.** No other module may construct a JSON response, an HTTP body, an
export file, or a log line containing these types.

This is enforced, not asserted:

- a contract test walks every registered route and asserts the response passed through the
  egress serialiser;
- a static check fails the build on a direct import of a raw dataclass into `api.py` or any
  renderer;
- a serialiser test asserts no response schema exposes a raw institution identifier, a census
  tract, a raw record key, or a per-application raw value.

Two changes closed a real leak: margins and margin ratios are **bucketed** before
serialisation, and `k_cohort` is computed over the **emitted** attribute set (§7).

Identifiers are keyed-HMAC pseudonyms with a published key version. Changing the key changes
every record reference and finding identifier, so a worksheet exported before the change will
not match one exported after — which is why the key is generated once and backed up rather
than rotated casually.

## 11. Reproducibility

`content_hash` is a canonical hash over sorted logical rows at fixed numeric precision. The
guarantee is **content identity, not byte identity**. Parquet byte-identity additionally
requires pinned writer and codec versions and single-threaded writes, and it is broken by
design across deployments because the pseudonym key differs. A CI test asserts two runs of
the same scan produce the same `content_hash`.

Scan identifiers are derived from `(filer, year, specification version, snapshot)`, so the
same inputs always produce the same scan.

Stated plainly: a deterministic wrong answer reproduces perfectly. This is a reproducibility
property, not a quality result.

## 12. Testing

249 tests, plus a mutation gate and a lint gate.

**The true-null fixture** is the validity test that was missing: labels assigned uniformly at
random within cells must produce a p-value distribution indistinguishable from uniform,
checked at n ∈ {4, 6, 10, 20}, under coarsening, and for the pooled test. It also asserts the
pooled test finds an effect that no single cell of three could, and that zero-variance cells
are excluded.

**Metamorphic properties** over the full candidate set. Swapping approved and denied inverts
the margin sign wherever the comparison is *resolved*, and flips the outcome. Where it is not
resolved the reported margin is a slack rather than a dominance, and the two directions sum to
minus the combined interval width; the test asserts that identity exactly rather than allowing
a tolerance. Adding a constant to both property values does not change matching; rounding both
incomes to the published bin changes no outcome; a null in a tested dimension lands in the
incomplete bucket and never in findings.

**Verdict accounting** is enforced rather than checked by eye:
`survives + defeated + untestable_matched == matched`. A double-count here was a live defect.

**Mutation testing** against a published, pre-registered catalogue, gated at a kill rate
≥ 0.90 with guard items at 100%. Published, because a kill rate against a private catalogue
is unreviewable. The harness takes a snapshot of every source file before it starts and
restores any leftover on the next run, because the `finally` block that restores a mutated
file does not survive a SIGKILL.

**Contract tests** for egress exclusivity, the sweep requirement, the SQL lint, the
tract-drop assertion, and the startup gate's own failure paths.

**Replay determinism.** The same snapshot, specification and code must produce the same
scan. That is a claim about the machinery, not about the output, and `content_hash`
cannot check it: the hash is computed over the findings that were emitted, so two runs
that selected different comparators for the same denial simply produce two different
hashes, and a reviewer only ever holds one of them.

Three reads inside the scan are order-sensitive by construction — `comparators[0]`, which
decides the untestable cause and seeds the reference distribution; the two `max()` calls
that pick the decisive dimension and the reported comparator; and the order of the null
cells, across which the seeded permutation stream is walked in sequence. The connection
sets `preserve_insertion_order=false` and the build is multi-threaded, so none of them is
stable unless the candidate query imposes a **total** order. It does:
`ORDER BY denied_key, approved_key`, on a pair that is unique per row. Ordering on the
denial alone would be a partial order, and would leave exactly the ties that matter.

`tests/test_determinism.py` asserts the order at three levels — that the query declares
it, that it survives a reversed physical row order, and that a whole scan over reversed
input is identical field for field, permutation null included.

## 13. Failure behaviour

| Condition | Behaviour |
| :--- | :--- |
| Specification invalid | Exit 78 with a structured payload, **before** binding the port |
| Input not at publication granularity | Refuse the load, name the rows |
| Ragged row | Refuse the load, report physical vs produced row counts |
| Post-treatment field | Refuse **that field**, with the diagnostic that decided it |
| Findings requested without a sweep | 409 |
| Controls failed | Nothing published from that scan |
| Egress contract violated | Build fails, or the request fails |
| Tripwire breached (either direction) | `tripwire_breached` set on the scan record, the summary and `/controls` |

Errors are machine-readable first and human-readable second: `errors.py` carries a `kind`, a
list of `failures` each naming the rule and the offending value, and an `emit_and_exit()` that
writes the payload to stdout and exits non-zero.

## 14. Packaging

**Container.** A two-stage build: a virtual environment assembled in a `python:3.12-slim`
builder, copied into a runtime layer that carries no compiler and no package index. The
runtime runs as uid/gid 10001 with a read-only root filesystem and a tmpfs for `/tmp`;
everything mutable goes to `/data`, which is a volume. The health check hits `/health`, so a
container that is listening is a container holding a valid, digested specification.

`likewise.sh` runs it rootless, publishing only to `127.0.0.1`, with `:Z` relabelling so it
works unmodified under SELinux on RHEL and Fedora, and `--memory 2g --cpus 2` as the cost
bound.

Tests are deliberately **not** in the runtime image — they have no business in a deployed
artefact. `install.sh --container` builds a throwaway layer on top of the runtime image and
runs the suite there, so what is tested is the image that will actually run.

**Virtual environment.** `install.sh --venv` builds `.venv` in the checkout, installs the
pinned dependencies, runs the startup gate, the test suite and the mutation gate. Nothing is
installed outside the directory; deleting the folder is a complete uninstall.

See [OPERATIONS.md](OPERATIONS.md) for the operational detail.
