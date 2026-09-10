"""Where the model actually runs -- and the seam that keeps it out of the engine.

`likewise/` has five runtime dependencies and no numpy. Adding a transformer to it would
change that by a factor of twenty-five: torch is 555 MB of wheel against DuckDB's 21.5,
before a checkpoint of 300 MB to 1.6 GB. The served container is rootless, `--read-only`
and makes no outbound network calls, and none of that survives a torch import.

So extraction is not part of the service. It is a pipeline stage that runs where a GPU
is, reads documents, and writes the same structured snapshot the loader already produces.
The engine never imports torch, and a test asserts that over every file in `likewise/`.

Two backends implement one protocol. `TransformersBackend` imports torch lazily, inside
the call, so that `import extract` costs nothing and the module is importable -- and
testable -- on a machine with no model on it. `DeterministicBackend` is a seeded fake:
it makes the whole pipeline, including abstention and provenance, exercisable in the test
suite with no weights and no network. That is not a convenience. A calibration rule whose
tests require a 400 MB download is a calibration rule nobody re-runs.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TokenScore:
    """One candidate reading of one field from one document."""
    field: str
    value: object
    token_probs: tuple[float, ...]
    start: int
    end: int
    text: str


@runtime_checkable
class Backend(Protocol):
    """What an extractor must provide. Deliberately narrow: it proposes readings with
    per-token probabilities and takes no decision. Every decision -- aggregate, scale,
    compare to a floor, speak or stay silent -- happens in `abstain.py`, where it is
    testable without a model."""

    def identity(self) -> dict[str, object]:
        """What produced these scores, for the provenance record."""

    def score(self, document: str, fields: Sequence[str]) -> list[TokenScore]:
        """Candidate readings. A field the document does not speak to is simply absent
        from the result: proposing nothing is how ABSENT is expressed, and it is not the
        same as proposing something with low confidence."""


class DeterministicBackend:
    """A seeded fake, for tests and for exercising the pipeline end to end.

    Derives its scores from a hash of (document, field), so the same input always
    produces the same reading. That makes an extraction run reproducible in the test
    suite in the same sense the scan is reproducible: same input, same output, no clock
    and no network.
    """

    def __init__(self, seed: str = "likewise-extract",
                 emit: dict[str, object] | None = None,
                 silent_fields: Sequence[str] = ()):
        self.seed = seed
        self._emit = emit or {}
        self._silent = set(silent_fields)

    def identity(self) -> dict[str, object]:
        return {"backend": "deterministic", "seed": self.seed,
                "note": "fixture backend; produces no evidence about any document"}

    def _u(self, *parts: str) -> float:
        h = hashlib.sha256("\x1f".join((self.seed, *parts)).encode()).digest()
        return int.from_bytes(h[:8], "big") / float(1 << 64)

    def score(self, document: str, fields: Sequence[str]) -> list[TokenScore]:
        out = []
        for f in fields:
            if f in self._silent:
                continue                      # the document does not speak to it
            u = self._u(document, f)
            n = 1 + int(self._u(document, f, "n") * 3)
            probs = tuple(min(0.999, max(0.001, u + 0.05 * i)) for i in range(n))
            out.append(TokenScore(field=f, value=self._emit.get(f, round(u * 100, 3)),
                                  token_probs=probs, start=0,
                                  end=min(len(document), 12), text=document[:12]))
        return out


class LiteralMatchBackend:
    """A naive baseline: find the field's label in the text and take what follows.

    Not a toy. It is the extractor somebody builds in an afternoon when the corpus is
    synthetic and the renderer is cooperative, and on plain prose it is very accurate --
    which is exactly why it is here. Run against the guard styles it asserts confidently
    on "the victim impact is NOT severe" and on a value attributed to a different case,
    because proximity to a label is all it knows.

    That failure is the point. It demonstrates that the guard styles have teeth before
    any real model is trained, and it gives the round-trip gate something it must reject.
    A harness that only ever sees extractors it passes has not been tested either.
    """

    def __init__(self, confidence: float = 0.95):
        #: Ceiling. The reported confidence falls off with the distance between the
        #: label and the value, which is the only signal a proximity extractor has. It
        #: is deliberately NOT sensitive to negation or attribution: a confidence floor
        #: does not rescue an extractor from a representational blind spot, and pretending
        #: otherwise would hide the lesson the guard styles exist to teach.
        self.confidence = confidence

    def identity(self) -> dict[str, object]:
        return {"backend": "literal_match", "confidence": self.confidence,
                "note": "label-proximity baseline; keys on the label alone and cannot "
                        "represent negation, attribution or hedging"}

    def score(self, document: str, fields: Sequence[str]) -> list[TokenScore]:
        import re
        out = []
        for f in fields:
            label = re.escape(f.replace("_", " "))
            m = re.search(rf"{label}\s*(?:is|to be|at|was|:|—|-)\s*([^\s.,;]+)",
                          document, re.IGNORECASE)
            if not m:
                continue                      # says nothing rather than guessing
            gap = m.start(1) - m.end(0) + len(m.group(0)) - len(m.group(1))
            conf = max(0.05, self.confidence - 0.02 * max(0, gap - 4))
            out.append(TokenScore(field=f, value=m.group(1).rstrip(".,;"),
                                  token_probs=(round(conf, 6),),
                                  start=m.start(1), end=m.end(1), text=m.group(1)))
        return out


class TransformersBackend:
    """The real one. Imports torch and transformers lazily, inside the methods.

    `add_prefix_space` is taken from the backbone rather than left to the default. The
    ModernBERT tokenizer prepends whitespace on a plain call, and on CoNLL that costs
    about 1.7 F1 -- 90.54 against 92.23. The whole ModernBERT family inherits the
    behaviour, so it is recorded per backbone and asserted by a test rather than
    remembered.
    """

    def __init__(self, backbone_name: str, checkpoint: str | None = None,
                 device: str | None = None, max_length: int | None = None):
        from . import backbones
        self.backbone = backbones.get(backbone_name)
        # `checkpoint` is the fine-tuned head; the backbone repo is the starting point it
        # was adapted from. Extraction against a bare backbone is not a supported mode --
        # a pretrained encoder has no field labels and cannot propose a reading.
        self.checkpoint = checkpoint
        self.device = device
        self.max_length = max_length or self.backbone.context
        self._tok = None
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        if not self.checkpoint:
            raise RuntimeError(
                "no fine-tuned checkpoint given. The backbone is a starting point for "
                "training, not an extractor: it has no field labels. Train a token "
                "classification head with tools/train_extractor.py first.")
        try:
            import torch                                            # noqa: F401
            from transformers import AutoModelForTokenClassification, AutoTokenizer
        except ImportError as e:                                    # pragma: no cover
            raise RuntimeError(
                "extraction needs torch and transformers, which the served engine "
                "deliberately does not carry. Install extract/requirements.txt in a "
                "separate environment; do not add them to requirements.txt."
            ) from e
        self._tok = AutoTokenizer.from_pretrained(
            self.checkpoint, add_prefix_space=self.backbone.add_prefix_space)
        self._model = AutoModelForTokenClassification.from_pretrained(self.checkpoint)
        self._model.eval()
        if self.device:
            self._model.to(self.device)

    def identity(self) -> dict[str, object]:
        return {"backend": "transformers", "backbone": self.backbone.name,
                "backbone_repo": self.backbone.repo,
                "backbone_revision": self.backbone.revision,
                "checkpoint": self.checkpoint,
                "add_prefix_space": self.backbone.add_prefix_space,
                "max_length": self.max_length}

    def score(self, document: str, fields: Sequence[str]) -> list[TokenScore]:  # pragma: no cover
        import torch
        self._load()
        enc = self._tok(document, return_tensors="pt", truncation=True,
                        max_length=self.max_length, return_offsets_mapping=True)
        offsets = enc.pop("offset_mapping")[0].tolist()
        if self.device:
            enc = {k: v.to(self.device) for k, v in enc.items()}
        with torch.no_grad():
            logits = self._model(**enc).logits[0]
        id2label = self._model.config.id2label
        wanted = set(fields)
        # BIO decoding: contiguous runs of the same label become one span, and the span
        # carries the probability of EVERY token in it. Aggregation is not done here --
        # abstain.py owns that, so the rule is testable without a model.
        spans, cur = [], None
        for i, off in enumerate(offsets):
            if off[0] == off[1]:
                continue                                  # special token
            probs = torch.softmax(logits[i], dim=-1)
            j = int(torch.argmax(probs))
            lab = id2label[j]
            base = lab.split("-", 1)[-1] if "-" in lab else lab
            begins = lab.startswith("B-") or cur is None or cur["field"] != base
            if lab in ("O", "0") or base not in wanted:
                cur = None
                continue
            if begins:
                cur = {"field": base, "start": off[0], "end": off[1],
                       "probs": [float(probs[j])]}
                spans.append(cur)
            else:
                cur["end"] = off[1]
                cur["probs"].append(float(probs[j]))
        return [TokenScore(field=s["field"], value=document[s["start"]:s["end"]],
                           token_probs=tuple(s["probs"]), start=s["start"],
                           end=s["end"], text=document[s["start"]:s["end"]])
                for s in spans]
