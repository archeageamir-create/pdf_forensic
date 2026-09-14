"""Bounded, read-only search across a project's saved metadata.

This initial implementation uses Unicode substring matching, not a lossy search
index. Limits and interruption are explicit so a large case cannot hang the UI.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.resources.labels import category_label, parameter_label


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: list[dict]
    limited: bool = False
    interrupted: bool = False


def search_project(
    database: Path,
    project_id: str | None,
    query: str,
    *,
    limit=200,
    timeout_seconds=5.0,
    cancelled: threading.Event | None = None,
) -> SearchResult:
    query = query.strip().casefold()
    if not query:
        return SearchResult([])
    limit = max(1, min(500, limit))
    deadline = time.monotonic() + timeout_seconds
    hits = []
    interrupted = False
    connection = sqlite3.connect(
        database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1
    )
    connection.row_factory = sqlite3.Row

    def searchable(name, category, source, value, location):
        return " ".join(
            (
                name,
                parameter_label(name),
                category,
                category_label(category),
                source,
                value,
                location,
            )
        ).casefold()

    def stop():
        return int(
            time.monotonic() >= deadline or bool(cancelled and cancelled.is_set())
        )

    try:
        connection.create_function("dfi_search_text", 5, searchable, deterministic=True)
        connection.set_progress_handler(stop, 500)
        try:
            cursor = connection.execute(
                """
                SELECT f.id AS finding_id, e.id AS evidence_id,
                       e.original_name, e.original_path, e.detected_format,
                       f.name, f.category, f.source, f.location,
                       substr(f.value_json, 1, 800) AS preview,
                       length(f.value_json) > 800 AS preview_truncated
                FROM evidence_files e JOIN findings f ON f.evidence_id = e.id
                WHERE e.project_id IS ? AND
                    instr(dfi_search_text(f.name, f.category, f.source, f.value_json, f.location), ?) > 0
                LIMIT ?
            """,
                (project_id, query, limit + 1),
            )
            for row in cursor:
                hits.append(dict(row))
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", None) != sqlite3.SQLITE_INTERRUPT:
                raise
            interrupted = True
    finally:
        connection.close()
    return SearchResult(hits[:limit], len(hits) > limit, interrupted)
