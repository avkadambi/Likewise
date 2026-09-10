"""Egress exclusivity and the disclosure boundary."""
import pathlib, pytest
from likewise.egress import Egress, content_hash

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_module_but_egress_builds_a_response_body():
    """A direct import of the raw finding dict into a handler is a CI failure."""
    api = ROOT / "likewise" / "api.py"
    if not api.exists():
        pytest.skip("api not present yet")
    src = api.read_text()
    assert "Egress(" in src or "egress" in src


FORBIDDEN_SQL = ("IS NOT DISTINCT FROM", "IFNULL(", "COALESCE(A.", "NULLS NOT DISTINCT")


def _executable_sql_text(path: pathlib.Path) -> str:
    """Return only the string literals a module would actually execute -- comments and
    docstrings stripped -- so the lint cannot be satisfied or tripped by prose."""
    import tokenize
    out = []
    with open(path, "rb") as fh:
        toks = list(tokenize.tokenize(fh.readline))
    prev_meaningful = None
    for t in toks:
        if t.type == tokenize.COMMENT:
            continue
        if t.type == tokenize.STRING:
            # a bare string as a statement is a docstring, not executable SQL
            if prev_meaningful in (None, tokenize.INDENT, tokenize.NEWLINE, tokenize.NL):
                continue
            out.append(t.string)
        if t.type not in (tokenize.NL, tokenize.COMMENT):
            prev_meaningful = t.type
    return "\n".join(out).upper()


def test_sql_lint_forbids_null_equating_constructs():
    """IS NOT DISTINCT FROM is forbidden UNCONDITIONALLY on exact-match
    dimensions -- not on a maintained list of EGRRCPA-susceptible ones, because such a
    list drifts. USING already delivers NULL rejection by SQL equality semantics; the
    rule is a guard against a future refactor by someone debugging 'why am I losing
    rows'. Enforced by lint over generated text, not by prose."""
    for p in (ROOT / "likewise").rglob("*.py"):
        body = _executable_sql_text(p)
        for bad in FORBIDDEN_SQL:
            assert bad not in body, f"{p.name} emits a NULL-equating construct: {bad}"
    for p in (ROOT / "likewise" / "sql").rglob("*.sql"):
        up = p.read_text().upper()
        for bad in FORBIDDEN_SQL:
            assert bad not in up, f"{p.name}: {bad}"


def test_lint_would_actually_catch_a_violation(tmp_path):
    """A lint never observed failing is a lint nobody has tested."""
    bad = tmp_path / "bad.py"
    bad.write_text('SQL = "SELECT * FROM a JOIN b ON a.x IS NOT DISTINCT FROM b.x"\n')
    assert "IS NOT DISTINCT FROM" in _executable_sql_text(bad)


def test_egress_rejects_forbidden_keys():
    e = Egress(b"k" * 32)
    with pytest.raises(AssertionError):
        e.summary({"lei": "549300X", "nested": {"census_tract": "12086001100"}})


def test_lei_mask_is_full_digest_not_truncated():
    """Six hex chars is 24 bits against ~4,782 filers: 0.68 expected colliding pairs,
    ~49% chance two institutions share a mask."""
    e = Egress(b"k" * 32)
    assert len(e.lei_masked("X").split("-", 1)[1]) == 64


def test_finding_id_excludes_scan_id_and_is_keyed():
    e = Egress(b"k" * 32)
    args = ("LEI1", 2025, {"m": "d"}, "snap", "img", "K1", "K2")
    e2 = Egress(b"j" * 32)
    assert e.finding_id(*args) == e.finding_id(*args)          # stable across reruns
    assert e.finding_id(*args) != e2.finding_id(*args)         # keyed, not an oracle


def test_content_hash_is_order_independent_and_precision_bounded():
    a = [{"x": 1.0000001}, {"y": 2.0}]
    b = [{"y": 2.0}, {"x": 1.0000002}]
    assert content_hash(a) == content_hash(b)


def test_no_module_hardcodes_a_data_path():
    """paths.py exists because the answer differs between a checkout and a container:
    the code is read-only at /app while everything mutable is a volume at /data. A
    hardcoded "data/curated" works in exactly one of those, and the failure is silent --
    the UI lists zero snapshots rather than raising. Enforced by lint, like the SQL rule,
    because a convention nobody checks is a convention that drifts."""
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for f in sorted((root / "likewise").rglob("*.py")):
        if f.name == "paths.py":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r'["\']\.?/?data/(curated|store|inbox)', code):
                offenders.append(f"{f.relative_to(root)}:{i}: {line.strip()}")
    assert not offenders, (
        "mutable paths must resolve through likewise/paths.py:\n  " + "\n  ".join(offenders))


def test_container_relocation_moves_every_mutable_root(monkeypatch, tmp_path):
    """Setting LIKEWISE_DATA alone must move the store, the curated root, the inbox and
    every derived glob. The container sets exactly that one variable."""
    from likewise import paths
    monkeypatch.setenv("LIKEWISE_DATA", str(tmp_path))
    for name in ("LIKEWISE_CURATED", "LIKEWISE_INBOX", "LIKEWISE_STORE"):
        monkeypatch.delenv(name, raising=False)

    assert paths.curated_root().startswith(str(tmp_path))
    assert paths.store_root().startswith(str(tmp_path))
    assert paths.inbox().startswith(str(tmp_path))
    assert paths.parquet_glob("snap", 2024, "LEI").startswith(str(tmp_path))
    assert paths.manifest_path("snap").startswith(str(tmp_path))


def test_mutation_catalogue_is_reviewable():
    """The catalogue is PUBLISHED, which is the whole basis for trusting the kill rate.
    A published catalogue with silent duplicates is not reviewable: six entries were
    listed twice, so both the numerator and the denominator counted them twice and the
    printed rate described a different experiment from the one in the file.

    Also asserts every entry still applies. A mutant whose pattern has drifted out of
    the source is scored as inapplicable, which quietly shrinks the gate."""
    import collections, pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from mutants import CATALOGUE

    ids = [m[0] for m in CATALOGUE]
    dupes = {k: n for k, n in collections.Counter(ids).items() if n > 1}
    assert not dupes, f"duplicate catalogue ids: {dupes}"

    root = pathlib.Path(__file__).resolve().parents[1]
    missing = [(m[0], m[1]) for m in CATALOGUE
               if m[2] not in (root / m[1]).read_text()]
    assert not missing, f"catalogue entries no longer present in the source: {missing}"

    assert len(CATALOGUE) >= 40, "the gate is only as wide as the catalogue"
