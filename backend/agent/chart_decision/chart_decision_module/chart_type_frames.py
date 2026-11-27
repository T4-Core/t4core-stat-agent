"""④-2 빈 좌표 판정 — View 표의 열 구조를 차트마다 정해 둔 자리(좌표)에 꽂아 볼 수 있는지 확인한다 (규칙, HCX 호출 없음)

  check_frame(chart, profile, measure, requested) → (통과 여부, 못 맞춘 이유 목록, 맞춘 자리 설명)
                                                    requested = 사용자가 요청한 차트 [NEW 11-25] · 값 1개면 이유 SINGLE_VALUE
  chart_measure(m, query_bundle)        → (차트에 쓸 measure, 바꾼 이유 | None)

  - 계산하지 않는다. 표의 열 종류(시점 · 지역 · 연령 · 성별 · 기타 범주 · 지표)와 개수만 본다
  - 최소 개수와 구조만 판정한다. 최대 개수(막대 20개 · 원그래프 5개 …)는 계산 뒤 개수가 달라질 수 있어
    모듈 3 이 requirements 로 판정한다 (상위 N개로 자르면 229개도 10개가 된다)
  - 계산 전에 알 수 없는 것(증감 · 차이 결과의 음수 여부)은 막지 않고 모듈 3 에 맡긴다
  - 의미 확인: 부분-전체 차트(원 · 도넛 · 누적 막대 · 트리맵)는 부분이 시점이 아니고, 값이 증감 · 차이 · 비율 · 순위가 아닐 때만
"""
import re

from .chart_type_rules import TOTAL_WORDS

TIME = "시점"
SIGNED_MEASURES = {"change", "growth_rate", "cagr", "diff", "index"}      # 계산 결과가 음수일 수 있다 → 음수 여부는 모듈 3 이 판정
NOT_PART_MEASURES = SIGNED_MEASURES | {"ratio", "rank", "extreme"}         # 더해서 전체가 되지 않는 값
PART_WHOLE = ("pie", "donut", "stacked_bar", "treemap")
DIFF_MEASURES = ("change", "growth_rate", "diff")                         # 결과가 1개면 비교한 값들을 그린다
YEARLY = re.compile(r"매년|해마다|매해|전년\s*대비|직전|연도별\s*(?:증감|증가|감소|변화)")   # 모듈 3 planner._YEARLY + '직전'


def _clean(v):
    return re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", str(v)))


def n_eff(dim):
    """총계(계 · 합계 · 전국 …)를 뺀 값 수. 차트의 부분 · 범주가 되는 값만 센다"""
    return sum(1 for v in dim.get("values") or [] if _clean(v) not in TOTAL_WORDS)


def _cats(p):
    """시점이 아닌 범주 열 중 값이 2개 이상인 것 (총계 제외)"""
    return [d for d in p.get("dims") or [] if d.get("axis") != TIME and n_eff(d) >= 2]


def _axis(cats, name):
    return next((d for d in cats if d.get("axis") == name), None)


def _whole_and_parts(p, measure):
    """[NEW 11-27] 전체 대비 부분 비중인가: 비중 · 시점 하나 · 시점이 아닌 범주 열 하나에 총계(전국 · 계)와 부분 1개 이상.
    '2024년 전국 대비 서울 출생아 비중' 은 총계를 빼면 조각이 서울 하나라 원 · 도넛에서 떨어지고 막대(전국 100 · 서울 17.5)가 됐다.
    모듈 3 이 총계 행을 빼고 '그 외' 조각(100% − 부분 합)을 더해 원을 채운다 (chart_calculate/content.py _whole_remainder)"""
    if measure != "share" or (p.get("n_points") or 0) > 1:
        return False
    dims = [d for d in p.get("dims") or [] if d.get("axis") != TIME]
    return any(n_eff(d) >= 1 and any(_clean(v) in TOTAL_WORDS for v in d.get("values") or []) for d in dims)


def _non_negative(p, measure):
    """음수가 없는가. 계산하면 부호가 바뀔 수 있는 measure 는 판정하지 않는다 (None)"""
    return None if measure in SIGNED_MEASURES else bool(p.get("non_negative"))


SINGLE_VALUE = "값이 1개뿐 (비교할 값이 없음)"     # [NEW 11-25 6-4] 좌표에서 떨어진 이유. 안내(agent/chart_notice.py)가 이 말로 이유를 알아본다


def _frames(p, measure, requested=False):
    """차트 → (자리를 채울 수 있는가, 필요한 자리 설명). 개수는 계산 전 표 기준이고 최소 개수만 본다
    requested: [NEW 11-25 6-3] 사용자가 이름으로 요청한 차트를 검사하는가. 요청한 산점도 · 버블은 계열(남자 · 여자처럼 정확히 2 · 3개)을
               지표로 본다 — '시도별 남자 인구수와 여자 인구수의 관계를 산점도로' 는 표의 항목이 남자인구수 · 여자인구수라
               모듈 2 가 지표 1개(인구수) + 성별 계열 2개로 읽어 산점도를 탈락시켰다 (15유형 T3-scatter). 요청이 없으면 이전과 같다"""
    t = p.get("n_points") or 0
    cats = _cats(p)
    c1 = n_eff(cats[0]) if cats else 0
    cat_n = p.get("n_categories") or 0
    ser_n = max(p.get("n_series") or 1, 1)
    nm = p.get("n_measures") or 0
    split = ser_n if requested and len(cats) >= 2 else 0                # 요청할 때만: 범주와 다른 나눔의 값 수
    pos = _non_negative(p, measure) is not False                         # 모르면 통과
    sex = _axis(cats, "성별")
    second = len(cats) >= 2 or (cats and t >= 2) or nm >= 2               # 범주 말고 나눌 기준(계열)이 하나 더 있는가
    # [NEW 11-27] 같은 주기끼리 견주는 레이더: 월 · 분기 3~12칸이 축, 연도(2개 이상) · 범주 · 지표가 다각형
    #   ('전국 월별 출생아수의 2015·2020·2025년' 은 시점이 아닌 범주가 없어 '범주 3개 이상 + 계열' 에서 떨어졌다)
    cyc = p.get("cycle") or {}
    by_cycle = 3 <= (cyc.get("n_positions") or 0) <= 12 and ((cyc.get("n_years") or 0) >= 2 or bool(cats) or nm >= 2)
    whole = _whole_and_parts(p, measure)          # [NEW 11-27] 전국 + 서울 → 서울 · 그 외 두 조각
    return {
        "line":        (t >= 3,                                  "시점 3개 이상"),
        "area":        (t >= 3 and pos,                          "시점 3개 이상 + 음수 없음"),
        "bar":         (cat_n * ser_n >= 2,                      "범주 또는 시점으로 값 2개 이상"),
        "stacked_bar": (bool(cats) and ser_n >= 2 and pos,       "범주 + 쌓을 계열 2개 이상 + 음수 없음"),
        "pyramid":     (bool(_axis(cats, "연령")) and bool(sex) and n_eff(sex) == 2 and pos,
                        "연령 + 성별 2개 + 음수 없음"),
        "pie":         ((c1 >= 2 or whole) and pos,              "시점이 아닌 범주 2개 이상 + 음수 없음"),
        "donut":       ((c1 >= 2 or whole) and pos,              "시점이 아닌 범주 2개 이상 + 음수 없음"),
        "combo":       (t >= 3 and nm >= 2,                      "시점 3개 이상 + 지표 2개"),
        "scatter":     (c1 >= 5 and (nm >= 2 or split == 2),     "범주 5개 이상 + 지표 2개"),
        "bubble":      (c1 >= 2 and (nm >= 3 or split == 3),     "범주 2개 이상 + 지표 3개"),
        "dumbbell":    (c1 >= 2 and bool(p.get("two_points_per_category")), "범주 2개 이상 + 비교 대상 2개"),
        "radar":       ((c1 >= 3 and bool(second)) or by_cycle,  "범주 3개 이상 + 계열"),
        "map":         (bool(p.get("has_region")),               "지역 2곳 이상"),
        "heatmap":     ((p.get("n_dims") or 0) >= 2,             "나누는 기준 2종류"),
        "treemap":     (len(cats) >= 2 and pos,                  "상위 범주 + 하위 범주 + 음수 없음"),
    }


def _meaning(chart, p, measure):
    """형식은 맞아도 뜻이 맞지 않는 차트 → 이유 (없으면 None)"""
    if chart not in PART_WHOLE:
        return None
    if measure in NOT_PART_MEASURES:
        return f"부분-전체 차트인데 값이 {measure} (더해서 전체가 되지 않음)"
    cat = (p.get("category_axis") or {}).get("axis")
    ser = (p.get("series_axis") or {}).get("axis")
    part = ser if chart == "stacked_bar" else cat
    if part == TIME:
        return "부분-전체 차트인데 부분이 시점 (시점은 전체의 부분이 아님)"
    return None


def check_frame(chart, profile, measure=None, requested=False):
    """차트 하나 → (통과 여부, 못 맞춘 이유 목록, 필요한 자리 설명)
    requested: [NEW 11-25] 사용자가 요청한 차트인가 (_frames 참고)
    [CHANGED 11-25 6-4] 표의 값이 1개뿐이면 떨어진 이유를 SINGLE_VALUE 로 남긴다 (통과 · 탈락은 그대로). 이전: 차트마다 필요한 자리
      ('좌표가 맞지 않음: 시점이 아닌 범주 2개 이상 …')만 남아, 안내가 '이 자료로는 원그래프를 그릴 수 없어' 처럼 이유 없이 나갔다"""
    frames = _frames(profile, measure, requested)
    if chart not in frames:
        return False, ["지원하지 않는 차트"], ""
    ok, need = frames[chart]
    single = profile.get("n_values") is not None and profile["n_values"] <= 1     # 값 수를 모르면(손으로 만든 profile) 이전 문구
    fails = [] if ok else [SINGLE_VALUE if single else f"좌표가 맞지 않음: {need}"]
    if ok and (why := _meaning(chart, profile, measure)):
        fails.append(why)
    return not fails, fails, need


def chart_measure(m, query_bundle):
    """차이 계산(change · growth_rate · diff)의 결과가 1개뿐이면 차트는 비교한 값들(raw)을 그린다 → (measure, 이유).
    답변의 계산은 모듈 3 이 질문으로 따로 정한다 (차트 measure 만 바꾼다).
    결과가 여러 개일 수 있는 경우는 그대로 둔다: 시도별 증감(범주가 여럿) · 시점 3개 이상 · 해마다의 증감(매년 · 전년 대비)"""
    measure = m.get("measure")
    if measure not in DIFF_MEASURES:
        return measure, None
    texts = " ".join(str(x or "") for x in (m.get("sub_question"), query_bundle.get("original"), query_bundle.get("rewritten")))
    if YEARLY.search(texts):
        return measure, None
    prof = m.get("profile") or {}
    cats = _cats(prof)
    if measure == "diff":
        single = all(n_eff(d) <= 2 for d in cats)                          # 두 대상(서울 · 부산)의 차이 하나
    else:
        # 한 대상 · 시점 2개(2015 vs 2018)의 증감 하나. 시점이 3개 이상이면 해마다의 증감일 수 있어 증감 차트를 그대로 둔다
        single = not cats and (prof.get("n_points") or 0) == 2
    if not single:
        return measure, None
    return "raw", f"{measure} 결과가 1개라 비교한 값을 그림 (답변은 {measure} 계산)"
