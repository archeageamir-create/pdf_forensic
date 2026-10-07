from pathlib import Path

import pytest

from app.adapters.extended_pdf_tools import PopplerAdapter
from app.models import ToolRun, ToolRunStatus


@pytest.mark.parametrize("writes_pages", [True, False])
def test_rendering_uses_private_short_path_and_requires_real_pages(tmp_path, writes_pages):
    case = tmp_path / ("long-case-" * 12) / ("nested-" * 12)
    case.mkdir(parents=True)
    revisions = [(i, case / f"revision-{i}.pdf") for i in (1, 2)]
    for _, path in revisions:
        path.write_bytes(b"synthetic input for mocked renderer")
    adapter = PopplerAdapter(None, revisions=revisions)
    temporary_dirs = []

    def run(name, command, version):
        if name.startswith("poppler/render-"):
            prefix = Path(command[-1])
            assert prefix.parent != case and not prefix.is_relative_to(case)
            temporary_dirs.append(prefix.parent)
            if writes_pages:
                Path(str(prefix) + "-1.png").write_bytes(name.encode())
        return ToolRun(name, command, "test", "", "", 0, ToolRunStatus.COMPLETED, "", "")

    adapter.runner.run = run
    result = adapter.analyze(case / "working-copy.pdf")
    renders = [run for run in result.tool_runs if run.tool_name.startswith("poppler/render-")]
    assert len(renders) == 2
    assert all(run.status == (ToolRunStatus.COMPLETED if writes_pages else ToolRunStatus.FAILED) for run in renders)
    assert not any(folder.exists() for folder in temporary_dirs)
    groups = result.artifacts["revision_renders"]
    assert len(groups) == 2
    for group in groups:
        assert bool(group["pages"]) == writes_pages
        if writes_pages:
            page = Path(group["pages"][0]["path"])
            assert page.parent == case / "revision-renders"
            assert page.read_bytes() == f"poppler/render-revision-{group['revision']:03d}".encode()
