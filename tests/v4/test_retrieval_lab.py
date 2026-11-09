"""[NEW v4] 검색 실험실 (HCX·네트워크·HF 모델 없음, 가짜 KOSIS 데이터 + 표 15개 추가, Swagger 와 같은 HTTP 경로)"""
from tests import fake_kosis
from tests.test_pipeline_e2e import ROOT, _env, _run

SIDO = fake_kosis.SIDO
EXTRA = [  # (tbl_id, tbl_nm, category, items[(id, 이름, 단위)])
    ("DT_X001", "시도별 출생아수 및 합계출산율", "인구동향조사", [("T1", "출생아수", "명"), ("T2", "합계출산율", "가임여성 1명당 명")]),
    ("DT_X002", "시도별 사망자수", "인구동향조사", [("T1", "사망자수", "명")]),
    ("DT_X003", "시도별 혼인·이혼 건수", "인구동향조사", [("T1", "혼인건수", "건"), ("T2", "이혼건수", "건")]),
    ("DT_X004", "시도별 1인가구 수", "인구총조사", [("T1", "1인가구", "가구")]),
    ("DT_X005", "가구원수별 가구", "인구총조사", [("T1", "일반가구", "가구"), ("T2", "1인가구", "가구"), ("T3", "2인가구", "가구")]),
    ("DT_X006", "시도별 외국인 주민 수", "지방자치단체외국인주민현황", [("T1", "외국인주민수", "명")]),
    ("DT_X007", "시도별 고령인구 비율", "주민등록인구현황", [("T1", "65세이상인구비율", "%")]),
    ("DT_X008", "시도별 주택 수", "주택총조사", [("T1", "주택수", "호")]),
    ("DT_X009", "시도별 경제활동인구", "경제활동인구조사", [("T1", "경제활동인구", "천명"), ("T2", "취업자", "천명"), ("T3", "실업자", "천명")]),
    ("DT_X010", "시도별 실업률", "경제활동인구조사", [("T1", "실업률", "%")]),
    ("DT_X011", "시도별 평균 초혼연령", "인구동향조사", [("T1", "평균초혼연령", "세")]),
    ("DT_X012", "시도별 인구밀도", "주민등록인구현황", [("T1", "인구밀도", "명/㎢")]),
    ("DT_X013", "시도별 순이동자수", "국내인구이동통계", [("T1", "순이동", "명"), ("T2", "전입자수", "명")]),
    ("DT_X014", "시도별 다문화 출생아수", "다문화인구동태통계", [("T1", "다문화출생아수", "명")]),
    ("DT_X015", "시도별 장래인구추계", "장래인구추계", [("T1", "추계인구", "명")]),
]


def _extra_tables():
    return [{"org_id": "101", "tbl_id": t, "tbl_nm": nm, "category": cat, "section": nm, "josa": cat,
             "levels": [("A", "행정구역(시도)별", SIDO)], "items": items, "prd_se": "A", "prd_meta": "년",
             "periods": [str(y) for y in range(2021, 2026)]} for t, nm, cat, items in EXTRA]


def test_retrieval_lab(tmp_path):
    storage = tmp_path / "storage"
    saved = list(fake_kosis.TABLES)
    try:
        fake_kosis.TABLES[:] = saved + _extra_tables()
        fake_kosis.build(storage / "kosis_data")
    finally:
        fake_kosis.TABLES[:] = saved
    r = _run(["-m", "tests.v4.scenario_retrieval"], ROOT,
             _env(STORAGE_DIR=str(storage), HCX_API_KEY="test-key", CSV_INDEX_DIR="", RUNS_DIR="", QUERY_V4_CONFIG=""))
    print(r.stdout)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-4000:]
    assert '"RETRIEVAL_LAB": "PASS"' in r.stdout
