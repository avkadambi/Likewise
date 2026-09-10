"""The drop folder is an input the operator controls, so the loader is a boundary.

It refuses rather than repairs. Every check here exists because the alternative -- a load
that quietly fixes your file -- produces a snapshot nobody can audit.
"""
import csv, os, pathlib
import pytest

from likewise import loader, specs
from likewise.errors import SpecError
from likewise.schema import COLUMNS

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "templates" / "likewise_lar_template.csv"
DICTIONARY = ROOT / "docs" / "templates" / "likewise_lar_dictionary.csv"


@pytest.fixture(scope="module")
def snap():
    return specs.load(version="1.2.0").snapshot


def _load(tmp_path, paths, snap, **kw):
    """Run the production path and hand back the report plus the written records."""
    out = str(tmp_path / "out.parquet")
    rep = loader.load_to_parquet(paths if isinstance(paths, list) else [paths],
                                 snap, out, **kw)
    import duckdb
    cols = ", ".join('"%s"' % c for c in COLUMNS)
    rows = duckdb.connect().execute(
        f"select {cols} from read_parquet('{out}')").fetchall()
    rep["records"] = [dict(zip(COLUMNS, r, strict=False)) for r in rows]
    return rep


def _write(tmp_path, rows, header=None, name="f.csv"):
    header = header or loader.TEMPLATE_COLUMNS
    p = tmp_path / name
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(c, "") for c in header])
    return str(p)


def _template_rows():
    with open(TEMPLATE, newline="") as fh:
        return list(csv.DictReader(fh))


# --- the shipped template is the contract ---------------------------------
def test_template_header_is_exactly_the_internal_schema():
    """If a field is added to the schema and not to the template, the template silently
    stops describing the thing it is a template for."""
    with open(TEMPLATE, newline="") as fh:
        header = next(csv.reader(fh))
    assert header == loader.TEMPLATE_COLUMNS
    assert "record_key" not in header, "record_key is derived; supplying one invites a join"
    assert set(header) | {"record_key"} == set(COLUMNS)


def test_dictionary_documents_every_template_column_and_no_others():
    documented = [r["column"] for r in csv.DictReader(open(DICTIONARY, newline=""))]
    assert documented == loader.TEMPLATE_COLUMNS


def test_the_shipped_template_loads_and_conforms(snap, tmp_path):
    got = _load(tmp_path, [str(TEMPLATE)], snap)
    assert got["layout"] == "template"
    assert got["granularity_conforming"]
    assert got["rows_written"] == 3


def test_the_shipped_example_filing_loads(snap, tmp_path):
    ex = ROOT / "data" / "examples" / "likewise_example_filing.csv"
    got = _load(tmp_path, [str(ex)], snap)
    assert got["granularity_conforming"]
    assert got["rows_written"] > 1000


# --- layout detection and equivalence -------------------------------------
def _header_for(layout):
    """A minimal header that satisfies `layout` completely, derived from the loader's own
    requirement set rather than transcribed -- so a new required column cannot leave this
    fixture quietly stale."""
    return sorted(loader.required_sources(layout))


def test_layouts_are_detected_from_the_header_not_the_filename():
    for layout in ("ffiec", "snapshot", "template"):
        assert loader.detect_layout(_header_for(layout)) == layout
    assert loader.detect_layout(loader.TEMPLATE_COLUMNS) == "template"
    with pytest.raises(SpecError) as ei:
        loader.detect_layout(["a", "b", "c"])
    assert ei.value.kind == "unrecognised_csv_layout"


def test_a_partial_header_is_refused_rather_than_guessed():
    """Detection scores the FULL required set. A header carrying only a marker column is
    a file the loader cannot read, and saying so beats reading three columns of it."""
    with pytest.raises(SpecError) as ei:
        loader.detect_layout(["lei", "loan_to_value_ratio", "denial_reason-1"])
    assert ei.value.kind == "unrecognised_csv_layout"
    # The refusal names how close each layout came, so the operator can see what is missing
    # instead of being told only that it did not work.
    layouts = ei.value.failures[0]["layouts"]
    assert set(layouts) == {"ffiec", "snapshot", "template"}
    assert layouts["ffiec"]["fraction_present"] > layouts["template"]["fraction_present"]


def test_the_snapshot_layout_is_not_read_as_a_template():
    """The regression this detector exists for.

    The Snapshot National Loan Level Dataset names its ratio `combined_loan_to_value_ratio`
    -- which used to be the template marker -- while publishing income in THOUSANDS, as the
    Data Browser does. Under marker detection a Snapshot file matched the template branch,
    the template branch does not scale income, and every income would have come out a
    thousand times too small with nothing about the load looking wrong."""
    header = _header_for("snapshot")
    assert "combined_loan_to_value_ratio" in header
    assert loader.detect_layout(header) == "snapshot"

    row = dict.fromkeys(header, "")
    row.update({"lei": "L", "activity_year": "2025", "income": "142",
                "co_applicant_credit_score_type": "10"})
    rec = loader.convert(row, "snapshot", {})
    assert rec["income"] == 142000.0, "income must be scaled from thousands"
    assert rec["has_co_applicant"] == 0, "credit score type 10 means no co-applicant"


def test_a_header_satisfying_two_layouts_is_refused_as_ambiguous():
    """Two complete matches are not a tie to break by declaration order. The layouts
    disagree on the unit of `income`, so guessing is a thousand-fold error either way."""
    with pytest.raises(SpecError) as ei:
        loader.detect_layout(_header_for("ffiec") + _header_for("snapshot")
                             + _header_for("template"))
    assert ei.value.kind == "ambiguous_csv_layout"
    assert len(ei.value.failures[0]["layouts_matched"]) > 1


def test_the_two_regulator_layouts_convert_a_record_identically():
    """Same regulator, same semantics, different punctuation. A record filed once and
    published in both products must arrive at the same internal record, or a filer's
    results would depend on which download the operator happened to use."""
    values = {"lei": "L", "activity_year": "2025", "income": "142",
              "loan_amount": "305000", "property_value": "315000",
              "debt_to_income_ratio": "44", "action_taken": "3",
              "county_code": "06073", "denial_reason_1": "1", "aus_1": "1",
              "combined_loan_to_value_ratio": "96.5",
              "co_applicant_credit_score_type": "10",
              "open_end_line_of_credit": "2"}
    # the same values, spelled the way each product spells them
    snap_row = dict.fromkeys(_header_for("snapshot"), "")
    snap_row.update(values)
    ffiec_row = dict.fromkeys(_header_for("ffiec"), "")
    ffiec_row.update({k: v for k, v in values.items()
                      if k not in ("denial_reason_1", "aus_1",
                                   "combined_loan_to_value_ratio",
                                   "co_applicant_credit_score_type",
                                   "open_end_line_of_credit")})
    ffiec_row.update({"denial_reason-1": "1", "aus-1": "1",
                      "loan_to_value_ratio": "96.5",
                      "co-applicant_credit_score_type": "10",
                      "open-end_line_of_credit": "2"})
    a = loader.convert(snap_row, "snapshot", {})
    b = loader.convert(ffiec_row, "ffiec", {})
    # record_key is a digest of the SOURCE row, so it differs by construction: the two
    # products publish different columns. Everything the engine reasons about must agree.
    for field in COLUMNS:
        if field == "record_key":
            continue
        assert a[field] == b[field], field


def test_income_crosses_the_two_layouts_intact():
    """The FFIEC file publishes income in THOUSANDS and the template in DOLLARS. Getting
    this backwards moves every income by three orders of magnitude, which the control-set
    tolerance would absorb silently on one side and reject everything on the other."""
    ffiec = loader.convert({"income": "142", "loan_to_value_ratio": "80.0",
                            "denial_reason-1": "", "lei": "L", "activity_year": "2024"},
                           "ffiec", {})
    tmpl = loader.convert({"income": "142000", "combined_loan_to_value_ratio": "80.0",
                           "lei": "L", "activity_year": "2024"}, "template", {})
    assert ffiec["income"] == 142000.0
    assert tmpl["income"] == 142000.0


def test_record_key_is_a_digest_of_the_source_row():
    a = loader.convert({"lei": "L", "income": "100"}, "template", {})
    b = loader.convert({"lei": "L", "income": "100"}, "template", {})
    c = loader.convert({"lei": "L", "income": "101"}, "template", {})
    assert a["record_key"] == b["record_key"] != c["record_key"]
    assert a["record_key"].startswith("R")


# --- refusals --------------------------------------------------------------
def _ok_row(**over):
    r = {c: v for c, v in [
        ("lei", "549300TEST00000001"), ("activity_year", 2024), ("action_taken", 1),
        ("denial_reason_1", ""), ("denial_reason_2", ""), ("denial_reason_3", ""),
        ("denial_reason_4", ""), ("loan_purpose", 1), ("occupancy_type", 1),
        ("lien_status", 1), ("loan_type", 1), ("county_code", "06073"), ("aus_1", 1),
        ("construction_method", 1), ("total_units", 1), ("submission_of_application", 1),
        ("initially_payable_to_institution", 1), ("conforming_loan_limit", "C"),
        ("amortization", 2), ("interest_only_payment", 2), ("balloon_payment", 2),
        ("negative_amortization", 2), ("has_co_applicant", 0), ("loan_amount", 485000),
        ("income", 142000), ("property_value", 605000),
        ("combined_loan_to_value_ratio", 80.165), ("debt_to_income_ratio", 41),
        ("open_end_line_of_credit", 2), ("reverse_mortgage", 2),
        ("business_or_commercial_purpose", 2)]}
    r.update(over)
    return r


def test_data_not_at_publication_granularity_is_refused(tmp_path, snap):
    """The one refusal people are surprised by, and the one that matters most: the whole
    resolution budget is derived from the regulator's coarsening. Full-precision values
    make every stated bin width a lie."""
    p = _write(tmp_path, [_ok_row(loan_amount=487321, property_value=603198)])
    with pytest.raises(SpecError) as ei:
        _load(tmp_path, [p], snap)
    assert ei.value.kind == "data_is_not_at_publication_granularity"
    fields = {f.get("field") for f in ei.value.failures}
    assert {"loan_amount", "property_value"} <= fields


def test_internal_data_can_be_loaded_but_is_stamped(tmp_path, snap):
    p = _write(tmp_path, [_ok_row(loan_amount=487321)])
    got = _load(tmp_path, [p], snap, allow_nonconforming=True)
    assert got["granularity_conforming"] is False
    assert got["granularity_report"]["loan_amount"]["conforming"] == 0


def test_a_ragged_row_is_refused_not_padded(tmp_path, snap):
    p = tmp_path / "r.csv"
    good = ",".join(str(_ok_row()[c]) for c in loader.TEMPLATE_COLUMNS)
    with open(p, "w") as fh:
        fh.write(",".join(loader.TEMPLATE_COLUMNS) + "\n")
        fh.write(good + "\n")
        fh.write(",".join(["x"] * (len(loader.TEMPLATE_COLUMNS) - 3)) + "\n")
    with pytest.raises(SpecError) as ei:
        _load(tmp_path, [str(p)], snap)
    assert ei.value.kind == "ragged_rows"
    assert ei.value.failures[0]["line"] == 3


def test_a_code_outside_its_domain_is_refused_with_its_line_number(tmp_path, snap):
    p = _write(tmp_path, [_ok_row(), _ok_row(action_taken=9)])
    with pytest.raises(SpecError) as ei:
        _load(tmp_path, [p], snap)
    assert ei.value.kind == "value_outside_published_domain"
    f = ei.value.failures[0]
    assert f["field"] == "action_taken" and f["value"] == 9 and f["row"] == 2


def test_two_filers_in_one_file_are_refused(tmp_path, snap):
    p = _write(tmp_path, [_ok_row(), _ok_row(lei="549300TEST00000002")])
    with pytest.raises(SpecError) as ei:
        _load(tmp_path, [p], snap)
    assert ei.value.kind == "snapshot_is_not_one_filer_year"


def test_two_years_in_one_file_are_refused(tmp_path, snap):
    p = _write(tmp_path, [_ok_row(), _ok_row(activity_year=2023)])
    with pytest.raises(SpecError) as ei:
        _load(tmp_path, [p], snap)
    assert ei.value.kind == "snapshot_is_not_one_filer_year"


def test_a_template_missing_a_required_column_is_refused(tmp_path, snap):
    cols = [c for c in loader.TEMPLATE_COLUMNS if c != "county_code"]
    p = _write(tmp_path, [_ok_row()], header=cols)
    with pytest.raises(SpecError) as ei:
        _load(tmp_path, [p], snap)
    assert ei.value.kind == "template_missing_required_columns"
    assert ei.value.failures[0]["missing"] == ["county_code"]


def test_mixed_layouts_in_one_load_are_refused(tmp_path, snap):
    a = _write(tmp_path, [_ok_row()], name="a.csv")
    b = tmp_path / "b.csv"
    b.write_text("lei,activity_year,loan_to_value_ratio,denial_reason-1\nL,2024,80,\n")
    with pytest.raises(SpecError) as ei:
        _load(tmp_path, [a, str(b)], snap)
    assert ei.value.kind == "headers_differ_between_files"


# --- rows-only exports -----------------------------------------------------
def test_a_header_file_supplies_names_for_a_rows_only_export(tmp_path, snap):
    """Some regulator downloads and most hand-split files arrive without a header. The
    first data line must not be eaten as one."""
    hdr = tmp_path / "h.csv"
    hdr.write_text(",".join(loader.TEMPLATE_COLUMNS) + "\n")
    rows = tmp_path / "rows.csv"
    with open(rows, "w", newline="") as fh:
        w = csv.writer(fh)
        for r in (_ok_row(), _ok_row(loan_amount=495000)):
            w.writerow([r[c] for c in loader.TEMPLATE_COLUMNS])
    got = _load(tmp_path, [str(rows)], snap, header_file=str(hdr))
    assert got["rows_written"] == 2


def test_a_repeated_header_line_is_not_read_as_a_record(tmp_path, snap):
    p = tmp_path / "r.csv"
    hdr = ",".join(loader.TEMPLATE_COLUMNS)
    row = ",".join(str(_ok_row()[c]) for c in loader.TEMPLATE_COLUMNS)
    p.write_text(hdr + "\n" + row + "\n" + hdr + "\n" + row + "\n")
    got = _load(tmp_path, [str(p)], snap)
    assert got["rows_written"] == 1          # the two data rows are identical, so deduped
    assert got["duplicates_dropped"] == 1


# --- sentinels -------------------------------------------------------------
def test_exempt_and_na_are_normalised_to_null_and_counted_separately(snap):
    causes = {}
    out = loader.convert({"lei": "L", "activity_year": "2024",
                          "combined_loan_to_value_ratio": "Exempt",
                          "debt_to_income_ratio": "NA", "income": "100000"},
                         "template", causes)
    assert out["combined_loan_to_value_ratio"] is None
    assert out["debt_to_income_ratio"] is None
    assert causes.get("exempt") == 1
    assert causes.get("na", 0) >= 1


def test_denial_reason_10_is_an_absence_not_a_reason():
    out = loader.convert({"lei": "L", "activity_year": "2024", "denial_reason_1": "10"},
                         "template", {})
    assert out["denial_reason_1"] is None


# --- the fast path and the readable one must agree -------------------------
def _reference_records(path, layout, header_file=None):
    """Run the plain-Python reference conversion over a file."""
    header = loader.read_header(header_file or path)
    out, causes = [], {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rdr = csv.reader(fh)
        if header_file is None:
            next(rdr)
        for rec in rdr:
            if not rec or all(c.strip() == "" for c in rec):
                continue
            if [c.strip() for c in rec] == header:
                continue
            if len(rec) != len(header):
                continue
            out.append(loader.convert(dict(zip(header, rec, strict=False)), layout, causes))
    return out, causes


def _norm(v):
    if isinstance(v, float) and v.is_integer():
        return v
    return v


@pytest.mark.parametrize("path,header_file", [
    ("data/raw/hmda_2024_fairway_sandiego/denied.csv",
     "data/raw/hmda_2024_fairway_sandiego/header.csv"),
    ("data/examples/likewise_example_filing.csv", None),
    ("docs/templates/likewise_lar_template.csv", None),
])
def test_sql_and_reference_conversions_agree(path, header_file, snap, tmp_path):
    """`convert()` is the legible statement of what a load means; the SQL in `projection()`
    is what production runs on a file too large to hold in memory. Two implementations of
    one rule drift unless something forces them together -- this is that thing.

    Every field of every record must match, record_key included: the pseudonymised
    record_ref an operator quotes in a worksheet is derived from it, so a digest that
    changed between implementations would silently invalidate work already done.
    """
    p = str(ROOT / path)
    hf = str(ROOT / header_file) if header_file else None
    header = loader.read_header(hf or p)
    layout = loader.detect_layout(header)

    got = _load(tmp_path, [p], snap, header_file=hf)
    ref, ref_causes = _reference_records(p, layout, hf)

    assert len(ref) >= 1
    by_key_sql = {r["record_key"]: r for r in got["records"]}
    by_key_ref = {r["record_key"]: r for r in ref}
    assert set(by_key_sql) == set(by_key_ref), "record_key digests differ"

    for k, expected in by_key_ref.items():
        actual = by_key_sql[k]
        for field in COLUMNS:
            a, b = _norm(actual[field]), _norm(expected[field])
            if isinstance(a, float) and isinstance(b, float):
                assert a == pytest.approx(b, rel=1e-12), f"{field} on {k}"
            else:
                assert a == b, f"{field} on {k}: sql={a!r} reference={b!r}"

    assert got["normalisation_causes"] == {k: v for k, v in ref_causes.items() if v}


def test_the_loader_spills_outside_the_working_directory(snap, tmp_path):
    """DuckDB's default spill location is `.tmp`, relative to the working directory, so a
    large filing would scatter scratch files through the operator's project next to the
    data being loaded. This does not affect whether a load succeeds -- it decides where the
    mess goes, and the answer must not be "in their repository"."""
    import duckdb
    con = duckdb.connect()
    assert con.execute("SELECT current_setting('temp_directory')").fetchone()[0] == ".tmp"
    loader.load_to_parquet([str(TEMPLATE)], snap, str(tmp_path / "o.parquet"), con=con)
    after = con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    assert os.path.isabs(after), f"spill directory is still relative: {after!r}"


@pytest.mark.slow
def test_the_loader_runs_inside_a_fixed_memory_budget(snap, tmp_path):
    """The row-at-a-time implementation needed roughly 120 bytes of interpreter heap per
    source byte, which put a 500,000-row filing near 1.8 GB and the national file out of
    reach entirely. What replaced it holds aggregates, not records, so the question is not
    how much memory it happens to use but whether it can be TOLD how much to use. A budget
    far below what the old path needed for this file, honoured."""
    import duckdb
    ex = str(ROOT / "data" / "examples" / "likewise_example_filing.csv")
    big = tmp_path / "big.csv"
    with open(ex) as src, open(big, "w") as dst:
        head = src.readline()
        body = src.read()
        dst.write(head)
        for _ in range(10):          # 10x the data, one filer-year, ~15 MB
            dst.write(body)

    def load_under(path, limit="512MB"):
        con = duckdb.connect()
        con.execute(f"SET memory_limit='{limit}'")
        con.execute("SET threads=2")
        try:
            return loader.load_to_parquet([str(path)], snap,
                                          str(tmp_path / "o.parquet"), con=con)
        finally:
            con.close()

    small = load_under(ex)
    large = load_under(big)
    assert small["rows_written"] > 10000
    # Twenty times the bytes, the same budget. The rows are repeats, so they dedupe back
    # to the same set -- which makes this the hardest case for the aggregate, not the
    # easiest, and proves the reader and the aggregate both spill rather than grow.
    assert large["rows_written"] == small["rows_written"]
    physical = small["rows_written"] + small["duplicates_dropped"]
    assert large["duplicates_dropped"] == 10 * physical - small["rows_written"]


def test_a_file_whose_every_row_is_ragged_says_so(snap, tmp_path):
    """DuckDB creates no reject table when nothing survives the scan, so without this the
    file would be reported as empty -- which is a different problem with a different fix."""
    p = tmp_path / "allbad.csv"
    p.write_text(",".join(loader.TEMPLATE_COLUMNS) + "\n"
                 + ",".join(["x"] * 5) + "\n" + ",".join(["y"] * 5) + "\n")
    with pytest.raises(SpecError) as ei:
        _load(tmp_path, [str(p)], snap)
    assert ei.value.kind == "ragged_rows"
    summary = next(f for f in ei.value.failures if "data_lines" in f)
    assert summary["data_lines"] == 2 and summary["records_parsed"] == 0


def test_engine_budget_comes_from_the_environment(monkeypatch):
    """Raising the container's --memory must actually raise DuckDB's limit. It used to
    be a default argument, so it did not: the operator had no lever and no signal."""
    import duckdb
    from likewise import runtime, scan

    def limit_gib(con):
        raw = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
        n, unit = raw.split()
        return float(n) * (1.0 if unit.upper().startswith("GI") else 1 / 1024)

    monkeypatch.setenv("LIKEWISE_MEMORY_MB", "1024")
    small = limit_gib(scan.configure(duckdb.connect()))
    monkeypatch.setenv("LIKEWISE_MEMORY_MB", "4096")
    monkeypatch.setenv("LIKEWISE_THREADS", "3")
    con = scan.configure(duckdb.connect())
    # DuckDB reports the limit with its own headroom applied, so assert the lever moves
    # rather than pinning a formatted string that is not ours to control.
    assert limit_gib(con) > small * 3
    assert int(con.execute("SELECT current_setting('threads')").fetchone()[0]) == 3

    # A value below DuckDB's own floor for this pipeline is a misconfiguration, not a
    # tighter budget: below it a three-row file fails too.
    monkeypatch.setenv("LIKEWISE_MEMORY_MB", "16")
    assert runtime.memory_mb() == runtime.MIN_MEMORY_MB

    # Junk falls back rather than crashing the process at startup.
    monkeypatch.setenv("LIKEWISE_MEMORY_MB", "lots")
    monkeypatch.setenv("LIKEWISE_THREADS", "")
    assert runtime.memory_mb() == 2048
    assert runtime.threads() == 2


def test_the_load_path_sets_a_memory_limit_at_all(monkeypatch, tmp_path):
    """The documentation has always said the loader honours a memory budget. It did not
    set one -- and the load is the step that reads the national file."""
    import inspect
    from likewise import loader
    src = inspect.getsource(loader.load_to_parquet)
    assert "memory_limit" in src, "the load path must bound its own memory"
