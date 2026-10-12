import json

import pytest

from app.adapters.extended_pdf_tools import VeraPdfAdapter
from app.models import ToolRun, ToolRunStatus


@pytest.mark.parametrize("features", [
    '<report><jobs><job><featuresReport><lowLevelInfo><pdfVersion>1.7</pdfVersion></lowLevelInfo></featuresReport></job></jobs></report>',
    '<report xmlns="urn:vera"><jobs><job><featuresReport><metadata>test</metadata></featuresReport></job></jobs></report>',
])
def test_features_preserve_xml_and_low_level_data(tmp_path, features):
    adapter = VeraPdfAdapter("java", tmp_path)

    def run(name, command, version):
        feature = name == "verapdf/features"
        assert command[command.index("--format") + 1] == ("xml" if feature else "json")
        assert f"-Dapp.home={tmp_path / 'verapdf-config'}" in command
        return ToolRun(name, command, "1.30.2", features if feature else '{"report": {}}', "", 0, ToolRunStatus.COMPLETED, "", "")

    adapter.runner.run = run
    result = adapter.analyze(tmp_path / "sample.pdf")
    assert all(r.status == ToolRunStatus.COMPLETED for r in result.tool_runs)
    assert (tmp_path / "verapdf-features.xml").read_text(encoding="utf-8") == features
    saved = json.loads((tmp_path / "verapdf-features.json").read_text(encoding="utf-8"))
    assert saved == {"format": "xml", "xml": features}


@pytest.mark.parametrize("features", ['<report><jobs>', '<report><jobs/></report>'])
def test_incomplete_feature_output_is_not_a_success(tmp_path, features):
    adapter = VeraPdfAdapter("java", tmp_path)
    adapter.runner.run = lambda name, command, version: ToolRun(name, command, "1.30.2", features if name.endswith("features") else '{"report": {}}', "", 0, ToolRunStatus.COMPLETED, "", "")
    result = adapter.analyze(tmp_path / "sample.pdf")
    assert result.tool_runs[1].status == ToolRunStatus.FAILED
    assert "verapdf_features_path" not in result.artifacts
    assert not (tmp_path / "verapdf-features.json").exists()
