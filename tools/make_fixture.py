"""Synthetic HMDA-shaped fixture.

Publication effects are applied on purpose: loan_amount and property_value are emitted
at $10,000 bin midpoints and income rounded to $1,000, because the whole point of the
resolution budget is that the public record has already coarsened the dimensions on
which materiality is judged.

A latent credit index drives the decision and is NOT emitted -- that is the omitted
variable the whole design is about. `--signal` plants dominated denials on top of it
so the pipeline has something to find.
"""
from __future__ import annotations
import argparse, math, random
import duckdb

COUNTIES = ["12086", "12011", "12099"]


def bin_mid(x, w):  return math.floor(x / w) * w + w / 2


def build(n=4000, seed=42, signal=0.03, exempt_frac=0.08, resub_frac=0.02):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        county = rng.choices(COUNTIES, weights=[6, 3, 1])[0]
        pv_true = max(60000, rng.lognormvariate(math.log(290000), 0.38))
        ltv_target = min(97.0, max(50.0, rng.gauss(85, 11)))
        la_true = pv_true * ltv_target / 100.0
        inc_true = max(18000, rng.lognormvariate(math.log(95000), 0.45))
        dti = min(64.0, max(12.0, rng.gauss(38, 8)))
        credit = rng.gauss(720, 55)                      # latent, never emitted
        aus = rng.choices([1, 2, 3], weights=[7, 2, 1])[0]

        pv = bin_mid(pv_true, 10000); la = bin_mid(la_true, 10000)
        inc = round(inc_true / 1000) * 1000
        cltv = round(100.0 * la_true / pv_true, 3)
        # Publication rule, not a modelling choice: the public file reports DTI as an exact
        # integer ONLY in [36, 49] and as a >=10pp band everywhere else, and a band has no
        # numeric value. Emitting a continuous DTI made the fixture more informative than
        # the record it stands in for, which is the one thing a fixture must never be.
        dti_pub = float(round(dti)) if 36 <= round(dti) <= 49 else None

        # decision: dominated by the latent index, as in reality
        z = (-1.70 + 0.010 * (760 - credit) + 0.055 * max(0, cltv - 80)
             + 0.045 * max(0, dti - 43) + rng.gauss(0, 0.7))
        denied = 1 / (1 + math.exp(-z)) > 0.50
        action = 3 if denied else rng.choices([1, 2], weights=[9, 1])[0]

        r1 = r2 = None
        if denied:
            if cltv > 88 and rng.random() < 0.45: r1 = 4
            elif dti > 45 and rng.random() < 0.5: r1 = 1
            else: r1 = rng.choice([3, 3, 3, 2, 6, 9])
            if rng.random() < 0.18: r2 = rng.choice([3, 9])

        rows.append(dict(
            record_key=f"R{i:07d}", lei="549300LIKEWISE0001", activity_year=2025,
            action_taken=action, denial_reason_1=r1, denial_reason_2=r2,
            denial_reason_3=None, denial_reason_4=None,
            loan_purpose=rng.choices([1, 31, 32], weights=[7, 2, 1])[0],
            occupancy_type=1, lien_status=1,
            loan_type=rng.choices([1, 2], weights=[8, 2])[0],
            county_code=county, aus_1=aus, construction_method=1,
            total_units=1, submission_of_application=rng.choices([1, 2], weights=[8, 2])[0],
            initially_payable_to_institution=1, conforming_loan_limit="C",
            amortization=1, interest_only_payment=2, balloon_payment=2,
            negative_amortization=2, has_co_applicant=rng.choices([0, 1], weights=[6, 4])[0],
            loan_amount=float(la), income=float(inc), property_value=float(pv),
            combined_loan_to_value_ratio=cltv, debt_to_income_ratio=dti_pub,
            open_end_line_of_credit=2, reverse_mortgage=2, business_or_commercial_purpose=2,
        ))

    # planted signal: dominated collateral denials with a real, above-threshold margin
    planted = 0
    approved = [r for r in rows if r["action_taken"] in (1, 2)]
    for r in rows:
        if r["action_taken"] != 3 or r["denial_reason_1"] != 4: continue
        if rng.random() > signal: continue
        peers = [a for a in approved if a["county_code"] == r["county_code"]
                 and a["loan_purpose"] == r["loan_purpose"] and a["aus_1"] == r["aus_1"]
                 and a["loan_type"] == r["loan_type"]
                 and a["has_co_applicant"] == r["has_co_applicant"]
                 and a["submission_of_application"] == r["submission_of_application"]
                 and abs(a["loan_amount"] - r["loan_amount"]) <= 20000
                 and abs(a["income"] - r["income"]) <= max(0.05 * r["income"], 2000)]
        if not peers: continue
        p = rng.choice(peers)
        p["combined_loan_to_value_ratio"] = round(r["combined_loan_to_value_ratio"] + 9.0, 3)
        p["property_value"] = r["property_value"]
        p["debt_to_income_ratio"] = r["debt_to_income_ratio"]
        planted += 1

    # exempt filers: every reason-engine input blanked, as EGRRCPA does
    for r in rng.sample(rows, int(exempt_frac * len(rows))):
        r["denial_reason_1"] = None; r["denial_reason_2"] = None
        r["combined_loan_to_value_ratio"] = None
        r["debt_to_income_ratio"] = None; r["property_value"] = None

    # resubmissions: same borrower twice, denied then approved
    extra = []
    dens = [r for r in rows if r["action_taken"] == 3 and r["denial_reason_1"] == 4]
    for r in rng.sample(dens, min(len(dens), int(resub_frac * len(rows)))):
        c = dict(r); c["record_key"] = r["record_key"] + "B"; c["action_taken"] = 1
        c["denial_reason_1"] = None; c["denial_reason_2"] = None
        c["combined_loan_to_value_ratio"] = round((r["combined_loan_to_value_ratio"] or 90) + 4.0, 3)
        extra.append(c)
    rows.extend(extra)
    return rows, planted


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--signal", type=float, default=0.03)
    ap.add_argument("--csv", default=None,
                    help="write a template-layout CSV instead of parquet, for the drop folder")
    ap.add_argument("--lei", default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--out", default="data/curated/snapshot=hmda_2025_2026-09-15/"
                                     "activity_year=2025/lei=549300LIKEWISE0001/data.parquet")
    a = ap.parse_args()
    rows, planted = build(a.n, a.seed, a.signal)
    import os, json
    if a.lei or a.year:
        for r in rows:
            if a.lei:
                r["lei"] = a.lei
            if a.year:
                r["activity_year"] = a.year
    if a.csv:
        # Template layout: the internal field names, income in dollars, no record_key
        # (it is a content digest and is derived at load).
        import csv as _csv, sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from likewise.loader import TEMPLATE_COLUMNS
        os.makedirs(os.path.dirname(a.csv) or ".", exist_ok=True)
        with open(a.csv, "w", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=TEMPLATE_COLUMNS)
            w.writeheader()
            for r in rows:
                w.writerow({c: ("" if r.get(c) is None else
                                (int(r[c]) if c in ("loan_amount", "income", "property_value",
                                                    "debt_to_income_ratio")
                                 and r[c] is not None else r[c]))
                            for c in TEMPLATE_COLUMNS})
        n_app = sum(1 for r in rows if r["action_taken"] in (1, 2))
        n_den = sum(1 for r in rows if r["action_taken"] == 3)
        print(f"wrote {len(rows)} rows -> {a.csv}")
        print(f"  approved={n_app}  denied={n_den}  planted_dominated={planted}")
        raise SystemExit(0)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    con = duckdb.connect()
    # No pandas anywhere: stage as JSONL, let DuckDB infer, then COPY to Parquet
    tmp = a.out + ".jsonl"
    with open(tmp, "w") as fh:
        for r in rows: fh.write(json.dumps(r) + "\n")
    con.execute(f"COPY (SELECT * FROM read_json_auto('{tmp}')) TO '{a.out}' (FORMAT PARQUET)")
    os.remove(tmp)
    n_app = sum(1 for r in rows if r["action_taken"] in (1, 2))
    n_den = sum(1 for r in rows if r["action_taken"] == 3)
    print(f"wrote {len(rows)} rows -> {a.out}")
    print(f"  approved={n_app}  denied={n_den}  planted_dominated={planted}")
