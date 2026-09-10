# Likewise

Reads a lender's own published HMDA filing and identifies denials for which the public
record contains an approved application in the same coarsened cell that is **not worse on
the reason the lender cited**.

It is a prioritised place to start a comparative file review — a way of deciding which
denials, out of thousands, are worth a human reading the file. It is not a determination.

```
./install.sh          # container if podman is present, otherwise a virtualenv
./likewise.sh start   # or: make serve
```

Then open <http://127.0.0.1:8080/ui>.

To see it work on the shipped example filing without supplying data:

```
./install.sh --with-example
```

## Documentation

| Document | For |
| :--- | :--- |
| **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** | Anyone. What it does, how to run it, how to read every screen and number |
| **[docs/METHOD.md](docs/METHOD.md)** | The statistics: matching, dominance, resolution, the inferential claim, sensitivity, controls, limits |
| **[docs/DESIGN.md](docs/DESIGN.md)** | The software: architecture, schemas, contracts, testing, packaging |
| **[docs/OPERATIONS.md](docs/OPERATIONS.md)** | Deploying, configuring, backing up, troubleshooting |
| **[CHANGELOG.md](CHANGELOG.md)** | What changed in each release and why |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | Changing the code: the rules that are load-bearing, the mutation gate, the testing habits |
| **[docs/DISTINGUISH_ENGINE.md](docs/DISTINGUISH_ENGINE.md)** | Design exploration: making the comparison kernel serve a second domain, and the retrieval-gate coherence property |
| **[docs/EXTRACTION.md](docs/EXTRACTION.md)** | Reading prose records into the structured form the engine consumes: the backbone survey, why an unsure extractor must produce silence, and how it is scored against computed ground truth |
| **[docs/REVIEW_RECORD_V3.md](docs/REVIEW_RECORD_V3.md)** | The third external design review: what was accepted, what was rejected and why, and the two defects it did not find |
| **[docs/PRECEDENCE.md](docs/PRECEDENCE.md)** | Admission when a prior adjudication governs: the design record, the abstention causes, and why silence must never bind |

| **[onboarding/](onboarding/)** | New to the project? Start here — a guided reading order, an install walkthrough and the product, method and architecture documents |

`docs/templates/likewise_lar_dictionary.csv` documents every input column, its allowed
values and what the engine uses it for.

## What this is not

- **Not a fair lending finding.** Likewise deliberately does not look at race, ethnicity or
  sex. Without a protected-class axis, a matched pair with opposite outcomes is inconsistent
  underwriting — a discretion risk factor, not a cause of action.
- **Not comparative file review** as the Interagency Fair Lending Examination Procedures
  define it. That is constituted by a prohibited-basis group against a control group,
  marginal-transaction selection, the lender's own criteria, and a lender-explanation step.
- **Not a claim about any individual application.** Every finding carries
  `evidentiary_status: screening_hypothesis` in the wire format, and no q-value, because the
  inferential claim is made once per scan and not per pair. See
  [METHOD §7](docs/METHOD.md#7-the-inferential-claim-and-why-it-sits-at-scan-level).

The full limitations list is [METHOD §13](docs/METHOD.md#13-known-limits-collected). It is
worth reading before showing anyone a result.

## The asymmetric-scepticism rule

A surprisingly **large** not-supported rate is far more likely to be a defect here than a
lender's misconduct. Any headline above its tripwire is fully re-derived and independently
replayed before it appears anywhere. The tripwires are **two-sided**: a rate below the lower
bound triggers the same investigation, because the characteristic failure of this design
produces zero.

## Licence

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

Apache rather than MIT for two reasons specific to this kind of tool. It carries an explicit
patent grant, which a compliance function's own counsel looks for before adopting anything
that touches lending decisions; and it obliges a distributor to state what they changed,
which suits a project whose whole posture is that the standard a result was judged under must
be nameable. Every runtime dependency is MIT, BSD-3-Clause or Apache-2.0, so either licence
would have been compatible.

## Dependencies

Five runtime packages, pinned in `requirements.txt`, plus two for the tests in
`requirements-dev.txt`. Everything installs as a pre-built wheel on macOS (Apple silicon and
Intel) and on Linux — no compiler, no Xcode, no Homebrew formula.

| Package | Why it is here |
| :--- | :--- |
| `duckdb` | The engine. Embedded OLAP over Parquet — a library, not a server, so there is nothing to install, start or secure |
| `fastapi` | `/v1` routes and the `/ui` renderer |
| `uvicorn` | ASGI server |
| `PyYAML` | Specifications are YAML; nothing else parses them |
| `python-multipart` | The disposition form posts `multipart/form-data` |
| `pytest`, `httpx` | Tests only. `httpx` is a dependency of `fastapi.testclient`, not of the app |

Statistics **in the served image** are the standard library plus DuckDB aggregates: no
numpy, no scipy, **no pandas**. The permutation machinery is a `GROUP BY` over a shuffled
label column, not a library.

That is a decision about the runtime, not about the method. Every one of those statistics
is implemented a second time in `analysis/`, against SciPy, statsmodels and NumPy, and
`make analysis` asserts the two agree on the same inputs — floating point for the exact
quantities, four Monte Carlo standard errors where the reference is simulated. Ten
statistics, ten agreements. The standard-library version is what serves; the reference
version is what makes it believable, and the check found a real overflow defect in the
exact binomial bound that no test in the suite could have reached.

`analysis/requirements.txt` therefore carries numpy, scipy, pandas, statsmodels and
matplotlib. They are never installed into the image, and
`tests/test_analysis_boundary.py` parses every file in `likewise/` and `extract/` —
function bodies included, since a lazy import never runs during a test — and fails the
build if any of them imports the analysis stack.

The optional extraction stage in `extract/` needs torch and transformers, and they are in
`extract/requirements.txt` rather than `requirements.txt` **on purpose**: torch alone is
555 MB against DuckDB's 21.5, and the served container is rootless, `--read-only` and makes
no outbound calls. Extraction runs offline and produces a snapshot; the engine never
imports a model runtime, and a test asserts it over every file in `likewise/`.

There is no database server, no message queue, no cache, no object store and no cloud
account. Storage is `get/put/create/list/uri` over the local filesystem, and `create` is the
only conditional operation. **The running application makes no outbound network calls at
all** — the FFIEC extract it was built against is already in `data/raw/`, and retrieving a
different one is a manual download through the CFPB HMDA Data Browser.

**Python 3.10 or newer** for the virtualenv path; the container ships 3.12. 3.9 will not
work: FastAPI evaluates route annotations at import and the routes use `str | None`.

## Loading your own data

```
make template                # copies the CSV template into data/inbox/
# edit data/inbox/my_filing.csv
make load                    # or: make load ARGS=--and-scan
```

Three input layouts are detected from the header row: an FFIEC **Snapshot** file, an FFIEC
**Data Browser** or Modified LAR export, or the **template** in `docs/templates/`.

The loader refuses rather than repairs, and every refusal prints a payload naming the rows or
columns: a ragged row (never padded — a shifted column is exactly what that catches), a code
outside its published domain, more than one filer or filing year in a snapshot, and values
that are not at publication granularity.

That last one surprises people and matters most. `loan_amount` and `property_value` must sit
on `$10,000` bin midpoints, `income` must be rounded to `$1,000`, and
`debt_to_income_ratio` must be an integer in `[36, 49]` or blank — because the whole
comparability argument rests on those fields arriving already coarsened by the regulator, and
the resolution budget is derived from that coarsening. `--internal-data` loads full-precision
data anyway and permanently stamps the snapshot `public_record: false`, which then travels
onto every screen.

`data/inbox/README.md` has the detail.

## Commands

```
make install                   # install.sh: venv, dependencies, gates
make template                  # CSV template into the drop folder
make load     ARGS=--and-scan  # load data/inbox, then scan, sweep and controls
make example                   # the same, on the shipped example filing
make fixture                   # synthetic dev snapshot (publication binning applied)
make ingest                    # load the retrieved FFIEC extract in data/raw
make scan                      # scan id is derived from filer|year|spec|snapshot
make sweep    SCAN=scn_...     # required: findings are not servable without it
make controls SCAN=scn_...     # nothing is published until this passes
make check                     # lint and the test suite
make test                      # the test suite
make mutate                    # mutation kill rate, gate >= 0.90
make analysis-env              # the scientific stack; NOT installed in the image
make analysis                  # cross-validation, simulation study, EDA, figures, report
make analysis-quick            # the same at reduced replication (~1 minute)
make serve                     # API on /v1, web view on /ui
```

The container equivalents are `./likewise.sh start|stop|status|logs|load|scan|shell|build`.

## The data in this repository

`data/raw/` carries the retrieved extract. `make ingest` and `make fixture` build two
snapshots from it, both listed on `/ui/scans` and each labelled:

- **`hmda_2024_ffiec_2026-09-07`** — real FFIEC records: Fairway Independent Mortgage
  Corporation, San Diego County, FY2024. 400 of the 440 records in that filer-county-year,
  retrieved through the FFIEC Data Browser and verified slice by slice against the
  aggregations endpoint on both row count and `loan_amount` sum. The manifest names the 40
  records that are missing, why, and the fact that they are demographically clustered rather
  than missing at random. `/ui/scans/{id}/coverage` renders that manifest.
- **`hmda_2025_2026-09-15`** — a synthetic fixture with a planted signal, so the review queue
  and finding detail have content to exercise. It is a fixture, not evidence.

## The analysis layer

`analysis/` is not part of the served engine and nothing in `likewise/` may import it. It
does three jobs the container has no business doing.

| Module | What it establishes |
| :--- | :--- |
| `crossvalidate.py` | Every engine statistic against SciPy / statsmodels / NumPy on identical inputs, to a stated tolerance |
| `simulate.py` | Operating characteristics: type-I error under a true null, power against effect size and cell count, coverage of both interval estimators, and the behaviour of the finding rule against the decisive threshold |
| `eda.py` | What the published record can express — publication grid, tie concentration, block and cell structure, and the smallest p-value each cell could ever produce |
| `figures.py` | Eleven figures plus a combined PDF, drawn only from the artefacts above |
| `report.py` | `ANALYSIS.md/.html/.pdf`, assembled from those artefacts so no number is typed twice |

`make analysis` runs all five and writes `analysis/out/`. Three results are worth knowing
before reading the code:

- At the design's own cell sizes, **no cell can reach q = 0.05** — the best attainable
  p-value in any simulated cell is 1/8. This is decided by cell size and ties before any
  comparison is made, and it is why the design pools across cells and publishes no
  per-finding p-value.
- Under a true null the finding rule still fires on about a third of cells, because a
  small cell with a threshold below its spread produces a finding by geometry. A raw rate
  would be mostly geometry; the headline is always the departure from the null.
- A naive row bootstrap covers 0.858 against a nominal 0.95 while being narrower than the
  cluster bootstrap. Pairs inside a cell are dependent by construction, and pretending
  otherwise buys apparent precision that is not there.

## Gates that will stop you

| Gate | Where | What it protects |
| :--- | :--- | :--- |
| Startup gate | `specs.py` | Empty band, missing budget entry, decisive threshold below the resolution the data supports, or a dimension with no sensitivity headroom. Exits non-zero **before binding the port** |
| Rule 3 | `specs.py` | Tolerance must be **strictly** greater than granularity |
| Rule 5 | `specs.py` | Blocking band must cover the matcher tolerance on both terms |
| Protected-class guard | `specs.py` + test | Protected-class fields may not enter the key or the feature sets |
| SQL lint | test | `IS NOT DISTINCT FROM` forbidden unconditionally |
| Egress leak test | `egress.py` + test | No raw institution identifier, tract, record key or per-application value in a response |
| Controls | `tools/run_controls.py` | Cited versus placebo; publication blocked on failure |
| Mutation gate | `tools/mutate.py` | Kill rate ≥ 0.90 on a published catalogue |
| Post-treatment diagnostic | `scan.py` + test | A matching field determined by the outcome makes matching circular. Refuses per field, with the diagnostic that decided it |
| Publication granularity | `loader.py` + test | Data not at the regulator's coarsening is refused |
| Sweep guarantee | `api.py` + test | Findings and the review queue both 409 without a sweep. A finding may not be presented without the curve showing whether its threshold was chosen to produce it |

## The specifications

`specs/` is the comparability standard: signed, versioned, cited by digest on every finding,
and **not fitted**. Changing a tolerance produces a new version with a written rationale and a
named author. It is never tuned to make a result look better.

| Version | Change | Why |
| :--- | :--- | :--- |
| 1.0.0 | initial | — |
| 1.1.0 | re-pointed at the FY2024 publication snapshot | The retrieved file is a 2024 filing; no matching rule changed |
| 1.2.0 | `initially_payable_to_institution` removed from the blocking key | On the scanned filer it was 3 ("not applicable") on every denial and 1 or 2 on every origination, because a denied application has no loan to be payable to anyone. A 1.1.0 scan refused with zero possible comparators |
| 1.3.0 | amortisation-family fields removed; income and loan amount moved from the control set to residual risk with declared directions; bands widened to ±22% with raised absolute floors; per-pair decisive thresholds | Measured matching cost and post-treatment reasoning. See [METHOD §3](docs/METHOD.md#3-matching-cells-not-neighbourhoods) and [§5](docs/METHOD.md#5-resolution-why-the-threshold-is-per-pair) |

The FY2024 snapshot is marked verified on a narrow claim: every publication-granularity value
in it was checked against all 400 retrieved records rather than asserted from a document
nobody has read. `loan_amount mod 10000` and `property_value mod 10000` are 5000 for every
record, `income mod 1000` is 0 for every record, combined loan-to-value carries three
decimals, and every numeric debt-to-income ratio falls in `[36, 49]`. The retrieved slice
contains no EGRRCPA partial-exemption records, so the `"Exempt"` sentinel path is exercised
only by tests.
