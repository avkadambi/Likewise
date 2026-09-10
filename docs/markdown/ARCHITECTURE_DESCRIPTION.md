# Likewise — Architecture Description

## Document control

| | |
| :--- | :--- |
| Document | Architecture Description (referred to internally as the SDD) |
| Product | Likewise |
| Version | 2.0 |
| Status | Baselined against software release v0.13.0 |
| Prepared by | Arun Kadambi |
| Date of issue | 10 September 2026 |
| Implements | Software Requirements Specification v2.0 |

### Revision history

| Version | Date | Author | Summary |
| :--- | :--- | :--- | :--- |
| 0.1 | 6 Sep 2026 | A. Kadambi | Initial draft, withdrawn |
| 0.2 | 6 Sep 2026 | A. Kadambi | Cloud architecture: object storage, platform job execution, three service identities |
| 1.0 | 10 Sep 2026 | A. Kadambi | Rewritten to describe the system that was actually built |
| 2.0 | 10 Sep 2026 | A. Kadambi | Restructured as a conforming architecture description: stakeholders, concerns, viewpoints, decisions |

---

## 1. Introduction

### 1.1 Purpose and scope

This document describes the architecture of Likewise: its stakeholders, what each of them needs the architecture to settle, the views that answer those concerns, and the decisions that produced them.

It does not describe algorithms, interfaces or schemas. Those are in the Software Design Description.

### 1.2 A note on the previous version, because it matters

Version 0.2 of this document specified a cloud architecture. Object storage on any of the three major providers, a platform job-execution API, three separate service identities, Terraform for provisioning, compare-and-swap coordination on entity tags, manifest pointer files to make snapshot publication atomic, lease expiry to detect a crashed executor.

None of it was built, and the decision not to build it looks correct in hindsight. The shipped system is a single unprivileged container reading local columnar files through an embedded engine, with no cloud account, no object storage, no job runner and no outbound network access whatsoever.

The reasoning is worth recording, because v0.2 was internally coherent and still wrong for this product. Almost every mechanism in it existed to coordinate concurrent writers, and this workload has one writer. A filer-year is tens of megabytes. Nothing contends for anything. v0.2 had been designed against a scaling problem the product does not have and, in doing so, spent the complexity budget in the wrong place, because the genuinely difficult problem here is not availability but disclosure: the dangerous artefact is the findings file, not the service.

A second consequence only became clear after the system was described to the people who might use it. A component that opens no outbound connection needs no network review. For a compliance function, that is worth considerably more than the ability to redeploy on a different cloud provider, which nobody asked for.

What survives from v0.2 unchanged: the disclosure controls, immutable snapshots cited by digest, specification integrity, the single serialisation boundary, and the correctness constraints it set out. All of those are now implemented rather than specified.

### 1.3 References

| Ref | Document |
| :--- | :--- |
| R1 | ISO/IEC/IEEE 42010, *Systems and software engineering — Architecture description* |
| R2 | Likewise Software Requirements Specification v2.0 |
| R3 | Likewise Software Design Description v2.0 |

---

## 2. Stakeholders and their concerns

An architecture description is only meaningful against the people who have to live with it. Five groups matter here, and their concerns pull in different directions.

The **compliance officer** who operates the system cares about two things: that it runs without a platform team, and that when it says something she can find out why. Neither is an aesthetic preference. If the tool needs an infrastructure ticket to install, it does not get installed; if it produces a number she cannot explain to an examiner, it does not get used twice.

**Internal audit** wants to know who did what and when, and wants that record to be one they could not have altered. This is the concern that forces per-principal credentials and an append-only log, and it is the reason a shared API key was never an option.

The **borrower** is a stakeholder who will never see the system and cannot advocate for themselves in its design. Their concern is that a public file which the regulator deliberately blurred to protect them is not un-blurred by a downstream tool that narrows to two records and attaches an adverse inference to one of them. This concern is the one most easily lost, and most of clause 6 exists because of it.

The **lender under examination** has a concern that sounds adversarial and is not: that any claim about their file can be reproduced and rebutted from published inputs. A finding they cannot check is a finding they cannot fix.

Finally the **engineer** who inherits this in a year needs the architecture to be small enough to hold in their head, because they will be asked whether a result is trustworthy and will have to reason about every component between the input and the answer to say yes.

| Concern | Raised by | Addressed in |
| :--- | :--- | :--- |
| C1 Installs and runs without a platform team | Compliance officer | View 4 (deployment) |
| C2 Any output can be explained and traced to its inputs | Compliance officer, lender | Views 2, 3 |
| C3 Nobody can quietly alter the record of what was reviewed | Internal audit | View 5 (security) |
| C4 A borrower is not re-identified from published output | Borrower | View 5, clause 6 |
| C5 A result can be reproduced from published inputs | Lender, engineer | Views 2, 3 |
| C6 The system is small enough to reason about in full | Engineer | View 1 (context), View 2 |
| C7 The blast radius of a defect is bounded | All | Clause 7 |

---

## 3. Architecture viewpoints

Five viewpoints govern the views that follow. Each frames a subset of the concerns above.

| Viewpoint | Frames | Notation |
| :--- | :--- | :--- |
| V1 Context | C1, C6 | Boundary diagram, prose |
| V2 Functional decomposition | C2, C5, C6 | Component register, responsibility statements |
| V3 Information | C2, C5 | Directory layout, lifecycle prose |
| V4 Deployment | C1, C7 | Runtime topology, dependency register |
| V5 Security and disclosure | C3, C4 | Control statements, threat register |

---

## 4. View 1: Context

Likewise is a single process with three ways in and one place to put things.

```
   Published HMDA extract                Operator                  Compliance officer
   (shipped with the software)        (make / CLI)                    (browser)
              |                            |                             |
              +----------------------------+-----------------------------+
                                           |
                          +----------------v------------------+
                          |  One container, one process:      |
                          |  REST API on /v1                  |
                          |  server-rendered web view on /ui  |
                          |  scan, sweep and control runners  |
                          +----------------+------------------+
                                           |
                                  local filesystem
                    raw/  inbox/  curated/  specs/  store/  audit/
```

There is nothing else in the diagram because there is nothing else in the system. No service is contacted at runtime. The container holds no credentials because it needs none. An operator who wants a different filing year downloads it by hand and drops it in the inbox, which is a deliberate inconvenience: an automatic fetch would mean an outbound connection, and clause 1.2 explains what that would cost.

---

## 5. View 2: Functional decomposition

Fourteen components, of which three carry the product and the rest feed or deliver them.

| ID | Component | Owns | Does not own |
| :--- | :--- | :--- | :--- |
| C1 | Loader | Layout detection, validation, normalisation, the manifest | Any judgement about comparability |
| C2 | Query layer | Columnar reads over local files, memory and thread limits | Anything domain-specific |
| C3 | Candidate generator | Grouping, banding, the total ordering of results | The decision about a pair |
| C4 | Comparison lattice | Placing one pair on a partial order for one dimension | The rule that turns comparisons into a finding |
| C5 | Reason engine | The four-clause test over those comparisons | Ranking, suppression, inference |
| C6 | Egress | Banding, bucketing, suppression, pseudonymisation | Computing anything |
| C7 | API | Routes, credentials, scopes, error mapping | Business logic |
| C8 | Specification registry | Load, validate, digest, serve | Deciding anything about a pair |
| C9 | Web view | Rendering stored artefacts | Ever seeing a raw record |
| C10 | Scan runner | Sequencing, suppression order, tripwires, the summary | Comparison logic |
| C11 | Inference | The pooled test, the exact null, sensitivity bounds | Anything that touches a record |
| C12 | Precedence | Admission when a prior decision governs | Disposing of a case |
| C13 | Binding gate | Scoring rulings against a known-answer corpus | Producing rulings |
| C14 | Extraction *(optional)* | Reading prose into a structured record | Anything in the served path |

The "does not own" column is the load-bearing one. C4 knows what the record says about a pair and has no opinion about what to do with it; C5 has the opinion and cannot see a record; C11 sees values and labels and never a key. That separation is what makes each of them testable in isolation, and it is why the disclosure guarantee in view 5 can be enforced at one place rather than audited everywhere.

C12 to C14 are not on the lending path at all. They exist because the comparison at the centre of this system answers a second question, in a different domain, where the cost of a wrong answer is higher; the design consequences of that are in the Software Design Description.

---

## 6. View 3: Information

### 6.1 Lifecycle

A filing arrives in the inbox as a CSV. The loader identifies which accepted layout it is from the header row, validates it, normalises it and writes it as columnar files under an immutable snapshot identifier, together with a manifest.

Identification is by score against each layout's complete required column set, not by a marker column, and it refuses when two layouts match completely. The reason is specific and was discovered the hard way. The two regulator products share the column name a marker-based detector keyed on, and they disagree on the unit of `income` — the Data Browser and the Snapshot both publish it in thousands, the internal template in dollars. A file read as the wrong layout loads cleanly, scales income by a factor of a thousand, matches almost everything inside the income band, and gives no indication anywhere that anything went wrong. Refusing an ambiguous header is therefore not conservatism; it is the only safe behaviour available.

The loader refuses rather than repairs, and this is the design rather than an implementation detail. A ragged row is never padded, because a shifted column is exactly what a ragged row detects. A value that is not at the granularity the regulator published is refused. Each refusal names the offending rows or columns, because a validation failure that says only "invalid input" tells an operator nothing and gets worked around.

The manifest records absence as well as presence. In the retrieved 2024 slice, 40 of 440 records did not come through, and they are demographically clustered rather than missing at random. That fact is in the manifest, is rendered on a coverage page, and cannot be adjusted away.

From the snapshot, a scan produces findings, a summary, a sweep and a set of control results, all stored. The API serves them; nothing is recomputed on read.

### 6.2 Layout

```
data/raw/          the retrieved public extract, as downloaded
data/inbox/        drop folder for a filing to be loaded
data/curated/      columnar snapshots plus manifests
specs/             materiality, reasons, budget, granularity snapshots
data/store/scans/  scan records, findings, summaries, sweeps, controls, dispositions
data/store/audit/  append-only event log
```

Specifications are immutable once published and are cited on every finding by digest as well as by version string. The distinction matters: a version string is a mutable pointer, and every evidentiary claim the product makes rests on the standard in force at the time. A pointer can be repointed; a digest cannot.

### 6.3 Ordering

The candidate query imposes a total order on its results. This looks like presentation and is not.

The scan reads the first comparator in each group to seed its reference distribution, breaks ties in two separate selections, and walks a seeded random stream across groups in the order they were built. The database connection is configured for throughput rather than insertion order and the build is multi-threaded. Without a total order, the same input can therefore produce a different statistical null, and the content hash cannot detect it because the inputs are identical.

It was found by asking what would happen rather than by observing a failure, which is the only way this class of defect ever gets found.

---

## 7. View 4: Deployment

The runtime is one container built in two stages, so the final image carries no compiler and no package index. It runs as a fixed unprivileged user with a read-only root filesystem and writes only to a mounted volume, with scratch space in memory.

```
./install.sh          # container where a runtime is present, otherwise a virtual environment
./likewise.sh start
```

The virtual environment path exists for a specific reason. A compliance function evaluating this product should not need to involve their platform team to see whether it does anything useful, and requiring a container runtime before the first look is a barrier at exactly the wrong moment.

Five runtime dependencies, all pinned, all installing as pre-built wheels on macOS and Linux with no compiler:

| Package | Licence | Why it is here |
| :--- | :--- | :--- |
| duckdb | MIT | The engine. Embedded columnar analytics over local files: a library, not a server, so there is nothing to provision or secure |
| fastapi | MIT | Routes and the renderer |
| uvicorn | BSD-3-Clause | The server |
| PyYAML | MIT | Specifications are YAML and nothing else parses them |
| python-multipart | Apache-2.0 | The disposition form posts multipart data |

No numerical stack in the image. The statistics are standard-library arithmetic plus database aggregates, and the randomisation machinery is a grouped query over a shuffled label column rather than a library call. That constraint keeps the served image small and its transitive surface auditable, and it proved easier to hold to than expected.

It is a decision about the runtime, and it should not be mistaken for a decision about the method. Two further components sit outside the image and carry their own dependencies. The optional extraction component's are never installed by default and are roughly twenty-five times the size of everything above. The analysis component's are the ordinary scientific stack:

| Package | Licence | Why it is here |
| :--- | :--- | :--- |
| numpy | BSD-3-Clause | Array arithmetic for the simulation studies, which run millions of cells |
| scipy | BSD-3-Clause | The reference implementations every engine statistic is checked against |
| statsmodels | BSD-3-Clause | Second, independent references for the empirical CDF and the exact binomial limit |
| pandas | BSD-3-Clause | Data profiling of a snapshot: granularity, ties, block structure |
| matplotlib | PSF-based | The figures |

The boundary between the two is enforced rather than described. A test parses every source file in the served packages — function bodies included, because a lazy import never executes during a test run and would be invisible to a runtime check — and fails the build if any of them imports the analysis stack, or if those package names appear in the served requirements file.

The reasoning behind having both is worth recording, because a reviewer will otherwise read the short list as a claim that this product does not need mature numerics. It needs them, and it uses them: every statistic the engine serves is implemented twice, once in the standard library for the image and once against SciPy for the check, and the release does not ship unless the two agree. Two independent implementations that agree is a stronger correctness argument than either alone, and it is an argument the runtime dependency list cannot weaken.

---

## 8. View 5: Security and disclosure

### 8.1 Access

Every route requires a credential, reads and the web view included. Credentials are per principal and carry a subject claim.

An earlier design gated writes with a shared static key and left reads to platform ingress controls. That does not work, for a reason worth stating: ingress control is a network path setting rather than authentication, and since the web view has to be reachable from a browser, ingress must be open, which means findings were being served anonymously. A shared key also cannot answer "who", and "who" is the entire question internal audit is asking.

### 8.2 Disclosure

Three controls, all applied at the single serialisation boundary.

Banding means the output carries a difference, a tolerance and a coarsened band per feature, and never both sides' raw values. Bucketing rounds margins to multiples of the applicable threshold before they are serialised. That second control closes a leak that went unnoticed for some time: an earlier build published margins to six decimal places beside four banded quasi-identifiers, and a contract test that inspects field names is blind to it, because a margin at that precision is very nearly a unique key for the pair even though nothing forbidden appears by name.

Suppression withholds any finding whose group is smaller than a declared threshold, computed over the attributes actually emitted rather than a chosen subset. Anonymity measured over a coarser set than what you publish is not anonymity.

Geography is capped at county, and census tract is removed at ingest so that no downstream component can carry it even by accident. The regulator bins loan amount and rounds property value and income precisely because tract, value and income together identify a borrower. A tool that narrows to two records in one tract and attaches an adverse inference to one of them is the disclosure those protections exist to prevent.

### 8.3 Threat register

| Adversary | Objective | Control |
| :--- | :--- | :--- |
| Anonymous network | Read findings | Credential on every route |
| Authorised insider | Name the institutions | Full-length keyed digest; no lookup oracle |
| Recipient of one finding | Re-identify a borrower from the public file | Banding, bucketing, county ceiling, suppression |
| The operator | Destroy an inconvenient finding | Append-only audit under a separate identity |
| Opposing counsel | Read a conclusion the evidence will not support | Evidentiary status on every record; no per-finding significance value exists to be quoted |

The last row is a design control rather than a security one, and it is the least dependable of them, because it relies on a reader taking a field seriously rather than on the system enforcing anything.

---

## 9. Architecture decisions and rationale

| ID | Decision | Alternative rejected | Why |
| :--- | :--- | :--- | :--- |
| AD-1 | Embedded columnar engine over local files | Managed database or warehouse | Tens of megabytes, one writer, no transactions. The alternative adds an operator burden that buys nothing |
| AD-2 | Local filesystem only | Object storage | Removes the cloud account, the credentials and the network review in one decision |
| AD-3 | Single unprivileged container | Serverless, or an orchestrator | One service, one job type, nothing to coordinate |
| AD-4 | Declarative comparability standard | Learned pairwise distance | The standard must be readable and contestable, and a fitted matcher defeats a name-based protected-class check |
| AD-5 | No fitted model in any output field | End-to-end learned matching | Admission is a box; no additive score has box-shaped level sets in more than one dimension |
| AD-6 | Synchronous scan | Asynchronous job with a record | No distributed executor exists to coordinate, so the record would describe nothing |
| AD-7 | One serialisation boundary | Controls applied at query time | One place to enforce, one contract test to write |
| AD-8 | Total order on the candidate query | Rely on insertion order | Replay determinism. The defect this closes was measured, not hypothesised |
| AD-9 | No template engine in the web view | A conventional templating library | A second interpolation site weakens the disclosure check that AD-7 concentrates in one place |
| AD-10 | Named, closed set of resolution models | Caller-supplied functions | A signed artefact has to be comparable by digest, and a digest over an arbitrary function certifies nothing |
| AD-11 | Model runtime isolated from the engine | Extraction inside the served package | 555 MB against 21.5 MB, on a read-only image with no egress |

AD-4 is the decision most likely to be revisited under schedule pressure, and the one whose reversal would cost the most. Tolerance changes go through the versioning process rather than a code edit, and the moment that stops being true the product's central claim stops being checkable.

---

## 10. Correspondences

| Requirement (R2) | Component or view |
| :--- | :--- |
| FR-1 to FR-6 | C1, view 3 |
| FR-7 to FR-9 | C3, C4 |
| FR-10 to FR-12 | C5 |
| FR-13 | C3, clause 6.3 |
| FR-14 to FR-19 | C10, C11 |
| FR-20 to FR-24 | C6, clause 8.2 |
| FR-25 to FR-28 | C7, C9, clause 8.1 |
| NFR performance | Clause 7 |
| NFR security | Clause 8 |
| NFR reliability | Clause 11 |

---

## 11. Failure behaviour

The system fails closed and says why.

An invalid, unsigned or missing specification stops the process before it binds a port, with a structured payload naming the rule that failed. Input that is not at publication granularity is refused with the offending rows named. A field that turns out to be determined by the outcome causes a refusal for that field, reported with the diagnostic that decided it, rather than a silent empty result. A scan with no sensitivity sweep will not serve its findings at all. A failed or inconclusive control blocks publication.

A scan process that dies leaves nothing to reconcile, because there is no distributed state, and is simply re-run.

The pattern across all of these is the same and it is deliberate: six of the eight pipeline stages can halt the run, and each one names its cause. An earlier version of this system had a stage that could return zero findings silently, and zero fell inside the expected range, tripped nothing, and would have been published as a fact about a lender.
