"""Shared helpers for storage modules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def iso_now() -> str:
    """UTC ISO-8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def row_to_dict(row: Any) -> dict:
    """Convert sqlite3.Row to plain dict, or return {} for None."""
    return dict(row) if row else {}
