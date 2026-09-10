# Extraction: reading prose into the record the engine already consumes

## 1. Why this exists at all

HMDA arrives structured. That is not a convenience — it is the comparability argument.
The regulator coarsens `loan_amount` to $10,000 midpoints, `income` to $1,000 and
debt-to-income to an integer only inside `[36, 49]`, and the resolution budget is derived
from exactly that coarsening. The loader refuses anything that is not already at
publication granularity, because a value at full precision is a value whose interval the
engine cannot construct.

A court record arrives as prose. Nothing coarsens it, nothing types it, and there is no
filing instruction guide that says what a field means. Something has to produce
`facts(c)` — the typed, ordered dimension vector the gate consumes — and that something
is a model.

This is the only place in the system where a model is appropriate, and the reasons it is
excluded everywhere else are worth restating, because they are what constrains the design
here.

## 2. Where a model may not go

**Not the gate.** Admission is a box: a conjunction of per-dimension interval
comparisons. No additive or learned score has super-level sets that are boxes in more than
one dimension, and `tests/test_precedent.py` contains a test that constructs the
counterexample. A similarity model does not loosen the gate; it replaces it with a
different shape and then reports the difference as the same quantity.

**Not the scoring.** The protected-class exclusion in `specs.py` is *syntactic* — it
checks field names. An embedding of a fact narrative is a proxy for everything in that
narrative, protected attributes included, and it would pass every test written to enforce
the exclusion while violating it in substance.

**Not retrieval, in the naive form.** Coherence requires
`¬distinguish(r,c) ⟹ sim(r,c) ≥ θ`: retrieval must never discard a pair the gate would
have admitted. A learned similarity offers no such guarantee and the failure is invisible,
because you never see the pair you did not retrieve. The admissible variant is union-only
— `candidates = symbolic_block ∪ model_neighbours` — where recall can only rise and the
symbolic block remains wholly contained. That is a measurable experiment, not a
replacement, and it is not built here.

**Not the service.** `likewise/` runs on five wheels totalling about 25 MB. Torch alone is
555 MB before a checkpoint of 300 MB to 1.6 GB. The container is rootless, `--read-only`,
and makes no outbound network calls, and none of that survives a torch import. Extraction
is a pipeline stage that produces a snapshot; the engine never imports a model runtime,
and `tests/test_extraction.py` asserts that over every file in the package.

## 3. Choosing the backbone

Surveyed September 2026. The headline finding is negative and worth stating plainly:
**no new encoder architecture was released in 2026.** Every 2026 encoder is a domain
adaptation of ModernBERT — CaseLaw, BioClinical, Climate, and others. ModernBERT as
substrate is the settled position, not a bet.

| Model | Params | Context | Licence | CoNLL-2003 NER F1 |
| :--- | ---: | ---: | :--- | :--- |
| CaseLawModernBERT-large | 395M | 8192 | Apache-2.0 | not measured |
| ModernBERT-large | 395M | 8192 | Apache-2.0 | 92.23 ± 0.16 (third party) |
| Ettin-encoder-400m | 400M | 8000 | MIT | 92.07 ± 0.21 (third party) |
| DeBERTaV3-large | 434M | 512 | MIT | 93.40 ± 0.62 (matched data) |

Two findings decided it, and neither is a headline benchmark.

**ModernBERT's advantage over DeBERTaV3 is data, not architecture.** Under identical
pretraining data, DeBERTaV3 wins token classification by about 1.4 F1 and extractive QA by
1.7. What ModernBERT actually buys is context length and speed. A filing does not fit in
512 tokens, so the trade is accepted — but `deberta-v3-large` stays in the set as a chunked
comparison arm so the trade remains measurable rather than becoming an assumption.

**Nothing is differentiated for this domain except by continued pretraining.**
CaseLawModernBERT-large is ModernBERT-large further pretrained on 8.3M US court opinions,
so every recipe and the measured NER number transfer unchanged. It is the default as a
*prior*: token classification has not been measured on that checkpoint, `modernbert-large`
is kept as the control arm, and `tools/train_extractor.py --control` trains both
identically and prints the gap. If the gap is not positive, the specification should name
the control.

**One measured trap.** The ModernBERT tokenizer prepends whitespace on a plain call, which
costs about 1.7 F1 on CoNLL — 90.54 against 92.23. The whole family inherits it. It is
recorded per backbone as `add_prefix_space` and asserted by a test rather than remembered.

**Calibration evidence is absent for every candidate.** No published ECE, reliability
diagram or selective-prediction number exists for ModernBERT, Ettin, EuroBERT, NeoBERT or
mmBERT. What is known is worse than nothing: on NER, encoder error-detection AUROC falls
from 0.922 in-domain to 0.633 out-of-domain, with calibration error between 0.36 and 0.41.
No backbone can be chosen on calibration grounds, and every design decision in §4 follows
from that.

## 4. What the extractor is allowed to say

Three statuses, and the distinction between the last two is the whole point.

| Status | Meaning | Reaches the engine as |
| :--- | :--- | :--- |
| `OBSERVED` | the document states a value, above the floor | the value |
| `ABSTAINED` | read, but not confidently enough to assert | `None` |
| `ABSENT` | the document does not speak to this dimension | `None` |

A `None` on a premise dimension is `UNRECORDED`, which under a rule of precedence outranks
distinguishing and breaks the bind. **An extractor that is unsure produces silence, and
silence never binds.** That is the safety property, and it is why `compare.py` split
`UNRECORDED` out of `AMBIGUOUS` in 0.8.0 — the split was built before there was anything
producing silences, and this is what it was for.

`FieldValue` refuses at construction to let a silent field carry a value. An abstention
that keeps its best guess is not an abstention; it is a guess one refactor away from being
read.

`ABSTAINED` and `ABSENT` stay distinct in the audit record even though the engine cannot
tell them apart. They are different facts: one is a defect in the instrument, the other a
property of the filing. Collapsed, the extractor's own miss rate becomes unmeasurable
against true absences.

## 5. The floor is a governance decision

A confidence threshold decides when the system is allowed to speak. It is not a model
hyperparameter and it does not live in a training script. It lives in
`specs/extraction/<version>.yaml`, signed, versioned, cited by digest on the snapshot it
produced, and validated by a gate:

| Rule | Requirement |
| :--- | :--- |
| E1 | The backbone is a member of the closed set |
| E2 | The revision is pinned; a specification that produced data may not cite a moving branch |
| E3 | Temperature positive, aggregation known, target precision in (0, 1] |
| E4 | Every floor in **(0, 1]** — zero is refused, not clamped |
| E5 | A ModernBERT-family backbone sets `add_prefix_space` |
| E6 | A specification with a checkpoint names its corpus, its fitted *n*, and at least one floor |
| E7 | Signed |

E4 is the one worth dwelling on. A floor of zero is not a lenient threshold — it is the
absence of one. Every reading would be asserted however weak, and the abstention path, the
only thing between a guess and a bind, becomes unreachable.

**Fitted for precision, never for F1.** The error asymmetry is the opposite of a normal
extraction task: a missed field abstains, which costs a reviewer nothing, while a
hallucinated field binds a decision to a premise nobody established. `floor_for_precision`
takes a target precision and returns the *most permissive* threshold that meets it. If no
threshold meets it, `tools/calibrate_extractor.py` exits non-zero and says to drop the
field — it does not lower the bar.

**Fitted per corpus, and only valid there.** `Calibration` carries `corpus_id` because a
floor fitted on one court's filings says nothing about another's. This is the direct
consequence of the domain-shift finding in §3, and it is the characteristic failure mode
of this design.

**Weakest link.** Span confidence defaults to `min` over the span's tokens: a span is only
as identified as its least certain token, and span-restricted probability is the more
robust signal under shift. `mean` and `product` are declared alternatives.

## 6. Running it

```
python3 -m venv .venv-extract
.venv-extract/bin/pip install -r extract/requirements.txt      # torch, transformers

.venv-extract/bin/python tools/train_extractor.py \
    --train spans.train.jsonl --eval spans.eval.jsonl \
    --out ./head-v1 --control                                  # trains the control too

.venv-extract/bin/python tools/calibrate_extractor.py \
    --readings held_out.jsonl --corpus-id cold-2026 \
    --checkpoint ./head-v1 --backbone-revision <commit sha> \
    --author "..." --version 1.1.0 \
    --out specs/extraction/1.1.0.yaml --target-precision 0.98
```

`--readings` needs adjudicated truth: a human decided whether each reading was correct.
There is no way to produce that from the model, and a calibration fitted against the
model's own output measures nothing.

## 7. Measuring it against truth that already exists

The judiciary corpora carry **computed** ground truth — a record's values are known by
construction, which is what makes the binding acceptance gate in `PRECEDENCE.md` §8
possible. That makes something else possible too.

Render a record whose values are known into the prose a court would have written, extract
it back, and compare. `extract/roundtrip.py` and `tools/roundtrip_extractor.py` do this.
No human labelling is needed, which matters because adjudicated truth is the one input
`calibrate_extractor.py` cannot synthesise — and a calibration fitted against the model's
own output measures nothing.

### The number is an upper bound, not an estimate

The renderer and the extractor share a vocabulary. The renderer writes "prior record
category III" and the extractor was trained on renderer output, so it reads exactly that.
A real filing was written by someone who had never seen the renderer. **The gap to a real
docket is unmeasured and unbounded**, and every report carries the caveat as a field
rather than a footnote — the same discipline that marks Rosenbaum's Γ
`not_applicable: generated_corpus` instead of transplanting a number that looks like the
lending one.

### Seven verdicts, because three statuses against two truth states do not collapse

| | truth has a value | truth is absent |
| :--- | :--- | :--- |
| `OBSERVED`, matching | `correct` | — |
| `OBSERVED`, differing | **`wrong`** | **`hallucinated`** |
| `ABSTAINED` | `missed` | `cautious` |
| `ABSENT` | `not_rendered` | `correct_silence` |

The two bold cells are the expensive errors: each puts a value the record does not support
in front of the gate, where it can bind a decision to a premise nobody established. Every
silence is cheap by construction. The headline is therefore **assertion precision** —
correct assertions over all assertions — and not F1, which would average the expensive
error against the cheap one.

### The gate, and the trap it exists to avoid

Mirrors the binding gate in `PRECEDENCE.md` §8, for the same reason: **perfect precision is
trivially satisfiable by never speaking.** So `assertion_precision` is `None` rather than
`1.0` when nothing was asserted, and:

| Condition | Verdict |
| :--- | :--- |
| An evaluation style was also a training style | `invalid` — the measurement is of memorisation |
| Any assertion on a guard record | `fail` — at any *n* |
| Fewer assertions than the floor | `inconclusive` — never `pass` |
| Assertion precision ≥ target | `pass` |

**Guard records** are rendered so the value appears in the prose while the record does not
carry it: `"the victim impact is not severe"`, `"counsel asserted ... which the court did
not reach"`, `"in the cited matter ... the present case differs"`. The only correct
behaviour is silence, so any assertion is a hallucination by construction rather than by
judgement. Guard styles are held out of training — a guard the extractor was trained on is
not a guard.

**Style disjointness is enforced, not advised.** If the evaluation styles were trained on,
the number is memorisation, and `report()` returns `invalid` rather than a headline. This
is the extraction analogue of the held-out corpus revision that tolerance selection may not
touch.

### The demonstration that the guards have teeth

`LiteralMatchBackend` is the extractor somebody builds in an afternoon: find the label,
take what follows. On plain prose it is accurate — it gets genuinely absent fields right,
staying silent rather than guessing. On the guard styles it asserts confidently and
wrongly, because label proximity is all it knows and negation, attribution and hedging are
outside what it can represent.

The lesson worth taking is in *how* it fails. Its confidence is high on the guards, so **a
confidence floor does not rescue an extractor from a representational blind spot.** The
floor governs uncertainty the model can express; it is silent about the errors the model
cannot see. That is why the gate reads guard assertions directly instead of trusting the
calibration to have caught them.

### Closing the loop

Only assertions become labelled readings. A silence is not a reading with a wrong answer,
it is the absence of one — feeding silences to a threshold fitter as negatives would push
the floor *down*, loosening the gate to recover coverage that was never lost.

```
tools/roundtrip_extractor.py --records w1.jsonl --fields ... \
    --absent restitution --guard victim_impact \
    --checkpoint ./head-v1 --readings readings.jsonl --report report.json
tools/calibrate_extractor.py --readings readings.jsonl --corpus-id w1 ...
```

## 8. What is not built, and must be before real records

- **Human adjudication with an agreement floor.** Round-trip scoring bounds the
  extractor against cooperative prose; it says nothing about a real filing. The extractor
  is the measurement instrument, and no amount of gate discipline substitutes for a
  labelled sample somebody argued over.
- **A coverage floor per field.** `coverage()` reports the three statuses per field; there
  is no rule yet that refuses to publish a dimension that abstains on most of the corpus.
  A premise dimension silent on most cases cannot carry a precedent.
- **The union-only retrieval experiment** of §2, which is measurable and is not measured.
- **Sensitivity.** Γ_max is already ≈2.1 for debt-to-income here against a benchmark near
  11. Real case records have *more* unobserved determinants of outcome, not fewer, and an
  extracted corpus adds the extractor's own error to that. The ceiling gets worse and no
  sample size lifts it. This belongs in the limitations of any real-records instantiation
  from day one.
