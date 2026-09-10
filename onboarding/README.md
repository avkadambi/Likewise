# Likewise — Onboarding

Welcome. This folder is everything you need to understand the product, the method and the
code, in the order it makes sense to read them.

Set aside about half a day. The method is unusual and the reasoning behind it is the part
that matters — most of the code is downstream of a handful of decisions, and if you
understand those the rest reads itself.

## What Likewise does, in three sentences

Mortgage lenders in the United States publish every application they received, whether
they approved it, and for denials the reason they gave. Likewise reads one lender's own
published filing and looks for denials where that same lender approved a comparable
application that was **no better** on the reason cited. It produces a short, prioritised
list of files worth a human reading — not a conclusion about any of them.

## Reading order

| # | Document | Time | What you get |
| :-- | :--- | :--- | :--- |
| 1 | [INSTALL.md](INSTALL.md) | 20 min | It running on your machine, with real data in it |
| 2 | [PRODUCT.md](PRODUCT.md) | 30 min | What it is for, who uses it, what it deliberately is not |
| 3 | [MODELS.md](MODELS.md) | 90 min | The method. Starts with no mathematics at all, then gets precise |
| 4 | [PIPELINE.md](PIPELINE.md) | 30 min | How data moves, what each engine does, the API surface |
| 4b | [reference/PRECEDENCE.md](../docs/PRECEDENCE.md) | 40 min | What changes when a prior decision *governs* rather than being flagged. Read it if the judiciary work is why you are here |
| 4c | [reference/EXTRACTION.md](../docs/EXTRACTION.md) | 30 min | Optional. Reading prose into a record, and why an unsure reader must produce silence. Only relevant once a corpus arrives unstructured |
| 5 | [ARCHITECTURE.md](ARCHITECTURE.md) | 45 min | Components, deployment, security and disclosure design |
| 6 | [TECHNICAL-SPEC.md](TECHNICAL-SPEC.md) | 60 min | Interfaces, schemas, algorithms, evaluation |

Then read `../CONTRIBUTING.md` before you change anything. It is short and every rule in
it is there because breaking it produced a wrong answer that looked right.

If you only have an hour: INSTALL, then MODELS §1–3 and §13.

## Five things to know before you start

**The output is a place to look, not a finding.** Every result carries
`evidentiary_status: screening_hypothesis` in the data itself, and no significance value.
That is a product position, not a legal disclaimer, and it shapes the schema.

**The comparability standard is a signed file, not a parameter.** `specs/` is versioned,
digested, cited on every result, and never fitted. Nobody tunes a tolerance because a scan
produced an inconvenient number. If you find yourself wanting to, that is the moment to
write a rationale and a new version instead.

**The system prefers refusing to guessing.** The loader refuses malformed data rather than
repairing it. The service refuses to start on an invalid specification. Findings are not
servable without a sensitivity sweep. Roughly a dozen gates exist and each one is there
because something got past its absence.

**Scepticism runs in both directions.** A surprisingly *large* result is more likely to be
our defect than a lender's misconduct. So is a surprisingly clean one — the characteristic
failure of this design produces zero. Both trip the same investigation.

**Under a rule of precedence the error asymmetry inverts.** A false flag costs a reviewer
an hour with a file; a decision that is *governed* by a wrongly-admitted precedent is
compelled, and its audit trail is accurate in every field. `likewise/precedent.py` exists
because of that difference, and its central rule is that silence never binds.

**The most interesting result so far is negative.** On every dataset run through the
corrected pipeline, the observed rate came out well *below* what chance would produce. The
lenders' stated reasons order their decisions more consistently than random relabelling
would. MODELS §7 and §13 explain what that does and does not mean. Read them before you
form a view about the product.

## Where the code is

```
likewise/       the engine and the web view
specs/          the comparability standard, versioned
tools/          command-line entry points
tests/          249 tests, plus a mutation catalogue
docs/           the maintained reference set this folder is drawn from
```

`../docs/` is the living documentation and stays current. This folder is a curated
entry path into it — if the two ever disagree, `../docs/` wins.

## Getting stuck

The failure modes worth knowing in advance are collected in `../docs/OPERATIONS.md` §8.
Two that catch everybody:

- **The service exits immediately with a JSON payload.** That is the startup gate refusing
  the specification. It is a real result about the specification, not a broken install.
- **The review queue returns 409.** The scan has no sensitivity sweep. Run
  `make sweep SCAN=…`. There is no flag to bypass it, on purpose.

## A note on the project's history

This design has been through several substantial revisions, including one that retracted
its own central statistical claim after contact with the full national file. The
documentation here describes the current state and the reasoning for it, not the path. If
you want the archaeology, the review records and superseded specifications are preserved
and the rationale for every specification version is in the file itself.
