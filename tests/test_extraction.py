"""Extraction: what a model is allowed to say, and what it must stay silent about.

Every test here runs with no torch, no transformers and no network. That is a design
requirement, not a convenience: a calibration rule whose tests need a 400 MB download is
a rule nobody re-runs, and the abstention path is the only thing standing between a
model's guess and a precedent that binds on it.
"""
import copy
import json
import pathlib
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extract import backbones
from extract import spec as espec
from extract.abstain import (AGGREGATIONS, Calibration, fit_temperature,
                             floor_for_precision, span_confidence, temperature_scale)
from extract.backends import DeterministicBackend
from extract.contract import (ABSENT, ABSTAINED, OBSERVED, SILENT, ExtractedRecord,
                              FieldValue, Span, coverage)
from extract.runner import extract_many, extract_one


@pytest.fixture
def cal():
    return Calibration(corpus_id="fixture", temperature=1.0, aggregation="min",
                       floors={"a": 0.2, "b": 0.9, "c": 0.5},
                       target_precision=0.98, fitted_n=100)


@pytest.fixture
def xspec():
    return espec.load(str(ROOT / "specs"))


# --- the separation the whole design rests on -------------------------------
def test_the_engine_never_imports_a_model_runtime():
    """`likewise/` runs on five wheels totalling about 25 MB. torch is 555 MB before a
    checkpoint. The served container is rootless, read-only and makes no outbound calls,
    and none of that survives a torch import -- so extraction is a pipeline stage, and
    this asserts the boundary rather than trusting it."""
    banned = ("torch", "transformers", "tokenizers", "safetensors", "numpy", "scipy")
    offenders = []
    for f in sorted((ROOT / "likewise").rglob("*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            s = line.strip()
            if not (s.startswith("import ") or s.startswith("from ")):
                continue
            mod = s.split()[1].split(".")[0]
            if mod in banned:
                offenders.append(f"{f.relative_to(ROOT)}:{i}: {s}")
    assert not offenders, "the engine imports a model runtime:\n" + "\n".join(offenders)


def test_importing_extract_does_not_pull_torch():
    """The package must be importable, and testable, on a machine with no model on it."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import extract; "
         "print('torch' in sys.modules or 'transformers' in sys.modules)" % str(ROOT)],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False", out.stdout


# --- silence is the safety property -----------------------------------------
def test_a_silent_field_may_not_carry_a_value():
    """An abstention that keeps its best guess is not an abstention. It is a guess one
    refactor away from being read."""
    for status in sorted(SILENT):
        with pytest.raises(ValueError, match="must not carry a value"):
            FieldValue(name="a", status=status, value=42.0)


def test_abstained_and_absent_are_identical_to_the_engine(cal, xspec):
    """Both reach the engine as a null, and a null on a premise dimension is UNRECORDED,
    which outranks distinguishing and breaks the bind. That is the point."""
    r = extract_one("doc", "k", ["a", "b", "c"],
                    DeterministicBackend(seed="s", silent_fields=["c"]), xspec, cal)
    eng = r.to_engine_record()
    statuses = {f.name: f.status for f in r.fields}
    for name, st in statuses.items():
        if st in SILENT:
            assert eng[name] is None


def test_abstained_and_absent_stay_distinct_in_the_audit(cal, xspec):
    """Different facts about the world. "The model could not read this" is a defect in
    the instrument; "the filing does not mention it" is a property of the filing.
    Collapsed, the extractor's own miss rate becomes unmeasurable against true
    absences."""
    r = extract_one("doc", "k", ["a", "b", "c"],
                    DeterministicBackend(seed="s", silent_fields=["c"]), xspec, cal)
    st = {f["name"]: f["status"] for f in r.audit()["fields"]}
    assert st["c"] == ABSENT
    assert set(st.values()) - {ABSENT}, "fixture produced no non-absent field"
    # An absent field has no confidence at all; an abstention has one, below its floor.
    absent = r.by_name("c")
    assert absent.confidence is None
    for f in r.fields:
        if f.status == ABSTAINED:
            assert f.confidence is not None and f.confidence < f.floor
        if f.status == OBSERVED:
            assert f.confidence >= f.floor


def test_coverage_reports_the_number_that_matters(cal, xspec):
    """A field that abstains on most of a corpus is not a field the extractor supports,
    whatever its accuracy on the rest."""
    docs = {f"k{i}": f"document number {i}" for i in range(20)}
    recs = extract_many(docs, ["a", "b", "c"],
                        DeterministicBackend(seed="s", silent_fields=["c"]), xspec, cal)
    cov = coverage(recs)
    assert cov["c"][ABSENT] == 20
    assert sum(cov["b"].values()) == 20


# --- the floor ---------------------------------------------------------------
def test_a_floor_of_zero_is_refused_not_clamped():
    """Zero is not a lenient threshold, it is the absence of one: every reading would be
    asserted and the abstention path would be unreachable."""
    with pytest.raises(ValueError, match="abstention unreachable"):
        Calibration("c", 1.0, "min", {"a": 0.0}, 0.98, 10)


def test_an_uncalibrated_field_gets_no_default(cal):
    """A borrowed threshold is the failure this class of system is most prone to."""
    with pytest.raises(KeyError, match="no floor calibrated"):
        cal.floor_for("never_fitted")


def test_extraction_refuses_without_a_calibration(xspec):
    with pytest.raises(RuntimeError, match="no calibration"):
        extract_one("doc", "k", ["a"], DeterministicBackend(), xspec, None)


def test_the_floor_chosen_is_the_most_permissive_that_meets_the_target():
    """Among thresholds satisfying the precision constraint, the one keeping most recall.
    Anything higher buys precision the constraint did not ask for, at the cost of
    coverage the corpus cannot spare."""
    scored = [(0.95, True), (0.9, True), (0.8, True), (0.7, False), (0.3, False)]
    floor, prec, rec = floor_for_precision(scored, 1.0)
    assert floor == 0.8 and prec == 1.0 and rec == 1.0
    lower, p2, r2 = floor_for_precision(scored, 0.6)
    assert lower < floor and p2 >= 0.6 and r2 >= rec


def test_an_unreachable_target_returns_its_achieved_precision():
    """It does not round up. The caller is expected to drop the field, and
    tools/calibrate_extractor.py exits non-zero rather than lowering the bar."""
    scored = [(0.9, False), (0.8, True), (0.4, False)]
    floor, prec, _ = floor_for_precision(scored, 0.99)
    assert prec < 0.99
    assert floor == 0.9


# --- confidence --------------------------------------------------------------
def test_temperature_one_is_the_identity_and_higher_flattens():
    logits = [3.0, 1.0, 0.0]
    p1 = temperature_scale(logits, 1.0)
    p5 = temperature_scale(logits, 5.0)
    assert pytest.approx(sum(p1)) == 1.0 and pytest.approx(sum(p5)) == 1.0
    assert max(p5) < max(p1)                     # flatter
    assert p1 == sorted(p1, reverse=True)        # order preserved
    assert p5 == sorted(p5, reverse=True)


def test_temperature_must_be_positive():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError, match="positive"):
            temperature_scale([1.0, 2.0], bad)


def test_span_confidence_defaults_to_the_weakest_link():
    """A span is only as identified as its least certain token. A mean lets one confident
    token carry three unreadable ones, and the measured finding is that span-restricted
    probability is the more robust signal under domain shift."""
    probs = [0.99, 0.99, 0.35]
    assert span_confidence(probs) == 0.35
    assert span_confidence(probs, "mean") > 0.35
    assert span_confidence(probs, "product") < 0.35


def test_span_confidence_rejects_a_non_probability():
    with pytest.raises(ValueError, match="not a probability"):
        span_confidence([0.5, 1.4])


def test_fitted_temperature_beats_the_unfitted_one_on_nll():
    import math
    rows = [[4.0, 0.0]] * 30 + [[0.0, 4.0]] * 10      # deliberately overconfident
    labels = [0] * 30 + [1] * 10
    t = fit_temperature(rows, labels)

    def nll(temp):
        return -sum(math.log(max(temperature_scale(r, temp)[y], 1e-12))
                    for r, y in zip(rows, labels, strict=True)) / len(labels)

    assert nll(t) <= nll(1.0) + 1e-9


# --- the backbone set --------------------------------------------------------
def test_the_backbone_set_is_closed():
    with pytest.raises(KeyError, match="the set is closed"):
        backbones.get("some-model-someone-liked")


def test_every_modernbert_backbone_sets_add_prefix_space():
    """Measured, not stylistic: the ModernBERT tokenizer prepends whitespace on a plain
    call, which costs about 1.7 F1 on CoNLL -- 90.54 against 92.23. The whole family
    inherits it, CaseLawModernBERT included."""
    for name, bb in backbones.BACKBONES.items():
        if bb.family == "modernbert":
            assert bb.add_prefix_space, f"{name} would silently lose ~1.7 NER F1"


def test_the_default_has_a_control_arm():
    """The default is domain-adapted and its token-classification gain is unmeasured. It
    is a prior, and a prior needs something to be measured against."""
    assert backbones.BACKBONES[backbones.DEFAULT_BACKBONE].role == "default"
    controls = [b for b in backbones.BACKBONES.values() if b.role == "control"]
    assert controls, "a domain-adapted default with no control arm is an assertion"


def test_every_backbone_is_permissively_licensed():
    for name, bb in backbones.BACKBONES.items():
        assert bb.licence in ("apache-2.0", "mit"), name


# --- the specification gate --------------------------------------------------
def _spec_with(tmp_path, mutate):
    raw = yaml.safe_load((ROOT / "specs" / "extraction" / "1.0.0.yaml").read_text())
    mutate(raw)
    d = tmp_path / "specs" / "extraction"
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.0.0.yaml").write_text(yaml.safe_dump(raw))
    return str(tmp_path / "specs")


def test_the_shipped_specification_passes_its_own_gate(xspec):
    assert xspec.version == espec.IN_FORCE
    assert xspec.digest.startswith("sha256:")
    assert xspec.backbone.name == backbones.DEFAULT_BACKBONE


@pytest.mark.parametrize("rule,mutate", [
    ("E1", lambda r: r.update(backbone="not-in-the-set")),
    ("E2", lambda r: r.update(backbone_revision=None)),
    ("E3", lambda r: r["calibration"].update(temperature=0)),
    ("E3", lambda r: r["calibration"].update(aggregation="softmax-ish")),
    ("E3", lambda r: r["calibration"].update(target_precision=1.5)),
    ("E4", lambda r: r.update(floors={"a": 0.0})),
    ("E7", lambda r: r.update(author="unsigned")),
])
def test_the_gate_refuses(tmp_path, rule, mutate):
    d = _spec_with(tmp_path, mutate)
    with pytest.raises(espec.ExtractionSpecError) as e:
        espec.load(d)
    assert any(f["rule"] == rule for f in e.value.failures), e.value.failures


def test_a_specification_that_produced_data_must_pin_a_commit(tmp_path):
    """"main" identifies different weights on different days. A snapshot cited against a
    moving branch cannot be replayed, which is the one thing the provenance exists for."""
    d = _spec_with(tmp_path, lambda r: r.update(
        checkpoint="org/head-v1", backbone_revision="main",
        floors={"a": 0.8}, calibration={**r["calibration"], "corpus_id": "c",
                                        "fitted_n": 10}))
    with pytest.raises(espec.ExtractionSpecError) as e:
        espec.load(d)
    assert any(f["rule"] == "E2" for f in e.value.failures), e.value.failures


def test_a_specification_with_a_checkpoint_must_be_calibrated(tmp_path):
    d = _spec_with(tmp_path, lambda r: r.update(
        checkpoint="org/head-v1", backbone_revision="a1b2c3d"))
    with pytest.raises(espec.ExtractionSpecError) as e:
        espec.load(d)
    rules = {f["rule"] for f in e.value.failures}
    assert "E6" in rules, e.value.failures


# --- provenance and determinism ----------------------------------------------
def test_every_record_cites_what_produced_it(cal, xspec):
    r = extract_one("a document", "k1", ["a"], DeterministicBackend(), xspec, cal)
    p = r.provenance
    for key in ("extraction_spec_version", "extraction_spec_digest", "backbone",
                "backbone_revision", "calibration", "document_sha256"):
        assert key in p, key
    assert p["extracted"] is True, "an extracted corpus must never look like a filing"
    assert p["calibration"]["corpus_id"] == "fixture"


def test_extraction_is_reproducible_and_totally_ordered(cal, xspec):
    docs = {"k3": "three", "k1": "one", "k2": "two"}
    a = extract_many(docs, ["a", "b"], DeterministicBackend(seed="s"), xspec, cal)
    b = extract_many(dict(reversed(list(docs.items()))), ["a", "b"],
                     DeterministicBackend(seed="s"), xspec, cal)
    assert [r.record_key for r in a] == ["k1", "k2", "k3"]
    assert [r.audit() for r in a] == [r.audit() for r in b]


def test_a_record_may_not_repeat_a_field():
    with pytest.raises(ValueError, match="repeated fields"):
        ExtractedRecord("k", (FieldValue("a", ABSENT), FieldValue("a", ABSENT)))


def test_a_degenerate_span_is_refused():
    with pytest.raises(ValueError, match="degenerate span"):
        Span(5, 2, "")


# --- the calibration tool ----------------------------------------------------
def test_the_calibration_tool_refuses_an_unreachable_target(tmp_path):
    """It does not lower the bar. A field that cannot reach the target at any threshold
    is a field the extractor does not support on this corpus."""
    rows = [{"field": "impossible", "logits": [0.1 * (i % 7), 0.1 * ((i + 3) % 7)],
             "label": 0, "correct": i % 2 == 0} for i in range(120)]
    p = tmp_path / "r.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "calibrate_extractor.py"),
         "--readings", str(p), "--corpus-id", "c", "--checkpoint", "org/h",
         "--backbone-revision", "abc1234", "--author", "A", "--version", "9.9.9",
         "--out", str(tmp_path / "o.yaml"), "--target-precision", "0.99"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 1, out.stdout
    assert "do not lower the target" in out.stderr


def test_the_calibration_tool_writes_a_loadable_specification(tmp_path):
    rows = []
    for i in range(200):
        good = i % 10 < 7
        rows.append({"field": "a", "logits": [3.0 if good else 0.2, 0.1],
                     "label": 0, "correct": good})
    p = tmp_path / "r.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    dst = tmp_path / "specs" / "extraction"
    dst.mkdir(parents=True)
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "calibrate_extractor.py"),
         "--readings", str(p), "--corpus-id", "cold-2026", "--checkpoint", "org/h",
         "--backbone-revision", "a1b2c3d", "--author", "Arun Kadambi",
         "--version", "1.1.0", "--out", str(dst / "1.1.0.yaml"),
         "--target-precision", "0.9"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr
    loaded = espec.load(str(tmp_path / "specs"), version="1.1.0")
    assert loaded.calibration.corpus_id == "cold-2026"
    assert loaded.calibration.fitted_n == 200
    assert 0.0 < loaded.calibration.floors["a"] <= 1.0
    assert loaded.raw["backbone_revision"] == "a1b2c3d"


def test_the_aggregation_set_is_closed_everywhere():
    """One list, so the tool's choices and the gate's cannot drift apart."""
    src = (ROOT / "tools" / "calibrate_extractor.py").read_text()
    assert "AGGREGATIONS" in src and "choices=list(AGGREGATIONS)" in src
    assert set(AGGREGATIONS) == {"min", "mean", "product"}


def test_the_deterministic_backend_says_it_is_not_evidence():
    ident = DeterministicBackend().identity()
    assert "no evidence" in ident["note"]
    assert copy.deepcopy(ident) == ident
