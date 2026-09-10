# Likewise — Product Definition

| | |
| :--- | :--- |
| Document | Product definition |
| Product | Likewise |
| Author | Arun Kadambi |
| Date | 9 September 2026 |
| Status | Current |
| Related | MODELS.md, ARCHITECTURE.md, TECHNICAL-SPEC.md |

This document defines what Likewise does, who uses it, and the conditions under which it is
accepted. It does not describe how it is built.

---

## 1. Problem

Lenders file mortgage application outcomes to HMDA. The file is public and includes the
coded reason for every denial.

Nobody compares two applications in that file against each other. Fair-lending vendors run
portfolio-level regressions and report a disparity coefficient. Examiners perform comparative
file review by hand, on a sample, once a cycle.

So a lender learns which of its own files do not stand up to comparison at examination —
from the examiner, after the fact. The data required to find them earlier is public and free.

## 2. Definition

Likewise reads a lender's own published HMDA filing, identifies pairs of applications that
are materially identical on legitimate underwriting features but received opposite outcomes,
and tests whether the coded denial reason survives that comparison. The output is a ranked
queue of pairs for human review.

Delivered as a REST API with a server-rendered web view over it.

## 3. Users

| | User | Need |
| :--- | :--- | :--- |
| U1 | Fair-lending officer at a mid-tier lender | Find and fix comparison-vulnerable files before an examination |
| U2 | Internal audit | Evidence that comparative review was performed, and on what basis |
| U3 | Outside counsel | Reproducible, parameterised analysis with a stated method |

U1 is the buyer and the primary user. U2 and U3 consume the same output read-only.

## 4. Goals

| | Goal | Measure |
| :--- | :--- | :--- |
| G1 | Name specific comparable pairs, not portfolio statistics | A result identifies two application records |
| G2 | Test the stated reason against the comparator | Every result carries survives / not-supported / untestable |
| G3 | Make the comparability standard inspectable and contestable | The specification is a published, versioned file |
| G4 | Run exhaustively and repeatedly, not on a sample once a cycle | A full-filer scan completes unattended within one run window |
| G5 | Operate with minimal infrastructure | No database, no cluster, no cloud account required |

## 5. Out of scope

| | |
| :--- | :--- |
| NG1 | Determining that discrimination occurred. Likewise produces screening hypotheses for the lender to check against its own origination file |
| NG2 | Analysis of non-public or lender-internal data |
| NG3 | Statistical disparity testing on protected class. That is the incumbent category and is not what this product does |
| NG4 | Lenders below the HMDA reporting threshold |
| NG5 | Multi-tenancy, billing, SSO. Single-tenant deployment |

NG3 is the consequential one. It forecloses any fair-lending claim, and the method is correct
under every resolution of that question — but a matched pair with opposite outcomes and no
protected-class axis is *inconsistent underwriting*, a discretion risk factor, and nothing
more. A syntactic guard prevents accidental introduction of a protected-class field, and
MODELS §17 sets out what could be learned without relaxing the exclusion.

## 6. Functional requirements

| | Requirement |
| :--- | :--- |
| FR-1 | Ingest a published HMDA filing and make it queryable |
| FR-2 | Generate candidate application pairs within a lender and filing year |
| FR-3 | Classify a candidate pair as matched or not against a named specification version |
| FR-4 | For a matched pair with opposite outcomes, classify the stated reason as survives, not-supported, untestable, or incomparable |
| FR-5 | Return results in a deterministic priority order |
| FR-6 | Expose the specification and reason testability map as retrievable documents |
| FR-7 | Return, for any result, the per-dimension comparisons that produced it |
| FR-8 | Evaluate a single caller-supplied pair synchronously |
| FR-9 | Produce a tolerance sensitivity sweep for a completed scan |
| FR-10 | Pseudonymise institution identifiers in all responses |
| FR-11 | Record the specification versions and digests on every result |
| FR-12 | Report coverage: results, matched pairs and untestable denials against their denominators |
| FR-13 | Web view listing a scan's ranked results, with a detail page and disposition capture |

**FR-5 carries no calibrated probability.** The outcome is a deterministic function of the
margin, so fitting a margin-to-probability model recovers a step function of its own input.
A calibrated score requires human-verdict labels the current budget does not fund.

## 7. Non-functional requirements

| | Requirement | Target |
| :--- | :--- | :--- |
| NFR-1 | Single-filer scan completes unattended | ≤ 30 min for a mid-tier filer |
| NFR-2 | Synchronous pair evaluation, warm path | p95 ≤ 500 ms |
| NFR-3 | Install from a clean checkout | One command |
| NFR-4 | Runtime dependencies | Five packages, all pure wheels |
| NFR-5 | Reproducibility | Content identity under a declared canonical hash |
| NFR-6 | No managed database, cluster or orchestrator | Local filesystem plus one container runtime |

NFR-6 is a hard constraint, not a preference. It is what makes NFR-3 achievable and it
drives the architecture.

NFR-5 is **content** identity, not byte identity. Parquet byte-identity additionally requires
pinned writer and codec versions and single-threaded writes, and is broken by design across
deployments because the pseudonymisation key differs.

## 8. Data constraints

The public file carries disclosure protections: loan amount is published at bin midpoint,
property value and income are rounded, parts of the debt-to-income range are bucketed, and
free-form text is removed.

Two consequences bind the product.

**No tolerance may be tighter than the corresponding publication bin width.** A tolerance
below the granularity of the published field is not a measurement. This is validated at load
and the service refuses to start on a violation.

**Two records indistinguishable to Likewise may differ materially in the lender's own file.**
Every result is therefore a screening hypothesis, and NG1 is a product statement rather than
a disclaimer.

Bin widths and top-coding rules for the filing year in use are stored as a dated snapshot and
validated against the retrieved file, not taken from any document.

## 9. Reason testability

A reason is testable only where the public record contains the dimension it names.

| Code | Reason | Dimension | In public record | Testable |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Debt-to-income ratio | DTI | Yes, partly banded | At band resolution |
| 2 | Employment history | Employment | No | No |
| 3 | Credit history | Credit score | No | No |
| 4 | Collateral | LTV, property value | Yes | Yes |
| 5 | Insufficient cash | Down payment, derived | Partial | Weak, flagged as derived |
| 6 | Unverifiable information | Procedural | No | No |
| 7 | Application incomplete | Procedural | No | No |
| 8 | Mortgage insurance denied | Third-party decision | No | No |
| 9 | Other | Unspecified | No | No |

Codes 4 and 1 are tested. Code 5 is deferred. All others return untestable.

**Untestable is a reported outcome with its own count.** It is never merged into survives or
not-supported, and every rate carries its denominator.

**Multi-code denials resolve conservatively.** A denial citing an untestable code alongside a
testable one is untestable as a whole. Reasons are first-sufficient, unranked and
non-exhaustive, so "the public record does not support the reason you cited" is only
defensible when every cited reason was examined. This is declared in the specification
(`multi_code_policy`) rather than implied by the engine, because the alternative changes the
estimand rather than the count.

**A consequence worth stating.** Conservative resolution means the result rate *falls* as a
lender adds untestable codes. The incentive runs the wrong way, so reason composition is
published per filer alongside every rate.

## 10. The specification

The comparability standard is a versioned YAML document, authored and signed by a named
person, retrievable through the API, and cited by version and digest on every result.

It is not a hyperparameter and it is not fitted. No statute defines materiality numerically:
a 0.4 percentage-point difference is the entire case in some files and noise in others. Loose
tolerances implicate every lender, tight ones implicate none, and no held-out accuracy figure
identifies the correct value because the target is partly defined by the choice.

| | Requirement |
| :--- | :--- |
| MS-1 | The specification is a file under version control, not a value in code or configuration state |
| MS-2 | Changing a tolerance produces a new version with a written rationale and a named author |
| MS-3 | Tolerances are validated at load against the publication snapshot. A tolerance tighter than its field's granularity is a load error |
| MS-4 | The sensitivity sweep across tolerance values ships alongside the operating point |

MS-4 is a product requirement rather than an analysis convenience. The first question any
informed reviewer asks is whether the threshold was chosen to produce the result, and the
sweep is the answer. It is enforced: findings are not servable without it.

## 11. Acceptance

| | Criterion |
| :--- | :--- |
| AC-1 | One result hand-traced to two source records |
| AC-2 | Paired discordance control passes, pooled nationally, with a real power calculation. **Nothing is published until this passes** |
| AC-3 | The pooled scan-level test, with its null built over every matched testable denial |
| AC-4 | Approved-to-approved decoy arm separates from the matched-pair arm |
| AC-5 | Mutation kill rate ≥ 0.90 on the published catalogue; guard items 100% |
| AC-6 | Inter-rater and intra-rater agreement lower bounds ≥ 0.60 on the boundary arm |
| AC-7 | Median margin ratio ≥ 2.0, excluding quantised dimensions, with the quantised share reported beside it |
| AC-8 | Exceedance curve published across the sweep, null recomputed per grid point |
| AC-9 | Full ordered denominator chain, pre- and post-suppression rates, cell-power counts |
| AC-10 | Startup-gate CI fixture asserts process failure on every rule |
| AC-11 | Egress contract test passes |
| AC-12 | Deployment reproduced from a clean checkout by someone other than the author |
| AC-13 | True-null fixture: labels assigned at random within cells produce a uniform p-value distribution |

**Stated openly: no gate reads the rebuttal rate.** A scan in which 90%
of results are rebutted by a named public field passes every gate above. The estimand that
matters is *lift* — P(rebutted | flagged) ÷ P(rebutted | random matched testable) — and at
the current label budget its interval spans "worse than random" to "five times better".
Either the budget rises to roughly 965 labels or the limitations section says plainly that
the core value claim is not evaluated.

## 12. Expected results and tripwires

Every headline carries a tripwire that triggers investigation rather than acceptance.

| Quantity | Tripwire |
| :--- | :--- |
| Denials with at least one matched comparator | Below 2%: tolerances tighter than bin widths. Above 60%: too loose for the pairs to be comparable |
| Share not supported | Below 1% or above 40%: treat as a defect until an independent replay confirms it |
| Median margin ratio | Below 2.0 |
| Cited-over-placebo ratio | Below 2.0 |
| Pooled scan-level statistic | z above 3.0 — the claim being raised. Re-derive before anything reaches a customer |

**Tripwires are two-sided by default.** A surprisingly large result is more likely to be a
defect in this software than a lender's misconduct, and the characteristic failure of this design produces
zero — so a suspiciously clean result gets the same treatment. The scan-level statistic is the
one deliberate exception, banded above only: |z| scales with the square root of the cell
count, so a lower bound could only be read off whatever scan happened to be at hand.

## 13. Compliance constraints

| | Constraint |
| :--- | :--- |
| LC-1 | Institution identifiers are pseudonymised in all outputs. Named-institution results are not produced, displayed or exported |
| LC-2 | No output displays geography finer than the county, and no export contains the joined source record |
| LC-3 | A written re-identification risk assessment ships with the release |
| LC-4 | Every external claim in customer-facing material cites a primary source |

LC-1 and LC-2 are enforced in code at a single serialisation boundary, not by convention.

LC-3 exists because the disclosure protections on the source file are there for a reason:
tract plus value plus income can identify a borrower. A matched-pair product narrows to two
records in one county and attaches an adverse inference to one of them, which is a different
disclosure surface from the one the original assessment covered.

## 14. Limitations carried on every export

- The inferential claim is scan-level, not per-result.
- The sampling frame is anti-correlated with the risk it prioritises: cells exist only where
  a filer has volume, so the method is blind to thin markets, non-metropolitan lending, the
  broker channel, manual underwriting and small filers.
- About 81.5% of debt-to-income denials cannot produce a result at any sample size.
- Sensitivity to unmeasured confounding is bounded above by the coarsening.
- Collateral is not loan-to-value. Denial reasons are first-sufficient, unranked and
  non-exhaustive. Income is not fully commensurable across a pair. Reason-coding is gameable.

The full list is MODELS §16. It is worth reading before showing anyone a result.
