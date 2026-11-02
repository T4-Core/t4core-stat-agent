"""
[엔드포인트 2] query_bundle — 슬롯 형식 질의문 → QueryBundle (filters / sub_filters 채우기)

입력  {"original": 사용자 원문, "rewritten": "[시점] 2025년 [지역] 대구광역시 …", "sub_questions": [...]}
출력  QueryBundle(dict) + notes(해석하지 못한 슬롯·값)

원칙
  - 파싱만 한다. 빈 슬롯은 None 으로 두고 기본값(최신 연도·전국 …)은 채우지 않는다
    → 표마다 최신 연도가 달라서, 기본값은 표를 고른 뒤 ③ resolve 가 적용
  - 지역 표준명·연령 범위는 normalize 의 규칙(std_geo_name, parse_age)을 그대로 써서 데이터 쪽 표기와 맞춘다
  - 모르는 슬롯·해석 못 한 값은 버리지 않고 notes 에 남긴다
  - 슬롯이 하나도 없으면 팀 스펙의 실패 규칙: rewritten = original, sub_questions = [], intent/filters = None

실행  API : POST /query/bundle, GET /query/examples   (routers/query.py)
"""
import json
import re
from pathlib import Path

from config import norm_space
from services.normalize import parse_age, std_geo_name

EXAMPLES = Path(__file__).resolve().parent.parent / "data" / "slot_queries.json"

SLOT_RE = re.compile(r"\[([^\]]+)\]\s*([^\[]*)")
LIST_SLOTS = {"지역", "대상", "성별", "지표"}           # 쉼표로 여러 값
TEXT_SLOTS = {"비교축", "의도"}                        # 값 하나
KNOWN = LIST_SLOTS | TEXT_SLOTS | {"시점", "연령"}
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
            notes.append(f"[시점] 해석 못 함: '{v}'")      # 예: '최근 5년' 은 쿼리 모듈이 연도로 바꿔 줘야 함
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


def parse_slots(text):
    # 슬롯 문자열 → (filters dict 또는 None, notes)
    notes, filters = [], {}
    slots = SLOT_RE.findall(text or "")
    if not slots:
        return None, ["슬롯([이름] 값)이 없음"]
    for name, raw in slots:
        name, values = norm_space(name), split_values(raw)
        if not values:
            notes.append(f"[{name}] 값이 비어 있음")
            continue
        if name == "시점":
            filters["시점"] = parse_years(values, notes)
        elif name == "연령":
            filters["연령"] = parse_ages(values, notes)
        elif name == "지역":
            filters["지역"] = [std_geo_name(v) for v in values]
            notes += [f"[지역] '{v}' → '{s}'" for v, s in zip(values, filters["지역"]) if v != s]
        elif name in LIST_SLOTS:
            filters[name] = values
        elif name in TEXT_SLOTS:
            filters[name] = ", ".join(values)
        else:
            notes.append(f"모르는 슬롯 [{name}] = '{norm_space(raw)}' (Filters 에 없음, 쿼리 모듈과 협의 필요)")
    return {k: v for k, v in filters.items() if v is not None}, notes


def build_bundle(original, rewritten, sub_questions=()):
    # 팀 스펙 QueryBundle(dict) + notes
    filters, notes = parse_slots(rewritten)
    if filters is None:
        return {"original": original, "rewritten": original, "sub_questions": [], "intent": None,
                "filters": None, "sub_filters": None}, ["재작성 실패로 처리: " + notes[0]]
    subs, sub_filters = list(sub_questions or []), []
    for i, sq in enumerate(subs, 1):
        f, n = parse_slots(sq)
        sub_filters.append(f or {})
        notes += [f"(하위 {i}) {x}" for x in n]
    return {"original": original, "rewritten": rewritten, "sub_questions": subs, "intent": filters.get("의도"),
            "filters": filters, "sub_filters": sub_filters or None}, notes


def load_examples():
    # 쿼리 모듈 담당자가 준 12개 질의 (data/slot_queries.json)
    return json.loads(EXAMPLES.read_text(encoding="utf-8"))["queries"]


def slot_text(filters):
    # 슬롯 값만 이어 붙인 문장 (서브쿼리 자연어가 없을 때 검색 문장으로 대신 사용)
    parts = []
    for k in ("지역", "대상", "성별", "지표", "비교축", "의도"):
        v = (filters or {}).get(k)
        parts += v if isinstance(v, list) else ([v] if v else [])
    return " ".join(parts)


def example_queries():
    # 12개 예시 → View 모듈 입력 형식 (자연어 original + 슬롯 dict filters, 서브쿼리도 자연어 + 슬롯)
    out = []
    for q in load_examples():
        filters, notes = parse_slots(q["rewritten"])
        sub_filters = [parse_slots(s)[0] or {} for s in q["sub_questions"]]
        nl_subs = list(q.get("original_sub_questions") or [])
        if q["sub_questions"] and len(nl_subs) != len(q["sub_questions"]):
            nl_subs = [slot_text(f) for f in sub_filters]
            notes.append("서브쿼리 자연어가 없어 슬롯 값을 이어 붙인 문장으로 검색")
        out.append({"bundle": {"query_id": q["query_id"], "original": q["original"], "rewritten": q["rewritten"],
                               "intent": (filters or {}).get("의도"), "filters": filters,
                               "sub_questions": nl_subs, "sub_filters": sub_filters or None},
                    "sub_ids": q["sub_ids"], "notes": notes})
    return out
