"""Where things live on disk.

One place decides it, because the answer differs between a checkout and a container:
in a checkout the data sits under ./data beside the code, and in a container the code
is read-only at /app while everything mutable is a volume at /data. Hardcoding the
relative path works in exactly one of those.

This module owns the NAMES of the mutable roots and the shape of the curated tree
beneath them. It owns nothing else: it creates no directories, reads no files, and
knows nothing about what a snapshot or a scan contains. A lint over the package asserts
that no other module spells one of these paths out.
"""
from __future__ import annotations
import os


# ---------------------------------------------------------------------------
# Mutable roots
# ---------------------------------------------------------------------------
# Each root is read from the environment on every call, never captured at import. A
# module-level constant would freeze whichever root happened to be set when the module
# was first imported, which is exactly what breaks under a test that relocates the tree.
# The container sets LIKEWISE_DATA alone and the other three follow from it.
def data_root() -> str:
    return os.environ.get("LIKEWISE_DATA", "data")


def curated_root() -> str:
    return os.environ.get("LIKEWISE_CURATED", os.path.join(data_root(), "curated"))


def inbox() -> str:
    return os.environ.get("LIKEWISE_INBOX", os.path.join(data_root(), "inbox"))


def store_root() -> str:
    return os.environ.get("LIKEWISE_STORE", os.path.join(data_root(), "store"))


# ---------------------------------------------------------------------------
# The curated tree
# ---------------------------------------------------------------------------
# The layout is Hive-style (`snapshot=`, `activity_year=`, `lei=`) because DuckDB reads
# those directory names as columns, so a scan can select one filer-year by globbing
# rather than by filtering a whole snapshot. The three functions below are the only
# description of that layout; the loader writes into it and the API reads from it.
def snapshot_dir(snapshot_id: str) -> str:
    return os.path.join(curated_root(), f"snapshot={snapshot_id}")


def parquet_glob(snapshot_id: str, year, lei: str) -> str:
    return os.path.join(snapshot_dir(snapshot_id), f"activity_year={year}",
                        f"lei={lei}", "*.parquet")


def manifest_path(snapshot_id: str) -> str:
    return os.path.join(snapshot_dir(snapshot_id), "manifest.json")
