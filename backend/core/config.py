"""
경로와 .env — 모든 모듈은 경로를 직접 만들지 않고 여기 상수만 import 한다

경로마다 ① 환경변수(.env 포함) → ② 실제로 있는 후보 위치 → ③ 기본 위치(storage/…) 순으로 정한다.

  KOSIS_DATA_DIR   수집 원본 (catalog.csv, meta/, raw/)        storage/kosis_data  (또는 ./kosis_data, ../kosis_data)
  VIEW_OUT_DIR     정규화 parquet·프로필·meta_profiles·views    storage/parquet
  TABLE_INDEX_DIR  표 설명문 BM25 색인                          storage/indices/table_index
  CSV_INDEX_DIR    CSV 값 사전                                  storage/csv_index
  EMBED_CACHE      HCX 임베딩 캐시 (sqlite)                     storage/indices/embed_cache.sqlite
  RUNS_DIR         단계별 실행 기록·검색 비교 결과              storage/runs
  ANSWERS_DIR      /chat save=true 결과                         storage/answers
  OKF_DIR          OKF 지식 카탈로그 번들 (git 에 커밋)          storage/okf
  OKF_BUILD_DIR    번들 파생물 (빌드별 폴더 + CURRENT)          storage/okf_build
  PRIVATE_DIR      개인 파이프라인 플러그인 (git 제외)          ./private, ../private, ../<저장소>_private

확인: GET /api/v1/system/paths  또는  python -m backend.core.config
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def find_env(start=ROOT):
    for d in [Path.cwd(), start, *start.parents]:
        if (d / ".env").is_file():
            return d / ".env"
    return None


ENV_PATH = find_env()
if ENV_PATH:
    load_dotenv(ENV_PATH, override=False)


def _env_path(*keys):
    for k in keys:
        v = (os.getenv(k) or "").strip()
        if v:
            p = Path(v).expanduser()
            return (p if p.is_absolute() else (ROOT / p)).resolve()
    return None


CONFIG_WARNINGS = []


def _pick(env_keys, candidates, default, marker=None, env_must_exist=False):
    """환경변수 → 후보 중 marker 가 있는 첫 위치 → default.
    env_must_exist: 환경변수 경로에 marker 가 없으면 경고를 남기고 무시"""
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
CONFIGS_DIR = ROOT / "configs"
FRONTEND_DIR = ROOT / "frontend"          # 정적 테스트 화면 (main.py 가 /lab 으로 서빙)

KOSIS_DATA_DIR = _pick(
    ("KOSIS_DATA_DIR",),
    [STORAGE_DIR / "kosis_data", ROOT / "kosis_data", ROOT.parent / "kosis_data", Path.cwd() / "kosis_data"],
    STORAGE_DIR / "kosis_data", marker="catalog.csv", env_must_exist=True)
VIEW_OUT_DIR = _env_path("VIEW_OUT_DIR") or STORAGE_DIR / "parquet"
TABLE_INDEX_DIR = _env_path("TABLE_INDEX_DIR") or STORAGE_DIR / "indices" / "table_index"
CSV_INDEX_DIR = _env_path("CSV_INDEX_DIR") or STORAGE_DIR / "csv_index"
EMBED_CACHE = _env_path("EMBED_CACHE") or STORAGE_DIR / "indices" / "embed_cache.sqlite"
RUNS_DIR = _env_path("RUNS_DIR") or STORAGE_DIR / "runs"
EVAL_RUNS_DIR = _env_path("EVAL_RUNS_DIR") or RUNS_DIR / "eval_generator"   # [NEW 11-23 KOS-40] Generator 평가 실행 결과 (git 제외)
ANSWERS_DIR = _env_path("ANSWERS_DIR") or STORAGE_DIR / "answers"
OKF_DIR = _env_path("OKF_DIR") or STORAGE_DIR / "okf"                     # OKF 지식 카탈로그 번들 (git 에 커밋)
OKF_BUILD_DIR = _env_path("OKF_BUILD_DIR") or STORAGE_DIR / "okf_build"   # 번들 파생물 (빌드별 폴더 + CURRENT)
PRIVATE_DIR = _pick(("PRIVATE_DIR",), [ROOT / "private", ROOT.parent / "private", ROOT.parent / f"{ROOT.name}_private"],
                    None, marker="pipelines")


def paths():
    named = {"ROOT": ROOT, "ENV_PATH": ENV_PATH, "STORAGE_DIR": STORAGE_DIR, "KOSIS_DATA_DIR": KOSIS_DATA_DIR,
             "VIEW_OUT_DIR": VIEW_OUT_DIR, "TABLE_INDEX_DIR": TABLE_INDEX_DIR, "CSV_INDEX_DIR": CSV_INDEX_DIR,
             "EMBED_CACHE": EMBED_CACHE, "RUNS_DIR": RUNS_DIR, "ANSWERS_DIR": ANSWERS_DIR, "PRIVATE_DIR": PRIVATE_DIR,
             "OKF_DIR": OKF_DIR, "OKF_BUILD_DIR": OKF_BUILD_DIR,
             "FRONTEND_DIR": FRONTEND_DIR}
    out = {k: {"path": str(v) if v else None, "exists": bool(v) and Path(v).exists()} for k, v in named.items()}
    if CONFIG_WARNINGS:
        out["WARNINGS"] = {"path": " / ".join(CONFIG_WARNINGS), "exists": False}
    return out


if __name__ == "__main__":
    for k, v in paths().items():
        print(f"{k:16s} {'✓' if v['exists'] else '·'} {v['path']}")
