"""
[NEW] 요청 슬롯(Filters) vs ViewContents → 슬롯별 SlotCheck

  check_slots(filters, contents, config)
    → {"시점": SlotCheck, "지역": …, "성별": …, "연령": …, "지표": …, "대상": …, "의도": …, "비교축": …}

  여기서는 슬롯 '하나하나' 만 판정한다. 점수·최종 판정(pass/partial/fail)은 aggregate.py 에서 한다.
  예외를 내지 않는다: 판단할 근거가 없으면 unknown.

  매칭 규칙은 View 를 만든 build_view.py / normalize.py 의 함수를 그대로 쓴다
"""
from backend.rag.ingestion.build_view import SEX_ALIAS, has_sex, match_name, match_name_ctx, sex_name, term_stems
from backend.rag.ingestion.normalize import parse_age, std_geo_name
from backend.rag.judge.extract import ViewContents, is_total, region_std
from backend.schemas.judge import JudgeConfig, ReasonCode, SlotCheck
from backend.schemas.judge import SlotStatus as S   

SLOT_ORDER = ["시점", "지역", "성별", "연령", "지표", "대상", "의도", "비교축"]
SEX_STD = {"남자", "여자"}   
INF = 10 ** 9                



def _filters_dict(filters) -> dict:
    if filters is None:
        return {}
    if hasattr(filters, "model_dump"):
        return filters.model_dump(by_alias=True)
    return dict(filters)


def _not_requested(requested=None) -> SlotCheck:
    return SlotCheck(status=S.not_requested, requested=requested)


def _has_values(points: dict, key) -> bool | None:
    """ViewContents 의 label_points → 값이 있는지(True), 없는지(False), 모르는지(None)"""
    if not points:
        return None
    return points.get(key, 0) > 0


def _span(years) -> str:
    """[2019, 2020, 2021] → '2019~2021',  [2023] → '2023'  (근거 문장용)"""
    ys = sorted(years)
    if not ys:
        return "-"
    return str(ys[0]) if len(ys) == 1 else f"{ys[0]}~{ys[-1]}"


def _hi(x):
    """상한 None(이상) 을 무한대로 바꿔 크기 비교가 되게 한다"""
    return INF if x is None else x


def _age_text(lo, hi) -> str:
    return f"{lo}세 이상" if hi is None else f"{lo}~{hi}세"


def check_period(req, c: ViewContents, config: JudgeConfig) -> SlotCheck:
    """시점 (요청 = 연도 목록, 예: [2024])"""
    if not req:                                    
        return _not_requested()
    want = sorted({int(y) for y in req})
    found = sorted(c.years)
    if not found:
        return SlotCheck(status=S.missing, requested=want, found=[], evidence="표에 시점 정보 없음")

    present = [y for y in want if y in c.years]   
    if not present:
        return SlotCheck(status=config.substitution_as, requested=want, found=found,
                         reason=ReasonCode.slot_substituted,
                         evidence=f"요청 {_span(want)} 없음 → 표의 {_span(found)} 사용")

    absent = [y for y in want if y not in c.years]                          
    empty = [y for y in present if _has_values(c.year_points, y) is False]   
    if not absent and not empty:
        return SlotCheck(status=S.match, requested=want, found=found, evidence=f"{_span(want)} 있음")
    parts = []
    if absent:
        parts.append(f"{absent} 없음")
    if empty:
        parts.append(f"{empty} 은 행은 있으나 값 없음")
    return SlotCheck(status=S.partial, requested=want, found=found, evidence=", ".join(parts))


def check_region(req, c: ViewContents, config: JudgeConfig) -> SlotCheck:
    """지역 (요청 = 표준 지역 이름 목록, 예: ["대구광역시"])"""
    if not req:
        return _not_requested()
    want = [std_geo_name(r) for r in req]       
    dims = c.dims_of("regions")
    if all(w in ("전국", "전체") for w in want):          # [NEW v4] 전국만 물음 = 합계 행 또는 지역 분류 없는 표면 맞음
        if not dims or any(d.has_total for d in dims):
            return SlotCheck(status=S.match, requested=want, found=["전국"],
                             evidence="지역 분류 없음 (전국 값)" if not dims else "합계(전국) 있음")

    points: dict[str, int | None] = {}
    for d in dims:
        for lb in d.labels:
            if is_total(lb):
                continue
            s = region_std(lb)
            n = d.label_points.get(lb) if d.label_points else None
            points[s] = None if n is None or points.get(s, 0) is None else points.get(s, 0) + n
    found = sorted(points)

    if not points:
        why = "지역 분류 없음 (전국 값으로 보임)" if not dims else "합계(전국)만 있음"
        return SlotCheck(status=S.missing, requested=want, found=found, evidence=why)

    exact, loose, empty, absent = [], [], [], []
    for w in want:
        if w in points:
            if points[w] == 0:
                empty.append(w)
            else:
                exact.append(w)                     
        elif any(s.endswith(" " + w) for s in points):
            loose.append(w)                     
        else:
            absent.append(w)

    if len(exact) == len(want):
        return SlotCheck(status=S.match, requested=want, found=found, evidence=f"{', '.join(want)} 있음")
    if exact or loose or empty:
        parts = []
        if absent:
            parts.append(f"{absent} 없음")
        if empty:
            parts.append(f"{empty} 은 값 없음")
        if loose:
            parts.append(f"{loose} 는 상위 지역이 붙은 라벨과만 맞음 (모호)")
        return SlotCheck(status=S.partial, requested=want, found=found, evidence=", ".join(parts))
    return SlotCheck(status=S.missing, requested=want, found=found[:10], evidence=f"요청 지역 {want} 없음")


def check_sex(req, c: ViewContents, config: JudgeConfig) -> SlotCheck:
    """성별 (요청 = ["남자"] 등).  ⚠ kind == sex 만 믿지 않는다 ('특성별' 오분류 → extract.py 주석 참고)"""
    if not req:
        return _not_requested()
    want = sorted({SEX_ALIAS.get(s, s) for s in req})  

    points: dict[str, int | None] = {}   
    fake = []                             
    for d in c.dims_of("sex"):
        sexes = {sex_name(lb) for lb in d.labels} & SEX_STD
        if not sexes:                     
            fake.append(d.column)
            continue
        for lb in d.labels:
            s = sex_name(lb)
            if s in SEX_STD:
                n = d.label_points.get(lb) if d.label_points else None
                points[s] = None if n is None or points.get(s, 0) is None else points.get(s, 0) + n
    for it in c.items:
        for s in SEX_STD:
            if has_sex(it, s) and s not in points:
                points[s] = None

    found = sorted(points)
    have = [w for w in want if w in points and points[w] != 0]
    empty = [w for w in want if points.get(w) == 0]
    note = f" ('{', '.join(fake)}' 열은 성별로 분류됐지만 라벨이 성별이 아님)" if fake else ""
    if len(have) == len(want):
        return SlotCheck(status=S.match, requested=want, found=found, evidence=f"{', '.join(want)} 있음")
    if have or empty:
        return SlotCheck(status=S.partial, requested=want, found=found,
                         evidence=(f"{empty} 은 값 없음" if empty else f"{[w for w in want if w not in have]} 없음") + note)
    return SlotCheck(status=S.missing, requested=want, found=found, evidence="성별 구분 없음" + note)


def _age_request(req) -> tuple[int | None, int | None]:
    """연령 요청 → (from, to).  {"from": 20, "to": 29} / {"from_": 20, …} / None 모두 처리"""
    if not req:
        return None, None
    if hasattr(req, "model_dump"):
        req = req.model_dump(by_alias=True)
    lo = req.get("from", req.get("from_"))
    return lo, req.get("to")


def _covers(ranges, lo: int, hi) -> bool:
    """구간들을 이어 붙여 lo~hi 를 빈틈없이 덮는가.
    예) [(20,24), (25,29)] 로 20~29 → True,   [(20,24)] 로 20~29 → False (25~29 빈틈)"""
    hi = _hi(hi)
    pos = lo                                      
    for a, b in sorted(ranges, key=lambda r: r[0]):  
        if a > pos:                               
            break
        pos = max(pos, _hi(b) + 1)                 
        if pos > hi:
            return True
    return pos > hi


def check_age(req, c: ViewContents, config: JudgeConfig) -> SlotCheck:
    """연령 (요청 = {"from": 20, "to": 29}, 상한 없으면 to=None)"""
    lo, hi = _age_request(req)
    if lo is None and hi is None:
        return _not_requested()
    lo = lo or 0
    want = _age_text(lo, hi)

    own = [d for d in c.dims_of("ages") if not d.role]   
    others = [d for d in c.dims_of("ages") if d.role]     

    ranges = []
    for d in own:
        for lb in d.labels:
            if is_total(lb):
                continue
            a, b = parse_age(lb)
            if a is not None:
                ranges.append((a, b, _has_values(d.label_points, lb), lb))
    if not own:                                    
        for it in c.items:
            a, b = parse_age(it)
            if a is not None:
                ranges.append((a, b, None, it))

    if not ranges:
        if others:
            roles = sorted({d.role for d in others})
            return SlotCheck(status=S.partial, requested=want, found=[d.column for d in others],
                             evidence=f"본인 연령이 아니라 {', '.join(roles)}의 연령 기준")
        return SlotCheck(status=S.missing, requested=want, found=[], evidence="연령 분류 없음 (전 연령 값일 수 있음)")

    inside = [r for r in ranges if r[0] >= lo and _hi(r[1]) <= _hi(hi)]     
    valued = [(a, b) for a, b, has, _ in inside if has is not False]          
    found = [lb for *_, lb in ranges][:20]   

    if _covers(valued, lo, hi):
        return SlotCheck(status=S.match, requested=want, found=found, evidence=f"{want}를 빈틈없이 덮음")

    empty = [lb for a, b, has, lb in inside if has is False]
    overlap = [lb for a, b, _, lb in ranges if a <= _hi(hi) and _hi(b) >= lo]   
    if valued or overlap:
        if empty:
            why = f"{', '.join(empty)} 는 값 없음"
        elif not inside:
            why = f"더 넓은 구간({', '.join(overlap)})과만 겹침"
        else:
            why = f"{want} 중 일부 구간만 있음"
        return SlotCheck(status=S.partial, requested=want, found=found, evidence=why)
    return SlotCheck(status=S.missing, requested=want, found=found, evidence=f"{want}에 해당하는 구간 없음")


def check_terms(req, c: ViewContents, config: JudgeConfig) -> SlotCheck:
    """지표·대상 (요청 = ["인구수"], ["출생아"] 등). 두 슬롯 모두 이 함수로 판정한다"""
    if not req:
        return _not_requested()
    want = list(req)
    stems = term_stems(want)                      
    in_items = [it for it in c.items if match_name(it, stems)]
    if in_items:
        return SlotCheck(status=S.match, requested=want, found=in_items[:10], evidence="항목에 있음")
    in_labels = [lb for d in c.dims for lb in d.labels if match_name(lb, stems)] or \
        [f"{d.column}={lb}" for d in c.dims for lb in d.labels if match_name_ctx(lb, stems, d.column)]
    # [CHANGED v4] 값 + 분류 이름 ('가구원수별' 의 '1인' = '1인가구') — build_view 가 고른 것과 같은 규칙
    if in_labels:
        return SlotCheck(status=S.match, requested=want, found=in_labels[:10], evidence="분류 라벨에 있음")
    if match_name(c.title, stems):
        return SlotCheck(status=S.partial, requested=want, found=c.items[:10],
                         evidence="항목에는 없고 표 이름·설명에만 있음")
    return SlotCheck(status=S.missing, requested=want, found=c.items[:10], evidence=f"{want} 를 항목·분류·표 이름에서 못 찾음")


def check_intent(req, c: ViewContents, config: JudgeConfig) -> SlotCheck:
    """의도 (값 조회 / 추이 / 비교 / 순위) — View 의 '모양' 이 질문 의도에 맞는가"""
    if not req:
        return _not_requested()
    if req == "추이":
        n = sum(v > 0 for v in c.year_points.values()) if c.year_points else len(c.years)
        ok, found = n >= 2, f"값 있는 시점 {n}개"
    elif req in ("비교", "순위"):
        counts = [len([lb for lb in d.labels if not is_total(lb) and _has_values(d.label_points, lb) is not False])
                  for d in c.dims]
        n = max(counts + [len(c.items)])           
        ok, found = n >= 2, f"비교 대상 최대 {n}개"
    else:                                         
        ok, found = c.n_points >= 1, f"값 {c.n_points}개"
    if ok:
        return SlotCheck(status=S.match, requested=req, found=found, evidence=f"'{req}' 에 맞는 모양")
    reason = None if req not in ("추이", "비교", "순위") else ReasonCode.intent_mismatch
    return SlotCheck(status=S.missing, requested=req, found=found, reason=reason,
                     evidence=f"'{req}' 를 보여 주기에 부족 ({found})")


def check_axis(req, c: ViewContents, config: JudgeConfig) -> SlotCheck:
    """비교축 (예: "시도"). slot_tiers 에 없어 점수에는 안 들어가고 판정만 남긴다"""
    if not req:
        return _not_requested()
    by_name = [d.column for d in c.dims if req in d.column]
    regions = [d for d in c.dims_of("regions") if len(d.std) >= 2]
    if by_name or (req in ("시도", "지역", "시군구") and regions):
        return SlotCheck(status=S.match, requested=req, found=by_name or [d.column for d in regions])
    return SlotCheck(status=S.unknown, requested=req, found=[d.column for d in c.dims],
                     evidence="비교축에 맞는 분류 열을 확인하지 못함")



def check_slots(filters, contents: ViewContents, config: JudgeConfig | None = None) -> dict[str, SlotCheck]:
    """요청 슬롯 전부를 판정. 요청이 없는 슬롯은 not_requested 로 채워 항상 SLOT_ORDER 의 8개를 돌려준다"""
    config = config or JudgeConfig()
    f = _filters_dict(filters)
    c = contents
    return {
        "시점": check_period(f.get("시점"), c, config),
        "지역": check_region(f.get("지역"), c, config),
        "성별": check_sex(f.get("성별"), c, config),
        "연령": check_age(f.get("연령"), c, config),
        "지표": check_terms(f.get("지표"), c, config),
        "대상": check_terms(f.get("대상"), c, config),
        "의도": check_intent(f.get("의도"), c, config),
        "비교축": check_axis(f.get("비교축"), c, config),
    }
