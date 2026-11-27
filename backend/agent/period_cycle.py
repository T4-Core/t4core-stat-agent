"""
[NEW 11-27] 주기(월 · 분기 · 반기) — 시점 라벨을 (연도, 주기 칸)으로 나눈다. 모듈 2 · 3 · 5 가 같이 쓴다

  View 의 시점 라벨 (backend.rag.ingestion.normalize 의 PERIOD_LABEL_SQL): 월 '2024.01' · 분기 '2024 1분기' · 반기 '2024 상반기' · 연 '2024'

  같은 주기끼리 견주는 차트: '전국 월별 출생아수의 2015·2020·2025년을 레이더로' → 축 = 1월~12월, 다각형 = 연도.
  '2025년 서울·부산·경기의 월별 혼인건수' → 축 = 1월~12월, 다각형 = 지역.
  시간 순서 축 하나로 그리면 2015.12 → 2020.01 이 이어지고 해끼리 겹쳐 볼 수 없다 (레이더 20선 11~20번).
  2026-11-27 기준 수집 데이터에는 월(M) 표가 없고 분기(Q) 표 15개가 있다 → 분기로 확인하고, 월 표가 들어오면 같은 규칙으로 동작한다
"""
import re

CYCLE_COL = {"M": "월", "Q": "분기", "H": "반기"}        # 주기 칸 열 이름 (레이더 축)
CYCLE_COLS = set(CYCLE_COL.values())
YEAR_COL = "연도"                                        # 주기 시점을 나눴을 때의 연도 열 (다각형 · 계열)
_FORMS = [
    (re.compile(r"^(\d{4})\.(\d{2})$"), "M", lambda m: int(m[2]), lambda m: f"{int(m[2])}월"),
    (re.compile(r"^(\d{4}) ?([1-4])분기$"), "Q", lambda m: int(m[2]), lambda m: f"{m[2]}분기"),
    (re.compile(r"^(\d{4}) ?(상|하)반기$"), "H", lambda m: 1 if m[2] == "상" else 2, lambda m: f"{m[2]}반기"),
]


def cycle_of(label) -> tuple[str, str, int, str] | None:
    """'2024.03' → ('2024', 'M', 3, '3월') · '2024 1분기' → ('2024', 'Q', 1, '1분기'). 연 · 일 · 읽을 수 없는 라벨은 None"""
    t = str(label).strip()
    for pattern, kind, pos, name in _FORMS:
        if (m := pattern.match(t)) and (kind != "M" or 1 <= pos(m) <= 12):
            return m[1], kind, pos(m), name(m)
    return None


def cycle_info(labels) -> dict | None:
    """라벨이 모두 같은 주기(월 · 분기 · 반기)면 {kind, col, years: [연도 …], positions: [주기 칸 이름 …(순서대로)]}, 아니면 None"""
    parsed = [cycle_of(x) for x in labels]
    if not parsed or any(p is None for p in parsed) or len({p[1] for p in parsed}) != 1:
        return None
    kind = parsed[0][1]
    return {"kind": kind, "col": CYCLE_COL[kind], "years": sorted({p[0] for p in parsed}),
            "positions": [name for _, name in sorted({(p[2], p[3]) for p in parsed})]}


def year_labels(years, labels) -> list[str] | None:
    """고정 연도(['2015', '2020']) → 그 해의 주기 라벨 전부 (시점 순서). 라벨이 주기가 아니거나 해당하는 라벨이 없으면 None
    질문이 '2015·2020·2025년' 이고 View 시점이 '2015 1분기' … 이면 연도 그대로는 고를 행이 없다"""
    want, labels = {str(y) for y in years or []}, list(labels)
    parsed = [(p, str(x)) for x in labels if (p := cycle_of(x))]
    if not want or not parsed or len(parsed) != len(labels) or len({p[1] for p, _ in parsed}) != 1:
        return None
    out = [x for p, x in sorted(parsed, key=lambda t: (t[0][0], t[0][2])) if p[0] in want]
    return list(dict.fromkeys(out)) or None
