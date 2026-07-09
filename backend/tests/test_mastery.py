from app.services.mastery import build_global_mastery_update, save_session_report

def test_save_session_report(tmp_path):
    path = save_session_report(tmp_path, "# report")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "# report"

def test_build_global_mastery_update():
    markdown = build_global_mastery_update("# 单轮报告")
    assert "type: mastery_report" in markdown
    assert "全局掌握度更新建议" in markdown
