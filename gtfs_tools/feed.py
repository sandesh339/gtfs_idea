"""In-memory GTFS feed model.

A feed is a set of CSV tables (agency.txt, stops.txt, ...). We keep every
value as a string (GTFS is all text) so that ids never get coerced to floats
and empty optional fields never become NaN. That keeps edits deterministic,
which matters because the same feed is graded by an oracle.

Both execution paths (function calling and code generation) operate on a
loaded Feed and serialise it back out for validation.
"""
from __future__ import annotations

import csv
import os
from typing import Dict, List


Row = Dict[str, str]


class Feed:
    def __init__(self) -> None:
        # table name (e.g. "stops.txt") -> list of row dicts
        self.tables: Dict[str, List[Row]] = {}
        # table name -> ordered column headers (preserved on save)
        self.headers: Dict[str, List[str]] = {}

    # ----- io -------------------------------------------------------------
    @classmethod
    def load(cls, directory: str) -> "Feed":
        feed = cls()
        for name in os.listdir(directory):
            if not name.endswith(".txt"):
                continue
            path = os.path.join(directory, name)
            with open(path, newline="", encoding="utf-8-sig") as fh:
                # restval="" so short rows (missing trailing commas) fill empty
                # strings, not None — otherwise a save/reload round-trip would
                # look like a change to every such row.
                reader = csv.DictReader(fh, restval="")
                feed.headers[name] = list(reader.fieldnames or [])
                feed.tables[name] = [dict(r) for r in reader]
        return feed

    def save(self, directory: str) -> None:
        os.makedirs(directory, exist_ok=True)
        for name, rows in self.tables.items():
            path = os.path.join(directory, name)
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=self.headers[name])
                writer.writeheader()
                writer.writerows(rows)

    # ----- table helpers --------------------------------------------------
    def table(self, name: str) -> List[Row]:
        """Return rows for a table, creating an empty one if absent."""
        if name not in self.tables:
            self.tables[name] = []
            self.headers[name] = []
        return self.tables[name]

    def ensure_column(self, table: str, column: str, default: str = "") -> None:
        """Add a column (with a default) to a table if it is not present."""
        if column not in self.headers.get(table, []):
            self.headers.setdefault(table, []).append(column)
            for row in self.tables.get(table, []):
                row.setdefault(column, default)

    def new_row(self, table: str) -> Row:
        """A blank row with every current column present and empty."""
        return {col: "" for col in self.headers.get(table, [])}

    def copy(self) -> "Feed":
        """Deep copy — used by the chat session so a failed edit can't corrupt
        the live feed (edit a clone, commit only on success)."""
        clone = Feed()
        clone.headers = {t: list(cols) for t, cols in self.headers.items()}
        clone.tables = {t: [dict(r) for r in rows] for t, rows in self.tables.items()}
        return clone
