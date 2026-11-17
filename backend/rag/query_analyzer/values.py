"""슬롯 값 파싱 — 시점 문자열 → 연도, 연령 문자열 → {from, to}, 슬롯 → 검색 문장

지역 표준명·연령 범위는 normalize 의 규칙(std_geo_name, parse_age)을 그대로 써서 데이터 쪽 표기와 맞춘다.
해석 못 한 값은 버리지 않고 notes 에 남긴다.
"""
import re

from backend.core.utils import norm_space
from backend.rag.ingestion.normalize import parse_age

YEAR_RANGE_RE = re.compile(r"^(\d{4})\s*년?\s*[~\-]\s*(\d{4})\s*년?$")
YEAR_RE = re.compile(r"^(\d{4})\s*년?$")


def split_values(text):
    return [v for v in (norm_space(x) for x in re.split(r"[,，、]", text)) if v]


def parse_years(values, notes):
    years = []
    for v in values:
        m = YEAR_RANGE_RE.match(v)
        if m:
            years += list(range(int(m[1]), int(m[2]) + 1))
        elif YEAR_RE.match(v):
            years.append(int(YEAR_RE.match(v)[1]))
        else:
            notes.append(f"[시점] 해석 못 함: '{v}'")  # 예: '최근 5년' 은 쿼리 모듈이 연도로 바꿔 줘야 함
    return sorted(set(years)) or None


def parse_ages(values, notes):
    # '20~29세' / '65세 이상' / '15세 미만' → {from, to}
    # 여러 값은 이어지거나 겹칠 때만 하나로 합친다 ('20~24세, 25~29세' → 20~29).
    # 떨어진 범위('15세 미만, 65세 이상')를 합치면 전 연령이 되어 버리므로 합치지 않고 None + notes
    rng = [parse_age(v) for v in values]
    for v, (f, _) in zip(values, rng):
        if f is None:
            notes.append(f"[연령] 해석 못 함: '{v}'")
    ok = sorted((f, t) for f, t in rng if f is not None)
    if not ok:
        return None
    lo, hi = ok[0]
    for f, t in ok[1:]:
        if hi is not None and f > hi + 1:
            notes.append(f"[연령] 떨어진 범위 여러 개는 아직 지원하지 않음: {values} (Filters.연령 은 범위 하나)")
            return None
        hi = None if hi is None or t is None else max(hi, t)
    return {"from": lo, "to": hi}


def slot_text(filters):
    # 슬롯 값만 이어 붙인 문장 (서브쿼리 자연어가 없을 때 검색 문장으로 대신 사용)
    parts = []
    for k in ("지역", "대상", "성별", "지표", "비교축", "의도"):
        v = (filters or {}).get(k)
        parts += v if isinstance(v, list) else ([v] if v else [])
    return " ".join(parts)
