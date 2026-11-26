"""
배포 묶음 — 원본이 있는 PC 에서 만든 산출물을 EC2 로 옮기기 위한 tar 하나

  python -m backend.db bundle create [--out t4core_bundle.tar.gz] [--parts indices,profiles,parquet,meta,embed]

  묶음 안의 경로                         내용                                          parts
  storage/ 의 나머지 전부                  메타 프로필 · 표기 사전 · 표 색인 · CSV 값 사전 · OKF ·  indices
                                         dense 카드 … (아래 EXCLUDE 에 없는 것은 모두 — 새 산출물도 자동)
  storage/parquet/profiles/              정규화 프로필 (PostgreSQL 에도 들어감)           profiles
  storage/parquet/processed/             정규화 parquet (EC2 에서 stats load 로 PostgreSQL 에) parquet
  kosis_data/catalog.csv · meta/         카탈로그 · 메타 JSON (원본 CSV raw/ 는 넣지 않음)  meta
  storage/indices/embed_cache.sqlite     HCX 임베딩 캐시 (EC2 에서 vectors import-sqlite) embed

EC2 에서:  tar -xzf t4core_bundle.tar.gz -C /srv/t4core   → /srv/t4core/storage, /srv/t4core/kosis_data
"""
from __future__ import annotations

import tarfile
import time
from pathlib import Path

PARTS = ("indices", "profiles", "parquet", "meta", "embed")

# storage/ 아래에서 묶음에 넣지 않는 것 (STORAGE_DIR 기준 상대 경로 앞부분). 나머지는 모두 "indices" 로 들어간다 →
# 팀원이 prepare 에 새 산출물(새 사전·색인 폴더)을 더해도 묶음 목록을 고치지 않아도 서버로 간다
EXCLUDE = ("kosis_data",                       # 원본은 "meta" 로 catalog.csv · meta/ 만
           "parquet/processed",                # "parquet"
           "parquet/profiles",                 # "profiles"
           "parquet/views",                    # View csv (실행할 때마다 다시 만듦)
           "indices/embed_cache.sqlite",       # "embed"
           "indices/embed_cache_view.sqlite",
           "indices/search_cache",             # BM25 토큰·dense pickle (서버에서 다시 만듦)
           "runs", "answers", "answers_dev",   # 실행 기록
           ".view_selection_secret")           # 서버마다 따로 (또는 VIEW_SELECTION_SECRET)


def _excluded(rel):
    rel = rel.replace("\\", "/")
    return any(rel == e or rel.startswith(e + "/") for e in EXCLUDE) or "__pycache__" in rel.split("/") \
        or rel.endswith(".tmp") or rel.endswith(".gitkeep")


def _entries(parts):
    """[(파일 또는 폴더, 묶음 안 경로)]"""
    from backend.core import config
    v = Path(config.VIEW_OUT_DIR)
    s = Path(config.STORAGE_DIR)
    k = Path(config.KOSIS_DATA_DIR)
    out = []
    if "indices" in parts:
        # 1) storage/ 전체에서 제외 목록만 빼고
        if s.exists():
            for f in sorted(s.rglob("*")):
                if f.is_file() and not _excluded(f.relative_to(s).as_posix()):
                    out.append((f, f"storage/{f.relative_to(s).as_posix()}"))
        # 2) 환경변수로 storage 밖에 둔 색인 (TABLE_INDEX_DIR · CSV_INDEX_DIR · OKF_*)
        for src, arc in [(Path(config.TABLE_INDEX_DIR), "storage/indices/table_index"),
                         (Path(config.CSV_INDEX_DIR), "storage/csv_index"),
                         (Path(config.OKF_DIR), "storage/okf"), (Path(config.OKF_BUILD_DIR), "storage/okf_build"),
                         (v / "meta_profiles.jsonl", "storage/parquet/meta_profiles.jsonl"),
                         (v / "dict", "storage/parquet/dict"), (v / "series.json", "storage/parquet/series.json")]:
            if src.exists() and not _inside(src, s):
                out.append((src, arc))
    if "profiles" in parts:
        out.append((v / "profiles", "storage/parquet/profiles"))
    if "parquet" in parts:
        out.append((v / "processed", "storage/parquet/processed"))
    if "meta" in parts:
        out += [(k / "catalog.csv", "kosis_data/catalog.csv"), (k / "meta", "kosis_data/meta")]
    if "embed" in parts:
        out.append((Path(config.EMBED_CACHE), "storage/indices/embed_cache.sqlite"))
    return out


def _inside(p, root):
    try:
        Path(p).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def create(out="t4core_bundle.tar.gz", parts=PARTS, compress=True, log=print):
    parts = [p for p in parts if p]
    bad = [p for p in parts if p not in PARTS]
    if bad:
        raise SystemExit(f"parts 는 {', '.join(PARTS)} 중에서: {bad}")
    t0, n_bytes, missing = time.time(), 0, []
    out = Path(out)
    seen, counts = set(), {}
    with tarfile.open(out, "w:gz" if compress else "w", **({"compresslevel": 5} if compress else {})) as tar:
        for src, arc in _entries(parts):
            if not src.exists():
                missing.append(arc)
                continue
            files = [src] if src.is_file() else [f for f in sorted(src.rglob("*")) if f.is_file()]
            for f in files:
                if "__pycache__" in f.parts or f.resolve() == out.resolve():
                    continue
                name = arc if f == src else f"{arc}/{f.relative_to(src).as_posix()}"
                if name in seen:
                    continue
                seen.add(name)
                tar.add(f, arcname=name, recursive=False)
                n_bytes += f.stat().st_size
                top = "/".join(name.split("/")[:3])
                counts[top] = counts.get(top, 0) + 1
    for top, n in sorted(counts.items()):
        log(f"[bundle] {top}  ({n}개)")
    for m in missing:
        log(f"[bundle] (없음, 건너뜀) {m}")
    log(f"[bundle] {out}  원본 {n_bytes / 2**20:.0f} MiB → 묶음 {out.stat().st_size / 2**20:.0f} MiB · "
        f"{time.time() - t0:.0f}초")
    return {"file": str(out), "bytes": out.stat().st_size, "missing": missing, "names": sorted(seen)}
