from scripts.create_public_source_archive import ROOT, allowed


def test_public_source_keeps_build_instructions_and_training_examples():
    for name in (
        "docs/STANDALONE_BUILD.md",
        "docs/DEPENDENCY_SOURCES.md",
        "docs/user-guide/DocumentForensicInspector-User-Guide-RU.pdf",
        "docs/user-guide/examples/sample.docx",
        "compliance/source-records/component/build.sh",
    ):
        assert allowed(ROOT / name)


def test_public_source_excludes_internal_reports_even_in_new_subfolders():
    for name in (
        "docs/release/QA-Windows-11-0.5.1.md",
        "docs/history/QA-0.5.0.md",
        "docs/validation/run.json",
        "docs/FINAL_REVIEW_2026-10-08.md",
        "docs/UNIVERSAL_ROADMAP.md",
        "docs/release/internal/new-report.md",
    ):
        assert not allowed(ROOT / name)
