"""Replay determinism: the same input must produce the same scan, byte for byte.

This is not a tidiness property. The product's whole evidentiary posture is that a
finding can be re-derived by someone who was not there, from the archived snapshot and
the cited specification digest. `content_hash` is published as the thing that makes that
checkable -- and `content_hash` is computed over the findings, so it cannot detect a
scan that would have produced different findings if the rows had arrived in another
order. The check has to be made against the machinery, not against its output.

Three reads inside the scan are order-sensitive by construction:

  * `comparators[0]` decides the untestable cause and seeds the reference distribution;
  * two `max()` calls select the decisive dimension and the reported comparator;
  * the ORDER of `null_cells` decides which permutation draws land on which cell, since
    the shuffle walks one seeded stream across them in sequence.

The connection sets `preserve_insertion_order=false` and the build is multi-threaded, so
none of those reads is stable unless the candidate query imposes a TOTAL order.
"""
import json
import duckdb
import pytest

from likewise import core, scan


def _rows():
    """One denial cited on debt-to-income, with a cell of comparators that TIE on it.

    The tie is the point. Comparators that differ on the tested dimension have a unique
    argmax and would pass this test under any ordering; comparators that agree on it are
    where an unqualified max() picks by arrival.
    """
    base = dict(lei="549300TEST00000001", activity_year=2025,
                denial_reason_1=None, denial_reason_2=None, denial_reason_3=None,
                denial_reason_4=None, loan_purpose=1, occupancy_type=1, lien_status=1,
                loan_type=1, county_code="12086", aus_1=1, construction_method=1,
                total_units=1, submission_of_application=1,
                initially_payable_to_institution=1, conforming_loan_limit="C",
                amortization=1, interest_only_payment=2, balloon_payment=2,
                negative_amortization=2, has_co_applicant=0, loan_amount=270000.0,
                income=88000.0, property_value=285000.0,
                combined_loan_to_value_ratio=94.0, debt_to_income_ratio=44.0,
                open_end_line_of_credit=2, reverse_mortgage=2,
                business_or_commercial_purpose=2)
    out = []
    # The approved files are WORSE on the cited dimension than the denials, which is the
    # configuration that produces a finding -- and they are worse by the same amount, so
    # the decisive margin ties across all twelve.
    # The approved side sits one income bin below the denials. That is not decoration:
    # the suspected-resubmission signature bins income and property value, and records
    # identical on both are routed out as one applicant resubmitting before they reach
    # the dominance test. Twelve thousand keeps the pair inside the +-22% blocking band
    # and leaves the approved file WORSE on income, which clause 4 admits.
    for i in range(12):
        out.append(dict(base, record_key=f"A{i:04d}", action_taken=1,
                        income=76000.0, debt_to_income_ratio=46.0))
    for i in range(12):
        out.append(dict(base, record_key=f"D{i:04d}", action_taken=3,
                        denial_reason_1=1, debt_to_income_ratio=40.0))
    return out


def _parquet(tmp_path, rows, name):
    p = tmp_path / f"{name}.parquet"
    j = tmp_path / f"{name}.jsonl"
    j.write_text("\n".join(json.dumps(r) for r in rows))
    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_json_auto('{j}')) TO '{p}' (FORMAT PARQUET)")
    return [str(p)]


def _comparable(res):
    """Everything the scan claims, minus the clock."""
    s = dict(res["summary"])
    s.pop("wall_time_by_stage", None)
    s.pop("wall_time_s", None)
    return {"summary": s, "findings": res["findings"]}


# --- the query itself ------------------------------------------------------
def test_the_candidate_query_carries_a_total_order(spec):
    """A lint, deliberately: the ORDER BY is a correctness requirement of the scan that
    reads the result, and nothing downstream can restore it once the rows have arrived
    in the wrong order.
    """
    sql = core.candidate_sql(spec)
    assert "ORDER BY" in sql, "candidate query has no ORDER BY"
    tail = sql[sql.rindex("ORDER BY"):]
    # (denied_key, approved_key) is unique per row. Ordering on the denial alone is a
    # PARTIAL order, and leaves exactly the ties that decide which comparator is read.
    assert "denied_key" in tail and "approved_key" in tail, \
        f"candidate query is ordered, but not totally: {tail.strip()}"


def test_the_ordering_survives_a_different_physical_row_order(spec, tmp_path):
    rows = _rows()
    a = _parquet(tmp_path, rows, "fwd")
    b = _parquet(tmp_path, list(reversed(rows)), "rev")
    pop = spec.raw["population"]
    params = {"approved": pop["approved_actions"], "denied": pop["denied_actions"]}

    def keys(files):
        con = scan.configure(duckdb.connect())
        cur = con.execute(core.candidate_sql(spec), {"files": files, **params})
        cols = [d[0] for d in cur.description]
        return [(r[cols.index("denied_key")], r[cols.index("approved_key")])
                for r in cur.fetchall()]

    ka, kb = keys(a), keys(b)
    assert ka, "fixture produced no candidate pairs; the test would pass vacuously"
    assert ka == kb
    assert ka == sorted(ka), "rows are stable but not in the declared order"


# --- the whole scan --------------------------------------------------------
def test_reversing_the_input_does_not_change_the_scan(spec, tmp_path):
    """The end-to-end claim. Same records, opposite physical order, identical result --
    including the permutation null, whose seeded draw stream is walked across the null
    cells in whatever order the cells were built.
    """
    rows = _rows()
    fwd = scan.run(_parquet(tmp_path, rows, "s_fwd"), spec,
                   lei=rows[0]["lei"], year=2025, scan_id="scn_det")
    rev = scan.run(_parquet(tmp_path, list(reversed(rows)), "s_rev"), spec,
                   lei=rows[0]["lei"], year=2025, scan_id="scn_det")
    assert _comparable(fwd) == _comparable(rev)
    assert fwd["summary"]["content_hash"] == rev["summary"]["content_hash"]


def test_content_hash_alone_would_not_have_caught_this(spec, tmp_path):
    """Why the tests above exist rather than a hash comparison.

    `content_hash` is computed over the findings that were emitted. Two runs that
    selected DIFFERENT comparators for the same denial produce different findings and so
    different hashes -- but a reviewer only ever sees one run, and has nothing to compare
    the hash against. The hash certifies that a result was not edited after the fact; it
    is silent on whether the same input would produce it again.
    """
    rows = _rows()
    res = scan.run(_parquet(tmp_path, rows, "s_h"), spec,
                   lei=rows[0]["lei"], year=2025, scan_id="scn_det")
    h = res["summary"]["content_hash"]
    assert h == scan.content_hash(res["findings"])
    # A single mutated finding moves it: the hash is a seal, not a determinism proof.
    if res["findings"]:
        f = dict(res["findings"][0])
        f["margin"] = (f.get("margin") or 0.0) + 1.0
        assert scan.content_hash([f] + res["findings"][1:]) != h
    else:
        pytest.skip("fixture produced no findings; nothing to perturb")
