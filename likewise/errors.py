"""Structured failures. The startup gate exits non-zero BEFORE binding
the port and emits a JSON error listing every offending dimension.

This module owns one thing: the shape of a refusal. A refusal is a `kind` plus a list of
dictionaries, each naming what was wrong and, where the raiser can say it, the remedy.
It owns no policy -- nothing here decides what is worth refusing -- and it does no
logging, no HTTP mapping and no formatting for a human reader. Callers that need those
build them from `payload()`.
"""
from __future__ import annotations
import json, sys
from typing import Any


# ---------------------------------------------------------------------------
# The refusal type
# ---------------------------------------------------------------------------
# One exception class, not a hierarchy. The `kind` string is what callers branch on and
# what CI asserts against, so a new refusal is a new string rather than a new subclass
# that every handler would have to learn about.
class SpecError(Exception):
    """Raised by spec loading/validation. Always carries a machine-readable payload.

    `failures` is a list because a gate reports EVERY offending dimension in one pass:
    an operator fixing a specification one refusal per run learns the second problem
    only after fixing the first.
    """

    def __init__(self, kind: str, failures: list[dict[str, Any]]):
        self.kind = kind
        self.failures = failures
        super().__init__(f"{kind}: {len(failures)} failure(s)")

    def payload(self) -> dict[str, Any]:
        return {"error": self.kind, "failure_count": len(self.failures), "failures": self.failures}

    # The payload goes to stderr rather than stdout: stdout is where the entry points
    # write their result, and a refusal mixed into that stream is a refusal a pipeline
    # will parse as a result. sort_keys makes two runs of the same refusal comparable
    # byte for byte, which is what lets CI assert on the object.
    def emit_and_exit(self, code: int = 78) -> None:  # 78 = EX_CONFIG
        json.dump(self.payload(), sys.stderr, indent=2, sort_keys=True)
        sys.stderr.write("\n")
        sys.exit(code)
