"""Scan execution.

Order matters and is not negotiable:
  candidates -> match -> dominance -> resubmission routing -> cells
  -> k-suppression -> midranks/power -> permutation null -> FDR -> rank -> egress
k-suppression runs BEFORE ranking and inside the scan, not in the read serialiser:
the unsuppressed findings file is the dangerous artifact, not the API.


===============================================================================
WHAT THIS FILE DECIDES, MATHEMATICALLY
===============================================================================

The comparison lives in core.py and the inference in stats.py. Three things that DO
carry mathematical content are decided here, because each needs the whole scan in view.

1. k-ANONYMITY SUPPRESSION, applied BEFORE ranking.
   A record is k-anonymous when it cannot be distinguished from at least k-1 others on
   the attributes being released. Cells below the floor are dropped, because a result
   resting on a group of two identifies the individuals in it. The ORDER matters and is
   deliberate: suppression is a disclosure control, not an inference step, so it runs
   after the comparison and before anything is ranked or counted as a finding. Doing it
   the other way round would let a suppressed cell influence the published ordering.

2. THE POWER FLOOR IN THE DENOMINATOR.
   Three counts are emitted together and never derived separately, so they cannot drift:
   dominating == with_finding + below_floor. A rate whose numerator includes cells that
   could never have reached the threshold counts geometry rather than evidence.

3. TWO-SIDED TRIPWIRES.
   Pre-registered bands on the headline rates, checked in BOTH directions. The asymmetry
   most people expect -- worry when a number is high -- is wrong here. A surprisingly
   large not-supported rate is far more likely to be a defect in this software than
   misconduct by a lender, and the characteristic failure mode of this design produces
   ZERO. So a rate below the lower bound triggers the same investigation as one above.

Also decided here: the reference distribution handed to stats.py is assembled over EVERY
matched testable denial, not over the cells that already produced a finding. A null built
from the latter is conditioned on the event under test and will reject at close to
certainty on data with no signal in it -- a defect that survived a full test suite and an
architecture review until a true-null fixture was built.
"""
from __future__ import annotations
import math, time
from collections import defaultdict

import duckdb

from . import core, stats
from .egress import content_hash
from . import runtime as _runtime
from .errors import SpecError
from .specs import Spec, Dimension


def configure(con: duckdb.DuckDBPyConnection, memory_mb: int | None = None,
              threads: int | None = None):
    """The DuckDB defaults are wrong for this runtime: there is no spill target and the
    temp directory is memory-backed, so the default behaviour is to spill into RAM and
    be killed by the kernel -- and a kernel-killed process cannot record its own failure.

    The budget comes from the environment, not from a default argument. Baked into the
    signature it silently ignored the container's own --memory setting, so an operator
    who gave the container 8g still got 2048MB and no way to see why.
    """
    memory_mb = _runtime.memory_mb() if memory_mb is None else memory_mb
    threads = _runtime.threads() if threads is None else threads
    con.execute(f"SET memory_limit='{memory_mb}MB'")
    con.execute("SET temp_directory=''")
    con.execute(f"SET threads={threads}")
    con.execute("SET preserve_insertion_order=false")
    return con


def dominance_statistic(cells) -> float:
    """Fraction of cells in which the labelled-denied member is dominated.

    Module-level and importable ON PURPOSE: when the null statistic lived inside run()
    a test could only reconstruct it, so a polarity mutation in this function survived
    the whole suite. The null and the finding rule must not be able to drift apart.

    `o` is WORSE than `v` when it is higher on a higher_is_worse dimension. Expressed
    on the same orientation as Dimension.margin: margin(approved=o, denied=v) = v - o,
    so `o worse` <=> margin < -threshold.
    """
    if not cells:
        return 0.0
    hits = 0
    for c in cells:
        i = c["labels"].index(1)
        v = c["values"][i]
        others = [x for j, x in enumerate(c["values"]) if j != i]
        hiw = c["direction"] == "higher_is_worse"
        margins = [(v - o) if hiw else (o - v) for o in others]
        worse = [m for m in margins if m < -c["threshold"]]
        better = [m for m in margins if m > c["threshold"]]
        if worse and not better:
            hits += 1
    return hits / len(cells)


def _primary_dim(spec: Spec, codes) -> Dimension | None:
    for c in codes:
        if c is None:
            continue
        r = spec.reason(int(c))
        if r.testable and r.dimensions:
            return r.dimensions[0]
    return None


def _nz(v):
    """Parquet nulls arrive as None; guard against NaN leaking in from any source."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _resub_signature(spec: Spec, row: dict, side: str) -> tuple | None:
    """The suspected-resubmission signature for one side of a pair, or None.

    None means "no signature", and a pair is routed out only when BOTH sides produce a
    signature and the two are equal. A null component used to compare equal to another
    null, so two records that merely both LACK an income and a property value were read
    as the same applicant resubmitting and dropped from the analysis without appearing
    in any denominator but this one. That is the same null-equality the SQL lint bans
    unconditionally elsewhere; it had no business being reintroduced in Python.
    """
    cfg = spec.raw["suspected_resubmission"]
    pw, iw = cfg["property_value_bin_width"], cfg["income_bin_width"]
    out = []
    for f in cfg["signature"]:
        if f == "property_value_bin":
            v = _nz(row.get(f"{side}_property_value"))
            if v is None:
                return None
            out.append(math.floor(v / pw))
        elif f == "income_bin":
            v = _nz(row.get(f"{side}_income"))
            if v is None:
                return None
            out.append(math.floor(v / iw))
        else:
            b = row.get(f"blk_{f}")
            if b is None:
                return None
            out.append(b)
    return tuple(out)



def _separating_fields(con, files, spec, pop) -> list[dict]:
    """Exact-match fields whose denied and approved value sets do not intersect."""
    out = []
    for f in spec.exact_match:
        if f in ("lei", "activity_year"):
            continue
        row = con.execute(f"""
          SELECT
            list_sort(array_agg(DISTINCT {f}) FILTER (WHERE list_contains($denied, action_taken))),
            list_sort(array_agg(DISTINCT {f}) FILTER (WHERE list_contains($approved, action_taken)))
          FROM read_parquet($files)
        """, {"files": files, "denied": pop["denied_actions"],
              "approved": pop["approved_actions"]}).fetchone()
        den, app = set(row[0] or []), set(row[1] or [])
        if den and app and not (den & app):
            out.append({"field": f,
                        "denied_values": sorted(map(str, den)),
                        "approved_values": sorted(map(str, app))})
    return out


def run(files: list[str], spec: Spec, lei: str, year: int, scan_id: str,
        image_digest: str = "sha256:dev", analysis_status: str = "confirmatory",
        con: duckdb.DuckDBPyConnection | None = None) -> dict:
    t0 = time.time()
    stage = {}
    con = con or configure(duckdb.connect())
    pop = spec.raw["population"]

    # ---- population census -------------------------------------------------
    t = time.time()
    census = con.execute("""
      SELECT
        count(*) FILTER (WHERE list_contains($approved, action_taken)
                            OR list_contains($denied, action_taken))            AS records_in_scope,
        count(*) FILTER (WHERE list_contains($denied, action_taken))            AS denials_in_scope,
        count(*) FILTER (WHERE list_contains($denied, action_taken)
                            AND denial_reason_1 IS NULL)                        AS denials_exempt_excluded,
        count(*) FILTER (WHERE list_contains($context, action_taken))           AS withdrawn_context_count
      FROM read_parquet($files)
    """, {"approved": pop["approved_actions"], "denied": pop["denied_actions"],
          "context": pop.get("context_actions", []), "files": files}).fetchone()
    stage["census"] = time.time() - t

    # ---- post-treatment guard --------------------------------------------
    # An exact-match field whose denial values and approval values are DISJOINT is
    # determined by the outcome, not by the application. Blocking on it is provably
    # empty -- no denial can ever match an approval -- and the pipeline would report
    # "no comparable files" for a reason that has nothing to do with lending.
    # The criterion is disjointness, not a correlation threshold, so there is nothing
    # to tune: either the two value sets intersect or the field cannot match.
    t = time.time()
    separating = _separating_fields(con, files, spec, pop)
    if separating:
        raise SpecError("exact_match_field_determined_by_outcome", [
            {**s_, "scan_id": scan_id, "filing_year": year, "spec_version": spec.version,
             "remedy": "Remove the field from blocking.key and exact_match_required, or "
                       "restrict the population so the value sets overlap. Matching on a "
                       "post-treatment field cannot produce a comparison."}
            for s_ in separating])
    stage["post_treatment_guard"] = time.time() - t

    # testability marginal over ALL denials in scope, NOT conditioned on matching
    t = time.time()
    testable_codes = [c for c, r in spec.reasons["codes"].items() if r.get("testable")]
    dtc = con.execute("""
      SELECT count(*) FROM read_parquet($files)
      WHERE list_contains($denied, action_taken)
        AND denial_reason_1 IS NOT NULL
        AND list_contains($testable, denial_reason_1)
        AND coalesce(denial_reason_2, -1) IN (SELECT unnest($testable_or_null))
    """, {"files": files, "denied": pop["denied_actions"], "testable": testable_codes,
          "testable_or_null": testable_codes + [-1]}).fetchone()[0]
    stage["marginal"] = time.time() - t

    # ---- candidates --------------------------------------------------------
    t = time.time()
    sql = core.candidate_sql(spec)
    cur = con.execute(sql, {"files": files, "approved": pop["approved_actions"],
                            "denied": pop["denied_actions"]})
    cols = [d[0] for d in cur.description]
    # strict: the cursor description and the row must agree. A truncating zip would
    # drop the trailing columns of every candidate silently, and the trailing columns
    # are the tested dimensions.
    cand = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]  # no pandas; nulls stay None
    stage["blocking"] = time.time() - t
    candidate_pairs = len(cand)

    # ---- match, dominance, routing ----------------------------------------
    t = time.time()
    matched, incomplete_records, resub_routed = [], set(), 0
    for row in cand:
        a = {k[2:]: _nz(v) for k, v in row.items() if k.startswith("a_")}
        d = {k[2:]: _nz(v) for k, v in row.items() if k.startswith("d_")}
        for k in spec.exact_match:
            a.setdefault(k, row.get(f"blk_{k}")); d.setdefault(k, row.get(f"blk_{k}"))
        m = core.match(a, d, spec)
        if m.incomplete:
            incomplete_records.add(row["denied_key"]); continue
        if not m.matched:
            continue
        sig_a = _resub_signature(spec, row, "a")
        sig_d = _resub_signature(spec, row, "d")
        if sig_a is not None and sig_a == sig_d:
            resub_routed += 1; continue                       # routed, not silently dropped
        codes = [_nz(row.get(f"d_denial_reason_{i}")) for i in (1, 2, 3, 4)]
        codes = [int(c) for c in codes if c is not None]
        out = core.evaluate(a, d, codes, spec)
        matched.append({"row": row, "a": a, "d": d, "codes": codes, "match": m, "outcome": out})
    stage["match"] = time.time() - t
    matched_pairs = len(matched)

    # ---- cells: one denial + its comparators -------------------------------
    cells_by_denial: dict[str, dict] = {}
    for rec in matched:
        dk = rec["row"]["denied_key"]
        c = cells_by_denial.setdefault(dk, {"denied_key": dk, "codes": rec["codes"],
                                            "comparators": [], "block": rec["row"]})
        c["comparators"].append(rec)

    # ---- k-suppression BEFORE ranking --------------------------------------
    t = time.time()
    kmin = int(spec.raw["disclosure"]["k_min"])
    bands = spec.raw["disclosure"]["bands"]
    cohort = defaultdict(int)
    _kc = spec.raw["disclosure"].get("cohort_key") or spec.blocking_key
    allrows = con.execute(f"""
      SELECT {", ".join(_kc)}, income, property_value, combined_loan_to_value_ratio
      FROM read_parquet($files)
      WHERE list_contains($approved, action_taken) OR list_contains($denied, action_taken)
    """, {"files": files, "approved": pop["approved_actions"], "denied": pop["denied_actions"]}).fetchall()
    kcols = spec.raw["disclosure"].get("cohort_key") or spec.blocking_key
    for r in allrows:
        blk = tuple(r[:len(kcols)])
        inc, pv, cl = _nz(r[len(kcols)]), _nz(r[len(kcols)+1]), _nz(r[len(kcols)+2])
        cohort[(blk,
                None if inc is None else math.floor(inc / bands["income"]),
                None if pv is None else math.floor(pv / bands["property_value"]),
                None if cl is None else math.floor(cl / bands["combined_loan_to_value_ratio"]))] += 1

    def _cohort_field(row, k, side):
        v = row.get(f"blk_{k}")
        return v if v is not None else _nz(row.get(f"{side}_{k}"))

    def kcohort(rec, side) -> int:
        row = rec["row"]
        blk = tuple(_cohort_field(row, k, side) for k in kcols)
        inc = _nz(row.get(f"{side}_income")); pv = _nz(row.get(f"{side}_property_value"))
        cl = _nz(row.get(f"{side}_combined_loan_to_value_ratio"))
        return cohort.get((blk,
                           None if inc is None else math.floor(inc / bands["income"]),
                           None if pv is None else math.floor(pv / bands["property_value"]),
                           None if cl is None else math.floor(cl / bands["combined_loan_to_value_ratio"])), 0)
    stage["k_cohort"] = time.time() - t

    # ---- score each cell ---------------------------------------------------
    t = time.time()
    q_target = float(spec.stat("fdr_q", 0.10))
    # No cell-size floor is read here on purpose. Power used to be `n >= cell_power_min`,
    # which is wrong on published data: a cell of forty in which every value is tied has
    # no power at all, and one of four with no ties has some. core.cell_power derives it
    # from the realised tie structure against q instead. The spec key is retained so
    # older specification versions still load; nothing consults it.
    findings, untest_code, untest_res, suppressed_k, underpowered = [], 0, 0, 0, 0
    null_cells = []           # EVERY matched testable denial, not only the finding-bearing ones
    candidates = []           # cells whose comparator dominates, before the rank test

    for dk, cell in cells_by_denial.items():
        winners = [r for r in cell["comparators"]
                   if r["outcome"].outcome == "not_supported_by_public_record"]
        anyout = cell["comparators"][0]["outcome"]

        # The decisive dimension is the tested dimension with the largest margin
        # relative to its OWN threshold. Margins across dimensions are in
        # incommensurable units, so a raw comparison between them is a unit error.
        def _best_dim(r, require_not_supported=True):
            cands = [t_ for t_ in r["outcome"].tested
                     if (t_.outcome == "not_supported" if require_not_supported
                         else not math.isnan(t_.margin))]
            if not cands:
                return None
            # The dimension name breaks the tie. Two dimensions can carry the same
            # threshold-relative margin, and `tested` is built by iterating the
            # specification, so an unqualified max() would be stable only by accident of
            # dict ordering. Naming the tiebreak makes it a decision rather than a
            # coincidence.
            return max(cands, key=lambda t_: (abs(t_.margin) / (t_.decisive_threshold or 1.0),
                                              t_.dimension))

        # ---- the reference distribution -----------------------------------
        # Built over every matched, testable denial: a null assembled from the cells
        # that already produced a finding is conditioned on the event being tested, and
        # will reject at close to certainty under data with no signal in it at all.
        # k-suppression governs disclosure, not inference, so it is applied after.
        ref = _best_dim(cell["comparators"][0], require_not_supported=False)
        if ref is not None:
            dimr = Dimension(ref.dimension, ref.direction)
            rvals = [cell["comparators"][0]["d"].get(dimr.name)] + \
                    [r["a"].get(dimr.name) for r in cell["comparators"]]
            rvals = [v for v in rvals if v is not None]
            if len(rvals) >= 2:
                hiw = dimr.direction == "higher_is_worse"
                mrr = core.midranks(rvals, higher_is_worse=hiw)
                null_cells.append({
                    "values": rvals, "midranks": mrr, "observed_midrank": mrr[0],
                    "labels": [1] + [0] * (len(rvals) - 1),
                    "direction": dimr.direction,
                    "threshold": ref.decisive_threshold or
                                 spec.budget.granularity(dimr.name),
                })

        if not winners:
            if anyout.outcome == "untestable":
                if anyout.cause == "untestable_code_present": untest_code += 1
                else: untest_res += 1
            continue

        # Ties here are not rare: a cell of comparators identical on the tested
        # dimension produces one margin for all of them, and which one is reported as
        # THE comparator then decides what a reviewer opens first. The approved record
        # key is unique, so this is a total order.
        best = max(winners, key=lambda r: (abs(_best_dim(r).margin) /
                                           (_best_dim(r).decisive_threshold or 1.0),
                                           r["row"]["approved_key"]))
        dec = _best_dim(best)
        dim = Dimension(dec.dimension, dec.direction)
        kc = min(kcohort(best, "a"), kcohort(best, "d"))
        if kc < kmin:
            suppressed_k += 1; continue

        vals = [best["d"].get(dim.name)] + [r["a"].get(dim.name) for r in cell["comparators"]]
        vals = [v for v in vals if v is not None]
        n = len(vals)
        hiw = dim.direction == "higher_is_worse"
        mr = core.midranks(vals, higher_is_worse=hiw)
        rank = mr[0]
        power, min_p = core.cell_power(vals, q_target, higher_is_worse=hiw)
        p = stats.rank_p_value(vals, vals[0], higher_is_worse=hiw)
        if power == "underpowered":
            underpowered += 1

        thr = dec.decisive_threshold or spec.budget.granularity(dim.name)
        mratio = abs(dec.margin) / thr if thr else 0.0

        candidates.append({
            "scan_id": scan_id, "lei": lei, "activity_year": year, "image_digest": image_digest,
            "approved_key": best["row"]["approved_key"], "denied_key": dk,
            "key_lo": best["row"]["key_lo"], "key_hi": best["row"]["key_hi"],
            "reason_outcome": "not_supported_by_public_record",
            "stated_reason_codes": cell["codes"],
            "tested": [t.as_dict() for t in best["outcome"].tested],
            "decisive_dimension": dim.name,
            "decisive_threshold": round(thr, 6),
            "margin": dec.margin, "margin_ratio": mratio,
            "rank_in_cell": rank, "cell_size": n, "rank_p_value": p,
            "cell_power": power, "min_attainable_p": round(min_p, 6),
            "gamma_star": round(stats.gamma_star(p, q_target), 4),
            "informative_dimension_count": len(best["outcome"].informative),
            "block_degree": len(cell["comparators"]),
            "geo_level": "county",
            "k_cohort": kc,
            "record_keys": {"approved": best["a"].get("record_key"),
                            "denied": best["d"].get("record_key")},
            # Raw values for the disclosure layer to band. Nothing downstream of egress
            # ever sees them.
            "a_income": best["a"].get("income"),
            "a_property_value": best["a"].get("property_value"),
            "a_combined_loan_to_value_ratio": best["a"].get("combined_loan_to_value_ratio"),
            "a_loan_amount": best["a"].get("loan_amount"),
            "county_code": best["row"].get("blk_county_code"),
            "spec_digests": spec.digests, "snapshot_id": spec.snapshot_id,
            "analysis_status": analysis_status,
        })
    findings = candidates
    stage["score"] = time.time() - t

    # ---- the scan-level test -----------------------------------------------
    # Per-finding significance is not attempted. Inside a family of m hypotheses the
    # false-discovery threshold needs a cell of roughly 1/(q*f) -- about a hundred at
    # q=0.10 -- and the median matched cell here holds three records. The within-cell
    # test cannot reject at any useful level however strong the effect, so a q-value on
    # a finding would be decoration on a test that never fires.
    #
    # What the data can support is a claim about the FILER: pooled across every matched
    # cell, do the denials sit better than chance on the dimension their own stated
    # reason names? Cells of two and three contribute to that, and there are enough of
    # them. Individual findings become a prioritised list with no significance attached.
    t = time.time()
    nullres = stats.permutation_null(
        null_cells, dominance_statistic, B=int(spec.stat("permutation_B", 2000)),
        B_initial=int(spec.stat("permutation_B_initial", 200)),
        B_max=int(spec.stat("permutation_B_max", 5000))) if null_cells else None
    pooled = stats.stratified_rank_test(null_cells)
    # The exact expectation under within-cell exchangeability. Closed form, one pass,
    # no seed -- so the anchor for the null does not depend on how many draws the
    # adaptive permutation happened to take.
    exact = stats.exact_expected_findings(null_cells)
    stage["statistics"] = time.time() - t

    findings.sort(key=lambda f: (-f["margin_ratio"], f["rank_p_value"], f["key_lo"]))
    for i_, f in enumerate(findings, 1):
        f["rank"] = i_

    adequate, counts_by_power = power_counts(findings)

    denom = {
        "records_in_scope": census[0], "denials_in_scope": census[1],
        "denials_exempt_excluded": census[2], "withdrawn_context_count": census[3],
        "denials_non_exempt": census[1] - census[2],
        "excluded_incomplete_records": len(incomplete_records),
        "candidate_pairs": candidate_pairs, "matched_pairs": matched_pairs,
        "same_applicant_routed": resub_routed,
        "denials_with_matched_comparator": len(cells_by_denial),
        "denials_testable_by_code_marginal": dtc,
        "untestable_code_present": untest_code,
        # Incomparability is a reported outcome, not an absence of one. A denial whose
        # tested dimension the published record cannot order is a statement about the
        # DATA -- roughly four in five debt-to-income denials are in that position at any
        # sample size, because the file replaces the number with a band exactly where a
        # lender denying for debt-to-income would be. Folding it into "no finding" would
        # report a silence as an absence of a problem.
        "denials_incomparable": untest_res,
        "untestable_below_resolution": untest_res,
        "suppressed_k": suppressed_k,
        "cells_underpowered": underpowered,
        **counts_by_power,
    }
    summary = {
        "scan_id": scan_id, "lei": lei, "activity_year": year,
        "counts": denom,
        # The published rate counts only cells that could have reached the threshold.
        # A rate whose numerator includes cells below the power floor is a count of
        # geometry, not of evidence.
        "rate_pre_suppression": _rate(len(adequate) + suppressed_k, len(cells_by_denial)),
        "rate_post_suppression": _rate(len(adequate), len(cells_by_denial)),
        "scan_level_test": pooled,
        "exact_null": exact,
        "null": nullres.as_dict() if nullres else None,
        "margin_ratio_median": _median([f["margin_ratio"] for f in findings]),
        "informative_dim_histogram": _hist([f["informative_dimension_count"] for f in findings]),
        "cell_size_distribution": _hist([f["cell_size"] for f in findings]),
        "block_degree_distribution": _hist([f["block_degree"] for f in findings]),
        "spec_digests": spec.digests, "snapshot_id": spec.snapshot_id,
        "image_digest": image_digest, "analysis_status": analysis_status,
        "content_hash": content_hash(findings),
        "wall_time_by_stage": {k: round(v, 4) for k, v in stage.items()},
        "wall_time_s": round(time.time() - t0, 3),
    }
    summary["tripwire_breaches"] = tripwires(summary, spec)
    summary["tripwire_breached"] = bool(summary["tripwire_breaches"])
    return {"summary": summary, "findings": findings, "gate_report": spec.gate_report}


def power_counts(findings: list[dict]) -> tuple[list[dict], dict]:
    """Split the dominating comparators into those from an adequately powered cell and
    those that are not, and produce the three counts that must agree.

    A cell below the power floor cannot reach the decision threshold however strong the
    effect, so counting it as a finding inflates the headline rate the tripwire reads.
    The three counts are emitted together, and never derived independently, so they
    cannot drift apart: dominating == with_finding + below_floor, by construction.
    """
    adequate = [f for f in findings if f["cell_power"] == "adequate"]
    return adequate, {
        "denials_with_dominating_comparator": len(findings),
        "denials_with_finding": len(adequate),
        "findings_below_power_floor": len(findings) - len(adequate),
    }


def _rate(num, den): return round(num / den, 6) if den else None
def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    return None if not xs else (xs[len(xs)//2] if len(xs) % 2 else (xs[len(xs)//2-1]+xs[len(xs)//2])/2)
def _hist(xs):
    h = defaultdict(int)
    for x in xs: h[x] += 1
    return dict(sorted(h.items()))


def tripwires(summary: dict, spec: Spec) -> list[dict]:
    """TWO-SIDED: a rate below the lower bound triggers the same
    investigation as one above. The characteristic failure of this design produces
    zero, and zero sat inside every pre-registered range."""
    out = []
    tw = spec.raw.get("tripwires", {})
    c = summary["counts"]
    checks = {
        "not_supported_rate": summary["rate_post_suppression"],
        # Over every denial in scope, not over the non-exempt subset. A denial whose
        # reason field is exempt still has comparators and still lands in a cell; it is
        # untestable, not unmatched. Dividing a numerator counted over all denials by a
        # denominator counted over some of them produced a "fraction" above one.
        "matched_fraction": _rate(c["denials_with_matched_comparator"], c["denials_in_scope"]),
        "median_margin_ratio": summary["margin_ratio_median"],
        # The pooled test is the ONLY inferential claim the product makes -- "across
        # this filer's denials, the dimension the stated reason names does not order the
        # decisions" -- and until this row existed no gate read it. A statistic that
        # nothing checks is documentation, not a control.
        "scan_level_z": (summary.get("scan_level_test") or {}).get("z"),
    }
    for name, val in checks.items():
        b = tw.get(name)
        if not b or val is None:
            if b and val is None:
                out.append({"tripwire": name, "value": None, "breach": "not_computable"})
            continue
        if "low" in b and val < b["low"]:
            out.append({"tripwire": name, "value": val, "bound": b["low"], "breach": "below_lower"})
        if "high" in b and val > b["high"]:
            out.append({"tripwire": name, "value": val, "bound": b["high"], "breach": "above_upper"})
    return out
