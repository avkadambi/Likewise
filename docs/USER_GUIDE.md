# Likewise — User Guide

This guide assumes nothing. It explains what the product does, how to run it, what every
screen shows, and — the part most people skip and shouldn't — what a result does **not**
mean.

If you want the statistics, read [METHOD.md](METHOD.md). If you want the architecture,
read [DESIGN.md](DESIGN.md). If you are deploying it, read [OPERATIONS.md](OPERATIONS.md).

---

## 1. What Likewise does, in one paragraph

Every year, mortgage lenders in the United States publish a record of every application
they received, whether they approved or denied it, and — for denials — the reason they
gave. This is the HMDA public file, and it is genuinely public: anyone can download it.

Likewise reads one lender's own published filing and asks a narrow question, one denial at
a time:

> Among the applications this lender **approved**, is there one that looks the same as
> this denied application on everything the public record shows, and is **no better** on
> the specific thing the lender said it denied for?

When the answer is yes, that denial is flagged. It is a place to look, not a conclusion.

## 2. Why that question is worth asking

A lender that denies an application "for collateral" and, in the same county, in the same
loan programme, approves an application at a *worse* loan-to-value ratio has not
necessarily done anything wrong. Underwriting uses information that never reaches the
public file — credit scores, reserves, employment history, the appraisal narrative. Any
single pair can have a perfectly good explanation.

What Likewise gives you is a **prioritised place to start**: a short list, out of thousands
of denials, where the public record itself does not support the stated reason. A compliance
team reviewing files by hand can only read so many. This decides which ones to read.

That is the entire value claim. Everything else in this document exists to keep the claim
that size.

## 3. What it is not

Read this section before you show anyone a result.

**It is not a fair lending finding.** Likewise deliberately does not look at race,
ethnicity or sex. Without a protected-class axis, a matched pair with opposite outcomes is
evidence of *inconsistent underwriting* — a discretion risk factor — and nothing more.

**It is not comparative file review.** The Interagency Fair Lending Examination Procedures
define that term: a prohibited-basis group against a control group, marginal transactions,
the lender's own written criteria, and a step where the lender explains each pair. Likewise
does the first mechanical slice of the work and none of the rest.

**A finding is not a claim about an application.** Every finding carries
`evidentiary_status: screening_hypothesis` in the data itself, so a downstream system
cannot quietly promote it to something stronger.

**"Collateral" is not "loan-to-value".** Denial reason 4 is a bucket for property
problems of every kind — a failed appraisal, a title defect, an uninsurable structure. A
loan-to-value difference of a point and a half has ordinary explanations.

**Denial reasons are first-sufficient, unranked and not exhaustive.** A lender lists up to
four; the list is not ordered by importance and does not have to be complete.

**Income is not fully comparable across the pair.** For an approved loan the income was
verified. For a denial it is often what the applicant stated.

**Reason-coding is gameable, and the incentive runs the wrong way.** Because Likewise
resolves multiple codes conservatively, a lender who adds untestable codes gets *fewer*
findings. That is why the reason-code composition of each filing is published beside every
result.

## 4. Installing and starting it

Two ways to run it. Both are one command.

**As a container** (recommended for anything but code work — nothing but podman is needed):

```
./install.sh --container
./likewise.sh start
```

**In a virtual environment** (if you are going to edit the code):

```
./install.sh --venv
make serve
```

Either way, open <http://127.0.0.1:8080/ui>.

The container path prints a read/write credential into a `.env` file on first start; sign
in with that. The virtual-environment path uses the development credential `dev-write`,
which is fine locally and wrong anywhere else.

The install runs the specification gate, the test suite and — unless you pass `--quick` —
the mutation gate before it tells you it succeeded. If it stops, it stops with a reason.

To see it work immediately without supplying data:

```
./install.sh --with-example
```

This loads a 15,000-row example filing and runs the whole sequence end to end.

## 5. Loading your own filing

```
make template                       # puts the CSV template in data/inbox/
# edit data/inbox/my_filing.csv
make load                           # or: make load ARGS=--and-scan
```

In the container, the equivalent is `./likewise.sh load`.

Drop any `.csv` into `data/inbox/` and load it. Three layouts are recognised automatically
from the header row:

| Layout | Where it comes from |
| :--- | :--- |
| FFIEC Data Browser export | the CFPB HMDA Data Browser, filtered to your institution |
| Modified LAR | the file your institution publishes itself |
| Template | `docs/templates/likewise_lar_template.csv` in this repository |

`docs/templates/likewise_lar_dictionary.csv` documents every column, its allowed values
and what the engine uses it for.

### The loader refuses; it does not repair

Every refusal prints a payload naming the offending rows or columns. It refuses:

- a **ragged row** — it is never padded, because a shifted column is exactly what that
  catches;
- a **code outside its published domain**;
- **more than one filer or filing year** in a single snapshot;
- values that are **not at publication granularity**.

That last one surprises people, and it is the one that matters most.

### Publication granularity, and why it is enforced

The regulator publishes these fields already rounded:

| Field | Published form |
| :--- | :--- |
| `loan_amount` | midpoint of a $10,000 bin (so `x mod 10000 == 5000`) |
| `property_value` | midpoint of a $10,000 bin |
| `income` | rounded to $1,000 |
| `debt_to_income_ratio` | an exact integer only inside `[36, 49]`; a band otherwise (`<20%`, `20%-<30%`, `30%-<36%`, `50%-60%`, `>60%`) |

Every comparability threshold in Likewise is *derived from* that rounding. If you load
data at full internal precision, the derivation is wrong and every screen states a bin
width the values do not have. So the loader refuses.

`--internal-data` loads it anyway and stamps the snapshot `public_record: false`. The
stamp travels: the coverage screen says so on every scan of that snapshot, permanently.

## 6. Running a scan

A scan is one filer, one filing year, one specification version, one snapshot. Its
identifier is derived from that tuple, so the same inputs always produce the same scan.

```
make scan                           # or ./likewise.sh scan <LEI> <YEAR>
make sweep    SCAN=scn_...          # required
make controls SCAN=scn_...          # required before publication
```

You can also start a scan from the web view, on `/ui/scans`.

### Why the sweep is required

`GET /v1/scans/{id}/findings` and the web review queue both return **409 Conflict** if the
scan has no sweep. This is deliberate.

The first question any informed reader asks is *"did you pick the threshold that produced
this result?"* The sweep re-runs the scan across a grid of tolerance values and publishes
the resulting curve. A finding may not be shown without the curve that answers that
question. There is no flag to skip it.

### Why the controls are required

The controls answer *"does this engine only fire on the reason that was actually cited, or
does it fire on anything?"* It re-runs the identical engine against a **placebo** dimension
the lender did not cite. If the cited dimension does not fire meaningfully more often than
the placebo, the engine is detecting noise and nothing is published.

## 7. Reading the screens

### Scans — `/ui/scans`

Every snapshot loaded, every scan run. Each row is labelled with the snapshot it used and
whether that snapshot is real public data or a fixture. A scan whose specification
post-dates its pre-registration is labelled **exploratory** here and on every finding it
produced.

### Coverage — `/ui/scans/{id}/coverage`

**Read this before the findings.** It is the denominator chain: how the population shrank
from every record in the filing down to the handful of findings, with the reason at each
step.

```
records in scope
  → denials in scope
  → denials not partially exempt          (exempt filers omit the fields we need)
  → denials with a complete record
  → denials with a matched comparator     (same cell, same key)
  → denials testable by their stated code
  → denials in an adequately powered cell
  → denials with a finding
```

Each row states its own denominator. Testability is a property of the denial's stated
reason code, not of whether it matched, so it is reported as a marginal over all denials in
scope as well.

The coverage screen also carries the **coverage profile**: matched fraction and finding
rate broken out by county volume, submission channel, loan purpose and complete-case
status. This is not decoration. A comparison cell exists only where the lender has volume,
so the method is structurally blind to thin markets, non-metropolitan lending, the broker
channel, manual underwriting and small filers — which is where underwriting discretion is
*largest*. The sampling frame is anti-correlated with the risk it is meant to prioritise,
and the coverage profile is where the product says so out loud.

### Review queue — `/ui/scans/{id}/queue`

The findings, ordered by priority. Each row shows the denial, the comparator, which
dimension decided it, the margin, and the size of the cell it came from.

**There is no significance score, and that is intentional.** The ranking is a triage
order — how far apart the two records are on the tested dimension, relative to the
smallest difference the published data can actually resolve. See §8.

### Finding detail — `/ui/scans/{id}/findings/{fid}`

One denial, one approved comparator, side by side. For each you see:

- the **banded** value of every published financial field (see below);
- the **tested dimension**, its direction, the margin between the two records, and the
  decisive threshold that applied *to this pair*;
- the cell: how many records were in it, where this denial ranked, and whether the cell was
  large enough to say anything;
- **Γ\*** (gamma-star), the sensitivity number described in §8;
- the specification digests and snapshot identifier, so the pair can be re-derived.

At the bottom is a disposition form: record what you checked and what you concluded. That
note is saved with your name and the date, and it stays with the finding.

**Why banded and not exact.** Everything published by Likewise passes through a single
serialisation boundary that bands financial values. An exact margin at six decimal places,
sitting next to four banded quasi-identifiers, is very nearly a unique key for the pair —
which would defeat the disclosure protection everywhere else. So the view shows the band,
the margin bucketed to multiples of the applicable threshold, and the threshold itself.

**Why county and not census tract.** The geography ceiling in force is the county. Census
tract is dropped at ingest, so no downstream code can emit it even by accident.

### Sweep — `/ui/scans/{id}/sweep`

The exceedance curve: how the finding count moves as the tolerance moves. A result that
only exists at one point on this curve is a result that was chosen rather than found.

### Controls — `/ui/scans/{id}/controls`

The placebo comparison, and whether it passed. Nothing is published from a scan whose
controls failed.

### Specification — `/ui/spec`

The comparability standard in force: every dimension, its tolerance, the written rationale
for that tolerance, and the author who signed it. Every finding cites this by digest.

## 8. The numbers on a finding, in plain language

**Margin.** How far apart the two records are on the tested dimension, in that dimension's
own units. Positive means the approved comparator is worse.

**Decisive threshold.** The smallest difference that counts as a real difference *for this
pair*. It is not one number for the whole scan: it is computed at the pair's own
magnitudes, because the published data resolves a percentage point of loan-to-value very
differently on a $125,000 house than on an $800,000 one. See METHOD.md §5.

**Margin ratio.** Margin ÷ the granularity of the field. A margin of 0.1 percentage points
and one of 5.0 used to produce identical verdicts; on a field published in bins, the first
is a rounding artefact. The ratio is what tells them apart.

**Cell size, and rank in cell.** The cell is the group of comparable records this denial
was compared against. Rank is where the denial sat inside it. Rank is a *midrank* and is
therefore often fractional — on data published in bins, ties are the normal case, not the
exception.

**Cell power.** `adequate` or `underpowered`. A small cell, or a cell where everything is
tied, cannot distinguish anything however strong the underlying effect. Underpowered cells
are counted separately and never presented as findings.

**Γ\* (gamma-star).** The honest one. It answers: *how much hidden bias would it take to
explain this away?* Γ\* = 1 means none at all — any unmeasured difference between the two
applicants is enough. Γ\* = 5 means an unmeasured factor would have to make one applicant
five times more likely to be denied before the result dissolves. Two applications identical
on every published field and 90 FICO points apart is completely ordinary, and that alone is
worth a Γ in the mid single digits. **Read Γ\* before you read the margin.**

## 9. What a scan-level result claims

Individual findings carry no significance value. The statistical claim Likewise makes is
made once per scan, over all of a filer's denials at once:

> Across this filer's denials, the dimension the filer's own stated reason names does not
> order the decisions.

That is a claim about a filer, not about an application. METHOD.md §7 explains why the
claim sits at that level and not at the level of a single pair.

## 10. Guard rails you will meet

These stop the product rather than warn you. Each is there because it caught something
real.

| What stops you | When |
| :--- | :--- |
| Startup gate | The specification declares a threshold finer than the published data can resolve. The service exits before it binds the port |
| Granularity check | You loaded data that is not at the regulator's coarsening |
| Post-treatment diagnostic | A matching field turns out to be determined by the outcome, so matching on it is circular. It refuses per field, with the reason |
| Sweep requirement | You asked for findings from a scan with no sweep — 409 |
| Controls gate | The placebo comparison did not pass; nothing is published |
| Egress contract | A response, an export or a rendered page tried to carry a raw institution identifier, a census tract, a record key or a per-application raw value |
| Two-sided tripwire | A headline rate above **or below** its expected band. A surprisingly large rate is far more likely to be a bug than misconduct — and the characteristic failure of this design produces zero, so a suspiciously clean result is investigated with equal force |

## 11. Command reference

| Command | What it does |
| :--- | :--- |
| `./install.sh` | Install, container or virtualenv, with all gates |
| `./likewise.sh start` \| `stop` \| `status` \| `logs` | Run the container |
| `make serve` | Run in the virtualenv |
| `make template` | Copy the CSV template into the drop folder |
| `make load ARGS=--and-scan` | Load `data/inbox/`, then scan, sweep and run controls |
| `make example` | The whole sequence on the shipped example filing |
| `make scan` / `make sweep SCAN=…` / `make controls SCAN=…` | The three steps separately |
| `make test` | The test suite |
| `make mutate` | The mutation gate |
| `make help` | Everything |

## 12. If something goes wrong

**The service exits immediately with a JSON payload.** That is the startup gate refusing
the specification. The payload names the dimension and the rule. This is a real result
about the specification, not an installation problem.

**A load refused.** Read the payload; it names the rows or columns. The most common cause
is data that is not at publication granularity.

**A scan produced no findings.** That is a normal and common outcome — check the coverage
screen. Usually the chain shows the population dropping out at matching (the filer is
dispersed across many geographies) or at testability (the stated reasons are codes the
public record cannot adjudicate).

**The queue returns 409.** The scan has no sweep. Run `make sweep SCAN=…`.

**Findings look too good.** Investigate them exactly as hard as findings that look too bad.
See the tripwire row in §10.
