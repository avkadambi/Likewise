"""Specification validation and the startup gate."""
import json, pathlib, tempfile, yaml, pytest
from likewise import specs
from likewise.errors import SpecError

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _spec_dir_with(mutate, version: str = specs.IN_FORCE) -> str:
    """A copy of specs/ with one version deliberately broken.

    It mutates the version IN FORCE by default. It used to mutate 1.0.0 unconditionally
    and rely on load()'s default landing on the same file; when that default moved, every
    one of these tests kept passing a valid specification to the gate and asserting that
    it raised. They failed loudly, which is the only reason this is a note and not a
    silent hole -- but the lesson is that the version under test has to be named.
    """
    tmp = tempfile.mkdtemp()
    dst = pathlib.Path(tmp)
    for sub in ("materiality", "reasons", "budget", "snapshots"):
        (dst / sub).mkdir(parents=True)
        for f in (ROOT / "specs" / sub).iterdir():
            (dst / sub / f.name).write_bytes(f.read_bytes())
    mpath = dst / "materiality" / f"{version}.yaml"
    m = yaml.safe_load(mpath.read_text())
    bpath = dst / "budget" / f"{m['budget']}.json"
    b = json.loads(bpath.read_text())
    mutate(m, b)
    mpath.write_text(yaml.safe_dump(m))
    bpath.write_text(json.dumps(b))
    return str(dst)


def test_valid_spec_loads(spec):
    assert spec.version == specs.IN_FORCE
    assert spec.digests["materiality"].startswith("sha256:")


def test_gate_reports_thresholds(spec):
    r = spec.gate_report
    assert r["combined_loan_to_value_ratio"]["decisive_threshold"] >= \
        r["combined_loan_to_value_ratio"]["comparability_floor"]
    # The irreducible publication floor is what makes a sub-pp CLTV claim impossible.
    assert r["combined_loan_to_value_ratio"]["publication_floor"] > 2.0


def test_gate_rejects_threshold_below_floor():
    """A fixture that deliberately violates the rule and asserts that the gate fails.
    A gate never observed failing is a gate nobody has tested."""
    d = _spec_dir_with(lambda m, b: b["dimensions"]["combined_loan_to_value_ratio"]
                       .update({"decisive_threshold": 0.4}))
    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=d)
    assert e.value.kind == "startup_gate_failed"
    assert e.value.failures[0]["gate"] == "decisive_threshold_below_floor"


def test_rule3_tolerance_must_exceed_granularity():
    d = _spec_dir_with(lambda m, b: m["residual_risk"]["debt_to_income_ratio"]
                       .update({"tolerance": 0.5}))
    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=d)
    assert any(f.get("rule") == 3 for f in e.value.failures)


def test_rule4_blocking_key_subset():
    def mut(m, b):
        m["blocking"]["key"].append("debt_to_income_ratio")
    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(mut))
    assert any(f.get("rule") == 4 for f in e.value.failures)


def test_rule5_band_floor_must_cover_matcher():
    """Blocking must not drop a pair the matcher accepts -- the hole was concentrated
    at low incomes, which is where findings concentrate."""
    def mut(m, b):
        m["blocking"]["band"]["income"]["min_absolute"] = 500
    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(mut))
    assert any(f.get("rule") == 5 for f in e.value.failures)


def test_rule6_k_min_floor():
    with pytest.raises(SpecError):
        specs.load(spec_dir=_spec_dir_with(lambda m, b: m["disclosure"].update({"k_min": 2})))


def test_protected_class_guard():
    """The protected-class exclusion is a standing constraint; an accidental
    introduction is not how it gets relaxed."""
    def mut(m, b):
        m["exact_match_required"].append("derived_race")
    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(mut))
    assert any(f.get("rule") == "1b" for f in e.value.failures)


def test_rule8_tested_dimension_may_not_be_matched_on():
    """Matching a dimension and then testing it are contradictory: the matcher forces
    the pair close on the field, and the test then asks whether they differ on it.
    Whatever survives is a difference the matcher already called immaterial.

    The design has said this since dominance was introduced. Nothing checked it, so it
    held only because the specification in force happened to satisfy it."""
    def in_key(m, b):
        m["blocking"]["key"].append("combined_loan_to_value_ratio")
        m["exact_match_required"].append("combined_loan_to_value_ratio")

    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(in_key))
    r8 = [f for f in e.value.failures if f.get("rule") == 8]
    assert r8, e.value.failures
    assert {f["where"] for f in r8} >= {"blocking.key", "exact_match_required"}
    assert "combined_loan_to_value_ratio" in r8[0]["fields"]


def test_rule8_covers_the_bands_not_just_the_key():
    """A banded tested dimension is matched within a window and then tested inside it --
    the same contradiction, quieter, because the band never appears in the key."""
    def banded(m, b):
        m["blocking"]["band"]["property_value"] = {"relative": 0.2, "min_absolute": 20000}

    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(banded))
    assert any(f.get("rule") == 8 and f["where"] == "blocking.band"
               for f in e.value.failures), e.value.failures


def test_rule9_residual_band_must_be_wider_than_its_own_tolerance():
    """Clause 4 asks whether the comparator is strictly better beyond tolerance on a
    residual dimension. Band the dimension at exactly that tolerance and every pair the
    clause could fire on is filtered out before it runs: live in the code, dead in
    effect. Rule 5 requires band >= tolerance for coverage; this requires strict, for
    power."""
    def flush(m, b):
        # Income is a residual-risk dimension carrying a direction, and its band is
        # deliberately wider than its tolerance. Close that gap and the clause is dead.
        m["blocking"]["band"]["income"]["relative"] = \
            m["residual_risk"]["income"]["tolerance"]

    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(flush))
    r9 = [f for f in e.value.failures if f.get("rule") == 9]
    assert r9, e.value.failures
    assert r9[0]["field"] == "income"


def test_the_shipped_specification_satisfies_the_new_rules():
    """Regression: every version in force loads. Rules 8 and 9 were added after the
    fact, and a rule that refuses the specification it was written against is a rule
    with the wrong threshold."""
    for v in ("1.0.0", "1.1.0", "1.2.0", "1.3.0"):
        s = specs.load(version=v)
        assert not (s.tested_dimensions & set(s.blocking_key))


def test_a_service_may_not_serve_an_unsigned_specification():
    """A default argument is not a decision.

    `load(spec_dir)` with no version silently served materiality 1.0.0 -- unsigned, with
    no `comparison` block -- so `multi_code_policy`, which the 1.4.0 rationale itself
    calls "a specification decision with a version and a rationale, not a tuning knob",
    was being supplied by a Python fallback in the engine.

    Historical versions must stay loadable: a decision has to be reproducible against the
    standard in force when it was made. It is SERVING one that is refused."""
    import os

    served = specs.load_in_force(str(ROOT / "specs"))
    assert served.version == specs.IN_FORCE
    assert str(served.raw["author"]).lower() != "unsigned"
    assert "comparison" in served.raw, "the served spec must declare its comparison policy"

    old = os.environ.get("LIKEWISE_SPEC_VERSION")
    os.environ["LIKEWISE_SPEC_VERSION"] = "1.0.0"
    try:
        with pytest.raises(SpecError) as e:
            specs.load_in_force(str(ROOT / "specs"))
        assert e.value.kind == "unsigned_specification_in_force"
    finally:
        if old is None:
            os.environ.pop("LIKEWISE_SPEC_VERSION", None)
        else:
            os.environ["LIKEWISE_SPEC_VERSION"] = old

    # replay is unaffected
    assert specs.load(spec_dir=str(ROOT / "specs"), version="1.0.0").version == "1.0.0"


def test_rule10_refuses_a_tolerance_that_switches_a_dimension_off():
    """A tolerance at or above a dimension's own span admits every case regardless of the
    dimension. That is not a looser standard, it is the dimension ceasing to participate
    -- a policy change with no version, no author and no rationale, effected by a number."""
    def vacuous(m, b):
        rng = b["dimensions"]["debt_to_income_ratio"].get("integer_range") or [36, 49]
        m["residual_risk"]["debt_to_income_ratio"]["tolerance"] = float(rng[1] - rng[0]) + 1

    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(vacuous))
    r10 = [f for f in e.value.failures if f.get("rule") == 10]
    assert r10, e.value.failures
    assert r10[0]["field"] == "debt_to_income_ratio"


def test_rule11_requires_a_banded_relative_tolerance_to_be_referenced_to_min():
    """Rule 5 compares band and tolerance as scalar coefficients. That is sound only when
    the tolerance is evaluated at the SMALLER of the two magnitudes; at 'max' or 'mean'
    the same coefficient buys a wider absolute window than the band, and blocking drops
    pairs the matcher accepts -- the loss rule 5 exists to prevent, reintroduced through
    the reference side. Nothing validated the reference before."""
    def shifted(m, b):
        m["residual_risk"]["income"]["reference"] = "max"

    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(shifted))
    assert any(f.get("rule") == 11 and f.get("field") == "income"
               for f in e.value.failures), e.value.failures

    def undeclared(m, b):
        m["residual_risk"]["income"].pop("reference", None)

    with pytest.raises(SpecError) as e:
        specs.load(spec_dir=_spec_dir_with(undeclared))
    assert any(f.get("rule") in (2, 11) for f in e.value.failures)


def test_no_entry_point_pins_a_historical_specification_version():
    """The defect this catches, stated plainly.

    `specs.load()` used to default to the literal string "1.0.0". Every caller that did
    not pass a version inherited it: the shared test fixture, `tools/run_scan.py`, and
    the service itself. 0.8.0 fixed the service and left the rest, so the product tested
    and scanned under materiality 1.0.0 while serving 1.4.0 -- three versions of moved
    control features, widened bands and per-pair thresholds apart. Nothing failed,
    because each artefact recorded the version it actually used; the versions simply
    disagreed, and no reader had both in front of them.

    A version default is a governance decision. This asserts there is exactly one, that
    it is `IN_FORCE`, and that no argument parser has quietly re-pinned an old one.
    """
    import inspect
    assert inspect.signature(specs.load).parameters["version"].default is None

    # The invariant is "no LITERAL version string as a default", not "spelled one of two
    # ways". `IN_FORCE` defers to the specification in force and `None` defers to the
    # loader, which does the same; a quoted "1.2.0" is the thing that goes stale.
    import re
    literal = re.compile(r'default\s*=\s*[\'"]\d+\.\d+\.\d+[\'"]')
    offenders = []
    for f in sorted((ROOT / "tools").glob("*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "version" in line and literal.search(line):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, "entry points pinning a historical version:\n" + "\n".join(offenders)


def test_the_service_and_the_command_line_agree_on_the_version():
    """Two ways in, one standard. `load_in_force` is what the API binds; the CLI default
    is what a scan run from the Makefile uses. If those ever diverge again, a finding
    served by the UI and a finding produced by `make scan` were made under different
    comparability standards while looking identical."""
    served = specs.load_in_force(str(ROOT / "specs")).version
    assert served == specs.IN_FORCE
    cli = (ROOT / "tools" / "run_scan.py").read_text()
    assert 'default=specs.IN_FORCE' in cli, "run_scan.py no longer defers to IN_FORCE"
