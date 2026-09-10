"""Runtime tuning, read from the environment.

The engine's memory and thread budget is an operator decision, not a source-code
constant. It lived as a default argument on one function, which meant raising the
container's `--memory` did nothing: DuckDB stayed capped at the hardcoded value and the
operator had no way to tell from the outside.

One module so the load path and the scan path cannot drift to different budgets — the
load is the memory-heavy step, and for a long time it set no limit at all while the
documentation claimed otherwise.

What this module owns: reading two environment variables and clamping them to values
the engine can actually honour. What it does NOT own: applying them. Nothing here talks
to DuckDB; the loader and the scanner each issue their own `SET`, and this module only
answers what the numbers should be.
"""
from __future__ import annotations
import os

# DuckDB's own floor for this pipeline. Below it a three-row file fails too, so a
# smaller value is a misconfiguration rather than a tighter budget.
MIN_MEMORY_MB = 512


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
# Both readers treat an unset variable and an unparsable one the same way: fall back to
# the default rather than raise. An operator who typed "8g" instead of "8192" should get
# a working process on the documented default, not a service that will not start -- and
# the value is visible on /health, so the mistake is discoverable.
def memory_mb(default: int = 2048) -> int:
    raw = os.environ.get("LIKEWISE_MEMORY_MB")
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    # Clamped UP, never down. A configured value below DuckDB's own floor does not make
    # the run leaner; it makes a three-row file fail, and the failure reads like a data
    # problem rather than a misconfiguration.
    return max(MIN_MEMORY_MB, v)


def threads(default: int = 2) -> int:
    raw = os.environ.get("LIKEWISE_THREADS")
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default
