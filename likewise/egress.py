"""The sole serialisation boundary.

All external serialisation of Finding, Summary, ControlResult or NullSummary MUST pass
through here. No other module may construct a response body, an export file, or a log
line containing these types. Enforced by contract test, not by convention: the rule cannot
be held by four contributors agreeing to be careful.

This module owns three transformations and nothing else: identifiers become keyed
pseudonyms, published financial values become disclosure bands, and margins are coarsened
to whole multiples of their own threshold. It owns no storage, no routing and no
statistics -- it never decides WHETHER a finding is served, only what a served finding is
allowed to say. Everything downstream of this module (the API, the web view, exports)
sees only what these functions returned.
"""
from __future__ import annotations
import hashlib, hmac, json, math
from typing import Any

# ---------------------------------------------------------------------------
# The leak vocabulary
# ---------------------------------------------------------------------------
# Fields that must never reach a response body.
# Two kinds of key are listed together: identifiers that would let a recipient join a
# finding back to a public row (lei, record_key, approved_key, denied_key), and the
# protected-class and fine-geography attributes the product refuses to carry at all.
# The check is by NAME, which is cheap and total; it cannot see an identifier hiding
# inside a number, which is why the numeric coarsening below exists as well.
FORBIDDEN_KEYS = {
    "lei", "census_tract", "tract_population", "record_key", "approved_key", "denied_key",
    "derived_race", "derived_ethnicity", "derived_sex", "applicant_age",
}


# ---------------------------------------------------------------------------
# Numeric coarsening
# ---------------------------------------------------------------------------
# A number can be an identifier. An unrounded margin on a dimension published to three
# decimal places is very nearly a unique key for the pair that produced it, so both
# helpers truncate towards zero onto a grid of the pair's own threshold. Truncation
# rather than rounding keeps the reported figure on the conservative side of the
# threshold that decided the finding.
def _bucket_ratio(r) -> float | None:
    """Margin ratio to whole multiples of its own threshold."""
    if r is None:
        return None
    return float(int(r))


def _bucket_margin(m, threshold) -> float | None:
    """Margin to whole multiples of the pair's decisive threshold."""
    # A threshold of zero or None gives no grid to bucket onto, so the margin is dropped
    # rather than published unbucketed -- withholding a value is recoverable, publishing
    # a near-unique one is not.
    if m is None or threshold in (None, 0):
        return None
    import math as _m
    # NaN and the infinities have no bucket; they arrive from a division upstream and
    # would serialise as JSON this product does not want to emit.
    if not _m.isfinite(m):
        return None
    # Magnitude bucketed, sign restored afterwards: bucketing the signed value would
    # round the two directions towards different neighbours and make an approved-worse
    # margin and a denied-worse margin of the same size print differently.
    return round(int(abs(m) / threshold) * threshold * (1 if m >= 0 else -1), 6)


# ---------------------------------------------------------------------------
# The boundary itself
# ---------------------------------------------------------------------------
class Egress:
    def __init__(self, key: bytes, key_version: int = 1):
        # A short key makes every pseudonym below cheap to brute-force against an
        # enumerable panel of filers, which would defeat the whole class. Refused at
        # construction, so a weak key cannot be discovered after a run has published.
        if len(key) < 32:
            raise ValueError("pseudonym key must be >= 32 bytes")
        self._key = key
        self.key_version = key_version

    # -- keyed identifiers ---------------------------------------------------
    # Keyed, not merely hashed. An unkeyed digest over a public value is an offline
    # confirmation oracle: the filer panel is published and enumerable, so anyone can
    # hash every candidate and look for a match. The HMAC makes that impossible without
    # the key, and the domain prefix ("lei", "rec", "fnd") keeps the three identifier
    # spaces from colliding with each other.
    def _mac(self, *parts: Any) -> str:
        # The parts are separated, not concatenated, so ("ab", "c") and ("a", "bc")
        # cannot produce the same message and therefore the same pseudonym.
        msg = "\x1f".join(str(p) for p in parts).encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def lei_masked(self, lei: str) -> str:
        """Full digest, not truncated. Six hex characters is 24 bits against a panel of
        ~4,782 filers: 0.68 expected colliding pairs, ~49% chance two institutions share
        a mask. That is a mis-attribution defect before it is a privacy one."""
        return "LEI-" + self._mac("lei", lei)

    def record_ref(self, record_key: str) -> str:
        """Keyed, so it is not a public-file row index. The operator resolves it locally
        against their own curated copy; a third-party recipient cannot."""
        return "rec_" + self._mac("rec", record_key)[:16]

    def finding_id(self, lei: str, year: int, spec_digests: dict, snapshot_id: str,
                   image_digest: str, key_lo: str, key_hi: str) -> str:
        """KEYED. An unkeyed digest over inputs of which everything except the LEI is
        published on the finding itself makes each finding an offline confirmation
        oracle across an enumerable panel. scan_id is deliberately NOT an input, so the
        identifier is stable across reruns of the same scan."""
        return "fnd_" + self._mac("fnd", lei, year, json.dumps(spec_digests, sort_keys=True),
                                  snapshot_id, image_digest, key_lo, key_hi)[:32]

    # -- banding -------------------------------------------------------------
    # Every published financial value leaves as the band it falls in, never as the
    # figure. The band widths come from the specification's disclosure section, so
    # widening or narrowing them is a versioned change with a written rationale rather
    # than an edit here.
    @staticmethod
    def band(value: float | None, width: float, unit: str = "") -> str | None:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        # floor, so a value sits in the band that CONTAINS it. Rounding to the nearest
        # boundary would move a value across a band edge and make two figures on
        # opposite sides of a cut print as the same band.
        lo = math.floor(value / width) * width
        hi = lo + width
        if unit == "usd":
            return f"{int(lo/1000)}k-{int(hi/1000)}k"
        return f"{lo:g}-{hi:g}"

    # -- the boundary --------------------------------------------------------
    # The three methods below are the only way a Finding, a Summary or a scan record
    # becomes something outside the process may see. Each ends with _assert_clean, so a
    # field added to an internal record cannot ride out on the next release unless
    # somebody names it here.
    def finding(self, f: dict, spec) -> dict:
        b = spec.raw["disclosure"]["bands"]
        # The output is BUILT, key by key, rather than copied and pruned. A copy-then-
        # delete boundary leaks whatever the internal record grew since the deletions
        # were written; an allow-list fails the other way, by omitting something new.
        fid = f.get("finding_id") or self.finding_id(
            f["lei"], f.get("activity_year", 0), f["spec_digests"], f["snapshot_id"],
            f.get("image_digest", "sha256:dev"), f["key_lo"], f["key_hi"])
        out = {
            "finding_id": fid,
            "scan_id": f["scan_id"],
            "rank": f["rank"],
            "evidentiary_status": "screening_hypothesis",
            "analysis_status": f.get("analysis_status", "confirmatory"),
            "reason_outcome": f["reason_outcome"],
            "stated_reason_codes": f["stated_reason_codes"],
            "record_ref": {"approved": self.record_ref(f["approved_key"]),
                           "denied": self.record_ref(f["denied_key"])},
            "rank_in_cell": f["rank_in_cell"],
            "cell_size": f["cell_size"],
            "cell_power": f["cell_power"],
            "rank_p_value": f["rank_p_value"],
            # No q-value. Per-finding significance is not claimed, and a
            # field that could carry one invites a reader to supply the claim itself.
            "gamma_star": f.get("gamma_star"),
            "min_attainable_p": f.get("min_attainable_p"),
            "geo_level": f.get("geo_level"),
            "significance": "none_attached_see_scan_level_test",
            # Margins are bucketed to whole multiples of the pair's own threshold. An
            # unrounded margin on a dimension published to three decimals is very nearly
            # a unique key for the pair: a five-hundred-record cell has about 250,000
            # ordered pairs against roughly 200,000 grid points. The forbidden-key check
            # reads field NAMES and cannot see an identifier hiding in a number.
            "margin_ratio": _bucket_ratio(f["margin_ratio"]),
            "informative_dimension_count": f["informative_dimension_count"],
            "block_degree": f["block_degree"],
            "k_cohort": f["k_cohort"],
            "tested": [{**t, "margin": _bucket_margin(t.get("margin"),
                                                      t.get("decisive_threshold"))}
                       for t in f["tested"]],
            "bands": {
                "income": self.band(f["a_income"], b["income"], "usd"),
                "property_value": self.band(f["a_property_value"], b["property_value"], "usd"),
                "combined_loan_to_value_ratio": self.band(
                    f["a_combined_loan_to_value_ratio"], b["combined_loan_to_value_ratio"]),
                "loan_amount": self.band(f["a_loan_amount"], b["loan_amount"], "usd"),
            },
            "county_code": f["county_code"],          # geography ceiling; tract dropped at ingest
            "spec_digests": f["spec_digests"],
            "snapshot_id": f["snapshot_id"],
            "pseudonym_key_version": self.key_version,
        }
        _assert_clean(out)
        return out

    # A summary and a scan record are aggregates, so they are copied rather than rebuilt
    # -- but the filer identifier is replaced by its mask in the same step, and the key
    # is popped rather than overwritten so the raw value cannot survive in the copy.
    def summary(self, s: dict) -> dict:
        out = dict(s)
        if "lei" in out:
            out["lei_masked"] = self.lei_masked(out.pop("lei"))
        _assert_clean(out)
        return out

    def scan_record(self, r: dict) -> dict:
        out = dict(r)
        if "lei" in out:
            out["lei_masked"] = self.lei_masked(out.pop("lei"))
        _assert_clean(out)
        return out


# ---------------------------------------------------------------------------
# The leak guard
# ---------------------------------------------------------------------------
def _assert_clean(obj: Any, path: str = "$") -> None:
    """Structural guarantee, checked at runtime as well as in the contract test.

    Recursive, because a forbidden key nested inside a dictionary that was copied
    wholesale is exactly the case a top-level check misses. It raises rather than
    redacting: a response that silently drops a field looks like a working response, and
    the defect that put the field there survives to the next release. The reported path
    names where the key was found, so the raiser does not have to search for it.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                raise AssertionError(f"egress leak: forbidden key {k!r} at {path}")
            _assert_clean(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _assert_clean(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# Content identity
# ---------------------------------------------------------------------------
def content_hash(rows: list[dict], precision: int = 6) -> str:
    """Content identity, not byte identity. Parquet byte-identity
    additionally requires pinned writer and codec versions and single-threaded writes,
    and is broken by design across deployments because the pseudonym key differs.

    A deterministic wrong answer reproduces perfectly. This is a reproducibility
    property, not a quality result.
    """
    def norm(v):
        if isinstance(v, float):
            return f"{round(v, precision):.{precision}f}"
        if isinstance(v, dict):
            return {k: norm(v[k]) for k in sorted(v)}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v
    # Rows are sorted after canonicalisation, so the hash does not depend on the order
    # the scan happened to emit them in -- the point of comparison is the SET of
    # findings. Floats are formatted to a fixed number of decimals first, so two runs
    # that agree to that precision hash the same and the comparison is not decided by the
    # last bits of a double.
    canon = sorted(json.dumps(norm(r), sort_keys=True) for r in rows)
    h = hashlib.sha256()
    for line in canon:
        h.update(line.encode()); h.update(b"\n")
    return "sha256:" + h.hexdigest()
