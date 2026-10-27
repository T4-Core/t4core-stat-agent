"""
프로파일링 설정 (경로 · 담당 범위 · 임계값을 한곳에서 관리)

경로는 이 파일 위치(profiling/) 기준으로 계산하므로 어느 폴더에서 실행해도 같다.
KOSIS_DATA 환경변수가 있으면 kosis_rag_qa.py 와 같은 규칙으로 데이터 폴더를 바꾼다.
"""
import os
from pathlib import Path

# ── 경로 ──
PROFILING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROFILING_DIR.parent                                   # kosis_*.py 가 있는 곳
DATA_DIR = Path(os.getenv("KOSIS_DATA", REPO_ROOT / "kosis_data"))
if not DATA_DIR.is_absolute():
    DATA_DIR = REPO_ROOT / DATA_DIR
VIEWS_DIR = DATA_DIR / "rag_views"                                 # kosis_views.py 기본 출력 (L3·L4 진단 대상)
OUTPUT_DIR = PROFILING_DIR / "output"
CACHE_DIR = OUTPUT_DIR / "cache"                                   # 표별 스캔 결과 캐시 (파일 크기·수정시각 기준)
DUCKDB_TMP = OUTPUT_DIR / ".duckdb_tmp"                            # 메모리를 넘는 집계의 임시 저장 위치

# ── 담당 범위 ──
CATEGORIES = ["인구동향조사", "국내인구이동통계", "인구동태패널통계", "장래가구추계"]

# ── DuckDB ──
DUCKDB_THREADS = max(1, (os.cpu_count() or 4) - 1)
DUCKDB_MEMORY_LIMIT = "6GB"        # 19GB 이동통계도 이 안에서 스트리밍 집계 (넘치면 DUCKDB_TMP 로 내려씀)

# ── 판정 임계값 ──
LARGE_FILE_MB = 1024               # 이보다 크면 '대용량 표' (조회 지연·분할 검토 대상)
SYMBOL_SHARE_WARN = 0.05           # 값 칸의 통계부호 비율이 이보다 크면 경고
SIBLING_NAME_SIM = 0.85            # 표 이름 유사도가 이 이상이면 형제 표 후보
STALE_YEARS = 3                    # 마지막 시점이 (올해 - N)년보다 이전이면 '오래된 표'

# ── 심각도 (summary.md 의 정렬 기준) ──
SEVERITY = {"high": 3, "medium": 2, "low": 1, "info": 0}
