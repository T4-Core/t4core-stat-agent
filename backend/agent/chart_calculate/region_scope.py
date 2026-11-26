"""
[NEW 11-18] 시군구 수준 표가 질문의 시도 범위인지 확인한다 (F4)

  시도 질문('경기도 시군구별 인구 순위')에 시군구 표가 오면 시도 이름 행이 없는 것이 정상이다. 하지만 '시군구 수준' 이라는 사실이나 View 메모가
  없다는 사실만으로는 그 시군구가 요청한 시도 아래 것인지 알 수 없다 (서울 자치구가 경기도 순위로 나갈 수 있다. 검토 1).
  → View 가 실제로 고른 지역 코드(Record.source.dims)를 표 프로필의 코드 계층(상위 코드)과 대조해, 모두 요청한 시도 아래일 때만 허용한다.
  프로필을 읽을 수 없거나 계층이 맞지 않으면 허용하지 않는다 (계산하지 않음).
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.core.config import VIEW_OUT_DIR
from backend.schemas.record import Record


@lru_cache(maxsize=64)
def _read(table_key: str) -> dict[str, Any] | None:
    path = Path(VIEW_OUT_DIR) / "profiles" / f"{table_key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    # STAT_BACKEND=postgres: 프로필 파일이 없는 서버 → PostgreSQL 에 올린 프로필 (없거나 연결 실패면 None)
    from backend.data_engine import stat_store
    try:
        return stat_store.pg_profile_by_key(table_key)
    except Exception:  # noqa: BLE001
        return None


def load_profile(table_key: str) -> dict[str, Any] | None:
    """표 프로필(levels[].codes 에 코드 · 이름 · 상위 코드가 있다). 시험에서는 이 함수를 바꿔 끼운다"""
    return _read(table_key) if table_key else None


def within(rec: Record, regions: list[str]) -> bool:
    """View 가 고른 지역 코드가 모두 regions(시도 이름) 중 하나의 아래(또는 그 자신)에 있는가"""
    source = rec.source or {}
    profile = load_profile(str(source.get("table_key") or ""))
    dims = source.get("dims") or {}
    if not profile or not dims:
        return False
    wanted = set(regions)
    checked = False
    for level in profile.get("levels") or []:
        if level.get("kind") != "regions":
            continue
        selected = (dims.get(f"c{level.get('level')}") or {}).get("codes") or []
        by_code = {c["code"]: c for c in level.get("codes") or []}
        for code in selected:
            c = by_code.get(code)
            if c is None:
                return False
            if c.get("is_total"):
                continue                               # 전국 합계 행은 범위 판단에서 제외
            checked = True
            seen, cur = set(), c
            while cur is not None and cur["code"] not in seen:
                seen.add(cur["code"])
                if cur.get("std") in wanted or cur.get("name") in wanted:
                    break
                cur = by_code.get(cur.get("parent"))
            else:
                return False
            if cur is None:
                return False
    return checked
