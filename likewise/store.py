"""Storage port.

Five operations. `create` is the only conditional one -- it fails if the key exists,
which is what makes two concurrent scan requests race safely.

One backend: the local filesystem. That runs development, CI and the whole product
with no cloud account, which is the point. A second object-storage backend would
implement the same five methods; it is deliberately not written until something needs
it, because an unused abstraction drifts out of date faster than a missing one hurts.

Plain functions behind a small class; no Protocol, no injection container.

What this module owns: putting bytes under a key and getting them back, atomically, and
refusing a key that would escape the root. What it does NOT own: what those bytes mean.
It knows nothing of scans, findings or egress, and it applies no schema -- a caller that
writes an un-egressed object here will succeed, which is why the egress contract is
enforced at the boundary rather than in the store.
"""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path


# ---------------------------------------------------------------------------
# The local filesystem backend
# ---------------------------------------------------------------------------
class LocalStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        # Resolved BEFORE the comparison, so a key containing `..` is caught by where it
        # lands rather than by what it looks like. Keys reach this class from route
        # parameters, and a traversal that reads or overwrites a file outside the store
        # is the failure this one line exists to prevent.
        if not str(p).startswith(str(self.root)):
            raise ValueError(f"key escapes store root: {key}")
        return p

    # -- the five operations -------------------------------------------------
    def get(self, key: str) -> tuple[bytes, str]:
        p = self._p(key)
        body = p.read_bytes()
        return body, hashlib.sha256(body).hexdigest()

    def put(self, key: str, body: bytes) -> str:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Written to a sibling temporary file and renamed, never written in place: a
        # reader that opens the key while a writer is part-way through a direct write
        # gets a truncated JSON document, and the scan record is read by the UI on every
        # page load while the background runner is updating it.
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, p)          # atomic for a SINGLE object on a POSIX fs
        return hashlib.sha256(body).hexdigest()

    def create(self, key: str, body: bytes) -> str:
        """Create-if-absent. The only conditional operation.

        O_CREAT|O_EXCL, not `exists()` then write: the check-then-act version has a
        window between the two in which a second request creates the same key, and two
        scan requests for the same tuple would both believe they won it.
        """
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            raise FileExistsError(f"object already exists: {key}") from exc
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        return hashlib.sha256(body).hexdigest()

    def list(self, prefix: str) -> list[str]:
        base = self._p(prefix)
        if not base.exists():
            return []
        if base.is_file():
            return [prefix]
        out = []
        # `.tmp` files are the half-written objects `put` is in the middle of renaming.
        # Listing one would hand a caller a key whose contents are incomplete and whose
        # name is about to disappear.
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.name.endswith(".tmp"):
                out.append(str(p.relative_to(self.root)))
        return out

    def uri(self, key: str) -> str:
        """Path handed to DuckDB. The engine reads objects
        directly rather than through this port; uri() is that seam, named."""
        return str(self._p(key))

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    # -- JSON convenience ----------------------------------------------------
    # sort_keys and a fixed indent so two writes of the same object are byte-identical.
    # Stored artifacts are diffed between runs and hashed for the reproducibility claim;
    # dictionary insertion order is not a property either of those should depend on.
    def get_json(self, key: str) -> dict:
        return json.loads(self.get(key)[0].decode())

    def put_json(self, key: str, obj) -> str:
        return self.put(key, json.dumps(obj, indent=2, sort_keys=True, default=str).encode())


# ---------------------------------------------------------------------------
# Opening a store
# ---------------------------------------------------------------------------
# The default root is resolved here, at call time, rather than being written at any call
# site: in a container the code is read-only at /app and the volume is elsewhere, so a
# hardcoded root writes somewhere the operator cannot see.
def open_store(root: str | Path | None = None) -> LocalStore:
    from . import paths
    return LocalStore(root or paths.store_root())
