from __future__ import annotations

from uuid import uuid4

from app.core.project_search import search_project
from app.models import Finding, ResearchProject
from tests.test_persistence_reporting import sample_result
from tests.test_universal import service_at


def test_project_search_matches_cyrillic_and_stays_in_selected_case(tmp_path):
    service = service_at(tmp_path)
    project = ResearchProject(
        title="Другой проект", case_number="test", object_description="synthetic"
    )
    service.repository.save_project(project)
    for project_id in (None, project.id):
        result = sample_result()
        result.evidence.id = str(uuid4())
        result.evidence.project_id = project_id
        result.findings = [
            Finding(
                "EXIF",
                "Software",
                "Редактор ИВАНОВ",
                "Synthetic source",
                location="tag 305",
            )
        ]
        service.repository.save(result)
    result = search_project(service.config.database_path, None, "иванов")
    assert len(result.hits) == 1
    assert (
        len(search_project(service.config.database_path, project.id, "иванов").hits)
        == 1
    )
    hit = result.hits[0]
    loaded = service.repository.load(hit["evidence_id"])
    assert loaded.evidence.project_id is None
    assert loaded.findings[0].id == hit["finding_id"]


def test_search_uses_russian_labels_and_returns_explicit_bounded_preview(tmp_path):
    service = service_at(tmp_path)
    result = sample_result()
    result.findings = [
        Finding("PDF Info", "Author", "Иван" + "A" * 900, "test") for _ in range(5)
    ]
    service.repository.save(result)
    found = search_project(service.config.database_path, None, "автор", limit=3)
    assert found.limited and len(found.hits) == 3
    assert found.hits[0]["preview_truncated"]
    assert len(found.hits[0]["preview"]) == 800
    assert len(service.repository.load(result.evidence.id).findings[0].value) == 904


def test_search_query_is_literal_not_sql_or_wildcards(tmp_path):
    service = service_at(tmp_path)
    result = sample_result()
    result.findings = [Finding("EXIF", "Model", "literal 100%", "test")]
    service.repository.save(result)
    assert len(search_project(service.config.database_path, None, "100%").hits) == 1
    assert not search_project(service.config.database_path, None, "' OR 1=1 --").hits
    assert not search_project(service.config.database_path, None, "_").hits
    assert not search_project(service.config.database_path, None, "  ").hits


def test_search_time_limit_is_distinct_from_no_matches(tmp_path):
    service = service_at(tmp_path)
    result = sample_result()
    result.findings = [Finding("EXIF", f"Tag {i}", "value", "test") for i in range(300)]
    service.repository.save(result)
    found = search_project(
        service.config.database_path, None, "no match", timeout_seconds=0
    )
    assert found.interrupted
