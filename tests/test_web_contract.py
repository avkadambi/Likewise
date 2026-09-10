"""The web view is not a second route out of the process.

Everything the renderer prints came through egress, the sweep guarantee holds at both
surfaces, and a field that is determined by the outcome refuses before it can be
mistaken for an absence of comparators.
"""
import json, pathlib, re
import duckdb
import pytest
from fastapi import HTTPException

from likewise import scan, web
from likewise.egress import FORBIDDEN_KEYS
from likewise.errors import SpecError

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rows(n, **over):
    base = dict(record_key="R", lei="549300TEST00000001", activity_year=2025,
                action_taken=1, denial_reason_1=None, denial_reason_2=None,
                denial_reason_3=None, denial_reason_4=None, loan_purpose=1,
                occupancy_type=1, lien_status=1, loan_type=1, county_code="12086",
                aus_1=1, construction_method=1, total_units=1,
                submission_of_application=1, initially_payable_to_institution=1,
                conforming_loan_limit="C", amortization=1, interest_only_payment=2,
                balloon_payment=2, negative_amortization=2, has_co_applicant=0,
                loan_amount=270000.0, income=88000.0, property_value=285000.0,
                combined_loan_to_value_ratio=94.0, debt_to_income_ratio=40.0,
                open_end_line_of_credit=2, reverse_mortgage=2,
                business_or_commercial_purpose=2)
    out = []
    for i in range(n):
        r = dict(base, record_key=f"R{i:04d}")
        r.update(over)
        out.append(r)
    return out


def _parquet(tmp_path, rows):
    p = tmp_path / "data.parquet"
    j = tmp_path / "rows.jsonl"
    j.write_text("\n".join(json.dumps(r) for r in rows))
    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_json_auto('{j}')) TO '{p}' (FORMAT PARQUET)")
    return [str(p)]


# --- post-treatment guard --------------------------------------------------
# The field the guard is demonstrated on. It has to be a member of the exact-match set
# of the specification IN FORCE, and the assertion below says so rather than trusting it:
# this test previously used initially_payable_to_institution, which 1.2.0 removed from
# the key for exactly the reason the guard exists. Against the current specification it
# was constructing a separation on a field nothing matched on, and asserting a refusal
# that could no longer happen.
FIELD = "submission_of_application"


def test_outcome_determined_exact_match_field_is_refused(spec, tmp_path):
    """A field whose value is decided BY the outcome makes matching circular: every
    approved record takes one value and every denial the other, so the blocking key is
    provably empty. The scan must name that rather than report no comparable files.

    This is not hypothetical. initially_payable_to_institution was 3 on every denial and
    1 on every origination in the real 2024 file -- a denied application has no loan to
    be payable to anyone -- and 1.2.0 removed it from the key on that evidence."""
    assert FIELD in spec.exact_match, "the guard is vacuous off the exact-match set"
    rows = _rows(20, action_taken=1, **{FIELD: 1})
    rows += _rows(20, action_taken=3, denial_reason_1=4, **{FIELD: 2})
    for i, r in enumerate(rows):
        r["record_key"] = f"X{i:04d}"
    with pytest.raises(SpecError) as ei:
        scan.run(_parquet(tmp_path, rows), spec, lei=rows[0]["lei"], year=2025,
                 scan_id="scn_test")
    assert ei.value.kind == "exact_match_field_determined_by_outcome"
    fields = {f["field"] for f in ei.value.failures}
    assert FIELD in fields


def test_guard_is_silent_when_the_value_sets_overlap(spec, tmp_path):
    """The criterion is disjointness, not correlation: a field that merely leans one way
    must not trip it, or the guard would be a tuning knob."""
    rows = _rows(20, action_taken=1, **{FIELD: 1})
    lean = _rows(18, action_taken=3, denial_reason_1=4, **{FIELD: 2})
    lean += _rows(2, action_taken=3, denial_reason_1=4, **{FIELD: 1})
    rows += lean
    for i, r in enumerate(rows):
        r["record_key"] = f"Y{i:04d}"
    res = scan.run(_parquet(tmp_path, rows), spec, lei=rows[0]["lei"], year=2025,
                   scan_id="scn_test2")
    assert res["summary"]["counts"]["records_in_scope"] == 40


def test_guard_ignores_fields_outside_exact_match(spec, tmp_path):
    """action_taken itself is perfectly separating by definition and must never be read
    as a defect."""
    assert "action_taken" not in spec.exact_match


# --- the renderer prints nothing egress did not hand it --------------------
def _sample_finding():
    return {
        "finding_id": "fnd_" + "a" * 32, "scan_id": "scn_x", "county_code": "12086",
        "record_ref": {"approved": "rec_1111111111111111", "denied": "rec_2222222222222222"},
        "bands": {"combined_loan_to_value_ratio": "95-100", "income": "60k-70k"},
        "tested": [{"dimension": "combined_loan_to_value_ratio", "margin": -9.0,
                    "decisive_threshold": 7.1, "direction": "higher_is_worse",
                    "outcome": "not_supported"}],
        "stated_reason_codes": [4], "reason_outcome": "not_supported_by_public_record",
        "rank_in_cell": 1.0, "cell_size": 12, "rank_p_value": 0.08,
        "cell_power": "powered", "q_value": None, "q_value_by": None,
        "margin_ratio": 2.0, "block_degree": 5, "k_cohort": 9,
        "informative_dimension_count": 1, "evidentiary_status": "screening_hypothesis",
        "analysis_status": "exploratory", "pseudonym_key_version": 1,
        "snapshot_id": "snap", "spec_digests": {"reasons": "sha256:abc"},
    }


LEAKS = ["549300MGPZBLQDIL7538", "census_tract", "06073016704", "Fairway"]


def test_rendered_finding_carries_no_forbidden_key_and_no_raw_identifier(spec):
    html = web.finding_page(
        "scn_x", {"activity_year": 2025, "spec_version": spec.version,
                  "preregistration_digest": "unset", "pseudonym_key_version": 1},
        {"null": {"B": 200, "null_mean": 0.12, "observed": 0.02, "direction": "below_null"},
         "tripwire_breaches": []},
        _sample_finding(), {}, {4: {"label": "Collateral"}}, None, 1, 1, None)
    low = html.lower()
    for k in FORBIDDEN_KEYS:
        assert k.lower() not in low, f"renderer leaked {k}"
    for k in LEAKS:
        assert k.lower() not in low


def test_rendered_queue_carries_no_forbidden_key(spec):
    html = web.queue_page(
        "scn_x", {"activity_year": 2025, "lei": "rec_x", "label": "L",
                  "spec_version": spec.version},
        {"counts": {"denials_non_exempt": 10, "untestable_code_present": 3,
                    "untestable_below_resolution": 1}, "tripwire_breaches": []},
        [_sample_finding()], {}, {4: {"label": "Collateral"}}, None, "needs", 25, 0)
    low = html.lower()
    for k in FORBIDDEN_KEYS:
        assert k.lower() not in low


def test_renderer_escapes_stored_text():
    """Disposition notes are operator input stored on the scan. They render as text."""
    f = _sample_finding()
    html = web.finding_page(
        "scn_x", {"activity_year": 2025, "spec_version": "1.0.0",
                  "preregistration_digest": "unset", "pseudonym_key_version": 1},
        {"tripwire_breaches": []}, f,
        {"verdict": "holds", "note": "<script>alert(1)</script>", "principal": "p",
         "recorded_at": "2026-09-07"},
        {4: {"label": "Collateral"}}, None, 1, 1, None)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_margin_is_shown_as_magnitude_not_a_signed_number():
    """The stored margin is signed on the dimension's own orientation. '-8.8 pp' in front
    of a reader means the opposite of what the finding says."""
    t = {"dimension": "combined_loan_to_value_ratio", "margin": -8.77,
         "decisive_threshold": 7.1, "outcome": "not_supported"}
    assert web.gap_short("combined_loan_to_value_ratio", t) == "8.77 pp worse"
    assert "-" not in web.gap_short("combined_loan_to_value_ratio", t)


def test_unscored_cells_get_no_strength_bar():
    f = dict(_sample_finding(), cell_power="underpowered", cell_size=2)
    assert web.strength(f) == ("Not scored", 0.0)


# --- the sweep guarantee ---------------------------------------------------
def test_findings_and_queue_both_refuse_without_a_sweep(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from likewise import api

    monkeypatch.chdir(ROOT)
    c = TestClient(api.app, raise_server_exceptions=False)
    sid = "scn_" + "f" * 16
    api.STORE.put_json(f"scans/{sid}/scan.json",
                       {"scan_id": sid, "status": "complete", "lei": "x",
                        "activity_year": 2025, "spec_version": "1.0.0"})
    api.STORE.put_json(f"scans/{sid}/summary.json", {"counts": {}, "tripwire_breaches": []})
    api.STORE.put_json(f"scans/{sid}/findings.json", [])
    try:
        r = c.get(f"/v1/scans/{sid}/findings", headers={"Authorization": "Bearer dev-read"})
        assert r.status_code == 409
        r = c.get(f"/ui/scans/{sid}/queue", cookies={"lw_session": "dev-read"})
        assert r.status_code == 409
    finally:
        for k in ("scan.json", "summary.json", "findings.json"):
            p = ROOT / "data" / "store" / "scans" / sid / k
            if p.exists():
                p.unlink()


def test_ui_requires_a_credential_and_offers_sign_in(monkeypatch):
    from fastapi.testclient import TestClient
    from likewise import api
    monkeypatch.chdir(ROOT)
    c = TestClient(api.app, raise_server_exceptions=False)
    r = c.get("/ui/scans", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ui/login"


def test_disposition_rejects_an_unknown_verdict_and_a_missing_scan(monkeypatch):
    from fastapi.testclient import TestClient
    from likewise import api
    monkeypatch.chdir(ROOT)
    c = TestClient(api.app, raise_server_exceptions=False)
    h = {"Authorization": "Bearer dev-write"}
    assert c.patch("/v1/findings/fnd_x/disposition", json={"verdict": "holds"},
                   headers=h).status_code == 422
    assert c.patch("/v1/findings/fnd_x/disposition",
                   json={"scan_id": "scn_nope", "verdict": "banana"},
                   headers=h).status_code == 422


def test_read_scope_cannot_record_a_disposition(monkeypatch):
    from fastapi.testclient import TestClient
    from likewise import api
    monkeypatch.chdir(ROOT)
    c = TestClient(api.app, raise_server_exceptions=False)
    r = c.patch("/v1/findings/fnd_x/disposition",
                json={"scan_id": "s", "verdict": "holds"},
                headers={"Authorization": "Bearer dev-read"})
    assert r.status_code == 403


# --- version history -------------------------------------------------------
def test_every_superseding_spec_version_carries_a_written_rationale():
    """The initial version has nothing to explain; every version after it does."""
    vs = web.read_versions(str(ROOT / "specs" / "materiality"))
    assert len(vs) >= 2
    for v in vs:
        if v["version"] == "1.0.0":
            continue
        assert len(v["rationale"]) > 40, f"v{v['version']} has no written rationale"


def test_coverage_chain_bars_never_exceed_their_own_denominator():
    """Testability is a marginal over non-exempt denials and is deliberately NOT
    conditioned on matching, so it can exceed the matched count. Chaining the two as if
    each nested inside the last produces a share above 100% and a bar that lies; each row
    states the denominator it is a share of instead."""
    counts = {"denials_in_scope": 1000, "denials_non_exempt": 900,
              "denials_with_matched_comparator": 120, "denials_testable_by_code_marginal": 300,
              "denials_with_finding": 30, "findings_after_fdr": 3,
              "untestable_code_present": 400, "untestable_below_resolution": 50}
    html = web.coverage_page("scn_x", {"pseudonym_key_version": 1},
                             {"counts": counts, "tripwire_breaches": [],
                              "wall_time_by_stage": {}, "wall_time_s": 1.0}, None, None)
    widths = [float(w) for w in re.findall(r'<i style="width:([0-9.]+)%"', html)]
    assert widths[0] == 100.0
    assert widths[1] == pytest.approx(90.0, abs=0.1)     # 900 non-exempt of 1000 denials
    assert widths[2] == pytest.approx(33.3, abs=0.1)     # 300 testable of 900 non-exempt
    assert widths[3] == pytest.approx(13.3, abs=0.1)     # 120 matched of 900 non-exempt
    assert widths[4] == pytest.approx(25.0, abs=0.1)     # 30 candidates of 120 matched
    assert all(w <= 100.0 for w in widths)
    assert len({round(w) for w in widths}) > 2, "every bar the same width says nothing"
    assert "of non-exempt denials" in html and "of matched denials" in html


def test_survives_defeated_and_untestable_partition_the_matched_denials():
    """product requirements section 10. The failure mode this decomposition exists to prevent is a matched-but-
    untestable denial being counted as 'survives' -- reporting an absence of evidence as
    evidence of absence."""
    c = {"denials_non_exempt": 6620, "denials_with_matched_comparator": 5750,
         "denials_with_finding": 342, "untestable_code_present": 3621,
         "untestable_below_resolution": 960}
    v = web.verdict_counts(c)
    assert v["survives"] + v["defeated"] + v["untestable_matched"] == v["matched"]
    assert v["survives"] == 827
    assert v["untestable"] == 4581 + (6620 - 5750)


def test_a_denial_with_no_comparator_is_untestable_not_surviving():
    c = {"denials_non_exempt": 33, "denials_with_matched_comparator": 4,
         "denials_with_finding": 0, "untestable_code_present": 4,
         "untestable_below_resolution": 0}
    v = web.verdict_counts(c)
    assert v["survives"] == 0
    assert v["untestable"] == 33
    assert v["no_comparator"] == 29


def test_a_non_public_snapshot_is_stamped_on_the_coverage_screen():
    """A snapshot loaded with --internal-data is stamped once, at load. Every screen that
    states a published bin width is wrong about it, so the stamp has to travel."""
    summary = {"counts": {"denials_in_scope": 10, "denials_non_exempt": 10},
               "tripwire_breaches": [], "wall_time_by_stage": {}, "wall_time_s": 1.0}
    man = {"source": "operator drop folder", "rows_written": 10,
           "public_record": False,
           "public_record_note": "LOADED WITH --internal-data. These values are NOT at "
                                 "publication granularity.",
           "granularity_report": {"loan_amount": {"conforming": 0, "n": 10}}}
    html = web.coverage_page("scn_x", {"pseudonym_key_version": 1}, summary, None, man)
    assert "not the published record" in html
    assert "--internal-data" in html

    ok = dict(man, public_record=True, public_record_note="conforms")
    assert "not the published record" not in web.coverage_page(
        "scn_x", {"pseudonym_key_version": 1}, summary, None, ok)


def test_a_known_gap_in_the_snapshot_is_stated_not_footnoted():
    summary = {"counts": {"denials_in_scope": 10, "denials_non_exempt": 10},
               "tripwire_breaches": [], "wall_time_by_stage": {}, "wall_time_s": 1.0}
    man = {"rows_written": 400, "public_record": True,
           "completeness": {"universe_rows": 440, "known_gap_rows": 40,
                            "known_gap_definition": "White, joint, conventional first lien",
                            "known_gap_effect": "approved side only"}}
    html = web.coverage_page("scn_x", {"pseudonym_key_version": 1}, summary, None, man)
    assert "not missing at random" in html and "White, joint" in html


def test_both_scan_paths_record_a_refusal_the_same_way(monkeypatch, tmp_path):
    """A refused specification is a result, not a crash. The synchronous route used to
    fold SpecError into its generic handler, so the same refusal produced status
    "failed" with a repr() from one path and status "refused" with the structured
    payload from the other. Which record you got depended on which route ran the scan."""
    from likewise import api as api_mod
    from likewise.errors import SpecError

    boom = SpecError("startup_gate_failed",
                     [{"gate": "decisive_threshold_below_floor", "dimension": "cltv"}])

    def refuse(*a, **k):
        raise SpecError(boom.kind, boom.failures)

    monkeypatch.setattr(api_mod.scan_mod, "run", refuse)

    sid = "scn_refusaltest0001"
    rec = {"scan_id": sid, "status": "queued", "lei": "549300TEST00000001",
           "activity_year": 2024, "analysis_status": "exploratory"}

    # background path
    api_mod.STORE.put_json(f"scans/{sid}/scan.json", rec)
    api_mod._run_scan_and_sweep(sid, dict(rec), api_mod.SPEC, [])
    background = api_mod.STORE.get_json(f"scans/{sid}/scan.json")

    # synchronous path
    api_mod.STORE.put_json(f"scans/{sid}/scan.json", rec)
    with pytest.raises(HTTPException) as exc:
        api_mod.execute(sid, files=[], p={"sub": "t", "scopes": ["read", "write"]})
    synchronous = api_mod.STORE.get_json(f"scans/{sid}/scan.json")

    assert background["status"] == "refused"
    assert synchronous["status"] == background["status"]
    assert synchronous["error"] == background["error"] == "startup_gate_failed"
    assert synchronous["refusal"] == background["refusal"]
    assert synchronous["refusal"]["failures"][0]["gate"] == "decisive_threshold_below_floor"
    # a refusal is the caller's problem, not a server crash
    assert exc.value.status_code == 422
