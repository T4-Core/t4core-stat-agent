"""
전역 설정 — 경로(데이터 위치)와 .env 를 한 곳에서 결정한다  (구 view_model/config.py 를 확장)

모든 모듈은 경로를 직접 만들지 않고 여기 상수만 import 한다.
데이터 폴더를 옮겨도 코드 수정 없이 동작하도록, 아래 순서로 "실제로 있는 곳"을 찾는다 (동적 해석).

  1) 환경변수(.env 포함)로 지정한 경로         예) KOSIS_DATA_DIR=D:/data/kosis_data
  2) 새 구조 기본 위치  storage/...
  3) 예전 위치          <저장소 루트>/kosis_data, view_model/output  (이전 구조와 호환)
  4) 어디에도 없으면 새 구조 기본 위치 (처음 실행 시 여기에 생성)

  ┌ 변수 ─────────────┬ 내용 ────────────────────────────────────────┬ 기본 위치 / 예전 위치 ──────────────────────┐
  │ KOSIS_DATA_DIR    │ 수집 원본: catalog.csv, meta/, raw/, parts/ … │ storage/kosis_data  / ./kosis_data          │
  │ RAG_VIEWS_DIR     │ kosis_views 결과: processed/, records.jsonl   │ KOSIS_DATA_DIR/rag_views (그대로 유지)       │
  │ RAG_INDEX_DIR     │ 하이브리드 인덱스(bm25.pkl, dense.npy)·캐시    │ storage/indices/rag_qa / kosis_data/index   │
  │ VIEW_OUT_DIR      │ View 모듈 산출물: processed/ profiles/ dict/  │ storage/parquet     / view_model/output     │
  │ TABLE_INDEX_DIR   │ 표 설명문 BM25 색인 (tokens.json …)           │ storage/indices/table_index / VIEW_OUT/table_index │
  │ VIEW_EMBED_CACHE  │ View 모듈 임베딩 캐시 sqlite                  │ storage/indices/embed_cache_view.sqlite      │
  │ ANSWERS_DIR       │ 답변 저장                                     │ KOSIS_DATA_DIR/answers                       │
  │ TEST_DATA_DIR     │ 평가 질문 CSV (80문항·정답 참고)              │ storage/test_data  / ./test_data, eval/query_rewrite/data │
  │ EVAL_RUNS_DIR     │ 80문항 검수 결과 (JSON·카드·CSV)              │ storage/eval_runs                            │
  └───────────────────┴───────────────────────────────────────────────┴──────────────────────────────────────────────┘

확인: GET /api/v1/system/paths  또는  python -m backend.core.config
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# ── 저장소 루트 / .env ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]          # <repo>/backend/core/config.py → <repo>
# [CHANGED] 이전: ROOT = Path(__file__).resolve().parent.parent   (view_model/config.py 기준 → 저장소 루트)


def find_env(start=ROOT):
    """저장소 루트 → 상위 폴더 순으로 처음 찾은 .env (구 rewriter/config.py 의 find_env 와 같은 규칙)"""
    for d in [Path.cwd(), start, *start.parents]:
        if (d / ".env").is_file():
            return d / ".env"
    return None


ENV_PATH = find_env()
if ENV_PATH:
    load_dotenv(ENV_PATH, override=False)
# [CHANGED] 이전: 모듈마다 따로 읽음
#   kosis_rag_builder.py : load_dotenv(Path.cwd() / ".env")
#   kosis_rag_qa.py      : load_dotenv(Path.cwd() / ".env")
#   rewriter/config.py   : load_dotenv(find_env(), override=True)
#   embedding.py         : load_dotenv(ROOT / ".env")
# → 여기서 한 번만 읽음. 셸 환경변수가 .env 보다 우선 (override=False)


def _env_path(*keys):
    for k in keys:
        v = (os.getenv(k) or "").strip()
        if v:
            p = Path(v).expanduser()
            return (p if p.is_absolute() else (ROOT / p)).resolve()
    return None


CONFIG_WARNINGS = []   # [NEW] 무시한 환경변수 등 (paths() · python -m backend.core.config 에 표시)


def _pick(env_keys, candidates, default, marker=None, env_must_exist=False):
    """환경변수 → 후보 중 marker(파일/폴더)가 있는 첫 위치 → default
    env_must_exist=True: 환경변수 경로에 marker 가 없으면 무시하고 후보로 (예: .env 에 남은 예전 KOSIS_DATA=kosis_data)"""
    p = _env_path(*env_keys)
    if p and env_must_exist and marker and not (p / marker).exists():
        CONFIG_WARNINGS.append(f"{'/'.join(env_keys)}={p} 에 {marker} 가 없어 무시하고 자동 탐색")
        p = None
    if p:
        return p
    for c in candidates:
        if (c / marker).exists() if marker else c.exists():
            return c
    return default


STORAGE_DIR = _env_path("STORAGE_DIR") or ROOT / "storage"
EVAL_DIR = ROOT / "eval"

# ── 1) 수집 원본 (kosis_rag_builder = collector 출력, 이미지의 kosis_data 폴더 통째) ──
KOSIS_DATA_DIR = _pick(
    ("KOSIS_DATA_DIR", "KOSIS_DATA"),               # KOSIS_DATA = 예전 kosis_rag_qa.py 가 쓰던 이름 (호환)
    [STORAGE_DIR / "kosis_data", STORAGE_DIR / "raw_csv", ROOT / "kosis_data", ROOT.parent / "kosis_data",
     Path.cwd() / "kosis_data"],
    STORAGE_DIR / "kosis_data", marker="catalog.csv", env_must_exist=True)   # [CHANGED] 없는 경로의 환경변수는 무시

# ── 2) kosis_views(view_builder) 결과 — 하이브리드 검색(legacy) 레코드와 processed parquet ──
RAG_VIEWS_DIR = _pick(("RAG_VIEWS_DIR",), [KOSIS_DATA_DIR / "rag_views", STORAGE_DIR / "rag_views"],
                      KOSIS_DATA_DIR / "rag_views", marker="processed")
RAG_INDEX_DIR = _pick(("RAG_INDEX_DIR",), [STORAGE_DIR / "indices" / "rag_qa", KOSIS_DATA_DIR / "index"],
                      STORAGE_DIR / "indices" / "rag_qa", marker="embed_cache.sqlite")
ANSWERS_DIR = _env_path("ANSWERS_DIR") or KOSIS_DATA_DIR / "answers"

# ── 3) View 모듈 (구 view_model/output) ──────────────────────────
VIEW_OUT_DIR = _pick(("VIEW_OUT_DIR",), [STORAGE_DIR / "parquet", ROOT / "view_model" / "output"],
                     STORAGE_DIR / "parquet", marker="meta_profiles.jsonl")
TABLE_INDEX_DIR = _pick(("TABLE_INDEX_DIR",), [STORAGE_DIR / "indices" / "table_index", VIEW_OUT_DIR / "table_index"],
                        STORAGE_DIR / "indices" / "table_index", marker="tokens.json")
_vec = [STORAGE_DIR / "indices" / "embed_cache_view.sqlite", VIEW_OUT_DIR / "embed_cache.sqlite"]
VIEW_EMBED_CACHE = _env_path("VIEW_EMBED_CACHE") or next((p for p in _vec if p.exists()), _vec[0])

# ── 4) 질의 재작성 평가 산출물 (구 Rewritten_fastapi/{data,outputs,dashboard}) ──
REWRITE_EVAL_DIR = EVAL_DIR / "query_rewrite"

# ── 5) 평가 질문·검수 결과 [NEW] ──────────────────────────────────
# 평가 질문 CSV (kosis_rag_eval_80_queries.csv, …_answers_references.csv) — storage/test_data 를 우선
TEST_DATA_DIR = _pick(("TEST_DATA_DIR",), [STORAGE_DIR / "test_data", ROOT / "test_data", REWRITE_EVAL_DIR / "data"],
                      STORAGE_DIR / "test_data", marker="kosis_rag_eval_80_queries.csv", env_must_exist=True)
# 80문항 파이프라인 검수 결과 (auto_results.json, json/, cards/, human_final.csv) — eval/pipeline_review
EVAL_RUNS_DIR = _env_path("EVAL_RUNS_DIR") or STORAGE_DIR / "eval_runs"

# ── 6) 개인 작업 폴더 (git 제외) [NEW] ──────────────────────────────────
# private/pipelines/<이름>.py 의 run_chat 을 파이프라인 플러그인으로 등록 (backend/core/plugins.py)
# 찾는 순서: 환경변수 PRIVATE_DIR → <저장소>/private → <저장소 상위>/private → <저장소 상위>/<저장소이름>_private
PRIVATE_DIR = _pick(("PRIVATE_DIR",), [ROOT / "private", ROOT.parent / "private", ROOT.parent / f"{ROOT.name}_private"],
                    None, marker="pipelines")

# ── 예전 이름 (View 모듈 코드가 그대로 쓰도록 남김) ──────────────
DATA = KOSIS_DATA_DIR      # [CHANGED] 이전: DATA = ROOT / "kosis_data"
OUT = VIEW_OUT_DIR         # [CHANGED] 이전: OUT = Path(__file__).resolve().parent / "output"   (view_model/output)
# [MOVED] connect / one / sql_str → backend/data_engine/duckdb_client.py,  safe / norm_space → backend/core/utils.py


def resolve_data_path(p):
    """예전에 저장된 상대 경로(예: 'kosis_data/rag_views/records.jsonl')를 지금 위치로 다시 찾음.
    인덱스 meta.json 처럼 경로 문자열을 파일에 저장해 둔 경우, 폴더를 옮기면 깨지는 문제를 막는다. [NEW]"""
    p = Path(str(p).replace("\\", "/"))   # Windows 에서 저장한 'kosis_data\\rag_views\\…' 도 mac/linux 에서 읽히게 (Windows 는 / 도 인식)
    for c in (p, Path.cwd() / p, ROOT / p):
        if c.exists():
            return c
    parts = p.parts
    if "kosis_data" in parts:                       # 'kosis_data' 이후 부분을 지금 KOSIS_DATA_DIR 에 붙임
        c = KOSIS_DATA_DIR.joinpath(*parts[parts.index("kosis_data") + 1:])
        if c.exists():
            return c
    if "rag_views" in parts:
        c = RAG_VIEWS_DIR.joinpath(*parts[parts.index("rag_views") + 1:])
        if c.exists():
            return c
    return p


def paths():
    """현재 해석된 경로와 존재 여부 (Swagger /api/v1/system/paths 에서 확인)"""
    named = {"ROOT": ROOT, "ENV_PATH": ENV_PATH, "STORAGE_DIR": STORAGE_DIR, "KOSIS_DATA_DIR": KOSIS_DATA_DIR,
             "RAG_VIEWS_DIR": RAG_VIEWS_DIR, "RAG_INDEX_DIR": RAG_INDEX_DIR, "ANSWERS_DIR": ANSWERS_DIR,
             "VIEW_OUT_DIR": VIEW_OUT_DIR, "TABLE_INDEX_DIR": TABLE_INDEX_DIR, "VIEW_EMBED_CACHE": VIEW_EMBED_CACHE,
             "REWRITE_EVAL_DIR": REWRITE_EVAL_DIR, "TEST_DATA_DIR": TEST_DATA_DIR, "EVAL_RUNS_DIR": EVAL_RUNS_DIR,
             "PRIVATE_DIR": PRIVATE_DIR}
    out = {k: {"path": str(v) if v else None, "exists": bool(v) and Path(v).exists()} for k, v in named.items()}
    if CONFIG_WARNINGS:
        out["WARNINGS"] = {"path": " / ".join(CONFIG_WARNINGS), "exists": False}
    return out


if __name__ == "__main__":
    for k, v in paths().items():
        print(f"{k:18s} {'✓' if v['exists'] else '·'} {v['path']}")
