"""[NEW v4] v4 단계별 검수 카드 — 질문 문장만 사용, 단계별 근거·원본 대조·사람 판정 저장 (HCX·네트워크 없음)"""
from tests.test_pipeline_e2e import ROOT, _env, _run
from tests.v4.test_view_v4 import build_conflict_data


def test_review_v4(tmp_path):
    storage = tmp_path / "storage"
    build_conflict_data(storage / "kosis_data")
    r = _run(["-m", "tests.v4.scenario_review"], ROOT,
             _env(STORAGE_DIR=str(storage), HCX_API_KEY="test-key", CSV_INDEX_DIR="", RUNS_DIR="", QUERY_V4_CONFIG="",
                  VIEW_SELECTION_SECRET="", TEST_DATA_DIR=str(tmp_path / "test_data"), EVAL_RUNS_DIR=""))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    assert '"REVIEW_V4": "PASS"' in r.stdout


def test_png_fallback_warns_once(tmp_path, monkeypatch):
    """PNG 는 별도 프로세스: 브라우저가 없으면 예외 없이 빈 목록 + 경고 한 줄 (카드마다 반복하지 않음)"""
    import sys
    sys.path.insert(0, str(ROOT / "eval" / "pipeline_review"))
    import review_80 as r80
    monkeypatch.setattr(r80, "_PNG_SCRIPT", "import sys; print('NOBROWSER chromium: not installed'); sys.exit(2)")
    monkeypatch.setitem(r80._PNG_STATE, "warned", False)
    monkeypatch.setitem(sys.modules, "html2image", None)                 # html2image 도 없다고 가정
    h = tmp_path / "Q001.html"
    h.write_text("<div class='card'>x</div>", encoding="utf-8")
    logs = []
    assert r80.png_many([(h, tmp_path / "Q001.png")], log=logs.append) == []
    assert r80.png_many([(h, tmp_path / "Q002.png")], log=logs.append) == []
    assert len(logs) == 1 and "NOBROWSER" in logs[0] and "playwright install" in logs[0], logs
