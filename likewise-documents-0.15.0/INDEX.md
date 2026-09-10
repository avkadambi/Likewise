# Likewise — document set, version 0.15.0

Four documents, each written to the standard a reviewer will expect. Word for reading and
markup; the markdown source of each sits in `markdown/` and is what the Word file is built
from, so the two cannot disagree.

| Document | Standard | Markdown source |
| :--- | :--- | :--- |
| Software Requirements Specification | ISO/IEC/IEEE 29148:2018 | `markdown/SOFTWARE_REQUIREMENTS_SPECIFICATION.md` |
| Architecture Description | ISO/IEC/IEEE 42010 | `markdown/ARCHITECTURE_DESCRIPTION.md` |
| Software Design Description | IEEE Std 1016-2009 | `markdown/SOFTWARE_DESIGN_DESCRIPTION.md` |
| User Guide | — | `markdown/USER_GUIDE.md` |

## Reading order

Start with the **User Guide** if you want to know what the product does: it walks every
screen and every number for a reader who is not a statistician.

Start with the **Software Requirements Specification** if you want to know what it is
required to do and how each requirement is verified. Clause 7 carries the acceptance
criteria and, more usefully, the list of what is *not* verified.

The **Architecture Description** covers the decisions and their consequences —
stakeholders, viewpoints, the deployment shape, and the disclosure controls. The
**Software Design Description** covers the mechanisms: the comparison lattice, the
resolution budget, the pooled test, the acceptance gates.

## What these documents will not tell you

The value claim is unverified. A scan in which most findings turn out to have an ordinary
explanation passes every acceptance criterion in the specification. Measuring the quantity
that matters — whether a reviewer working this queue finds more, faster, than one working
the filing unaided — needs a lender's own files and a reviewer's judgement on each case.
Both the requirements specification and the user guide say so in their own words.

Apache License 2.0. Copyright 2026 Arun Kadambi.
