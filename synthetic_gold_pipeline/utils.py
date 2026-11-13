"""공용 유틸: 경로 · 설정 · 해시 · 안전한 JSON/JSONL 저장 · 시점 표기.

Windows 절대 경로를 하드코딩하지 않는다. 모든 경로는 Pathlib + 환경변수 + YAML 로 해석한다.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
DEFAULT_CONFIG = PACKAGE_ROOT / "configs" / "pipeline.yaml"

# ── 경로 ──────────────────────────────────────────────────────────


def resolve_path(p: str | os.PathLike | None, base: Path = REPO_ROOT) -> Path | None:
    if p is None or str(p).strip() == "":
        return None
    q = Path(str(p).replace("\\", "/")).expanduser()
    return (q if q.is_absolute() else base / q).resolve()


def display_path(p: str | os.PathLike) -> str:
    """기록용 경로: 저장소 안이면 저장소 기준 상대 경로 (POSIX), 밖이면 절대 경로."""
    q = Path(p).resolve()
    try:
        return q.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return q.as_posix()


def ensure_inside(path: Path, root: Path) -> Path:
    """쓰기 경로가 root 안인지 확인 (신규 프로젝트 밖에 쓰는 것을 막음)."""
    path, root = Path(path).resolve(), Path(root).resolve()
    if path != root and root not in path.parents:
        raise PermissionError(f"쓰기 금지 경로: {path} (허용 루트: {root})")
    return path


# ── 설정 ──────────────────────────────────────────────────────────
_ENV_PAT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def _expand_env(v: Any) -> Any:
    if isinstance(v, str):
        def rep(m):
            return os.getenv(m.group(1), m.group(2) if m.group(2) is not None else "")
        return _ENV_PAT.sub(rep, v)
    if isinstance(v, dict):
        return {k: _expand_env(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_expand_env(x) for x in v]
    return v


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> dict:
    p = resolve_path(path) if path else DEFAULT_CONFIG
    if not p or not p.exists():
        raise FileNotFoundError(f"설정 파일 없음: {p}")
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # [NEW 11-12] extends: 다른 설정 파일을 바탕으로 바뀐 값만 적기 (이 파일 기준 상대 경로). 예) pipeline_easy.yaml
    if cfg.get("extends"):
        base = load_config(p.parent / cfg.pop("extends"))
        base.pop("_config_path", None)
        cfg = deep_merge(base, cfg)
    cfg = _expand_env(cfg)
    if overrides:
        cfg = deep_merge(cfg, overrides)
    cfg["_config_path"] = display_path(p)
    return cfg


def load_dotenv_if_present() -> Path | None:
    """저장소 루트(또는 상위)의 .env 를 읽기 전용으로 로드. 셸 환경변수가 우선 (override=False)."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return None
    for d in [Path.cwd(), REPO_ROOT, *REPO_ROOT.parents]:
        if (d / ".env").is_file():
            load_dotenv(d / ".env", override=False)
            return d / ".env"
    return None


# ── 해시 ──────────────────────────────────────────────────────────


def sha256_file(path: str | os.PathLike, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(obj: Any, n: int = 16) -> str:
    return sha256_text(canonical_json(obj))[:n]


# ── 안전 저장 ─────────────────────────────────────────────────────


def atomic_write_text(path: str | os.PathLike, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def atomic_write_json(path: str | os.PathLike, obj: Any) -> Path:
    return atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")


def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def append_jsonl(path: str | os.PathLike, rows: Iterable[Any]) -> int:
    """한 줄씩 기록 + fsync. 중간에 죽어도 마지막 불완전한 줄만 버리면 된다 (read_jsonl 이 무시)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(to_jsonable(r), ensure_ascii=False, default=str) + "\n")
            n += 1
        f.flush()
        os.fsync(f.fileno())
    return n


def write_jsonl(path: str | os.PathLike, rows: Iterable[Any]) -> Path:
    text = "".join(json.dumps(to_jsonable(r), ensure_ascii=False, default=str) + "\n" for r in rows)
    return atomic_write_text(path, text)


def read_jsonl(path: str | os.PathLike) -> Iterator[dict]:
    path = Path(path)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue          # 중단으로 잘린 마지막 줄


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 시점 ──────────────────────────────────────────────────────────
# backend/rag/ingestion/normalize.py 의 PRD_SE_MAP 과 같은 규칙 (코드 재사용 대신 독립 구현)
PRD_SE_MAP = {"A": "Y", "Y": "Y", "년": "Y", "연": "Y", "Q": "Q", "분기": "Q", "H": "H", "반기": "H",
              "M": "M", "월": "M", "D": "D", "일": "D", "IR": "IR", "부정기": "IR", "F": "F"}


def normalize_frequency(prd_se: str | None) -> str:
    s = re.sub(r"\s+", "", str(prd_se or ""))
    if s in PRD_SE_MAP:
        return PRD_SE_MAP[s]
    if s.endswith("년"):
        return "F"
    return s or "Y"


def period_digits(prd_de: str) -> str:
    return "".join(ch for ch in str(prd_de) if ch.isdigit())


def period_year(prd_de: str) -> int | None:
    d = period_digits(prd_de)
    return int(d[:4]) if len(d) >= 4 else None


def period_label(freq: str, prd_de: str) -> str:
    d = period_digits(prd_de)
    if len(d) < 4:
        return str(prd_de)
    y = d[:4]
    rest = d[4:]
    if freq == "M" and rest:
        return f"{y}년 {int(rest[:2])}월"
    if freq == "Q" and rest:
        return f"{y}년 {int(rest[-1] if len(rest) <= 2 else rest[:2])}분기"
    if freq == "H" and rest:
        return f"{y}년 {'상' if int(rest[-1]) == 1 else '하'}반기"
    if freq == "D" and len(rest) >= 4:
        return f"{y}년 {int(rest[:2])}월 {int(rest[2:4])}일"
    return f"{y}년"


def period_sort_key(prd_de: str) -> tuple:
    d = period_digits(prd_de)
    return (len(d), d)


def norm_text(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def safe_name(s: str, n: int = 120) -> str:
    return re.sub(r"[^\w\-.]+", "_", str(s)).strip("_")[:n]
