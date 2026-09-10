# Likewise — Software Requirements Specification

## Document control

| | |
| :--- | :--- |
| Document | Software Requirements Specification (referred to internally as the PRD) |
| Product | Likewise |
| Version | 2.0 |
| Status | Baselined against software release v0.13.0 |
| Prepared by | Arun Kadambi |
| Date of issue | 10 September 2026 |
| Licence | Apache License 2.0 |

### Revision history

| Version | Date | Author | Summary |
| :--- | :--- | :--- | :--- |
| 0.1 | 6 Sep 2026 | A. Kadambi | Initial draft, written before implementation began |
| 1.0 | 10 Sep 2026 | A. Kadambi | Brought into line with the built system; six requirements withdrawn |
| 2.0 | 10 Sep 2026 | A. Kadambi | Restructured to ISO/IEC/IEEE 29148; verification methods added per requirement |

### Approvals

| Role | Name | Signature | Date |
| :--- | :--- | :--- | :--- |
| Author | Arun Kadambi | | |
| Engineering review | | | |
| Compliance review | | | |

Approval blocks are unsigned. Nobody outside the project has reviewed this document, and it should not be read as though somebody has.

---

## 1. Introduction

### 1.1 Purpose

This specification states what Likewise is required to do, for whom, and the conditions under which those requirements are considered met. It is the baseline against which the software at release v0.13.0 is assessed, and it supersedes the pre-implementation draft of 6 September.

It does not describe how the system is built. Architecture is in the Architecture Description; algorithms, interfaces and the statistical design are in the Software Design Description.

### 1.2 Scope

Likewise reads a mortgage lender's own published HMDA filing and identifies denied applications for which that same public file contains an approved application, closely comparable on the things a lender would ordinarily weigh, that is no worse on the specific reason the lender gave for the denial. The output is a ranked list of denials worth a person opening the file.

The product does not decide anything. It puts a pile of files in an order.

Everything the system reads is already public. It requires no access to a lender's own systems, no borrower data, and no network connection at runtime.

### 1.3 Intended audience

Three groups read this document for different reasons. A compliance officer evaluating the product needs clauses 2 and 7 and can skip the rest. An engineer joining the project needs clause 3 onwards, and will find the reasoning behind most of it in the design documents rather than here. A reviewer asking whether the product's claims are supportable should read clause 2.6 first, because it is the clause that constrains everything else, and then clause 7.

### 1.4 References

| Ref | Document |
| :--- | :--- |
| R1 | ISO/IEC/IEEE 29148:2018, *Systems and software engineering — Life cycle processes — Requirements engineering* |
| R2 | FFIEC, *A Guide to HMDA Reporting: Getting It Right!*, and the Filing Instructions Guide for the filing year in use |
| R3 | Interagency Fair Lending Examination Procedures, FFIEC, June 2021 |
| R4 | Rosenbaum, P. R., *Observational Studies*, 2nd ed., Springer, 2002 (sensitivity analysis, clause 2.6) |
| R5 | Likewise Architecture Description v2.0 (the SDD) |
| R6 | Likewise Software Design Description v2.0 (the TDD) |

### 1.5 Definitions and abbreviations

**Cell.** A group of applications that match on every field the specification requires to be identical, and fall within the declared band on the numeric fields. Comparison happens only inside a cell.

**Coarsened.** Rounded or bucketed by the regulator before publication. Loan amounts are published at $10,000 bin midpoints, income to the nearest $1,000, and debt-to-income as an exact integer only between 36 and 49.

**Comparability specification.** The signed, versioned file that states what counts as comparable and how large a difference must be to be real.

**Finding.** A denial for which a comparator was found and the cited reason was not supported by the public record. It is a screening hypothesis, not a conclusion.

**HMDA.** The Home Mortgage Disclosure Act, under which lenders above a size threshold publish a record of every mortgage application they handled.

**LAR.** Loan Application Register, the filed record.

**Sensitivity (Γ).** How strong an unmeasured factor would have to be, expressed as a bias in odds, before it could account for a result on its own.

---

## 2. Overall description

### 2.1 Product perspective

Two kinds of tool already look at this data. Fair-lending vendors run portfolio-level regressions across a lender's book and report a disparity coefficient, which tells a compliance officer that something may be wrong somewhere but not which file to open. Examiners perform comparative file review by hand, on a sample, once an examination cycle, and that review is where individual files actually get read.

Likewise sits in the gap. It works on the same public file the vendors use, but it produces named pairs rather than a coefficient, and it produces them continuously rather than once a cycle. The intended effect is that a lender finds its own comparison-vulnerable files before an examiner does, using data the lender already published.

It is a standalone component. It integrates with nothing, calls nothing, and stores nothing outside its own data directory.

### 2.2 Product functions

The system loads a published filing and refuses it if the numbers have been sharpened past what the regulator published. It groups applications into cells of genuinely comparable records. Within a cell it reads the reason the lender recorded for each denial, and compares the denial to each approved application on the specific quantity that reason names. Because published values are ranges rather than points, the comparison is between ranges, and it can return "the record does not order these two" as a real answer.

Comparisons that survive that test are ranked, suppressed where a group is too small to be anonymous, and served as a queue. A reviewer works the queue, opens files, and records what they found. Nothing is published until a negative control has passed and a threshold sensitivity curve exists.

### 2.3 User characteristics

The primary user is a fair-lending or compliance officer at a lender large enough that deciding what to read is genuinely hard. They are not statisticians. They are, quite properly, sceptical of any tool that arrives with a number attached and a claim about their book.

Two secondary users consume the same output without operating the system. Internal audit needs evidence that a review was performed, on a stated basis, with a recorded outcome per item. Outside counsel needs the analysis to be reproducible and the standard it was judged under to be nameable and unchanged since.

The design targets the first of the three, because the other two are satisfied by a by-product of serving it well: an audit trail.

### 2.4 Constraints, assumptions and dependencies

The single hardest constraint is the shape of the source data, and it is worth stating plainly because it surprises people.

The regulator deliberately blurs the file before publishing it. That blur exists to protect borrowers, and it is not an inconvenience to be worked around; it is the thing that makes the whole method defensible, because every tolerance in the specification is derived from it. A tolerance finer than the blur is not a measurement of anything. The system therefore refuses to load data that has been sharpened, and if an operator loads full-precision internal data anyway, the resulting snapshot is permanently stamped as not-public-record and that stamp travels onto every screen.

Two consequences follow that shape the requirements. First, a published value denotes an interval, so the comparison is a partial order and some pairs are genuinely unrankable. Second, two records indistinguishable to Likewise may differ materially in the lender's own file, which is why every finding is a screening hypothesis and clause 2.6 is where it is.

Assumptions: that the public file for the target year is downloadable without registration; that the denial reason fields are populated at usable rates, which is not true for lenders operating under the EGRRCPA partial exemption; and that a filer-year fits comfortably in memory as columnar data, which it does by roughly two orders of magnitude.

The served system depends on five third-party libraries and nothing else. There is no database, no queue, no cache, no object store, no cloud account and no network egress.

That figure is about the *served* system, and the distinction matters enough to state here rather than bury in clause 4.7. Analysis, validation and reporting are a separate layer with its own dependency list — NumPy, SciPy, pandas, statsmodels and matplotlib — which is never installed into the image and which the served code is forbidden to import. The two lists exist for opposite reasons. The runtime list is short because a compliance function has to be able to audit what it is running. The analysis list is conventional because the statistics in this product are worth checking against mature implementations, and checking them against nothing would be the weaker choice. Clause 7.1 says what that layer is required to establish.

### 2.5 Operational environment

One container, or a virtual environment on any machine with Python 3.10 or newer. The container runs unprivileged with a read-only root filesystem and writes only to a mounted data volume. It makes no outbound network calls of any kind, which means it can be deployed inside a compliance function's own perimeter without a network review, and that turned out to matter more to the compliance staff the design was described to than portability across cloud providers ever would have.

### 2.6 What the results can and cannot support

This clause is here rather than in an appendix because it constrains every requirement that follows, and a reader who skips it will misread the rest of the document.

The public file does not contain everything an underwriter saw. Credit score is absent. So are reserves, employment history, appraisal detail and the conversation. The right question about any result from this data is therefore not "is there a difference" but "how much hidden information would it take to explain the difference away".

That quantity is computable. Rosenbaum's sensitivity bound (R4) asks how strong an unmeasured factor would have to be, and the engine computes it per finding. For debt-to-income the answer is that a factor about twice as influential as everything visible would account for the entire result. For loan-to-value it is less than that. Credit score alone, a field everyone knows is missing, is estimated at around eleven times.

So: **these results cannot support an enforcement action, and the product does not claim they can.** They can support a decision about which files a person opens first, which is a smaller claim and a genuinely useful one. Every finding carries a machine-readable status saying so, and there is no per-finding significance value anywhere in the system. The machinery that would have produced one was written, measured, found to be arithmetically incapable of firing at the cell sizes this data produces, and deleted rather than left switched off.

There is a second limit worth stating in the same breath. The method only sees a denial if the lender has enough volume in that geography and product combination to have approved a closely similar application. That makes the sampling frame blind to thin markets, non-metro lending, the broker channel, manual underwriting and small filers, which is precisely where underwriting discretion is widest. The frame is anti-correlated with the risk it is meant to prioritise, and every scan publishes a coverage profile saying which half of the book it could not see.

---

## 3. Functional requirements

Requirements are stated to be individually verifiable. The verification method is one of: **T** test in the automated suite, **D** demonstration on the shipped example data, **I** inspection of the artefact, **A** analysis against measured output.

### 3.1 Ingest and validation

| ID | Requirement | V |
| :--- | :--- | :--- |
| FR-1 | The system shall detect which accepted layout a supplied filing uses by scoring its header against each layout's complete required column set, shall claim a layout only when every column it needs is present, and shall refuse rather than choose when two layouts match completely | T |
| FR-2 | The system shall reject a filing whose numeric fields are not at the granularity the regulator publishes, and shall name the offending rows or columns in the rejection | T |
| FR-3 | The system shall reject a ragged row rather than padding it | T |
| FR-4 | The system shall reject a filing containing more than one filer or more than one filing year | T |
| FR-5 | The system shall record, in the snapshot manifest, every record that was expected and not retrieved | I |
| FR-6 | Where an operator loads full-precision data under an explicit override, the system shall mark the snapshot as not public record, permanently and visibly | T |

FR-5 exists because of what the retrieved data showed. Of 440 records in the filer-year, 400 came through and 40 did not, and the 40 are not a random sample: they cluster demographically. No statistical adjustment repairs that, so the only honest response is to write it down where a reader cannot miss it.

### 3.2 Comparison

| ID | Requirement | V |
| :--- | :--- | :--- |
| FR-7 | The system shall group applications into cells that match exactly on the declared key and fall within the declared band on the numeric fields | T |
| FR-8 | The system shall treat a published value as the interval it denotes, and shall report a pair as unordered where those intervals overlap by more than the applicable threshold | T |
| FR-9 | The system shall compute the decisive threshold for each pair from that pair's own magnitudes | T |
| FR-10 | The system shall test only the quantity named by the reason the lender itself recorded | T |
| FR-11 | Where a denial cites any reason the public record cannot test, the system shall treat the denial as untestable as a whole | T |
| FR-12 | The system shall refuse to match on a field whose value is determined by the outcome, and shall report which field and the diagnostic that decided it | T |
| FR-13 | The system shall produce identical output from identical input, including the permutation envelope | T |

FR-9 deserves a note, because a scalar threshold looks obviously sufficient until you check it. Loan-to-value is a ratio, so the matcher's tolerance on the loan amount propagates into it, and how far it propagates depends on the property value. At a $285,000 property the smallest defensible difference works out at 7.02 percentage points. At $175,000 it is 11.43, and at $125,000 it is 16.00.

The threshold had been certified at a single reference point, and nothing in the results showed it. The only real filer scanned at that stage was in San Diego County, where the median property value is around $805,000 and fewer than one record in two hundred falls below the boundary where the certified value breaks down. One expensive market concealed a defect affecting most of the country, and the direction of the error was the worst possible one: it manufactures findings preferentially in cheap markets. FR-9 is the requirement that closes it.

FR-13 was also written after the fact. The candidate query carried no total ordering, and the scan reads the first comparator in a cell to build its reference distribution, so the same input could produce a different statistical null on a different run. The content hash could not detect it, because the inputs were identical.

### 3.3 Inference and controls

| ID | Requirement | V |
| :--- | :--- | :--- |
| FR-14 | The system shall make exactly one inferential claim per scan, about the filer, and none about any individual application | I |
| FR-15 | The system shall not attach a significance value to any individual finding | T |
| FR-16 | The system shall compute and publish a sensitivity bound for every finding, and a ceiling for every tested dimension | T |
| FR-17 | The system shall run the identical analysis against a reason the filer did not cite, and shall block publication if that control fails or is inconclusive | T |
| FR-18 | The system shall refuse to serve findings until a threshold sensitivity sweep exists for that scan | T |
| FR-19 | The system shall check every published headline against a pre-registered band in both directions | T |

FR-19 is two-sided on purpose. The intuition is to worry when a number comes back high, but for this product a surprisingly large rate is far more likely to be a defect in this software than misconduct by a lender, and the characteristic failure of the design produces zero. A rate below the lower bound gets the same investigation as one above it.

### 3.4 Disclosure

| ID | Requirement | V |
| :--- | :--- | :--- |
| FR-20 | All external serialisation shall pass through a single boundary | T |
| FR-21 | No response shall contain a raw institution identifier, a census tract, a record key, or an individual application's raw value | T |
| FR-22 | No finding shall be emitted unless at least *k* records share its group and coarsened bands, with *k* at least five | T |
| FR-23 | Margins shall be bucketed to multiples of the applicable threshold before serialisation | T |
| FR-24 | Race, ethnicity and sex shall not appear in the grouping key, the bands, or any feature set | T |

FR-23 closes a subtle leak. An earlier build published margins to six decimal places next to four banded quasi-identifiers, and a contract test that checks field names cannot see the problem: a margin at that precision is very nearly a unique identifier for the pair, even though no forbidden field name appears anywhere in the response.

FR-24 is enforced by checking field names, which is a syntactic check. That is exactly why the constraint in clause 4.7 exists.

### 3.5 Review workflow

| ID | Requirement | V |
| :--- | :--- | :--- |
| FR-25 | The system shall present findings as a ranked queue with the specification version each was judged under | D |
| FR-26 | The system shall record a disposition per finding from a closed set, with a free-text note, an author and a timestamp | T |
| FR-27 | Dispositions shall be written to an append-only audit log | T |
| FR-28 | The system shall report the full ordered chain of denominators from records in scope through to findings | T |

The three dispositions are: the reason holds, meaning something outside the public record explains it; the reason does not hold; and cannot tell yet. The note field is the part that matters. A year later the defensible artefact is not the flag, it is the record of who looked, when, and what they concluded.

---

## 4. Non-functional requirements

### 4.1 Performance

A full scan of one filer-year completes unattended in a single run with no operator intervention. Synchronous evaluation of a single caller-supplied pair returns within 500 ms at the ninety-fifth percentile on a warm instance; cold start is excluded and reported separately.

### 4.2 Security

Every route requires a credential, including reads and the web view. Credentials are per principal and carry a subject claim, because a shared key cannot answer the question "who", which is the only question internal audit is really asking.

Institution identifiers are pseudonymised with a full keyed digest, never truncated. An earlier design truncated to 24 bits against a panel of roughly 4,800 filers, which gives close to a fifty per cent chance that two institutions collide on the same mask. That is a mis-attribution defect before it is a privacy one.

The endpoint that evaluates a caller-supplied pair rejects institution identifiers rather than masking them. Masking whatever the caller sends turns the endpoint into an oracle over its own pseudonymisation function, and since the filer panel is public and enumerable, a complete lookup table could be built in about an hour.

### 4.3 Reliability

The system fails closed. An invalid, unsigned or missing specification stops the process before it binds a port, with a structured payload naming what failed. There is no partially-configured mode.

### 4.4 Usability

The review queue is designed to be worked by someone who is not a statistician, and the finding detail page is expected to be legible to a compliance officer with no training beyond reading it. Whether that was achieved is untested; see clause 7.3.

### 4.5 Maintainability

The comparability standard is a signed file under version control, never a value in code or configuration state. Changing a tolerance produces a new version with a written rationale and a named author. It is never fitted to make a result look better, and the system will not serve an unsigned specification at all, though historical versions remain loadable so that an old decision can be replayed against the standard in force when it was made.

### 4.6 Portability

The system runs anywhere a container runs, or in a virtual environment on macOS or Linux with no compiler required. Every dependency installs as a pre-built wheel.

### 4.7 Constraints on the solution

No fitted model may determine any output field. This is a requirement rather than a preference, and it has three reasons.

The protected-class exclusion in FR-24 is syntactic; it checks names. A propensity model or learned ranker over the permitted features would be a good proxy for the excluded attributes and would pass every test written to enforce FR-24 while violating it completely in substance.

Second, admission is a conjunction of per-dimension conditions, which is a box. No additive or learned score has level sets that are boxes in more than one dimension, so a score cannot reproduce the region; it can only replace it with a different shape and keep the name.

Third, a lender must be able to reproduce and rebut a finding from the published specification and the public file. "Given the vendor's model" is not a claim a lender can check.

---

## 5. External interface requirements

A REST API under `/v1` with a server-rendered read-only web view at `/ui`, both from the same process. There are no hardware interfaces. There are no communications interfaces, in the sense that the running system opens no outbound connection; the public extract it was built against ships with the software, and retrieving a different one is a manual download performed outside the system.

Data interfaces are two published input layouts — the FFIEC Data Browser export of the Modified LAR, and the Snapshot National Loan Level Dataset — plus the shipped CSV template, three in all. They are separated by scoring the header against each layout's complete required column set rather than by a marker column, because the two regulator products disagree on the unit of `income` while sharing a column name: a detector that guesses between them is wrong by three orders of magnitude and leaves nothing in the load that looks wrong. Every input column, its permitted values and the use the engine makes of it are documented in the data dictionary that ships with the software.

---

## 6. Other requirements

### 6.1 Legal and regulatory

The product is not a fair-lending finding and must not be presented as one. It excludes protected-class attributes by design, so a matched pair with opposite outcomes is evidence of inconsistent underwriting, which is a risk factor worth someone's attention, and not a cause of action.

It is not comparative file review as the Interagency Procedures (R3) define it. That review is constituted by a prohibited-basis group against a control group, marginal-transaction selection, the institution's own written credit standards, and a step where the underwriter is asked to explain. Likewise contributes to two of its eight steps and replaces none of them.

Findings concern identifiable consumers and are treated as sensitive derived data regardless of the public status of the source.

### 6.2 Packaging and deployment

One command installs and one starts. A worked example runs end to end on shipped data without the operator supplying anything, which exists so that a compliance function evaluating the product can see it work before deciding whether to feed it their own filing.

### 6.3 Data requirements

Snapshots are immutable and cited by digest. Republication and late corrections are certainties within the product's life, so a second vintage of a filing year is a second snapshot, and every finding remains replayable against the bytes it was computed from.

---

## 7. Verification and validation

### 7.1 Method

Requirements carry a verification method in clause 3. The automated suite holds 253 tests. Beyond ordinary unit and contract testing, four techniques carry most of the weight.

Mutation testing runs a published, pre-registered catalogue of deliberate defects against the suite and measures how many the suite catches. The gate is ninety per cent and the current rate is 80 of 80. The catalogue is published because a kill rate measured against a private catalogue is unreviewable, and because publishing it prevents the obvious gaming, which is to write mutants you already know you catch.

Metamorphic testing asserts properties that must hold across the whole candidate set rather than on hand-built fixtures: swapping the two sides of a comparison inverts the result where the comparison is resolved, adding a constant to both property values changes no match, rounding both incomes to the published bin changes no outcome.

A true-null fixture generates data with no signal in it at all and asserts the machinery says so. It is about thirty lines, and it would have caught three of the five statistical defects on the first day rather than the fortieth.

Cross-validation computes every statistic a second time against SciPy, statsmodels or NumPy on the same inputs and requires the two to agree to a stated tolerance — floating point for the exact quantities, four Monte Carlo standard errors where the reference is simulated. Ten statistics are covered and all ten agree. The technique earned its place immediately: it found a defect in the exact binomial bound that no existing test could have reached, because the bound was summed as a direct product and overflowed at the very sample sizes the release gate is designed to operate at, and every test in the suite happened to use a small failure count.

Alongside it, a simulation study establishes the operating characteristics that no amount of unit testing can reach — the type-I error rate of the pooled test under a true null across four publication regimes, its power as a function of effect size and cell count, and the realised coverage of both interval estimators. These are properties of the design rather than of the code, and until they were measured they were assumptions.

### 7.2 Acceptance criteria

| ID | Criterion | Status |
| :--- | :--- | :--- |
| AC-1 | One finding hand-traced to two records in the source file | Met |
| AC-2 | Negative control passes; nothing is published until it does | Met |
| AC-3 | Mutation kill rate at or above 0.90 on the published catalogue | Met, 80/80 |
| AC-4 | Full ordered denominator chain published, pre- and post-suppression | Met |
| AC-5 | Startup gate has a fixture asserting process failure | Met |
| AC-6 | Disclosure contract test passes | Met |
| AC-7 | True-null fixture produces a uniform p-value distribution | Met |
| AC-8 | Replay determinism, envelope included | Met |
| AC-9 | Installation reproduced from a clean machine by someone other than the author | **Not met** |
| AC-10 | Every published statistic agrees with an independent reference implementation | Met, 10/10 |
| AC-11 | Pooled test is calibrated or conservative in every simulated regime; never anti-conservative | Met, 12/12 |
| AC-12 | Minimum detectable effect and interval coverage measured and published | Met |

### 7.3 What is not verified

AC-9 is open: the container image has never been built, because no container runtime was available in the environment the software was developed in. Until it is built on a clean machine, the installation path is designed rather than demonstrated.

The other honest gap is that the substantive question has never been asked of a filing large enough to answer it. The one real slice in the repository holds 400 records and 33 denials, and its null envelope spans the entire unit interval; the correct report on that filing is that it is silent, and the system says so. Everything demonstrated at scale has been demonstrated on generated data, which is labelled as such wherever it appears.

More importantly, the value claim is unverified, and this document should be direct about that. A scan in which most findings turn out to have an ordinary explanation passes every criterion in clause 7.2. The quantity that matters is lift, meaning the share of flagged denials that reward a reviewer's time against the share for a randomly chosen matched denial, and measuring it requires a lender's own files and a reviewer's judgement on each.

FR-26 exists partly for this reason. A lender using the product generates exactly the labels needed to measure it, as a by-product of ordinary work, and after a hundred dispositions can compute a number nobody else can compute for them.

---

## 8. Assumptions, dependencies and risks

| ID | Risk | Consequence | Response |
| :--- | :--- | :--- | :--- |
| RK-1 | The sensitivity ceiling is low enough that findings cannot bear weight | The product's value proposition narrows to triage | Accepted and stated in clause 2.6 |
| RK-2 | Only about one denial in five has any comparable approved application | Coverage is thin, and the frame misses the riskiest lending | Accepted; a coverage profile is published per scan |
| RK-3 | Roughly 81.5% of debt-to-income denials can never produce a finding | The largest denial reason in the country is mostly out of reach | Structural, not fixable; documented |
| RK-4 | Small lenders are a poor fit | The intuitive first market is the wrong one | Target selection reconsidered; see clause 2.3 |
| RK-5 | The container build is unverified | Installation may fail on first contact | Open, AC-9 |

RK-3 is a property of the disclosure regime rather than of the implementation. Debt-to-income is published as an exact number only between 36 and 49 per cent, and as an open band above 60. A denial reported above 60 has no upper bound at all, so nothing can be shown to be worse than it, at any sample size, under any correct rule.

---

## Appendix A. Traceability

| Requirement | Design section (R6) | Verification |
| :--- | :--- | :--- |
| FR-1 to FR-6 | 5.1 | T, I |
| FR-7 to FR-9 | 5.2, 6 | T |
| FR-10 to FR-12 | 8 | T |
| FR-13 | 5.2 | T |
| FR-14 to FR-16 | 9.3, 9.4 | T, I |
| FR-17 to FR-19 | 9.5, 5.5 | T |
| FR-20 to FR-24 | 10.1 | T |
| FR-25 to FR-28 | 5.4 | T, D |
