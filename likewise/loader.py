"""Load a CSV filing into the internal schema.

This is the only place source drift can fail, so it fails loudly. Two layouts are
accepted and detected from the header:

  ffiec     the FFIEC Modified LAR / Data Browser export, column names exactly as the
            regulator publishes them (`denial_reason-1`, `loan_to_value_ratio`, income
            in THOUSANDS of dollars)
  template  the simplified template in docs/templates/, which uses the internal field
            names directly and income in DOLLARS

The conversion runs inside DuckDB and streams: the CSV is read, normalised, checked and
written to Parquet without a Python object per row. A filer's full Modified LAR is tens
to hundreds of megabytes and the earlier row-at-a-time implementation needed roughly
120 bytes of interpreter heap per source byte, which put a 500,000-row filing at about
1.8 GB. Nothing here holds more than the aggregates.

`convert()` below is the same mapping written as plain Python. It is the readable
reference and it is NOT what production runs -- `test_sql_and_reference_conversions_agree`
drives both over real files and asserts they produce identical records, so the fast path
cannot drift from the legible one without a test failing.

Three things happen here that cannot happen anywhere else:

  * The EGRRCPA "Exempt" sentinel and the NA sentinels become null, and which of the two
    it was is counted. "Exempt" == "Exempt" would otherwise pass an exact-match test.
  * Census tract is dropped, so no downstream code can emit geography finer than the
    county ceiling.
  * Publication granularity is CHECKED rather than assumed. The whole comparability
    argument rests on the claim that these fields arrive already coarsened by the
    regulator's publication rules. If a file arrives at full internal precision that
    claim is false, the resolution budget does not describe it, and loading it quietly
    would put un-coarsened data behind a screen that says "published as a $10k band".

The design is REFUSE, NEVER REPAIR. Nothing in this module pads a short row, truncates a
long one, coerces an unrecognised code to null, or drops a record it could not read.
Every check below either passes or raises SpecError with a payload naming the file, the
position and the remedy, because a partially loaded snapshot is indistinguishable from a
complete one once it is on disk.

What this module does NOT own: it does not decide what is comparable (that is the
versioned specification), does not scan, and does not pseudonymise. It writes the
curated Parquet and a manifest describing it; everything after that reads them.
"""
from __future__ import annotations
import csv
import hashlib
import json
import logging
import os
import tempfile

import duckdb

from . import paths as _paths
from . import runtime as _runtime
from .errors import SpecError
from .schema import (COLUMNS, EXEMPT_SENTINELS, INTERNAL_SCHEMA, NA_SENTINELS,
                     NUMERIC_SENTINELS, normalise_value)

log = logging.getLogger("likewise.loader")

INCOME_UNIT_THOUSANDS = 1000.0
NO_CO_APPLICANT = "10"          # co-applicant credit score type 10 == "No co-applicant"
REASON_NOT_APPLICABLE = 10      # a denial reason of 10 is an absence, not a reason

# internal field -> source column, for the regulator's own layout
FFIEC_MAP = {
    "lei": "lei", "activity_year": "activity_year", "action_taken": "action_taken",
    "loan_purpose": "loan_purpose", "occupancy_type": "occupancy_type",
    "lien_status": "lien_status", "loan_type": "loan_type", "county_code": "county_code",
    "aus_1": "aus-1", "construction_method": "construction_method",
    "total_units": "total_units", "submission_of_application": "submission_of_application",
    "initially_payable_to_institution": "initially_payable_to_institution",
    "conforming_loan_limit": "conforming_loan_limit",
    "interest_only_payment": "interest_only_payment", "balloon_payment": "balloon_payment",
    "negative_amortization": "negative_amortization",
    "loan_amount": "loan_amount", "property_value": "property_value",
    "combined_loan_to_value_ratio": "loan_to_value_ratio",
    "debt_to_income_ratio": "debt_to_income_ratio",
    "open_end_line_of_credit": "open-end_line_of_credit",
    "reverse_mortgage": "reverse_mortgage",
    "business_or_commercial_purpose": "business_or_commercial_purpose",
    "denial_reason_1": "denial_reason-1", "denial_reason_2": "denial_reason-2",
    "denial_reason_3": "denial_reason-3", "denial_reason_4": "denial_reason-4",
}

# internal field -> source column, for the Snapshot National Loan Level Dataset. Same
# regulator, same semantics, same publication coarsening, different punctuation: the
# Snapshot spells with underscores where the Data Browser spells with hyphens, and names
# the ratio in full. Income is in THOUSANDS in both.
#
# It is a separate map rather than a normalisation pass over the header because the two
# products are not the same file. The Snapshot carries census tract and the full
# demographic block, which the Modified LAR omits; a rule that rewrote punctuation would
# make the two look interchangeable when only one of them is safe to publish geography
# from.
SNAPSHOT_MAP = {**FFIEC_MAP,
                "aus_1": "aus_1",
                "open_end_line_of_credit": "open_end_line_of_credit",
                "combined_loan_to_value_ratio": "combined_loan_to_value_ratio",
                "denial_reason_1": "denial_reason_1",
                "denial_reason_2": "denial_reason_2",
                "denial_reason_3": "denial_reason_3",
                "denial_reason_4": "denial_reason_4"}

# The column each layout derives co-applicant presence from. Differs by one hyphen, and
# getting it wrong makes every record look like it has a co-applicant.
CO_APPLICANT_COLUMN = {"ffiec": "co-applicant_credit_score_type",
                       "snapshot": "co_applicant_credit_score_type"}

# Source columns a layout needs that are not in its map, because the field they feed is
# derived rather than renamed.
LAYOUT_DERIVED_SOURCES = {
    "ffiec": ("income", "other_nonamortizing_features", CO_APPLICANT_COLUMN["ffiec"]),
    "snapshot": ("income", "other_nonamortizing_features", CO_APPLICANT_COLUMN["snapshot"]),
    "template": (),
}

# The two regulator layouts share every derivation; only their spelling differs.
FFIEC_LIKE = ("ffiec", "snapshot")

REASON_FIELDS = ("denial_reason_1", "denial_reason_2", "denial_reason_3", "denial_reason_4")
DOUBLE_FIELDS = ("loan_amount", "income", "property_value",
                 "combined_loan_to_value_ratio", "debt_to_income_ratio")
VARCHAR_FIELDS = ("record_key", "lei", "county_code", "conforming_loan_limit")
INT_FIELDS = tuple(c for c in COLUMNS if c not in DOUBLE_FIELDS + VARCHAR_FIELDS)

# Template columns. record_key is derived from a content digest, never supplied: the
# public file carries no applicant identifier and inventing one invites a join.
TEMPLATE_COLUMNS = [c for c in COLUMNS if c != "record_key"]
TEMPLATE_REQUIRED = [c for c in TEMPLATE_COLUMNS
                     if c not in ("denial_reason_2", "denial_reason_3", "denial_reason_4")]

# Value domains. A code outside its domain is a load failure, not a null: silently
# nulling an unrecognised action_taken would move records between populations.
DOMAINS = {
    "action_taken": set(range(1, 9)),
    "loan_purpose": {1, 2, 31, 32, 4, 5},
    "occupancy_type": {1, 2, 3},
    "lien_status": {1, 2},
    "loan_type": {1, 2, 3, 4},
    "construction_method": {1, 2},
    "submission_of_application": {1, 2, 3},
    "initially_payable_to_institution": {1, 2, 3},
    "open_end_line_of_credit": {1, 2},
    "reverse_mortgage": {1, 2},
    "business_or_commercial_purpose": {1, 2},
    "interest_only_payment": {1, 2},
    "balloon_payment": {1, 2},
    "negative_amortization": {1, 2},
    "amortization": {1, 2},
    "has_co_applicant": {0, 1},
    "denial_reason_1": set(range(1, 11)),
    "denial_reason_2": set(range(1, 11)),
    "denial_reason_3": set(range(1, 11)),
    "denial_reason_4": set(range(1, 11)),
}


# --------------------------------------------------------------------------
# layout
# --------------------------------------------------------------------------
def layout_maps() -> dict[str, dict]:
    """Every accepted layout, as internal field -> source column."""
    return {"ffiec": FFIEC_MAP, "snapshot": SNAPSHOT_MAP,
            "template": {c: c for c in TEMPLATE_COLUMNS}}


def required_sources(layout: str) -> set[str]:
    """The source columns a layout cannot be read without.

    The three optional denial reasons are excluded: a filing where no record cites a
    second reason legitimately omits the column. Everything else is required, which is
    the point of the check below -- a layout is only claimed when the WHOLE of it is
    present.
    """
    optional = {"denial_reason_2", "denial_reason_3", "denial_reason_4"}
    m = layout_maps()[layout]
    return ({src for field, src in m.items() if field not in optional}
            | set(LAYOUT_DERIVED_SOURCES[layout]))


def score_layouts(header: list[str]) -> dict[str, tuple[float, list[str]]]:
    """How completely each layout is satisfied by this header, and what it is missing."""
    h = {c.strip() for c in header}
    out = {}
    for layout in layout_maps():
        need = required_sources(layout)
        missing = sorted(need - h)
        out[layout] = ((len(need) - len(missing)) / len(need), missing)
    return out


def detect_layout(header: list[str]) -> str:
    """Which accepted layout this header is, or a refusal.

    Scored against each layout's FULL required column set, not against a marker column.
    A layout is claimed only when every column it needs is present, and two complete
    matches are an ambiguity that refuses rather than a tie broken by declaration order.

    The marker approach this replaced had a real hole, and it is worth recording because
    it failed in the most dangerous direction available. The Snapshot National Loan Level
    Dataset names its ratio `combined_loan_to_value_ratio` -- which was the TEMPLATE
    marker -- while publishing income in thousands, as the Data Browser does. A Snapshot
    file therefore matched the template branch, and the template branch does not scale
    income. Every income would have come out a thousand times too small, the blocking
    band on income would have matched almost everything, and nothing about the load would
    have looked wrong. It happened to fail safe only because the Snapshot lacks the
    derived `amortization` and `has_co_applicant` columns and the required-column check
    downstream refused it. That is luck, not design, and luck is not a detector.
    """
    scored = score_layouts(header)
    complete = sorted(k for k, (frac, _) in scored.items() if frac == 1.0)
    if len(complete) == 1:
        return complete[0]
    if len(complete) > 1:
        raise SpecError("ambiguous_csv_layout", [{
            "problem": "the header satisfies more than one layout completely",
            "layouts_matched": complete,
            "remedy": "Export the file unchanged from one source. A header assembled "
                      "from two products cannot be read as either, because the two "
                      "disagree on the unit of `income`."}])
    # The drop folder is operator-facing and the template is the operator's path, so a
    # header that is unambiguously a template with something missing gets the specific
    # refusal naming the missing columns rather than a three-layout score table. This
    # chooses a MESSAGE, never a reading: the file is refused either way.
    t_missing = set(scored["template"][1])
    if all(t_missing < set(m) for k, (_, m) in scored.items() if k != "template"):
        raise SpecError("template_missing_required_columns", [{
            "missing": sorted(t_missing),
            "remedy": "Start from docs/templates/likewise_lar_template.csv; the "
                      "column names and their order are the contract."}])

    best = sorted(scored.items(), key=lambda kv: -kv[1][0])
    raise SpecError("unrecognised_csv_layout", [{
        "problem": "the header satisfies no accepted layout completely",
        "layouts": {k: {"fraction_present": round(f, 4), "missing": m[:8]}
                    for k, (f, m) in best},
        "header_seen": header[:12] + (["..."] if len(header) > 12 else []),
        "remedy": "Export from the FFIEC Data Browser or the Snapshot National Loan "
                  "Level Dataset unchanged, or start from "
                  "docs/templates/likewise_lar_template.csv"}])


def read_header(path: str) -> list[str]:
    # utf-8-sig, because a spreadsheet export carries a byte-order mark and the first
    # column name would otherwise arrive with it still attached and match nothing in
    # either layout map. An empty file is refused here rather than at the first
    # aggregate, where it would look like a filing with no records.
    with open(path, newline="", encoding="utf-8-sig") as fh:
        try:
            return [h.strip() for h in next(csv.reader(fh))]
        except StopIteration as exc:
            raise SpecError(
                "empty_csv", [{"file": path, "problem": "file is empty"}]) from exc


# --------------------------------------------------------------------------
# the reference conversion, in plain Python
# --------------------------------------------------------------------------
def _convert_ffiec(raw: dict, causes: dict, layout: str = "ffiec") -> dict:
    # Both regulator layouts, since they differ only in how the source columns are
    # spelled. Three fields are not a straight rename and are handled after the mapping
    # loop: income arrives in thousands, amortization is derived from a differently named
    # source column, and co-applicant presence is derived from a credit-score-type
    # sentinel rather than published as a flag.
    out = {}
    for field, src in layout_maps()[layout].items():
        v, cause = normalise_value(field, raw.get(src))
        if cause:
            causes[cause] = causes.get(cause, 0) + 1
        out[field] = v
    inc, cause = normalise_value("income", raw.get("income"))
    if cause:
        causes[cause] = causes.get(cause, 0) + 1
    # The regulator publishes income in THOUSANDS of dollars. Left unscaled, every
    # income in the snapshot is off by three orders of magnitude, the blocking band on
    # income matches almost everything, and nothing about the load looks wrong.
    out["income"] = None if inc is None else float(inc) * INCOME_UNIT_THOUSANDS
    amort, _ = normalise_value("amortization", raw.get("other_nonamortizing_features"))
    out["amortization"] = None if amort is None else int(amort)
    co = (raw.get(CO_APPLICANT_COLUMN[layout]) or "").strip()
    out["has_co_applicant"] = 0 if co == NO_CO_APPLICANT else 1
    return out


def _convert_template(raw: dict, causes: dict) -> dict:
    out = {}
    for field in TEMPLATE_COLUMNS:
        v, cause = normalise_value(field, raw.get(field))
        if cause:
            causes[cause] = causes.get(cause, 0) + 1
        out[field] = v
    return out


def record_key(raw: dict) -> str:
    """A content digest over the source row. The public file carries no applicant
    identifier; a digest is stable across re-loads and carries no identity of its own."""
    return "R" + hashlib.sha256(
        "\x1f".join("%s=%s" % (k, raw.get(k)) for k in sorted(raw)).encode()).hexdigest()[:16]


def convert(raw: dict, layout: str, causes: dict) -> dict:
    """Reference implementation. Production runs the SQL in `projection()`; a differential
    test asserts the two agree record for record."""
    out = (_convert_ffiec(raw, causes, layout) if layout in FFIEC_LIKE
           else _convert_template(raw, causes))
    # Denial reason 10 is "not applicable" -- an absence written as a code. Nulling it is
    # what puts such a denial in the excluded count the scan reports rather than in the
    # population it tests; kept as 10 it would be a reason code like any other.
    for k in REASON_FIELDS:
        if out.get(k) is not None:
            out[k] = int(out[k])
            if out[k] == REASON_NOT_APPLICABLE:
                out[k] = None
    for k in INT_FIELDS:
        if out.get(k) is not None:
            out[k] = int(out[k])
    for k in DOUBLE_FIELDS:
        if out.get(k) is not None:
            out[k] = float(out[k])
    # County codes are five-digit FIPS and are matched on exactly. A source that lost a
    # leading zero -- which a spreadsheet round-trip does -- would otherwise put "1001"
    # and "01001" in different blocks, and neither would find its comparators.
    if out.get("county_code") is not None:
        out["county_code"] = str(out["county_code"]).strip().zfill(5)
    out["record_key"] = record_key(raw)
    return {c: out.get(c) for c in COLUMNS}


# --------------------------------------------------------------------------
# the SQL conversion
# --------------------------------------------------------------------------
# The SQL below is built as text because the column names come from the file being read.
# _q quotes an IDENTIFIER and _lit quotes a STRING LITERAL, each doubling its own quote
# character; both are used everywhere a source-derived name or value enters a statement,
# so a column called `a"b` -- or a file path with an apostrophe in it -- cannot terminate
# the token it sits in.
def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _sentinels_sql() -> str:
    vals = sorted(EXEMPT_SENTINELS | {s for s in NA_SENTINELS if s})
    return "(" + ", ".join(_lit(v) for v in vals) + ")"


def _nz(col: str) -> str:
    """Sentinel normalisation, matching `schema.normalise_value` exactly."""
    c = _q(col)
    return (f"CASE WHEN {c} IS NULL OR trim({c}) = '' OR trim({c}) IN {_sentinels_sql()} "
            f"THEN NULL ELSE trim({c}) END")


def _num(col: str, field: str) -> str:
    """Numeric normalisation. A value that will not parse becomes null, as does one of
    the HMDA numeric sentinels -- except in total_units, where 1111 is a unit count."""
    nz = _nz(col)
    guard = ""
    if field != "total_units":
        sent = ", ".join(str(s) for s in sorted(NUMERIC_SENTINELS))
        guard = (f"WHEN CAST(trunc(TRY_CAST({nz} AS DOUBLE)) AS BIGINT) IN ({sent}) "
                 f"THEN NULL ")
    return f"CASE WHEN TRY_CAST({nz} AS DOUBLE) IS NULL THEN NULL {guard}" \
           f"ELSE TRY_CAST({nz} AS DOUBLE) END"


def cause_columns(layout: str, header: list[str]) -> str:
    """Per-row counts of source values normalised away, split by which sentinel did it.

    Computed in the same pass as the projection so the source is never materialised. The
    split matters and is not cosmetic: an EGRRCPA partial exemption and a genuinely absent
    value are different populations, and the summary reports them against different
    denominators. A numeric HMDA sentinel -- 1111, 8888, 9999, -1 -- counts as absent too,
    which is why this walks the same field/source pairs the reference conversion does
    rather than the source columns alone.
    """
    if layout in FFIEC_LIKE:
        pairs = list(layout_maps()[layout].items()) + [
            ("income", "income"),
            ("amortization", "other_nonamortizing_features")]
    else:
        pairs = [(c, c) for c in TEMPLATE_COLUMNS]
    pairs = [(f, c) for f, c in pairs if c in header]

    ex = ", ".join(_lit(v) for v in sorted(EXEMPT_SENTINELS))
    na = ", ".join(_lit(v) for v in sorted(v for v in NA_SENTINELS if v))
    sent = ", ".join(str(v) for v in sorted(NUMERIC_SENTINELS))
    numeric = {k for k, v in INTERNAL_SCHEMA.items() if v in ("DOUBLE", "INTEGER")}

    e_terms, n_terms = [], []
    for field, col in pairs:
        q = _q(col)
        blank = f"{q} IS NULL OR trim({q}) = '' OR trim({q}) IN ({na})"
        e_terms.append(f"CASE WHEN trim({q}) IN ({ex}) THEN 1 ELSE 0 END")
        if field in numeric:
            unparsable = f"TRY_CAST(trim({q}) AS DOUBLE) IS NULL"
            cond = f"{blank} OR {unparsable}"
            if field != "total_units":
                cond += (f" OR CAST(trunc(TRY_CAST(trim({q}) AS DOUBLE)) AS BIGINT) "
                         f"IN ({sent})")
        else:
            cond = blank
        n_terms.append(f"CASE WHEN trim({q}) IN ({ex}) THEN 0 "
                       f"WHEN {cond} THEN 1 ELSE 0 END")
    return (f"({' + '.join(e_terms)}) AS _cause_exempt,\n  "
            f"({' + '.join(n_terms)}) AS _cause_na")


def projection(layout: str, header: list[str]) -> str:
    """The SELECT list that turns source columns into the internal schema."""
    src = layout_maps()[layout]
    parts = []
    digest = " || chr(31) || ".join(
        f"{_lit(k + '=')} || coalesce({_q(k)}, '')" for k in sorted(header))
    parts.append(f"'R' || substr(sha256({digest}), 1, 16) AS record_key")

    for field in COLUMNS:
        if field == "record_key":
            continue
        if layout in FFIEC_LIKE and field == "income":
            e = f"({_num('income', 'income')}) * {INCOME_UNIT_THOUSANDS}"
        elif layout in FFIEC_LIKE and field == "amortization":
            e = _num("other_nonamortizing_features", "amortization")
        elif layout in FFIEC_LIKE and field == "has_co_applicant":
            e = (f"CASE WHEN trim(coalesce({_q(CO_APPLICANT_COLUMN[layout])}, '')) = "
                 f"{_lit(NO_CO_APPLICANT)} THEN 0 ELSE 1 END")
        elif field == "county_code":
            e = f"lpad({_nz(src[field])}, 5, '0')"
        elif field in VARCHAR_FIELDS:
            e = _nz(src[field])
        else:
            e = _num(src[field], field)

        if field in REASON_FIELDS:
            e = f"nullif(CAST({e} AS BIGINT), {REASON_NOT_APPLICABLE})"
        elif field in INT_FIELDS:
            e = f"CAST({e} AS BIGINT)"
        elif field in DOUBLE_FIELDS:
            e = f"CAST({e} AS DOUBLE)"
        parts.append(f"{e} AS {_q(field)}")
    return ",\n  ".join(parts)


# --------------------------------------------------------------------------
# reading the files
# --------------------------------------------------------------------------
def _reader(paths: list[str], header: list[str], has_header: bool) -> str:
    """Read every source column as VARCHAR with the schema pinned, so the sniffer cannot
    quietly decide a ragged file has one column -- which is what it does when left to
    infer. Repeated header lines are dropped: concatenating per-filer exports is the
    normal way these files are assembled, and each part carries its own header."""
    cols = "{" + ", ".join(f"{_lit(h)}: 'VARCHAR'" for h in header) + "}"
    files = "[" + ", ".join(_lit(p) for p in paths) + "]"
    repeated = " AND ".join(f"trim(coalesce({_q(h)}, '')) = {_lit(h)}" for h in header)
    return (f"(SELECT * FROM read_csv({files}, columns={cols}, "
            f"header={'true' if has_header else 'false'}, store_rejects=true) "
            f"WHERE NOT ({repeated}))")


def _reject_rows(con, paths: list[str], header: list[str], has_header: bool) -> list[dict]:
    """Line numbers for rows the CSV reader dropped.

    DuckDB only materialises its reject table under some query plans -- a scan wrapped in
    a projection produces none -- so this is never used to DECIDE whether rows were
    dropped, only to locate them once the row-count reconciliation has already said so.
    """
    cols = "{" + ", ".join(f"{_lit(h)}: 'VARCHAR'" for h in header) + "}"
    files = "[" + ", ".join(_lit(p) for p in paths) + "]"
    try:
        # A full scan, not LIMIT 0: the reject table is a side effect of reading the
        # rows, so a plan that skips the scan produces nothing to read.
        con.execute(f"SELECT count(*) FROM read_csv({files}, columns={cols}, "
                    f"header={'true' if has_header else 'false'}, "
                    f"store_rejects=true)").fetchall()
        rows = con.execute(
            "SELECT line, csv_line, error_message FROM reject_errors "
            "ORDER BY line LIMIT 25").fetchall()
    except duckdb.Error:
        # Best-effort location only. The reject table does not materialise under every
        # plan, and the caller has already decided rows were dropped by reconciling
        # counts. A narrow catch here so a genuine bug in this module still surfaces.
        log.debug("reject-table probe failed", exc_info=True)
        return []
    seen, out = set(), []
    for line, csv_line, msg in rows:
        if line in seen:
            continue
        seen.add(line)
        out.append({"line": int(line), "csv_line": (csv_line or "")[:120], "problem": msg})
    return out


# --------------------------------------------------------------------------
# the checks that refuse
# --------------------------------------------------------------------------
# Four independent questions, each with its own refusal:
#   * is every coded value one the regulator publishes?     (value domain)
#   * did the reader see every data line in the files?      (row reconciliation)
#   * is this one filer and one year?                       (snapshot purity)
#   * has the data already been coarsened for publication?  (granularity)
# Each is a COUNT first and a location second: the common case is zero and must not pay
# to find that out, and a file about to be refused does not need its rows numbered until
# somebody has to go and look at them.
def count_domain_violations(con, src: str) -> dict:
    """How many values fall outside each published domain. One streaming aggregate: the
    common path is zero violations and must not pay to find that out."""
    terms = []
    for field, allowed in DOMAINS.items():
        vals = ", ".join(str(v) for v in sorted(allowed))
        terms.append(f"count(*) FILTER (WHERE {_q(field)} IS NOT NULL "
                     f"AND {_q(field)} NOT IN ({vals})) AS {_q(field)}")
    row = con.execute(f"SELECT {', '.join(terms)} FROM {src}").fetchone()
    # strict: a projection that returns a different number of terms than DOMAINS has
    # is a construction bug, and a silent zip truncation would report fewer domain
    # violations than the file contains -- a refusal gate reading low.
    return {f: int(n) for f, n in zip(DOMAINS, row, strict=True) if n}


def locate_domain_violations(con, src: str, fields: list[str],
                             first_n: int = 25) -> list[dict]:
    """Where they are. Only runs when the count above is non-zero, because numbering the
    rows means materialising them and the file is about to be refused anyway.

    The position reported is the record's ordinal among data rows, not a physical line
    number: the CSV reader does not surface one, and a blank line in the middle of the
    file would make a claimed line number quietly wrong.
    """
    clauses = []
    for field in fields:
        vals = ", ".join(str(v) for v in sorted(DOMAINS[field]))
        clauses.append(
            f"SELECT row_num AS row, {_lit(field)} AS field, "
            f"CAST({_q(field)} AS BIGINT) AS value, "
            f"{_lit(str(sorted(DOMAINS[field])))} AS allowed "
            f"FROM numbered WHERE {_q(field)} IS NOT NULL "
            f"AND {_q(field)} NOT IN ({vals})")
    sql = (f"WITH numbered AS (SELECT row_number() OVER () AS row_num, * FROM {src}) "
           + " UNION ALL ".join(clauses) + f" ORDER BY row, field LIMIT {first_n}")
    return [{"row": int(r[0]), "field": r[1], "value": int(r[2]), "allowed": r[3]}
            for r in con.execute(sql).fetchall()]


def _physical_rows(con, paths: list[str], header: list[str], has_header: bool) -> int:
    """Data lines in the files, read as opaque text: non-blank, and not a header line.

    This is the reference the parsed row count is reconciled against, so it must count the
    same things the scan counts -- blank lines and repeated header lines are skipped by
    both. Reading the files a second time as one opaque column costs a scan and buys the
    only trustworthy answer to "did the reader drop anything".
    """
    files = "[" + ", ".join(_lit(p) for p in paths) + "]"
    head = _lit(",".join(header))
    try:
        n = con.execute(
            f"SELECT count(*) FROM read_csv({files}, columns={{'line': 'VARCHAR'}}, "
            f"header=false, delim=chr(7), quote='', escape='') "
            f"WHERE trim(coalesce(line, '')) <> '' "
            f"AND trim(replace(coalesce(line, ''), chr(13), '')) <> {head}").fetchone()[0]
    except duckdb.Error:
        log.debug("physical row count failed", exc_info=True)
        return 0
    return max(0, int(n))


def check_granularity(con, src: str, snapshot: dict) -> dict:
    """Does this file actually carry the publication coarsening the resolution budget
    assumes? Reported per field as a conforming fraction, never silently."""
    gran = snapshot.get("publication_granularity", {})
    report = {}
    for field, g in gran.items():
        c = _q(field)
        w = float(g.get("width") or 0)
        kind = g.get("kind")
        if kind == "bin_midpoint" and w:
            cond = f"abs(({c} % {w}) - {w / 2.0}) < 1e-6"
            expect = "value mod %g == %g" % (w, w / 2.0)
        elif kind == "rounded" and w:
            cond = f"(abs({c} % {w}) < 1e-6 OR abs(({c} % {w}) - {w}) < 1e-6)"
            expect = "value mod %g == 0" % w
        elif kind == "bucketed" and g.get("integer_range"):
            lo, hi = g["integer_range"]
            cond = f"({c} BETWEEN {lo} AND {hi} AND {c} = trunc({c}))"
            expect = ("integer within [%s, %s]; anything else must arrive as a band"
                      % (lo, hi))
        else:
            cond = "TRUE"
            expect = "reported as filed; no coarsening to check"
        n, ok = con.execute(
            f"SELECT count({c}), count(*) FILTER (WHERE {c} IS NOT NULL AND {cond}) "
            f"FROM {src}").fetchone()
        if not n:
            report[field] = {"kind": kind, "n": 0, "conforming": None,
                             "note": "no non-null values"}
            continue
        report[field] = {"kind": kind, "n": int(n), "conforming": int(ok),
                         "fraction": round(ok / n, 6), "expected": expect}
    return report


def nonconforming(report: dict) -> list[dict]:
    """Fields where at least one value is finer than the published coarsening.

    The bar is EVERY value, not most of them: a single row at full internal precision
    means the file is not the published record, and a tolerated fraction would be a
    threshold nobody could justify. A field with nothing to check, or with no non-null
    values, is skipped rather than counted as failing.
    """
    out = []
    for field, r in report.items():
        if r.get("conforming") is None or not r.get("n"):
            continue
        if r["conforming"] < r["n"]:
            out.append({"field": field, "conforming": r["conforming"], "of": r["n"],
                        "fraction": r["fraction"], "expected": r["expected"]})
    return out


# --------------------------------------------------------------------------
# the load
# --------------------------------------------------------------------------
def load_to_parquet(paths: list[str], snapshot: dict, out_path: str,
                    allow_nonconforming: bool = False, header_file: str | None = None,
                    con: duckdb.DuckDBPyConnection | None = None) -> dict:
    """Read, convert, check and write, without a Python object per row.

    Raises SpecError with a machine-readable payload rather than returning a partial
    result: a half-loaded snapshot is worse than no snapshot.

    Order is deliberate and every check precedes the write: headers agree, layout is
    known, required columns are present, rows reconcile, values are in domain, the
    snapshot is one filer-year, granularity conforms -- and only then is anything put on
    disk. Nothing this function raises leaves a Parquet file behind.
    """
    own = con is None
    con = con or duckdb.connect()
    con.execute("SET preserve_insertion_order=true")
    # DuckDB spills over its memory limit to `temp_directory`, which defaults to `.tmp`
    # RELATIVE to the working directory -- so a large filing would scatter scratch files
    # through the operator's project tree, next to the data it is loading. Pointing it at
    # the system temp directory keeps spill out of their working copy. It does not change
    # whether the load succeeds; it changes where the mess goes.
    con.execute("SET temp_directory = " + _lit(tempfile.gettempdir()))
    # The load is the memory-heavy step -- it is the one that reads the national file --
    # and for a long time it set no limit at all while the documentation claimed a budget
    # was honoured. Without this, DuckDB sizes itself from host RAM, which in a memory-
    # capped container is a number the process is not allowed to have.
    con.execute(f"SET memory_limit='{_runtime.memory_mb()}MB'")
    con.execute(f"SET threads={_runtime.threads()}")

    # Every file in one load must present the same header, compared as a LIST: a
    # differing name and a differing order both refuse. One pinned schema is used to read
    # all of them, so a file whose columns are in another order has no way of saying so
    # once the read has started.
    headers = {}
    for p in paths:
        headers[p] = read_header(header_file) if header_file else read_header(p)
    first = headers[paths[0]]
    for p, h in headers.items():
        if h != first:
            raise SpecError("headers_differ_between_files", [{
                "file": os.path.basename(p),
                "problem": "every file in one load must have the same columns",
                "first_file": os.path.basename(paths[0])}])
    layout = detect_layout(first)
    if layout == "template":
        missing = [c for c in TEMPLATE_REQUIRED if c not in first]
        if missing:
            raise SpecError("template_missing_required_columns", [{
                "missing": missing,
                "remedy": "Start from docs/templates/likewise_lar_template.csv; the "
                          "column names and their order are the contract."}])

    reader = _reader(paths, first, has_header=header_file is None)
    # No temp table: the converted records are a SQL expression the checks re-scan. Reading
    # a 200 MB CSV three times costs seconds; holding it costs the whole file plus DuckDB's
    # own copy, and that is what the row-at-a-time implementation could not afford.
    conv = (f"(SELECT {projection(layout, first)},\n  {cause_columns(layout, first)}\n"
            f"   FROM {reader})")

    n_raw, exempt, nas = con.execute(
        f"SELECT count(*), coalesce(sum(_cause_exempt), 0), coalesce(sum(_cause_na), 0) "
        f"FROM {conv}").fetchone()

    # Reconcile what was parsed against what is physically in the files. The CSV reader
    # drops a row whose field count differs from the header, and it does so silently, so
    # the only trustworthy detector is the count: a row that vanished between the file and
    # the scan is exactly the shifted-column defect this refuses to load past.
    physical = _physical_rows(con, paths, first, has_header=header_file is None)
    if physical and physical != n_raw:
        located = _reject_rows(con, paths, first, has_header=header_file is None)
        raise SpecError("ragged_rows", (located or []) + [{
            "problem": "rows were dropped between the file and the scan",
            "data_lines": physical, "records_parsed": int(n_raw),
            "dropped": int(physical - n_raw), "expected_fields": len(first),
            "files": [os.path.basename(p) for p in paths],
            "note": "A row is dropped when its field count differs from the header. Nothing "
                    "is padded and nothing is truncated: a shifted column would otherwise "
                    "load as data."}])
    if not n_raw:
        raise SpecError("no_rows", [{"files": [os.path.basename(p) for p in paths]}])

    # A code outside its published domain is refused, never nulled. An unrecognised
    # action_taken decides which population a record belongs to, so silently dropping it
    # moves the record between the numerator and the denominator of every rate the scan
    # reports.
    counts = count_domain_violations(con, conv)
    if counts:
        raise SpecError("value_outside_published_domain",
                        locate_domain_violations(con, conv, sorted(counts))
                        + [{"totals_by_field": counts}])

    leis, years, n_keys = con.execute(
        f"SELECT list_sort(array_agg(DISTINCT lei)), "
        f"list_sort(array_agg(DISTINCT activity_year)), count(DISTINCT record_key) "
        f"FROM {conv}").fetchone()
    leis, years = list(leis or []), list(years or [])
    # ONE filer and ONE year, or refuse. A scan identifier is a pure function of
    # (filer, year, spec, snapshot); a snapshot holding two filers or two years makes
    # that function ambiguous, and the second scan of the tuple would return the first
    # scan's answer. The condition is OR, not AND: either kind of mixing breaks it.
    if len(leis) != 1 or len(years) != 1:
        raise SpecError("snapshot_is_not_one_filer_year", [{
            "leis": [str(x) for x in leis[:10]], "years": [str(x) for x in years[:10]],
            "problem": "a scan is a pure function of filer, year, spec and snapshot",
            "remedy": "Split the file, or load one filer-year at a time."}])
    dupes = int(n_raw) - int(n_keys)

    gran = check_granularity(con, conv, snapshot)
    nc = nonconforming(gran)
    # The one refusal with an override, because there is a legitimate reason to load
    # internal data: a filer testing the product against its own records. The override is
    # explicit (--internal-data), and the snapshot it produces is stamped non-public, so
    # every screen built on it says which record it is looking at.
    if nc and not allow_nonconforming:
        raise SpecError("data_is_not_at_publication_granularity", nc + [{
            "why_this_matters":
                "Likewise compares two applications only where the public record has "
                "already coarsened the fields materiality is judged on, and the resolution "
                "budget is derived from that coarsening. Data at full internal precision "
                "breaks the derivation: every screen would state a bin width the values do "
                "not have, and margins below the stated floor would read as findings.",
            "remedy": "Load the filing as the regulator publishes it. If you mean to load "
                      "internal, un-coarsened data, pass --internal-data: the snapshot is "
                      "then stamped as non-public and every scan on it says so."}])

    causes = {}
    if nas:
        causes["na"] = int(nas)
    if exempt:
        causes["exempt"] = int(exempt)

    # Duplicate record_key means a byte-identical source row, so DISTINCT over the
    # projected columns is the same set as keeping the first of each key -- and DuckDB
    # can spill a hash aggregate, where a window function over one partition cannot.
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cols = ", ".join(_q(c) for c in COLUMNS)
    con.execute(f"COPY (SELECT DISTINCT {cols} FROM {conv}) "
                f"TO {_lit(out_path)} (FORMAT PARQUET)")

    n_rows = int(n_keys)

    report = {"lei": leis[0], "activity_year": int(years[0]), "layout": layout,
              "rows_written": int(n_rows), "duplicates_dropped": int(dupes),
              "normalisation_causes": causes, "granularity_report": gran,
              "granularity_conforming": not nc,
              "files": [{"file": os.path.basename(p), "layout": layout} for p in paths],
              "parquet": out_path}
    if own:
        con.close()
    return report


def _causes(con) -> dict:
    exempt, nas = con.execute(
        "SELECT coalesce(sum(_cause_exempt), 0), coalesce(sum(_cause_na), 0) "
        "FROM _lw_raw").fetchone()
    out = {}
    if nas:
        out["na"] = int(nas)
    if exempt:
        out["exempt"] = int(exempt)
    return out


# --------------------------------------------------------------------------
# the curated tree
# --------------------------------------------------------------------------
# The manifest is what every later screen reads to say where the data came from and what
# is wrong with it -- the granularity report, the duplicate count, the non-public stamp.
# It is written beside the Parquet rather than into it so it can be read without opening
# the data, and it carries a content hash of the file it describes.
def write_manifest(report: dict, snapshot_id: str, out_root: str | None = None,
                   extra: dict | None = None) -> dict:
    # Resolved at call time, not at import: the curated root differs between a
    # checkout and a container, and a default bound at import freezes the wrong one.
    out_root = out_root or _paths.curated_root()
    man = dict(extra or {})
    man.update(snapshot_id=snapshot_id, lei=report["lei"],
               activity_year=report["activity_year"], layout=report["layout"],
               source_files=report["files"], rows_written=report["rows_written"],
               duplicates_dropped=report["duplicates_dropped"],
               normalisation_causes=report["normalisation_causes"],
               granularity_report=report["granularity_report"],
               granularity_conforming=report["granularity_conforming"],
               parquet=report["parquet"],
               content_hash="sha256:" + hashlib.sha256(
                   open(report["parquet"], "rb").read()).hexdigest())
    path = f"{out_root}/snapshot={snapshot_id}/manifest.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(man, fh, indent=2, sort_keys=True)
    return {"manifest": path, "content_hash": man["content_hash"]}


def parquet_path(snapshot_id: str, lei: str, year: int,
                 out_root: str | None = None) -> str:
    out_root = out_root or _paths.curated_root()
    return f"{out_root}/snapshot={snapshot_id}/activity_year={year}/lei={lei}/data.parquet"


def load(paths: list[str], snapshot: dict, snapshot_id: str,
         out_root: str | None = None, allow_nonconforming: bool = False,
         header_file: str | None = None) -> dict:
    """Load into the curated tree. The destination depends on the filer and year, which
    are only known after the file has been read, so the conversion writes to a scratch
    path first and the result is moved into place once the snapshot identity is settled.
    """
    # mkstemp then unlink: what is wanted is a name no other process will take, not a
    # file -- the COPY below creates the Parquet itself.
    fd, tmp = tempfile.mkstemp(suffix=".parquet")
    os.close(fd)
    os.unlink(tmp)
    # The finally clause is the reason for the try: a refused load must not leave a
    # scratch Parquet in the system temp directory, and the refusals above raise from
    # inside load_to_parquet.
    try:
        rep = load_to_parquet(paths, snapshot, tmp, allow_nonconforming, header_file)
        dest = parquet_path(snapshot_id, rep["lei"], rep["activity_year"], out_root)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.replace(tmp, dest)
        rep["parquet"] = dest
        return rep
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
