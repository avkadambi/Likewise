# Drop folder

Put a filing here as `.csv` and run `make load`. Nothing else in the project reads this
directory, and nothing is loaded until you ask for it.

    cp docs/templates/likewise_lar_template.csv data/inbox/my_filing.csv
    # edit it, then
    make load

Two layouts are accepted and the loader works out which it is from the header:

| Layout | Where it comes from | Marker |
| :--- | :--- | :--- |
| **FFIEC** | An unmodified export from the FFIEC Data Browser or a Modified LAR file | `loan_to_value_ratio` and `denial_reason-1` |
| **Template** | `docs/templates/likewise_lar_template.csv` | `combined_loan_to_value_ratio` |

Do not mix the two in one load, and do not rename columns to make them match: the loader
would rather refuse than guess.

## One filer, one year, one file

A scan is a pure function of filer, year, specification version and snapshot, so a
snapshot is one filer-year. A file containing two LEIs or two years is refused with both
lists printed. Split it and load each part.

## What will get your file refused

Every one of these prints a machine-readable payload naming the offending rows or columns.
None of them silently coerce, because a load that quietly repairs your data is a load you
cannot audit.

- **A ragged row.** A row whose field count differs from the header is never padded — a
  shifted column is exactly the defect this catches.
- **A code outside its published domain**, for example `action_taken=9`. Nulling it would
  move the record between populations.
- **More than one filer or filing year.**
- **Values that are not at publication granularity.** `loan_amount` and `property_value`
  must sit on `$10,000` bin midpoints (`value mod 10000 == 5000`), `income` must be
  rounded to `$1,000`, and `debt_to_income_ratio` must be an integer in `[36, 49]` or
  blank. This is the one refusal people are most surprised by, and it is the most
  important: the comparability argument rests on the claim that these fields arrive
  already coarsened by the regulator, and the entire resolution budget is derived from
  that coarsening. Full-precision internal data breaks the derivation — every screen would
  state a bin width the values do not have, and differences below the stated floor would
  read as findings.

If you deliberately want to load internal, un-coarsened data — to test the pipeline, say —
pass `--internal-data`. The snapshot is then stamped `public_record: false` in its
manifest and that is carried forward, so nobody later mistakes the run for one made on the
published file.

    .venv/bin/python tools/load.py --internal-data

## Column reference

`docs/templates/likewise_lar_dictionary.csv` — every column, whether it is required, its
allowed values, and what it is used for. Worth reading before filling the template in;
three of the columns behave in ways that are not obvious from their names.

## After loading

`make load` prints the scan command. `make load ARGS=--and-scan` runs the whole sequence —
load, scan, sweep, controls — and prints the URL of the review queue.

Loaded files stay where they are unless you pass `--archive`, which moves them to
`data/inbox/loaded/`.
