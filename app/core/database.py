from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.models import (
    AnalysisResult,
    AnalysisMode,
    EvidenceFile,
    FileKind,
    Finding,
    FindingLevel,
    IntegrityStatus,
    ResearchProject,
    ToolRun,
    ToolRunStatus,
)


class AnalysisRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(_SCHEMA)
            for column, declaration in (
                ("initiator", "TEXT NOT NULL DEFAULT ''"),
                ("legal_basis", "TEXT NOT NULL DEFAULT ''"),
                ("source_description", "TEXT NOT NULL DEFAULT ''"),
                ("examiner_name", "TEXT NOT NULL DEFAULT ''"),
                ("notes", "TEXT NOT NULL DEFAULT ''"),
                ("user_conclusions", "TEXT NOT NULL DEFAULT ''"),
                ("created_at", "TEXT NOT NULL DEFAULT ''"),
            ):
                _ensure_column(connection, "projects", column, declaration)
            _ensure_column(connection, "projects", "updated_at", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "evidence_files", "analysis_mode", "TEXT NOT NULL DEFAULT 'full'")
            _ensure_column(connection, "evidence_files", "user_notes", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "evidence_files", "user_conclusions", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "analyses", "artifacts_json", "TEXT NOT NULL DEFAULT '{}'")
            _ensure_column(connection, "analyses", "summary_json", "TEXT NOT NULL DEFAULT '[]'")
            for column, declaration in (
                ("description", "TEXT NOT NULL DEFAULT ''"),
                ("details", "TEXT NOT NULL DEFAULT ''"),
                ("location", "TEXT NOT NULL DEFAULT ''"),
                ("user_mark", "TEXT NOT NULL DEFAULT ''"),
                ("include_in_report", "INTEGER NOT NULL DEFAULT 1"),
            ):
                _ensure_column(connection, "findings", column, declaration)
            _ensure_column(
                connection, "tool_runs", "duration_ms", "INTEGER NOT NULL DEFAULT 0"
            )
            _ensure_column(
                connection,
                "tool_runs",
                "parsed_result_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )

    def save_project(self, project: ResearchProject) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO projects
                (id, title, case_number, object_description, initiator, legal_basis,
                 source_description, examiner_name, notes, user_conclusions, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    case_number=excluded.case_number,
                    object_description=excluded.object_description,
                    initiator=excluded.initiator,
                    legal_basis=excluded.legal_basis,
                    source_description=excluded.source_description,
                    examiner_name=excluded.examiner_name,
                    notes=excluded.notes,
                    user_conclusions=excluded.user_conclusions,
                    updated_at=excluded.updated_at
                """,
                (
                    project.id,
                    project.title,
                    project.case_number,
                    project.object_description,
                    project.initiator,
                    project.legal_basis,
                    project.source_description,
                    project.examiner_name,
                    project.notes,
                    project.user_conclusions,
                    project.created_at,
                    project.updated_at,
                ),
            )

    def list_projects(self) -> list[ResearchProject]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [ResearchProject(**dict(row)) for row in rows]

    def get_project(self, project_id: str) -> ResearchProject | None:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return ResearchProject(**dict(row)) if row else None

    def delete_project(self, project_id: str) -> None:
        with self._connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM evidence_files WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
            if count:
                raise ValueError("Project contains evidence files")
            connection.execute(
                "UPDATE audit_log SET project_id = NULL WHERE project_id = ?", (project_id,)
            )
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.log_event("project_deleted", project_id, "deleted")

    def list_evidence_ids(self, project_id: str | None = None) -> list[str]:
        with self._connection() as connection:
            if project_id is None:
                rows = connection.execute(
                    "SELECT id FROM evidence_files ORDER BY added_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id FROM evidence_files WHERE project_id = ? ORDER BY added_at DESC",
                    (project_id,),
                ).fetchall()
        return [str(row[0]) for row in rows]

    def list_evidence_summaries(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Lightweight sidebar records; None means the unassigned research group."""
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("""
                SELECT e.id, e.original_name, e.original_path, e.detected_format,
                       e.sha256, e.kind, e.analysis_mode, e.added_at, a.incomplete
                FROM evidence_files e JOIN analyses a ON a.evidence_id = e.id
                WHERE e.project_id IS ? ORDER BY e.added_at DESC, e.rowid DESC
            """, (project_id,)).fetchall()
        return [dict(row) for row in rows]

    def save(self, result: AnalysisResult) -> None:
        evidence = result.evidence
        with self._connection() as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                """
                INSERT INTO evidence_files
                (id, project_id, original_path, working_copy_path, original_name, extension,
                 detected_format, mime_type, sha256, sha1, md5, working_copy_sha256,
                 integrity_status, size_bytes, kind, added_at, file_created_at, file_modified_at,
                 analysis_mode, user_notes, user_conclusions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id=excluded.project_id,
                    original_path=excluded.original_path,
                    working_copy_path=excluded.working_copy_path,
                    original_name=excluded.original_name,
                    extension=excluded.extension,
                    detected_format=excluded.detected_format,
                    mime_type=excluded.mime_type,
                    sha256=excluded.sha256,
                    sha1=excluded.sha1,
                    md5=excluded.md5,
                    working_copy_sha256=excluded.working_copy_sha256,
                    integrity_status=excluded.integrity_status,
                    size_bytes=excluded.size_bytes,
                    kind=excluded.kind,
                    added_at=excluded.added_at,
                    file_created_at=excluded.file_created_at,
                    file_modified_at=excluded.file_modified_at,
                    analysis_mode=excluded.analysis_mode,
                    user_notes=excluded.user_notes,
                    user_conclusions=excluded.user_conclusions
                """,
                (
                    evidence.id,
                    evidence.project_id,
                    evidence.original_path,
                    evidence.working_copy_path,
                    evidence.original_name,
                    evidence.extension,
                    evidence.detected_format,
                    evidence.mime_type,
                    evidence.sha256,
                    evidence.sha1,
                    evidence.md5,
                    evidence.working_copy_sha256,
                    _enum_value(evidence.integrity_status),
                    evidence.size_bytes,
                    _enum_value(evidence.kind),
                    evidence.added_at,
                    evidence.file_created_at,
                    evidence.file_modified_at,
                    _enum_value(evidence.analysis_mode),
                    evidence.user_notes,
                    evidence.user_conclusions,
                ),
            )
            connection.execute("DELETE FROM findings WHERE evidence_id = ?", (evidence.id,))
            connection.execute("DELETE FROM tool_runs WHERE evidence_id = ?", (evidence.id,))
            connection.execute(
                """
                INSERT INTO analyses
                (evidence_id, analyzed_at, errors_json, incomplete, artifacts_json, summary_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    analyzed_at=excluded.analyzed_at,
                    errors_json=excluded.errors_json,
                    incomplete=excluded.incomplete,
                    artifacts_json=excluded.artifacts_json,
                    summary_json=excluded.summary_json
                """,
                (
                    evidence.id,
                    result.analyzed_at,
                    _json(result.errors),
                    int(result.incomplete),
                    _json(result.artifacts),
                    _json(result.summary),
                ),
            )
            connection.executemany(
                """
                INSERT INTO findings
                (id, evidence_id, category, name, value_json, source, level, conflict,
                 description, details, location, user_mark, include_in_report)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        evidence.id,
                        item.category,
                        item.name,
                        _json(item.value),
                        item.source,
                        _enum_value(item.level),
                        int(item.conflict),
                        item.description,
                        item.details,
                        item.location,
                        item.user_mark,
                        int(item.include_in_report),
                    )
                    for item in result.findings
                ],
            )
            connection.executemany(
                """
                INSERT INTO tool_runs
                (id, evidence_id, tool_name, command_json, version, stdout, stderr,
                 exit_code, status, started_at, finished_at, duration_ms, parsed_result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run.id,
                        evidence.id,
                        run.tool_name,
                        _json(run.command),
                        run.version,
                        run.stdout,
                        run.stderr,
                        run.exit_code,
                        _enum_value(run.status),
                        run.started_at,
                        run.finished_at,
                        run.duration_ms,
                        _json(run.parsed_result),
                    )
                    for run in result.tool_runs
                ],
            )

    def load(self, evidence_id: str) -> AnalysisResult | None:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            evidence_row = connection.execute(
                """
                SELECT e.*, a.analyzed_at, a.errors_json, a.incomplete,
                       a.artifacts_json, a.summary_json
                FROM evidence_files e JOIN analyses a ON a.evidence_id = e.id
                WHERE e.id = ?
                """,
                (evidence_id,),
            ).fetchone()
            if evidence_row is None:
                return None
            finding_rows = connection.execute(
                "SELECT * FROM findings WHERE evidence_id = ? ORDER BY rowid", (evidence_id,)
            ).fetchall()
            run_rows = connection.execute(
                "SELECT * FROM tool_runs WHERE evidence_id = ? ORDER BY rowid", (evidence_id,)
            ).fetchall()

        evidence = EvidenceFile(
            id=evidence_row["id"],
            project_id=evidence_row["project_id"],
            original_path=evidence_row["original_path"],
            working_copy_path=evidence_row["working_copy_path"],
            original_name=evidence_row["original_name"],
            extension=evidence_row["extension"],
            detected_format=evidence_row["detected_format"],
            mime_type=evidence_row["mime_type"],
            sha256=evidence_row["sha256"],
            sha1=evidence_row["sha1"],
            md5=evidence_row["md5"],
            working_copy_sha256=evidence_row["working_copy_sha256"],
            integrity_status=IntegrityStatus(evidence_row["integrity_status"]),
            size_bytes=evidence_row["size_bytes"],
            kind=FileKind(evidence_row["kind"]),
            added_at=evidence_row["added_at"],
            file_created_at=evidence_row["file_created_at"],
            file_modified_at=evidence_row["file_modified_at"],
            analysis_mode=AnalysisMode(evidence_row["analysis_mode"]),
            user_notes=evidence_row["user_notes"],
            user_conclusions=evidence_row["user_conclusions"],
        )
        findings = [
            Finding(
                id=row["id"],
                category=row["category"],
                name=row["name"],
                value=json.loads(row["value_json"]),
                source=row["source"],
                level=FindingLevel(row["level"]),
                conflict=bool(row["conflict"]),
                description=row["description"],
                details=row["details"],
                location=row["location"],
                user_mark=row["user_mark"],
                include_in_report=bool(row["include_in_report"]),
            )
            for row in finding_rows
        ]
        runs = [
            ToolRun(
                id=row["id"],
                tool_name=row["tool_name"],
                command=json.loads(row["command_json"]),
                version=row["version"],
                stdout=row["stdout"],
                stderr=row["stderr"],
                exit_code=row["exit_code"],
                status=ToolRunStatus(row["status"]),
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                duration_ms=row["duration_ms"],
                parsed_result=json.loads(row["parsed_result_json"]),
            )
            for row in run_rows
        ]
        return AnalysisResult(
            evidence=evidence,
            findings=findings,
            tool_runs=runs,
            analyzed_at=evidence_row["analyzed_at"],
            errors=json.loads(evidence_row["errors_json"]),
            incomplete=bool(evidence_row["incomplete"]),
            artifacts=json.loads(evidence_row["artifacts_json"]),
            summary=json.loads(evidence_row["summary_json"]),
        )

    def update_finding_mark(self, finding_id: str, mark: str, include: bool = True) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE findings SET user_mark = ?, include_in_report = ? WHERE id = ?",
                (mark, int(include), finding_id),
            )

    def update_evidence_notes(self, evidence_id: str, notes: str, conclusions: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE evidence_files SET user_notes = ?, user_conclusions = ? WHERE id = ?",
                (notes, conclusions, evidence_id),
            )

    def log_event(
        self, action: str, object_id: str, result: str, project_id: str | None = None, user: str = ""
    ) -> None:
        from app.models.domain import utc_now_iso

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (timestamp, project_id, user_name, action, object_id, result)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), project_id, user, action, object_id, result),
            )

    def list_audit(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            if project_id:
                rows = connection.execute(
                    "SELECT * FROM audit_log WHERE project_id = ? ORDER BY id", (project_id,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _enum_value(value: Any) -> str:
    """Serialize StrEnum values while tolerating GUI-provided plain strings."""
    return str(getattr(value, "value", value))


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, case_number TEXT NOT NULL,
    object_description TEXT NOT NULL, initiator TEXT NOT NULL, legal_basis TEXT NOT NULL,
    source_description TEXT NOT NULL, examiner_name TEXT NOT NULL, notes TEXT NOT NULL,
    user_conclusions TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_files (
    id TEXT PRIMARY KEY, project_id TEXT, original_path TEXT NOT NULL,
    working_copy_path TEXT NOT NULL, original_name TEXT NOT NULL, extension TEXT NOT NULL,
    detected_format TEXT NOT NULL, mime_type TEXT NOT NULL, sha256 TEXT NOT NULL,
    sha1 TEXT NOT NULL, md5 TEXT NOT NULL, working_copy_sha256 TEXT NOT NULL,
    integrity_status TEXT NOT NULL, size_bytes INTEGER NOT NULL, kind TEXT NOT NULL,
    added_at TEXT NOT NULL, file_created_at TEXT NOT NULL, file_modified_at TEXT NOT NULL,
    analysis_mode TEXT NOT NULL, user_notes TEXT NOT NULL, user_conclusions TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS analyses (
    evidence_id TEXT PRIMARY KEY, analyzed_at TEXT NOT NULL, errors_json TEXT NOT NULL,
    incomplete INTEGER NOT NULL, artifacts_json TEXT NOT NULL, summary_json TEXT NOT NULL,
    FOREIGN KEY (evidence_id) REFERENCES evidence_files(id)
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL, category TEXT NOT NULL, name TEXT NOT NULL,
    value_json TEXT NOT NULL, source TEXT NOT NULL, level TEXT NOT NULL,
    conflict INTEGER NOT NULL, description TEXT NOT NULL, details TEXT NOT NULL,
    location TEXT NOT NULL, user_mark TEXT NOT NULL, include_in_report INTEGER NOT NULL,
    FOREIGN KEY (evidence_id) REFERENCES evidence_files(id)
);
CREATE TABLE IF NOT EXISTS tool_runs (
    id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL, tool_name TEXT NOT NULL,
    command_json TEXT NOT NULL, version TEXT NOT NULL, stdout TEXT NOT NULL,
    stderr TEXT NOT NULL, exit_code INTEGER, status TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL, duration_ms INTEGER NOT NULL, parsed_result_json TEXT NOT NULL,
    FOREIGN KEY (evidence_id) REFERENCES evidence_files(id)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, project_id TEXT,
    user_name TEXT NOT NULL, action TEXT NOT NULL, object_id TEXT NOT NULL, result TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_sha256 ON evidence_files(sha256);
CREATE INDEX IF NOT EXISTS idx_evidence_project ON evidence_files(project_id, added_at);
CREATE INDEX IF NOT EXISTS idx_findings_evidence ON findings(evidence_id);
CREATE INDEX IF NOT EXISTS idx_runs_evidence ON tool_runs(evidence_id);
"""
