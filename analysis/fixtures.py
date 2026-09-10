"""Synthetic cell populations for cross-validation and simulation.

Every function here builds the same `cell` dictionary the engine passes around, so that
the reference implementations in `crossvalidate` and the studies in `simulate` consume
exactly the structure `likewise.stats` consumes. Nothing is adapted, reshaped or
simplified on the way in; a check that had to reshape its input would be checking the
reshaping.

A cell is:

    values            list[float]  the tested dimension for every record in the cell,
                                   index 0 being the denied record by convention
    labels            list[int]    1 for the denied record, 0 for each approved one
    midranks          list[float]  core.midranks(values, higher_is_worse)
    observed_midrank  float        the denied record's midrank
    direction         str          "higher_is_worse" | "lower_is_worse"
    threshold         float        the pair's decisive threshold, in dimension units

Two properties of real HMDA cells are reproduced deliberately, because both of them
break naive statistics and neither shows up in cells drawn from a continuous
distribution:

  TIES. Published values are binned -- loan amount and property value at $10,000 bin
  midpoints, income to $1,000, DTI to an integer or a band. Ties are the rule, so the
  generators quantise. A reference implementation that agrees with the engine on
  distinct values and diverges on ties has found nothing.

  TINY STRATA. The median cell holds three records. Asymptotics inside a cell are
  meaningless at that size, which is the entire reason the design pools across cells
  instead of testing within them.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from likewise import core


# The DTI band structure Regulation C actually publishes: exact integers in [36, 49],
# coarse bands either side. Sampling from this rather than from a Gaussian is what makes
# the tie structure realistic -- roughly half of a real column lands on four values.
DTI_PUBLISHED_LEVELS = [20.0, 30.0, *range(36, 50), 50.0, 60.0]


def make_cell(values, direction: str = "higher_is_worse", threshold: float = 1.0,
              denied_index: int = 0) -> dict:
    """Assemble one cell in the engine's own shape.

    `denied_index` exists so a caller can place the denial anywhere in the cell; the
    engine's convention is index 0, and every generator here honours it, but the
    permutation reference needs to move the label and must not have to rebuild the dict
    by hand to do so.
    """
    vals = [float(v) for v in values]
    hiw = direction == "higher_is_worse"
    mr = core.midranks(vals, higher_is_worse=hiw)
    labels = [0] * len(vals)
    labels[denied_index] = 1
    return {"values": vals, "labels": labels, "midranks": mr,
            "observed_midrank": mr[denied_index], "direction": direction,
            "threshold": float(threshold)}


def null_cells(n_cells: int = 300, rng: np.random.Generator | None = None,
               size_lo: int = 2, size_hi: int = 8, quantise: float = 1.0,
               threshold: float = 1.0, direction: str = "higher_is_worse") -> list[dict]:
    """Cells drawn under a TRUE null: the denial label is independent of the value.

    Construction: draw the cell's values from a single distribution, then let index 0 be
    the denied record. Because every value in the cell comes from the same distribution
    and the label is assigned without reference to the value, exchangeability holds by
    construction rather than by assumption -- which is what makes this population usable
    as the reference for a type-I error study.

    `quantise` is the bin width. At 1.0 the values are integers and ties are frequent;
    at a small value the cells are effectively continuous, which is useful only for
    isolating whether a disagreement is caused by the tie handling.
    """
    rng = rng or np.random.default_rng(20260910)
    cells = []
    for _ in range(n_cells):
        # Cell sizes are drawn small and right-skewed on purpose. A uniform draw over a
        # wide range would produce a population where the pooled test is dominated by a
        # handful of large cells, which is the opposite of the real design.
        n = int(rng.integers(size_lo, size_hi + 1))
        # One centre per cell: cells differ from each other, records within a cell do
        # not. That is precisely the stratified structure the pooled test assumes, and
        # the between-cell spread is what makes pooling non-trivial.
        centre = float(rng.normal(38.0, 6.0))
        raw = rng.normal(centre, 4.0, size=n)
        vals = np.round(raw / quantise) * quantise
        cells.append(make_cell(vals, direction=direction, threshold=threshold))
    return cells


def shifted_cells(n_cells: int = 300, shift: float = 1.0,
                  rng: np.random.Generator | None = None, size_lo: int = 2,
                  size_hi: int = 8, quantise: float = 1.0,
                  threshold: float = 1.0) -> list[dict]:
    """Cells under an alternative: the denied record sits `shift` units BETTER.

    This is the location-shift alternative van Elteren's weight is optimal against, and
    the direction is the one the product cares about -- denials that look better than
    their cell on the dimension their own stated reason names. `shift` is in dimension
    units, so on DTI a shift of 1.0 is one percentage point.
    """
    rng = rng or np.random.default_rng(20260910)
    cells = []
    for _ in range(n_cells):
        n = int(rng.integers(size_lo, size_hi + 1))
        centre = float(rng.normal(38.0, 6.0))
        raw = list(rng.normal(centre, 4.0, size=n))
        # Subtract on a higher_is_worse dimension: lower is better, so the denied record
        # is shifted toward the good end. The shift is applied BEFORE quantisation, so a
        # shift smaller than the bin width partially disappears -- which is the real
        # effect coarsening has on power and must not be hidden by shifting afterwards.
        raw[0] = raw[0] - shift
        vals = np.round(np.array(raw) / quantise) * quantise
        cells.append(make_cell(vals, threshold=threshold))
    return cells


def published_dti_cells(n_cells: int = 300,
                        rng: np.random.Generator | None = None) -> list[dict]:
    """Cells whose values are drawn from the DTI levels Regulation C actually publishes.

    The tie structure here is severe by design: with only eighteen attainable levels and
    cells of two to eight records, a large share of cells are entirely tied and can
    contribute nothing to any rank statistic. That is not a defect of the fixture. It is
    the measured reason 81.5% of DTI denials are structurally incapable of a finding,
    reproduced in a form the studies can vary.
    """
    rng = rng or np.random.default_rng(20260910)
    levels = np.array(DTI_PUBLISHED_LEVELS, dtype=float)
    cells = []
    for _ in range(n_cells):
        n = int(rng.integers(2, 9))
        # A triangular-ish weighting toward the middle of the band range, which is where
        # the exact integers live and where real filings concentrate.
        w = np.exp(-0.5 * ((levels - 42.0) / 6.0) ** 2)
        vals = rng.choice(levels, size=n, p=w / w.sum())
        cells.append(make_cell(vals, threshold=1.0))
    return cells


def binomial_trials(n: int, p: float, rng: np.random.Generator | None = None) -> int:
    """One binomial draw -- the input the Clopper-Pearson bound consumes."""
    rng = rng or np.random.default_rng(20260910)
    return int(rng.binomial(n, p))
