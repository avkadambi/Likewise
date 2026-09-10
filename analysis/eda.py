"""Exploratory analysis of the data the engine actually reads.

WHY THIS COMES BEFORE ANY MODELLING
-----------------------------------
Every design choice in this product is a response to a property of the published record
rather than a preference: interval dominance instead of a score because the values are
binned; a pooled test instead of a per-cell one because the cells are tiny; a decisive
threshold that is a maximum of three floors because two of those floors are set by the
publication scale. None of that is defensible if the properties are asserted. This
module measures them.

Four profiles, in the order the record passes through the engine:

  1. GRANULARITY. What the published values can and cannot express. Loan amount and
     property value arrive as $10,000 bin midpoints, income rounded to $1,000, DTI as an
     exact integer only inside [36, 49] and as a coarse band elsewhere. Each of those is
     checked against the data rather than taken from Regulation C, because a filer can
     and does deviate.

  2. AVAILABILITY. What is missing, and why -- an EGRRCPA partial exemption is not the
     same absence as an unreported field, and conflating them would let an exempt filer
     look like a well-populated one.

  3. BLOCK AND CELL STRUCTURE. The exact-match key partitions the filing; the size of the
     resulting cells is the single parameter that decides whether any per-cell inference
     is possible at all.

  4. ATTAINABILITY. Given those cell sizes and their ties, the smallest p-value each cell
     could ever produce -- computed before any comparison is made, because it does not
     depend on one.

Run it:  python -m analysis.eda
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from likewise import specs, stats

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "out"

# The two snapshots in the repository. One is a real FFIEC slice, the other is generated
# at a size no single small filer reaches. They are labelled, always, and never pooled:
# a figure that mixed them would be reporting a property of the generator as a property
# of the record.
SNAPSHOTS = {
    "ffiec_2024_real": {
        "path": ("data/curated/snapshot=hmda_2024_ffiec_2026-09-07/activity_year=2024/"
                 "lei=549300MGPZBLQDIL7538/data.parquet"),
        "provenance": "real -- FFIEC 2024 snapshot, one filer, income in thousands"},
    "fixture_2025_generated": {
        "path": ("data/curated/snapshot=hmda_2025_2026-09-15/activity_year=2025/"
                 "lei=549300LIKEWISE0001/data.parquet"),
        "provenance": "GENERATED fixture -- structure only, no inference may rest on it"},
}

NUMERIC = ["loan_amount", "income", "property_value",
           "combined_loan_to_value_ratio", "debt_to_income_ratio"]


def load(name: str) -> pd.DataFrame:
    """Read one snapshot into a DataFrame through DuckDB.

    DuckDB rather than pandas' own Parquet reader because it is the engine's reader: the
    profile should see the values the engine sees, including its type coercions, not a
    second library's interpretation of the same file.
    """
    path = ROOT / SNAPSHOTS[name]["path"]
    if not path.exists():
        raise FileNotFoundError(path)
    return duckdb.connect().execute(f'SELECT * FROM "{path}"').df()


# ---------------------------------------------------------------------------
# 1. Granularity
# ---------------------------------------------------------------------------
def granularity(df: pd.DataFrame) -> list[dict]:
    """What resolution each numeric field is actually published at.

    THE TEST. If a column is published at bin midpoints of width w, every non-null value
    satisfies (v - w/2) mod w == 0. The profile checks the candidate widths directly
    rather than assuming the regulation was followed, and reports the SHARE that
    conforms, so a partial deviation is visible instead of being rounded away by an
    all-or-nothing assertion.

    The consequence is the publication floor: two values that differ by less than one bin
    are not distinguishable in the filing at all, whatever the true difference was. That
    floor is one of the three terms in the decisive threshold, and this is where its
    value comes from.
    """
    out = []
    for col in NUMERIC:
        if col not in df:
            continue
        v = pd.to_numeric(df[col], errors="coerce").dropna()
        if v.empty:
            out.append({"field": col, "n": 0, "note": "no numeric values present"})
            continue
        row = {"field": col, "n": int(v.size),
               "distinct": int(v.nunique()),
               "min": float(v.min()), "median": float(v.median()), "max": float(v.max()),
               "distinct_per_observation": round(v.nunique() / v.size, 4)}
        # Candidate publication grids, largest first. The first that fits is reported;
        # "fits" means at least 99% of values land on it, which tolerates a handful of
        # corrected records without tolerating a column that is not on the grid at all.
        for w in (10000, 1000, 100, 10, 1):
            mid = float(np.mean(np.isclose((v - w / 2) % w, 0)))
            edge = float(np.mean(np.isclose(v % w, 0)))
            if mid >= 0.99:
                row["published_grid"] = f"{w:g} bin midpoints"
                row["grid_conformance"] = round(mid, 4)
                row["publication_floor"] = float(w)
                break
            if edge >= 0.99:
                row["published_grid"] = f"multiples of {w:g}"
                row["grid_conformance"] = round(edge, 4)
                row["publication_floor"] = float(w)
                break
        else:
            row["published_grid"] = "no common grid at 99%"
            row["publication_floor"] = None
        # The tie load: how much of the column sits on its most common single value. This
        # is the quantity that caps every rank statistic computed on the field, and it is
        # not implied by the grid -- a fine grid with a concentrated distribution ties
        # just as badly as a coarse one.
        top = v.value_counts()
        row["modal_value"] = float(top.index[0])
        row["modal_share"] = round(float(top.iloc[0] / v.size), 4)
        row["top5_share"] = round(float(top.iloc[:5].sum() / v.size), 4)
        out.append(row)
    return out


def dti_band_structure(df: pd.DataFrame) -> dict:
    """The one field whose resolution CHANGES across its own range.

    Regulation C publishes DTI as an exact integer only inside [36, 49]. Outside that
    window it arrives as a band -- "<20%", "20%-<30%", ">60%" and so on -- so two
    applicants twenty points apart can be reported identically. The engine's DTI
    comparison is therefore exact in the middle and interval-valued at the ends, and this
    profile is the evidence for that split.
    """
    v = pd.to_numeric(df.get("debt_to_income_ratio"), errors="coerce")
    present = v.dropna()
    if present.empty:
        return {"n": 0}
    exact_window = present.between(36, 49) & (present % 1 == 0)
    return {"n_records": int(v.size),
            "n_present": int(present.size),
            "absent_share": round(float(v.isna().mean()), 4),
            "exact_integer_in_36_49_share": round(float(exact_window.mean()), 4),
            "outside_window_share": round(float((~exact_window).mean()), 4),
            "distinct_values": int(present.nunique()),
            "value_counts": {str(k): int(x) for k, x in
                             present.value_counts().sort_index().items()},
            "consequence": ("inside the window a one-point difference is expressible; "
                            "outside it a ten-point difference may not be")}


# ---------------------------------------------------------------------------
# 2. Availability
# ---------------------------------------------------------------------------
def availability(df: pd.DataFrame) -> list[dict]:
    """Missingness, separated from exemption.

    An EGRRCPA partial exemption is a lawful refusal to report, arriving as the string
    "Exempt" or the sentinel 1111 depending on the layout. It is not the same as a field
    the filer simply left blank, and the two must not be pooled: an exempt filer is
    outside the product's scope, while a filer with sporadic blanks is inside it with
    fewer testable records. The loader maps both to null, so the count is taken here
    against the raw column.
    """
    out = []
    for col in df.columns:
        s = df[col]
        raw = s.astype("string")
        exempt = raw.str.strip().str.lower().eq("exempt") | raw.eq("1111")
        out.append({"field": col,
                    "null_share": round(float(s.isna().mean()), 4),
                    "exempt_marked_share": round(float(exempt.fillna(False).mean()), 4),
                    "distinct": int(s.nunique(dropna=True))})
    return sorted(out, key=lambda r: -r["null_share"])


# ---------------------------------------------------------------------------
# 3. Block and cell structure
# ---------------------------------------------------------------------------
def block_structure(df: pd.DataFrame, spec) -> dict:
    """Partition the filing on the exact-match key and measure what comes out.

    The key is taken from the specification in force, not restated here, so this profile
    cannot drift away from what the engine blocks on. Records that share the key are
    candidates for comparison; records that do not are never compared, whatever they look
    like.

    Reported: how many blocks, how large, and -- the number that governs everything
    downstream -- how many blocks contain BOTH a denial and an approval. A block with
    denials and no approvals produces nothing, and it is a large share of the filing.
    """
    key = [k for k in spec.blocking_key if k in df.columns]
    d = df.copy()
    # Action taken 3 is "application denied"; 1 is "loan originated". The engine's
    # population rules are richer than this, but the block-structure question is about
    # who can be compared with whom, and that only needs the two roles.
    d["_role"] = np.where(d["action_taken"] == 3, "denied",
                          np.where(d["action_taken"] == 1, "approved", "other"))
    g = d.groupby(key, dropna=False)["_role"]
    sizes = g.size()
    denied = g.apply(lambda s: int((s == "denied").sum()))
    approved = g.apply(lambda s: int((s == "approved").sum()))
    usable = (denied > 0) & (approved > 0)
    cell_sizes = (denied + approved)[usable]
    return {"blocking_key": key,
            "n_records": len(d),
            "n_blocks": int(sizes.size),
            "block_size_distribution": {str(int(k)): int(v) for k, v in
                                        sizes.value_counts().sort_index().items()},
            "blocks_with_a_denial": int((denied > 0).sum()),
            "blocks_with_both_roles": int(usable.sum()),
            "share_of_denials_in_a_usable_block": round(
                float(denied[usable].sum() / max(denied.sum(), 1)), 4),
            "usable_cell_size_median": (float(cell_sizes.median())
                                        if cell_sizes.size else None),
            "usable_cell_size_max": (int(cell_sizes.max()) if cell_sizes.size else None),
            "note": ("a denial in a block with no approval is not a negative result; "
                     "it is a record the public data cannot speak to")}


# ---------------------------------------------------------------------------
# 4. Attainability
# ---------------------------------------------------------------------------
def attainability(df: pd.DataFrame, spec, q_target: float = 0.05) -> dict:
    """The smallest p each usable cell could ever produce, before any comparison.

    THE ARITHMETIC. A record can be no more extreme than the tie block it sits in, so a
    cell's floor is |best tie block| / n. The floor depends only on the cell's values and
    its size; it is fixed the moment the filing is published.

    Reported as a distribution and as a single share -- what fraction of cells could
    reach the target at all. Where that share is zero, no per-cell claim is available at
    any evidence level, and the design's decision to pool is not a preference but the
    only remaining option.
    """
    key = [k for k in spec.blocking_key if k in df.columns]
    d = df.copy()
    d["_role"] = np.where(d["action_taken"] == 3, "denied",
                          np.where(d["action_taken"] == 1, "approved", "other"))
    floors, sizes = [], []
    for _, grp in d[d["_role"].isin(["denied", "approved"])].groupby(key, dropna=False):
        if not (grp["_role"] == "denied").any() or not (grp["_role"] == "approved").any():
            continue
        vals = pd.to_numeric(grp["debt_to_income_ratio"], errors="coerce").dropna()
        if vals.size < 2:
            continue
        floors.append(stats.min_attainable_p(list(vals.astype(float))))
        sizes.append(int(vals.size))
    if not floors:
        return {"cells": 0, "note": "no cell carries two or more reported DTI values"}
    f = np.array(floors)
    return {"cells": int(f.size), "q_target": q_target,
            "share_capable_of_reaching_q": round(float(np.mean(f <= q_target)), 4),
            "median_floor": round(float(np.median(f)), 4),
            "best_floor": round(float(np.min(f)), 4),
            "cell_size_median": int(np.median(sizes)),
            "cell_size_max": int(np.max(sizes)),
            "floors": [round(float(x), 6) for x in f],
            "sizes": sizes}


# ---------------------------------------------------------------------------
def profile(name: str) -> dict:
    df = load(name)
    spec = specs.load(ROOT / "specs")
    return {"snapshot": name,
            "provenance": SNAPSHOTS[name]["provenance"],
            "rows": len(df),
            "action_taken_counts": {str(int(k)): int(v) for k, v in
                                    df["action_taken"].value_counts().sort_index().items()},
            "granularity": granularity(df),
            "dti_bands": dti_band_structure(df),
            "availability": availability(df)[:15],
            "blocks": block_structure(df, spec),
            "attainability": attainability(df, spec)}


def run_all() -> dict:
    out = {}
    for name in SNAPSHOTS:
        try:
            out[name] = profile(name)
        except FileNotFoundError as exc:
            out[name] = {"snapshot": name, "unavailable": str(exc)}
    return out


def main() -> int:
    rep = run_all()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eda.json").write_text(json.dumps(rep, indent=2, default=float))
    for name, p in rep.items():
        if "unavailable" in p:
            print(f"\n{name}: not present ({p['unavailable']})")
            continue
        print(f"\n{name}  ({p['provenance']})")
        print(f"  {p['rows']} records; action_taken {p['action_taken_counts']}")
        print(f"  {'field':<32}{'grid':>24}{'modal':>9}{'top5':>8}{'distinct/obs':>14}")
        for g in p["granularity"]:
            if not g.get("n"):
                continue
            print(f"  {g['field']:<32}{g.get('published_grid', '-'):>24}"
                  f"{g['modal_share']:>9.3f}{g['top5_share']:>8.3f}"
                  f"{g['distinct_per_observation']:>14.4f}")
        b = p["blocks"]
        print(f"  blocks: {b['n_blocks']} over {b['n_records']} records; "
              f"{b['blocks_with_both_roles']} carry both a denial and an approval; "
              f"{b['share_of_denials_in_a_usable_block']:.1%} of denials are comparable")
        a = p["attainability"]
        if a.get("cells"):
            print(f"  attainable p: {a['share_capable_of_reaching_q']:.1%} of "
                  f"{a['cells']} cells could ever reach q = {a['q_target']}; "
                  f"best floor {a['best_floor']}")
        else:
            print(f"  attainable p: {a.get('note')}")
    print(f"\nwritten to {OUT / 'eda.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
