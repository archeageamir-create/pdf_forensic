from __future__ import annotations

import os
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.models import AnalysisMode
from app.models.domain import utc_now_iso


@dataclass(frozen=True, slots=True)
class QueueJob:
    id: str
    path: str
    project_id: str | None
    mode: str
    status: str
    size: int
    mtime_ns: int
    evidence_id: str | None
    error: str
    created_at: str
    updated_at: str
    selected_analyzers: str


class JobQueue:
    """Durable local work queue. One process owns execution; producers may enqueue."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL, project_id TEXT,
                    mode TEXT NOT NULL, status TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    evidence_id TEXT, error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);
                CREATE TABLE IF NOT EXISTS watches (
                    path TEXT PRIMARY KEY, project_id TEXT, mode TEXT NOT NULL,
                    recursive INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1
                );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "selected_analyzers" not in columns:
                db.execute(
                    "ALTER TABLE jobs ADD COLUMN selected_analyzers TEXT NOT NULL DEFAULT '[]'"
                )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(
        self,
        path: Path,
        project_id: str | None = None,
        mode: AnalysisMode = AnalysisMode.QUICK,
        *,
        force=False,
        selected_analyzers: set[str] | None = None,
    ) -> str:
        source = path.expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError("Для очереди нужен обычный файл")
        selected = json.dumps(sorted(selected_analyzers or []))
        stat = source.stat()
        # Identity is intentionally source path + filesystem version + target case/mode.
        # Byte hashes remain the integrity authority in the analysis result.
        key = repr(
            (
                os.path.normcase(str(source)),
                stat.st_size,
                stat.st_mtime_ns,
                project_id,
                str(mode),
                selected,
            )
        )
        if force:
            key += str(uuid4())
        job_id = str(uuid4())
        now = utc_now_iso()
        with self.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, ?, 'pending', ?, ?, NULL, '', ?, ?, ?, ?)",
                (
                    job_id,
                    str(source),
                    project_id,
                    str(mode),
                    stat.st_size,
                    stat.st_mtime_ns,
                    now,
                    now,
                    key,
                    selected,
                ),
            )
            return db.execute(
                "SELECT id FROM jobs WHERE dedupe_key = ?", (key,)
            ).fetchone()[0]

    def list_jobs(self, limit: int = 500) -> list[QueueJob]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._job(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self.connection() as db:
            return {
                row[0]: row[1]
                for row in db.execute(
                    "SELECT status, COUNT(*) FROM jobs GROUP BY status"
                )
            }

    def project_in_use(self, project_id: str) -> bool:
        with self.connection() as db:
            pending = db.execute(
                "SELECT 1 FROM jobs WHERE project_id = ? AND status IN ('pending', 'running') LIMIT 1",
                (project_id,),
            ).fetchone()
            watch = db.execute(
                "SELECT 1 FROM watches WHERE project_id = ? LIMIT 1", (project_id,)
            ).fetchone()
            return bool(pending or watch)

    def claim(self) -> QueueJob | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET status = 'running', evidence_id = COALESCE(evidence_id, ?), updated_at = ? WHERE id = ?",
                (str(uuid4()), utc_now_iso(), row["id"]),
            )
            return self._job(
                db.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
            )

    def finish(
        self,
        job_id: str,
        status: str,
        *,
        evidence_id: str | None = None,
        error: str = "",
    ):
        if status not in {"completed", "partial", "failed", "cancelled", "pending"}:
            raise ValueError("Invalid queue status")
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status = ?, evidence_id = COALESCE(?, evidence_id), error = ?, updated_at = ? WHERE id = ?",
                (status, evidence_id, error, utc_now_iso(), job_id),
            )

    def retry(self, job_id: str):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status = 'pending', evidence_id = NULL, error = '', updated_at = ? WHERE id = ? AND status IN ('failed', 'cancelled', 'partial')",
                (utc_now_iso(), job_id),
            )

    def cancel_pending(self, job_id: str):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status = 'cancelled', updated_at = ? WHERE id = ? AND status = 'pending'",
                (utc_now_iso(), job_id),
            )

    def recover_interrupted(self):
        # Call only after acquiring the execution lock.
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET status = 'pending', error = 'Возобновлено после остановки приложения', updated_at = ? WHERE status = 'running'",
                (utc_now_iso(),),
            )

    def save_watch(
        self, path: Path, project_id: str | None, mode: AnalysisMode, recursive=False
    ):
        path = path.expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Выберите существующую папку")
        if mode == AnalysisMode.CUSTOM:
            raise ValueError("Для наблюдения выберите быстрый или полный режим")
        with self.connection() as db:
            db.execute(
                "INSERT INTO watches VALUES (?, ?, ?, ?, 1) ON CONFLICT(path) DO UPDATE SET project_id=excluded.project_id, mode=excluded.mode, recursive=excluded.recursive, enabled=1",
                (str(path), project_id, str(mode), int(recursive)),
            )

    def watches(self) -> list[dict]:
        with self.connection() as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM watches ORDER BY path")
            ]

    def set_watch_enabled(self, path: str, enabled: bool):
        with self.connection() as db:
            db.execute(
                "UPDATE watches SET enabled = ? WHERE path = ?", (int(enabled), path)
            )

    def remove_watch(self, path: str):
        with self.connection() as db:
            db.execute("DELETE FROM watches WHERE path = ?", (path,))

    @staticmethod
    def _job(row) -> QueueJob:
        return QueueJob(**{key: row[key] for key in QueueJob.__dataclass_fields__})


class QueueExecutionLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise RuntimeError(
                "Очередь уже обрабатывается другим экземпляром приложения"
            ) from exc
        return self

    def __exit__(self, *_):
        if self.stream:
            self.stream.close()
            self.stream = None
