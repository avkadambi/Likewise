"""Internal record schema. Normalisation to this schema is the only place
source drift can fail, and census tract is dropped here so no downstream code can emit it.

This module owns the column list, the column types, the sentinel vocabulary and the
single-value normalisation rule. It owns no I/O and no policy: it does not read files,
does not decide which fields are compared or matched on -- that is the versioned
specification -- and does not enforce the protected-class rule it names. It only states
the set; a test and the specification loader do the enforcing.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Sentinel vocabulary
# ---------------------------------------------------------------------------
# HMDA sentinels for non-reported values. These arrive as STRINGS, not nulls.
# "Exempt" == "Exempt" passes an exact-match test, which is the defect this closes.
EXEMPT_SENTINELS = {"Exempt", "exempt", "EXEMPT"}
NA_SENTINELS = {"NA", "N/A", "na", ""}
NUMERIC_SENTINELS = {1111, 8888, 9999, -1}

# ---------------------------------------------------------------------------
# Fields the product refuses to use
# ---------------------------------------------------------------------------
# Fields that may NEVER appear in a block key, a feature set, a ranker allow-list,
# or a finding schema. This is the protected-class guard; enforced by a test.
# The set is named here rather than at each use site so there is one list to review,
# and so adding a field to it takes effect everywhere at once.
PROTECTED_CLASS_FIELDS = {
    "derived_race", "derived_ethnicity", "derived_sex", "applicant_age",
    "applicant_race_1", "applicant_ethnicity_1", "applicant_sex",
    "co_applicant_race_1", "co_applicant_ethnicity_1", "co_applicant_sex",
    "tract_minority_population_percent", "tract_to_msa_income_percentage",
}

# Geography finer than the disclosure ceiling. Dropped at ingest.
DROPPED_AT_INGEST = {"census_tract", "tract_population", "tract_owner_occupied_units"}

# ---------------------------------------------------------------------------
# The internal schema
# ---------------------------------------------------------------------------
# Declaration order is meaningful: COLUMNS is derived from it, and the loader writes its
# Parquet columns in that order. The groupings below say what each field is FOR, which is
# the question a reader has when deciding whether a new column belongs here at all.
INTERNAL_SCHEMA = {
    # identity / partition
    "record_key":                       "VARCHAR",
    "lei":                              "VARCHAR",
    "activity_year":                    "INTEGER",
    # outcome
    "action_taken":                     "INTEGER",
    "denial_reason_1":                  "INTEGER",
    "denial_reason_2":                  "INTEGER",
    "denial_reason_3":                  "INTEGER",
    "denial_reason_4":                  "INTEGER",
    # exact-match / blocking dimensions
    "loan_purpose":                     "INTEGER",
    "occupancy_type":                   "INTEGER",
    "lien_status":                      "INTEGER",
    "loan_type":                        "INTEGER",
    "county_code":                      "VARCHAR",
    "aus_1":                            "INTEGER",
    "construction_method":              "INTEGER",
    "total_units":                      "INTEGER",
    "submission_of_application":        "INTEGER",
    "initially_payable_to_institution": "INTEGER",
    "conforming_loan_limit":            "VARCHAR",
    "amortization":                     "INTEGER",
    "interest_only_payment":            "INTEGER",
    "balloon_payment":                  "INTEGER",
    "negative_amortization":            "INTEGER",
    "has_co_applicant":                 "INTEGER",
    # continuous
    "loan_amount":                      "DOUBLE",
    "income":                           "DOUBLE",
    "property_value":                   "DOUBLE",
    "combined_loan_to_value_ratio":     "DOUBLE",
    "debt_to_income_ratio":             "DOUBLE",
    # population filters
    "open_end_line_of_credit":          "INTEGER",
    "reverse_mortgage":                 "INTEGER",
    "business_or_commercial_purpose":   "INTEGER",
}

NUMERIC_FIELDS = {k for k, v in INTERNAL_SCHEMA.items() if v in ("DOUBLE", "INTEGER")}
COLUMNS = list(INTERNAL_SCHEMA)


# ---------------------------------------------------------------------------
# Single-value normalisation
# ---------------------------------------------------------------------------
def normalise_value(field: str, value):
    """Map HMDA sentinels to None.

    Returns (value, cause) where cause is None | 'exempt' | 'na'.

    The cause is returned rather than discarded because an EGRRCPA partial exemption and
    a genuinely absent value are different populations, and the load summary reports them
    against different denominators.
    """
    if value is None:
        return None, "na"
    if isinstance(value, str):
        s = value.strip()
        if s in EXEMPT_SENTINELS:
            return None, "exempt"
        if s in NA_SENTINELS:
            return None, "na"
        # A numeric field arriving as text is parsed and then re-entered, so a numeric
        # sentinel spelled as a string ("9999") is caught by the same rule as one that
        # arrived as a number. A value that will not parse is absent, not zero.
        if field in NUMERIC_FIELDS:
            try:
                v = float(s)
            except ValueError:
                return None, "na"
            return normalise_value(field, v)
        return s, None
    # total_units is the exception: 1111 is a genuine unit count in that field, so
    # applying the shared sentinel set to it would delete real data.
    if field in NUMERIC_FIELDS and isinstance(value, (int, float)):
        if int(value) in NUMERIC_SENTINELS and field not in ("total_units",):
            return None, "na"
    return value, None
