# Likewise — Architecture

| | |
| :--- | :--- |
| Document | Solution architecture |
| Product | Likewise |
| Author | Arun Kadambi |
| Date | 9 September 2026 |
| Status | Current |
| Related | PIPELINE.md for data flow, TECHNICAL-SPEC.md for interfaces |

Components, deployment, security and disclosure properties, and the decisions behind them.

---

## 1. Design principles

| | Principle | Consequence |
| :--- | :--- | :--- |
| P1 | No managed database | Columnar files on disk, queried in-process. Nothing to provision, patch or pay for at idle |
| P2 | Governance artifacts are content-addressed files | Specifications are versioned documents, served by the API, cited on results by digest as well as version |
| P3 | The output is disclosure-controlled by construction | Egress carries bands and comparisons, never both records' raw values, enforced at one serialisation boundary |
| P4 | Fail closed, loudly | Invalid specification, malformed input or a missing prerequisite stops the process with a structured payload. Nothing degrades quietly |
| P5 | Every invariant the design asserts is checked by something | A rule nobody tests holds by luck until it does not |

P1 shapes everything else. P3 exists because an early finding payload re-identified both the
filer and the borrowers from a public file, which made the institution mask decorative. P5 is
the newest and the most frequently violated in practice — the last two validation rules were
added because two long-standing design assertions turned out to be enforced by nothing.

## 2. Components

| | Component | Responsibility |
| :--- | :--- | :--- |
| C1 | Loader | Read CSV, detect layout, validate domains and publication granularity, normalise, write Parquet under an immutable snapshot prefix with a manifest |
| C2 | Query layer | In-process columnar engine over Parquet, with an explicit memory limit and sub-blocking |
| C3 | Candidate generator | Blocking on an explicitly declared key; deterministic within-block pair generation with a canonical ordering constraint |
| C4 | Matcher | Applies the specification to a candidate pair; returns matched plus per-dimension comparisons |
| C5 | Reason engine | Classifies the denial against the dominance clauses, per tested dimension, with declared polarity |
| C6 | Comparison lattice | Places one pair on the comparison lattice for one dimension |
| C6b | Precedence admission | The status ladder and the abstention causes, when a prior decision governs |
| C7 | Statistics | Exact null, pooled stratified rank test, sensitivity bounds, permutation envelope |
| C8 | Egress | Disclosure control, banding, margin bucketing, k-suppression and pseudonymisation at serialisation |
| C9 | API | REST surface, authentication, validation |
| C10 | Specification registry | Loads, validates and serves specifications; fails service start on any validation error; exposes digests |
| C11 | Web view | Server-rendered read-only pages over stored post-egress artifacts. No business logic |
| C12 | Ranker | Deterministic ordering of results. No fitted model |

C4, C5 and C6 carry the product. C1 to C3 feed them. C7 supplies the only inferential claim.
C8 to C11 deliver them.

## 3. Technology

| Choice | Reason |
| :--- | :--- |
| Python 3.10+ (3.12 in the container) | 3.9 cannot parse `str \| None` in route annotations, which FastAPI evaluates at import |
| DuckDB, embedded over Parquet | An OLAP engine as a library. Nothing to install, start or secure. Columnar scans over the national file without a server |
| FastAPI + Uvicorn | `/v1` routes and the `/ui` renderer, one ASGI app |
| Frozen dataclasses over YAML | Specifications are configuration with legal weight. Pydantic coerces `"1.0"` to `1.0` and fills defaults silently; a specification must fail loudly |
| **No pandas, numpy or scipy** | The statistics are standard-library plus DuckDB aggregates. The permutation machinery is a `GROUP BY` over a shuffled label column, not a library |

Five runtime packages: `duckdb`, `fastapi`, `uvicorn`, `PyYAML`, `python-multipart`. Two more
for tests: `pytest`, `httpx`. All pure wheels on macOS and Linux — no compiler, no Xcode, no
Homebrew formula.

**The application makes no outbound network calls.** Data arrives as files; retrieving a
filing from the CFPB HMDA Data Browser is a manual download outside the process. The only
external resource a rendered page reaches for is a web-font stylesheet, and if it is blocked
the pages render in the system font stack.

## 4. Storage layout

```
data/
  inbox/                                       drop .csv files here
  raw/                                         retrieved source extracts
  curated/snapshot=<id>/activity_year=<y>/lei=<lei>/*.parquet
  curated/snapshot=<id>/manifest.json
  store/scans/<scan_id>/scan.json
  store/scans/<scan_id>/summary.json
  store/scans/<scan_id>/findings.json
  store/scans/<scan_id>/sweep.json
  store/scans/<scan_id>/controls.json
  store/audit/<date>/*.json                    append-only
specs/materiality/<version>.yaml               immutable once published
specs/reasons/<version>.yaml                   immutable once published
specs/budget/<version>.json
specs/snapshots/<snapshot_id>.json
```

**Snapshots are never overwritten.** Republication and late filer corrections are certainties
within the product's life, so a second vintage of a filing year is a second snapshot, and
every result remains replayable against the bytes it was computed from.

**Specification objects are immutable once published** and are cited on results by digest as
well as by version string. A version string is a mutable pointer, and every evidentiary claim
the product makes rests on the specification in force.

`store.py` is deliberately tiny: `get`, `put`, `create`, `list`, `uri`. `create` is the only
conditional operation, which is all the concurrency control the design needs.

`paths.py` exists because the container runs with a read-only `/app` and a writable `/data`
volume. Every mutable location resolves from the environment with sensible local defaults, so
the same code runs from a checkout and from an image with no conditional logic elsewhere. A
lint test rejects hardcoded mutable paths, because the failure mode is silent: the interface
lists zero snapshots rather than raising.

## 5. Scan lifecycle

States: `queued → running → complete | failed | refused`.

**A refused specification is a result, not a crash.** It records `status: refused` with the
full structured payload so the specification screen can render the refusal verbatim. Both the
synchronous route and the background runner map it the same way — for a while they did not,
and the same refusal produced two different records depending on which path ran it.

**A crashed executor cannot record its own failure.** Out-of-memory kills and timeouts are the
dominant crash classes and in both the process that would write `failed` is gone. A reader
therefore treats a `running` record whose lease has expired as failed.

A scan is a pure function of `(filer, year, specification version, snapshot)`, so its
identifier derives from that tuple and a repeated request returns the existing scan.

## 6. Security and disclosure

### Authentication

Every route requires a credential, including reads and the web view. Credentials are per
principal, not shared, and carry a subject claim. The web view exchanges the same credential
for a session cookie — no second signing key, no second trust root, one place to revoke.

A shared credential cannot answer "who", which is the question U2 and U3 exist to ask.

### Audit

Read and export are the sensitive operations; starting a scan is cheap and reversible. Both
are logged with principal, scan id, result ids and timestamp to an append-only prefix.

### Disclosure control

Three controls, applied at the single egress boundary:

**Banding.** Egress carries the comparison, the threshold, and a coarsened band for each
field. It does not carry both sides' raw values. Margins are bucketed to multiples of the
dimension's own threshold — published at six decimal places beside four banded
quasi-identifiers, the exact margin was very nearly a unique key for the pair.

**Geographic ceiling.** County, not census tract. Tract is dropped at ingest so no
intermediate file and no downstream code can carry it.

**k-suppression.** A result is not emitted unless at least *k* records in the filer-year share
its block key and coarsened bands. `k` is declared in the specification with a written
justification, minimum 5, and computed over the **emitted** attribute set — k-anonymity over
a coarser set than what you publish is not k-anonymity.

### The oracle problem

`/pairs/evaluate` **rejects** institution identifiers rather than redacting them. Redacting
caller-supplied input would make the endpoint an oracle over its own pseudonymisation
function: the filer panel is public and enumerable, so a complete mask-to-identifier table
would be buildable in about an hour.

### Pseudonymisation

The full HMAC digest, keyed by a CSPRNG value of at least 32 bytes, carrying a `key_version`
recorded on every scan and result. An earlier design truncated to 24 bits against a panel of
roughly 4,782 filers, which gives a **49% probability that two institutions share a mask** —
a mis-attribution defect before it is a privacy one.

The key is an input to the output, so it belongs in the reproducibility tuple. Rotation does
not re-derive historical pseudonyms; the version field is what lets a reader detect that two
exports are not comparable rather than concluding there are two institutions.

Pseudonymisation over a small public enumerable domain is a keyed pseudonym, not
de-identification, and its strength is entirely the key's secrecy.

### Threat model

| Adversary | Objective | Control |
| :--- | :--- | :--- |
| Anonymous network | Read results | Authentication on all routes; published to loopback only |
| Authorised insider | Name institutions | No oracle; full digest; per-release mapping on publication |
| Any recipient of one result | Re-identify borrowers from the public file | Banding, county ceiling, k-suppression over the emitted set |
| The operator | Destroy adverse results | Append-only audit |
| Opposing counsel | Read a conclusion the evidence does not support | Evidentiary status in the wire format, no per-result significance |

The dangerous artifact is the findings file, not the API.

## 7. Packaging and deployment

**Container.** Two-stage build: a virtual environment assembled in a `python:3.12-slim`
builder, copied into a runtime layer carrying no compiler and no package index. Runs as
uid/gid 10001 with a read-only root filesystem and a tmpfs for `/tmp`; everything mutable goes
to `/data`, a volume. The health check hits `/health`, so a container that is listening is a
container holding a valid, digested specification.

`likewise.sh` runs it rootless, publishing only to `127.0.0.1`, with `:Z` relabelling so it
works unmodified under SELinux, and `--memory 2g --cpus 2` as the cost bound.

Tests are deliberately **not** in the runtime image. `install.sh --container` builds a
throwaway layer on top and runs the suite there, so what is tested is the image that ships.

**Virtual environment.** `install.sh --venv` builds `.venv` in the checkout. Nothing is
installed outside the directory.

## 8. Scaling

The unit of work is one filer within one filing year, and filers are independent, so scans
scale by running more of them.

Within a filer the constraint is not the base table — a mid-tier filer is tens of megabytes
materialised — but a single oversized block. A filer concentrated in its home market puts
thousands of records into one block key, and the blocking aggregate is where memory goes. The
response is recursive sub-blocking on loan-amount bin above a declared row threshold, applied
before pair generation. Partitioning by block does not help: the failure *is* one block.

Engine memory and threads come from the environment, not from a default argument. Bound into
the signature they silently ignored the container's own `--memory`, so an operator who gave
the container 8 GB still got 2 GB with no way to see why.

## 9. Failure behaviour

| Condition | Behaviour |
| :--- | :--- |
| Specification invalid | Exit 78 with a structured payload, **before** binding the port |
| Input not at publication granularity | Refuse the load, name the rows |
| Ragged row | Refuse the load, report physical against produced row counts |
| Post-treatment field | Refuse **that field**, with the diagnostic that decided it |
| Findings requested without a sweep | 409 |
| Controls failed | Nothing published from that scan |
| Egress contract violated | Build fails, or the request fails |
| Tripwire breached, either direction | Recorded on the scan record, the summary and `/controls` |

Errors are machine-readable first and human-readable second: a `kind`, a list of `failures`
each naming the rule and the offending value, and an `emit_and_exit()` that writes the payload
and exits non-zero.

## 10. Design decisions

| | Decision | Rejected | Reason |
| :--- | :--- | :--- | :--- |
| D1 | Embedded columnar engine over Parquet | Managed database, warehouse | Few GB, single writer, no transactions |
| D2 | Coarsened exact matching against a specification | Learned pairwise distance | The standard must be readable and contestable; removes circularity |
| D3 | No fitted model determines an output field | End-to-end learned matching | A learned ranker over permitted features is a protected-class proxy the syntactic guard cannot see |
| D4 | Disclosure control at one serialisation boundary | Control at query time | One enforcement point, testable by walking every route |
| D5 | Immutable snapshots published by manifest pointer | Temporary prefix and rename | Atomic multi-object rename does not exist on the targets |
| D6 | Deterministic ranking | Calibrated probability | The outcome is a deterministic function of the margin; calibration would be circular |
| D7 | Named resolution models, closed set | User-supplied resolution function | An arbitrary callable in a signed artifact is neither reviewable nor comparable by digest |
| D8 | Server-rendered views, no template engine | Jinja2 | A second interpolation site is a hole in the static half of the egress check |
| D9 | Frozen dataclasses over YAML | Pydantic | Silent coercion and default-filling in a governance artifact |

D2 remains the decision most likely to be revisited under schedule pressure. Tolerance changes
go through the versioning process, not a code edit.

## 11. Testing architecture

253 tests plus a mutation gate and a lint gate.

| Kind | What it catches |
| :--- | :--- |
| True-null fixture | Machinery that cannot fail to find something |
| Differential | The fast conversion path drifting from the readable reference |
| Metamorphic | Invariants that must hold whatever the data |
| Generative | Algebraic properties over randomly drawn inputs, fixed seed, no extra dependency |
| Contract | The architectural rules above, enforced rather than documented |
| Mutation | Whether the tests would notice a defect, as opposed to whether they pass |

The mutation catalogue is **published**, because a kill rate against a private catalogue is
unreviewable. A test asserts it contains no duplicate ids and that every entry still applies —
six entries were listed twice for a while, so the printed rate described a different experiment
from the one in the file.
