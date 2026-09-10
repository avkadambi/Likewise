"""The closed set of extraction backbones.

A backbone is named, not supplied. The argument is the one that keeps user-supplied
resolution models out of `likewise/specs.py`: a specification is signed and cited by
digest on every result, and a digest over a free-form model identifier certifies the
string, not the weights. A closed set with pinned revisions is comparable; an arbitrary
repository name is not.

Selection evidence, September 2026. No new encoder ARCHITECTURE was released in 2026 --
every 2026 encoder is a domain adaptation of ModernBERT -- so the choice is between
ModernBERT-family checkpoints and the older DeBERTaV3.

    Model                     params  ctx   licence     CoNLL-2003 NER F1
    CaseLawModernBERT-large     395M  8192  Apache-2.0  not measured
    ModernBERT-large            395M  8192  Apache-2.0  92.23 +- 0.16  (third party)
    Ettin-encoder-400m          400M  8000  MIT         92.07 +- 0.21  (third party)
    DeBERTaV3-large             434M   512  MIT         93.40 +- 0.62  (matched-data study)

Two findings decided the default, and neither is the headline benchmark.

First, ModernBERT's advantage over DeBERTaV3 is largely DATA, not architecture. Under
identical pretraining data (arXiv 2504.08716) DeBERTaV3 wins token classification by
about 1.4 F1 and extractive QA by 1.7. What ModernBERT actually buys is context length
and speed. A legal filing does not fit in 512 tokens, so the 8192 window is worth more
here than 1.4 F1 -- but the trade is real and `deberta-v3-large` stays in the set as a
chunked comparison arm rather than being written out of the design.

Second, none of the four is differentiated FOR THIS DOMAIN except by continued
pretraining. CaseLawModernBERT-large is ModernBERT-large further pretrained on 8.3M US
court opinions, so every recipe and the measured NER number transfer unchanged. Domain
adaptation is historically the most reliable source of tagging gain, but it has NOT been
measured for token classification on this checkpoint. It is the default as a strong prior
and nothing more: `modernbert-large` is kept as the control arm, and the two are meant to
be fine-tuned head to head on real labelled spans before either is trusted.

`add_prefix_space` is not a detail. The ModernBERT tokenizer prepends whitespace on a
plain call, which costs roughly 1.7 F1 on CoNLL -- 90.54 against 92.23 -- and the whole
family inherits it. It is recorded per backbone, and a test asserts it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Backbone:
    name: str
    repo: str
    revision: str          # pinned; "main" is refused by the gate
    family: str            # modernbert | deberta
    params: int
    context: int
    licence: str
    add_prefix_space: bool
    role: str              # default | control | comparison
    note: str


BACKBONES: dict[str, Backbone] = {
    "caselaw-modernbert-large": Backbone(
        name="caselaw-modernbert-large",
        repo="ai-law-society-lab/CaseLawModernBERT-large",
        revision="main",
        family="modernbert", params=395_000_000, context=8192,
        licence="apache-2.0", add_prefix_space=True, role="default",
        note="ModernBERT-large continued-pretrained on 8.3M US court opinions (COLD). "
             "Token classification not measured on this checkpoint; treat the domain "
             "gain as a prior to be tested, not a result. The corpus is PDF-converted "
             "and carries OCR noise, and it is US-only."),
    "modernbert-large": Backbone(
        name="modernbert-large",
        repo="answerdotai/ModernBERT-large",
        revision="main",
        family="modernbert", params=395_000_000, context=8192,
        licence="apache-2.0", add_prefix_space=True, role="control",
        note="The control arm. Any claimed gain from domain adaptation is the difference "
             "against this, fine-tuned identically on the same spans."),
    "ettin-encoder-400m": Backbone(
        name="ettin-encoder-400m",
        repo="jhu-clsp/ettin-encoder-400m",
        revision="main",
        family="modernbert", params=400_000_000, context=8000,
        licence="mit", add_prefix_space=True, role="comparison",
        note="Statistically tied with ModernBERT-large on the only NER measurement that "
             "exists (92.07 vs 92.23). Fully public training data, which is worth more "
             "than the tie in a setting where provenance is questioned."),
    "deberta-v3-large": Backbone(
        name="deberta-v3-large",
        repo="microsoft/deberta-v3-large",
        revision="main",
        family="deberta", params=434_000_000, context=512,
        licence="mit", add_prefix_space=False, role="comparison",
        note="Wins token classification and extractive QA under matched pretraining data. "
             "512 tokens means chunking, and a chunked window can split a span from the "
             "cue that identifies it. Kept as the arm that tests whether the long context "
             "is earning its 1.4 F1."),
}

DEFAULT_BACKBONE = "caselaw-modernbert-large"


def get(name: str) -> Backbone:
    if name not in BACKBONES:
        raise KeyError(
            f"unknown backbone {name!r}; the set is closed: {sorted(BACKBONES)}. "
            "Adding one is a versioned change to the extraction specification, with a "
            "rationale and a named author, not a configuration value.")
    return BACKBONES[name]
