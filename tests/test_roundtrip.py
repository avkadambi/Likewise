"""The round-trip harness: measuring an extractor against truth the corpus already has.

The judiciary corpora carry computed ground truth, so a record's values are known by
construction. Render one into prose, extract it back, compare. No human labelling, which
matters because adjudicated truth is the one input `calibrate_extractor.py` cannot
synthesise.

What these tests protect is mostly the honesty of the measurement rather than its
arithmetic: that a memorising extractor cannot score, that an extractor which never
speaks cannot score, and that a single assertion on a guard fails at any n.
"""
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extract import roundtrip as rt
from extract import spec as espec
from extract.abstain import Calibration
from extract.backends import LiteralMatchBackend
from extract.contract import ABSENT, ABSTAINED, OBSERVED
from extract.runner import extract_one

FIELDS = ["prior_category", "offence_level", "victim_impact", "restitution"]


def _records(n):
    return [{"record_key": f"w1-c{i:04d}", "prior_category": ["I", "II", "III"][i % 3],
             "offence_level": 6 + (i % 25), "victim_impact": ["none", "moderate",
             "severe"][i % 3], "restitution": [0, 500, 2500][i % 3]}
            for i in range(n)]


@pytest.fixture
def xspec():
    return espec.load(str(ROOT / "specs"))


@pytest.fixture
def cal():
    return Calibration("roundtrip", 1.0, "min", dict.fromkeys(FIELDS, 0.3), 0.98, 0)


# --- the verdict taxonomy ----------------------------------------------------
def test_the_six_way_product_does_not_collapse_into_right_and_wrong():
    """Three extractor statuses against two truth states. Asserting the wrong value and
    staying silent on a value that was there are both "not correct" and are not remotely
    the same error: one binds a decision to a false premise, the other abstains."""
    assert rt.verdict_for(OBSERVED, "III", "III") == rt.CORRECT
    assert rt.verdict_for(OBSERVED, "II", "III") == rt.WRONG
    assert rt.verdict_for(OBSERVED, "III", None) == rt.HALLUCINATED
    assert rt.verdict_for(ABSTAINED, None, "III") == rt.MISSED
    assert rt.verdict_for(ABSTAINED, None, None) == rt.CAUTIOUS
    assert rt.verdict_for(ABSENT, None, "III") == rt.NOT_RENDERED
    assert rt.verdict_for(ABSENT, None, None) == rt.CORRECT_SILENCE
    assert len(rt.VERDICTS) == 7


def test_the_expensive_errors_are_exactly_the_assertions():
    """Every silence is cheap by construction: it reaches the gate as UNRECORDED and
    abstains. Only an assertion can put a false premise in front of the gate."""
    assert rt.ASSERTION_ERRORS == {rt.WRONG, rt.HALLUCINATED}
    assert rt.ASSERTION_ERRORS < rt.ASSERTIONS
    assert rt.ASSERTIONS.isdisjoint(rt.SILENCES)
    assert rt.ASSERTIONS | rt.SILENCES == set(rt.VERDICTS)


# --- the renderer ------------------------------------------------------------
def test_an_absent_field_has_no_truth_and_is_not_in_the_prose():
    r = rt.render(_records(1)[0], FIELDS, "plain", absent=["restitution"])
    assert r.truth["restitution"] is None
    assert "restitution" not in r.prose.lower()


def test_a_guard_puts_the_value_in_the_prose_and_not_in_the_truth():
    """That is what makes it a guard: the only correct behaviour is silence, and any
    assertion is a hallucination by construction rather than by judgement."""
    rec = _records(1)[0]
    r = rt.render(rec, FIELDS, "hedged", guard_fields=["victim_impact"])
    assert r.truth["victim_impact"] is None
    assert str(rec["victim_impact"]) in r.prose
    assert r.guard


def test_a_field_cannot_be_both_absent_and_guarded():
    with pytest.raises(ValueError, match="both absent and guarded"):
        rt.render(_records(1)[0], FIELDS, "plain",
                  absent=["restitution"], guard_fields=["restitution"])


def test_rendering_is_deterministic():
    """A corpus that re-renders differently is a corpus whose score is not reproducible."""
    rec = _records(1)[0]
    a = rt.render(rec, FIELDS, "narrative", guard_fields=["victim_impact"])
    b = rt.render(rec, FIELDS, "narrative", guard_fields=["victim_impact"])
    assert a.prose == b.prose and a.digest() == b.digest()


def test_guard_styles_are_never_used_for_training():
    """A guard the extractor was trained on is not a guard."""
    train, evaluate = rt.split_styles()
    assert set(train).isdisjoint(evaluate)
    assert set(rt.GUARD_STYLES) <= set(evaluate)
    assert set(rt.GUARD_STYLES).isdisjoint(train)


# --- the acceptance gate -----------------------------------------------------
def _scored(verdict, n, *, guard=False, style="tabular", field="prior_category"):
    return [rt.Scored(f"k{i}", style, guard, field, verdict, 0.9, 0.3) for i in range(n)]


def test_never_speaking_is_not_a_pass():
    """The trap the binding gate in PRECEDENCE section 8 names: perfect precision is
    trivially satisfiable by never asserting anything. `assertion_precision` is None
    rather than 1.0, and the gate says inconclusive rather than pass."""
    rep = rt.report(_scored(rt.CORRECT_SILENCE, 500), min_assertions=300)
    assert rep.assertion_precision is None
    assert rep.gate["verdict"] == "inconclusive"
    assert "never speaking" in rep.gate["why"] or "satisfiable" in rep.gate["why"]


def test_too_few_assertions_is_inconclusive_not_pass():
    rep = rt.report(_scored(rt.CORRECT, 10), min_assertions=300)
    assert rep.assertion_precision == 1.0
    assert rep.gate["verdict"] == "inconclusive"


def test_one_guard_assertion_fails_at_any_n():
    """A guard is engineered so that silence is the only correct behaviour. One bind on
    one guard demonstrates the floor does not hold, whatever the aggregate says."""
    scored = _scored(rt.CORRECT, 5000) + _scored(rt.HALLUCINATED, 1, guard=True,
                                                 style="negated")
    rep = rt.report(scored, min_assertions=300)
    assert rep.gate["verdict"] == "fail"
    assert len(rep.guard_assertions) == 1
    assert rep.assertion_precision > 0.999      # the aggregate would have passed


def test_a_style_appearing_in_both_splits_invalidates_the_measurement():
    """Not a warning. If the evaluation styles were trained on, the number is
    memorisation, and a memorisation number reported as accuracy is worse than none."""
    rep = rt.report(_scored(rt.CORRECT, 400, style="plain"),
                    train_styles=["plain", "formal"], min_assertions=300)
    assert rep.gate["verdict"] == "invalid"
    assert rep.gate["style_leak"] == ["plain"]


def test_a_clean_run_can_pass():
    rep = rt.report(_scored(rt.CORRECT, 400) + _scored(rt.WRONG, 4),
                    train_styles=["plain"], min_assertions=300, target_precision=0.98)
    assert rep.gate["verdict"] == "pass", rep.gate
    assert rep.assertion_precision > 0.98


def test_every_report_carries_the_upper_bound_caveat():
    """The renderer and the extractor share a vocabulary. This number is what the
    extractor achieves when the prose is as cooperative as it will ever be, and the gap
    to a real docket is unmeasured. Same discipline as marking Rosenbaum's gamma
    not_applicable on a generated corpus."""
    rep = rt.report(_scored(rt.CORRECT, 400))
    assert "UPPER BOUND" in rep.caveat
    assert "upper bound" in rep.as_dict()["caveat"].lower()


# --- the guard mechanism has teeth -------------------------------------------
def test_the_label_proximity_baseline_is_caught_by_the_guards(xspec, cal):
    """The extractor somebody builds in an afternoon: find the label, take what follows.
    On plain prose it is very accurate. It cannot represent negation, attribution or
    hedging, so on the guard styles it asserts confidently and wrongly -- which is the
    demonstration that the guards work before any model exists."""
    backend = LiteralMatchBackend()
    scored = []
    for rec in _records(60):
        r = rt.render(rec, FIELDS, "negated", absent=["restitution"],
                      guard_fields=["victim_impact"])
        ex = extract_one(r.prose, r.record_key, FIELDS, backend, xspec, cal)
        scored.extend(rt.score(ex, r))
    rep = rt.report(scored, min_assertions=1)
    assert rep.guard_assertions, "the guard style did not catch a proximity extractor"
    assert rep.gate["verdict"] == "fail"


def test_the_baseline_gets_a_genuinely_absent_field_right(xspec, cal):
    """It is a baseline, not a straw man: on a field the prose omits it says nothing,
    which is correct. A harness that only ever sees bad extractors is not tested."""
    backend = LiteralMatchBackend()
    rec = _records(1)[0]
    r = rt.render(rec, FIELDS, "plain", absent=["restitution"])
    ex = extract_one(r.prose, r.record_key, FIELDS, backend, xspec, cal)
    verdicts = {s.field: s.verdict for s in rt.score(ex, r)}
    assert verdicts["restitution"] == rt.CORRECT_SILENCE
    assert verdicts["prior_category"] == rt.CORRECT


# --- closing the loop into calibration ---------------------------------------
def test_only_assertions_become_labelled_readings():
    """A silence is not a reading with a wrong answer, it is the absence of one. Feeding
    silences to a threshold fitter as negatives pushes the floor DOWN, which is exactly
    backwards: the fitter would loosen the gate to recover the coverage it never lost."""
    scored = (_scored(rt.CORRECT, 3) + _scored(rt.WRONG, 2) + _scored(rt.MISSED, 7)
              + _scored(rt.CORRECT_SILENCE, 5))
    rows = rt.readings(scored)
    assert len(rows) == 5
    assert sum(1 for r in rows if r["correct"]) == 3
    assert all(r["confidence"] is not None for r in rows)


def test_the_readings_feed_the_calibration_tool(tmp_path, xspec, cal):
    """End to end: render, extract, score, write readings, calibrate. The step that
    normally needs a human reading every document is computed here."""
    backend = LiteralMatchBackend()
    scored = []
    for i, rec in enumerate(_records(150)):
        # Non-guard styles: the loop under test is calibration, and a run whose readings
        # are all wrong tests the refusal path, which has its own test.
        r = rt.render(rec, FIELDS, ["plain", "formal", "narrative"][i % 3])
        ex = extract_one(r.prose, r.record_key, FIELDS, backend, xspec, cal)
        scored.extend(rt.score(ex, r))
    path = tmp_path / "readings.jsonl"
    n = rt.write_readings(scored, str(path))
    assert n > 0

    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert {"field", "confidence", "correct", "token_probs"} <= set(rows[0])
    # The tool needs logits; readings carry token_probs, which is the documented path.
    for r in rows:
        r["logits"] = [2.0 if r["correct"] else 0.1, 0.1]
    path.write_text("\n".join(json.dumps(r) for r in rows))

    dst = tmp_path / "specs" / "extraction"
    dst.mkdir(parents=True)
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "calibrate_extractor.py"),
         "--readings", str(path), "--corpus-id", "roundtrip-w1",
         "--checkpoint", "org/head", "--backbone-revision", "a1b2c3d",
         "--author", "Arun Kadambi", "--version", "1.1.0",
         "--out", str(dst / "1.1.0.yaml"), "--target-precision", "0.6"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, out.stderr
    loaded = espec.load(str(tmp_path / "specs"), version="1.1.0")
    assert loaded.calibration.corpus_id == "roundtrip-w1"
    assert loaded.calibration.fitted_n == len(rows)


# --- the CLI -----------------------------------------------------------------
def test_the_cli_reports_and_exits_nonzero_when_the_gate_fails(tmp_path):
    recs = tmp_path / "r.jsonl"
    recs.write_text("\n".join(json.dumps(r) for r in _records(80)))
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "roundtrip_extractor.py"),
         "--records", str(recs), "--fields", ",".join(FIELDS),
         "--absent", "restitution", "--guard", "victim_impact",
         "--floor", "0.3", "--min-assertions", "20"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 1, out.stdout
    d = json.loads(out.stdout)
    assert d["gate"]["verdict"] == "fail"
    assert d["guard_assertions"]
    assert "not a trained model" in d["WARNING"]
    assert "UPPER BOUND" in d["caveat"]
