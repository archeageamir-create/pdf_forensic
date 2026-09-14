from __future__ import annotations

from unittest.mock import patch

import pytest

from app.adapters.base import AnalysisCancelled
from app.core.daemon import FolderScanner, QueueDaemon
from app.core.job_queue import JobQueue, QueueExecutionLock
from app.models import AnalysisMode
from tests.test_universal import service_at


def source_at(tmp_path):
    path = tmp_path / "sample.bin"
    path.write_bytes(b"synthetic sample")
    return path


def test_queue_deduplicates_persists_and_recovers(tmp_path):
    source = source_at(tmp_path)
    queue = JobQueue(tmp_path / "queue.sqlite3")
    identifier = queue.enqueue(source)
    assert queue.enqueue(source) == identifier
    job = queue.claim()
    assert job.id == identifier and job.status == "running"
    assert queue.claim() is None
    restarted = JobQueue(queue.path)
    restarted.recover_interrupted()
    assert restarted.claim().id == identifier
    restarted.finish(identifier, "completed", evidence_id="result-id")
    assert restarted.list_jobs()[0].evidence_id == "result-id"
    assert restarted.claim() is None
    assert restarted.enqueue(source, force=True) != identifier


def test_queue_modes_and_modified_file_are_distinct(tmp_path):
    source = source_at(tmp_path)
    queue = JobQueue(tmp_path / "queue.sqlite3")
    first = queue.enqueue(source)
    assert queue.enqueue(source, mode=AnalysisMode.FULL) != first
    source.write_bytes(b"changed content")
    assert queue.enqueue(source) != first


def test_lock_prevents_two_execution_owners(tmp_path):
    with QueueExecutionLock(tmp_path / "execution.lock"):
        with pytest.raises(RuntimeError, match="другим"):
            with QueueExecutionLock(tmp_path / "execution.lock"):
                pass
    with QueueExecutionLock(tmp_path / "execution.lock"):
        pass


def test_scanner_waits_until_stable_and_deduplicates_restart(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = source_at(inbox)
    queue = JobQueue(tmp_path / "queue.sqlite3")
    queue.save_watch(inbox, None, AnalysisMode.QUICK)
    scanner = FolderScanner(queue, [], settle_seconds=3)
    assert scanner.scan(now=0) == 0
    source.write_bytes(b"still writing")
    assert scanner.scan(now=2) == 0
    assert scanner.scan(now=4) == 0
    assert scanner.scan(now=5) == 1
    assert scanner.scan(now=6) == 0
    scanner = FolderScanner(queue, [], settle_seconds=3)
    scanner.scan(now=10)
    scanner.scan(now=14)
    assert len(queue.list_jobs()) == 1


def test_scanner_ignores_output_temp_files_and_subfolders_by_default(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    excluded = inbox / "workspace"
    excluded.mkdir()
    source_at(excluded)
    (inbox / "unfinished.part").write_bytes(b"temporary")
    sub = inbox / "sub"
    sub.mkdir()
    source_at(sub)
    source_at(inbox)
    queue = JobQueue(tmp_path / "queue.sqlite3")
    queue.save_watch(inbox, None, AnalysisMode.QUICK)
    scanner = FolderScanner(queue, [excluded], settle_seconds=0)
    scanner.scan(now=0)
    scanner.scan(now=1)
    assert len(queue.list_jobs()) == 1
    queue.save_watch(inbox, None, AnalysisMode.QUICK, recursive=True)
    scanner.scan(now=2)
    scanner.scan(now=3)
    assert len(queue.list_jobs()) == 2


def test_disabled_watch_stops_scanning(tmp_path):
    queue = JobQueue(tmp_path / "queue.sqlite3")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source_at(inbox)
    queue.save_watch(inbox, None, AnalysisMode.QUICK)
    queue.set_watch_enabled(str(inbox), False)
    scanner = FolderScanner(queue, [], settle_seconds=0)
    scanner.scan(now=0)
    scanner.scan(now=1)
    assert not queue.list_jobs()


def test_daemon_completes_and_persists_results(tmp_path):
    service = service_at(tmp_path / "workspace")
    queue = JobQueue(service.config.data_dir / "queue.sqlite3")
    identifier = queue.enqueue(source_at(tmp_path), mode=AnalysisMode.CUSTOM)
    received = []
    daemon = QueueDaemon(service, queue, on_result=received.append)
    daemon.run(once=True)
    job = queue.list_jobs()[0]
    assert job.id == identifier and job.status == "completed"
    assert received[0].evidence.id == job.evidence_id
    assert service.repository.load(job.evidence_id) is not None


def test_daemon_bad_file_does_not_stop_next_job(tmp_path):
    service = service_at(tmp_path / "workspace")
    queue = JobQueue(service.config.data_dir / "queue.sqlite3")
    source = source_at(tmp_path)
    queue.enqueue(source, mode=AnalysisMode.CUSTOM)
    source.unlink()
    good = tmp_path / "good.bin"
    good.write_bytes(b"synthetic good")
    queue.enqueue(good, mode=AnalysisMode.CUSTOM)
    QueueDaemon(service, queue).run(once=True)
    assert queue.counts() == {"failed": 1, "completed": 1}


def test_changed_source_not_silently_analyzed(tmp_path):
    service = service_at(tmp_path / "workspace")
    queue = JobQueue(service.config.data_dir / "queue.sqlite3")
    source = source_at(tmp_path)
    queue.enqueue(source, mode=AnalysisMode.CUSTOM)
    source.write_bytes(b"new version of the source file")
    QueueDaemon(service, queue).run(once=True)
    assert queue.list_jobs()[0].status == "failed"
    assert "изменился" in queue.list_jobs()[0].error


def test_shutdown_requeues_current_but_user_cancel_does_not(tmp_path):
    service = service_at(tmp_path / "workspace")
    queue = JobQueue(service.config.data_dir / "queue.sqlite3")
    queue.enqueue(source_at(tmp_path), mode=AnalysisMode.CUSTOM)
    daemon = QueueDaemon(service, queue, isolate=False)

    def stop(*args, **kwargs):
        daemon.stop()
        raise AnalysisCancelled()

    with patch.object(service, "analyze_file", side_effect=stop):
        daemon.process_one()
    assert queue.list_jobs()[0].status == "pending"
    daemon = QueueDaemon(service, queue, isolate=False)
    with patch.object(service, "analyze_file", side_effect=AnalysisCancelled):
        daemon.process_one()
    assert queue.list_jobs()[0].status == "cancelled"


def test_retry_cannot_take_running_or_successful_jobs(tmp_path):
    queue = JobQueue(tmp_path / "queue.sqlite3")
    identifier = queue.enqueue(source_at(tmp_path))
    queue.claim()
    queue.retry(identifier)
    assert queue.list_jobs()[0].status == "running"
    queue.finish(identifier, "failed", error="test")
    queue.retry(identifier)
    assert queue.list_jobs()[0].status == "pending"
    queue.cancel_pending(identifier)
    assert queue.list_jobs()[0].status == "cancelled"


def test_restart_recovers_result_saved_before_acknowledgment(tmp_path):
    service = service_at(tmp_path / "workspace")
    queue = JobQueue(service.config.data_dir / "queue.sqlite3")
    source = source_at(tmp_path)
    queue.enqueue(source, mode=AnalysisMode.CUSTOM)
    job = queue.claim()
    result = service.analyze_file(
        source, mode=AnalysisMode.CUSTOM, result_id=job.evidence_id
    )
    # Simulate power loss after committing the report, before acknowledging the job.
    received = []
    with patch.object(
        service, "analyze_file", side_effect=AssertionError("must reuse saved report")
    ):
        QueueDaemon(service, queue, isolate=False, on_result=received.append).run(
            once=True
        )
    assert queue.list_jobs()[0].status == "completed"
    assert received[0].evidence.id == result.evidence.id
    assert len(service.repository.list_evidence_ids()) == 1


def test_project_with_pending_jobs_or_watches_is_in_use(tmp_path):
    queue = JobQueue(tmp_path / "queue.sqlite3")
    identifier = queue.enqueue(source_at(tmp_path), project_id="case-1")
    assert queue.project_in_use("case-1")
    queue.cancel_pending(identifier)
    assert not queue.project_in_use("case-1")
    queue.save_watch(tmp_path, "case-1", AnalysisMode.QUICK)
    assert queue.project_in_use("case-1")
    queue.remove_watch(str(tmp_path.resolve()))
    assert not queue.project_in_use("case-1")
