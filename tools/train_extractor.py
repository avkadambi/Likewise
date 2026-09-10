#!/usr/bin/env python3
"""Fine-tune a token-classification head on labelled spans.

Runs in the extraction environment, not the engine's: `pip install -r
extract/requirements.txt` into a separate virtualenv on a machine with a GPU. Nothing in
`likewise/` imports what this needs.

Two things it does that a stock recipe does not, both because they were measured rather
than assumed:

  * `add_prefix_space` comes from the backbone. The ModernBERT tokenizer prepends
    whitespace on a plain call, and on CoNLL that costs about 1.7 F1 -- 90.54 against
    92.23. The entire ModernBERT family inherits it, CaseLawModernBERT included.
  * `--control` trains the same head on `modernbert-large` with an identical
    configuration, so the domain-adaptation claim for CaseLawModernBERT is a measured
    difference rather than a citation. Continued pretraining on court opinions has been
    shown to help classification and retrieval on legal text; it has NOT been measured
    for token classification, which is what this does.

Input is JSONL: {"tokens": [...], "labels": [...], "id": "..."} with BIO labels.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from extract import backbones


def _read(path: str) -> list[dict]:
    return [json.loads(x) for x in pathlib.Path(path).read_text().splitlines() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backbone", default=backbones.DEFAULT_BACKBONE,
                    choices=sorted(backbones.BACKBONES))
    ap.add_argument("--control", action="store_true",
                    help="also train modernbert-large identically, and report the gap")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--max-length", type=int, default=None)
    ap.add_argument("--seed", type=int, default=20260909)
    a = ap.parse_args()

    try:
        import numpy as np
        import torch
        from transformers import (AutoModelForTokenClassification, AutoTokenizer,
                                  DataCollatorForTokenClassification, Trainer,
                                  TrainingArguments)
    except ImportError as e:
        print("extraction needs torch and transformers, which the served engine "
              "deliberately does not carry:\n"
              "  python3 -m venv .venv-extract\n"
              "  .venv-extract/bin/pip install -r extract/requirements.txt\n"
              f"({e})", file=sys.stderr)
        return 2

    train_rows, eval_rows = _read(a.train), _read(a.eval)
    labels = sorted({t for r in train_rows + eval_rows for t in r["labels"]})
    l2i = {v: i for i, v in enumerate(labels)}

    def build(bb_name: str):
        bb = backbones.get(bb_name)
        tok = AutoTokenizer.from_pretrained(
            bb.repo, revision=bb.revision, add_prefix_space=bb.add_prefix_space)
        model = AutoModelForTokenClassification.from_pretrained(
            bb.repo, revision=bb.revision, num_labels=len(labels),
            id2label={i: v for v, i in l2i.items()}, label2id=l2i)

        def encode(rows):
            out = []
            for r in rows:
                enc = tok(r["tokens"], is_split_into_words=True, truncation=True,
                          max_length=a.max_length or bb.context)
                wid, prev, lab = enc.word_ids(), None, []
                for w in wid:
                    if w is None:
                        lab.append(-100)
                    elif w != prev:
                        lab.append(l2i[r["labels"][w]])
                    else:
                        # Label the first sub-token only. Labelling every piece lets a
                        # long word outvote a short one in the loss.
                        lab.append(-100)
                    prev = w
                enc["labels"] = lab
                out.append(dict(enc))
            return out

        return bb, tok, model, encode(train_rows), encode(eval_rows)

    def metrics(p):
        preds = np.argmax(p.predictions, axis=2)
        tp = fp = fn = 0
        for pr, gl in zip(preds, p.label_ids, strict=True):
            for pi, gi in zip(pr, gl, strict=True):
                if gi == -100:
                    continue
                pl, glab = labels[pi], labels[gi]
                if glab != "O" and pl == glab:
                    tp += 1
                elif pl != "O" and pl != glab:
                    fp += 1
                if glab != "O" and pl != glab:
                    fn += 1
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        # Precision is reported first and deliberately. The floor this feeds is fitted
        # for precision at a target, and F1 is here only for comparison with published
        # numbers, never as the selection criterion.
        return {"precision": prec, "recall": rec, "f1": f1}

    results = {}
    for name in ([a.backbone, "modernbert-large"] if a.control else [a.backbone]):
        if name in results:
            continue
        _bb, tok, model, tr, ev = build(name)
        out_dir = a.out if name == a.backbone else f"{a.out}-control-{name}"
        trainer = Trainer(
            model=model,
            args=TrainingArguments(
                output_dir=out_dir, learning_rate=a.lr, num_train_epochs=a.epochs,
                per_device_train_batch_size=a.batch, per_device_eval_batch_size=a.batch,
                eval_strategy="epoch", save_strategy="epoch", seed=a.seed,
                load_best_model_at_end=True, metric_for_best_model="precision",
                bf16=torch.cuda.is_available()),
            train_dataset=tr, eval_dataset=ev,
            data_collator=DataCollatorForTokenClassification(tok),
            compute_metrics=metrics)
        trainer.train()
        results[name] = trainer.evaluate()
        trainer.save_model(out_dir)
        tok.save_pretrained(out_dir)
        print(f"[{name}] {json.dumps(results[name])}")

    if a.control and len(results) == 2:
        d = results[a.backbone]["eval_f1"] - results["modernbert-large"]["eval_f1"]
        print(json.dumps({"domain_adaptation_f1_gap": round(d, 4),
                          "verdict": "supported" if d > 0 else "not supported"}, indent=2))
        if d <= 0:
            print("\nThe domain-adapted backbone did not beat the control on this data. "
                  "Set backbone: modernbert-large in the extraction specification.",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
