from scripts.audit_public_release import audit_build_records


def test_build_records_reject_environment_dump(tmp_path):
    (tmp_path / "config.log").write_text("process environment dump", encoding="utf-8")
    assert audit_build_records(tmp_path) == ["Unexpected build record: config.log"]


def test_build_records_reject_home_path(tmp_path):
    (tmp_path / "config.mak").write_text("prefix=/c/" + "Users/test-owner/build/", encoding="utf-8")
    assert audit_build_records(tmp_path) == ["Private marker in build record: config.mak"]


def test_build_records_accept_portable_configuration(tmp_path):
    (tmp_path / "config.mak").write_text("prefix=BUILD_ROOT/installed", encoding="utf-8")
    assert audit_build_records(tmp_path) == []
