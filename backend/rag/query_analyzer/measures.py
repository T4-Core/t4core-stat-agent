"""[NEW 11-12] 지표 칸에 들어오는 '계산 단어' · '수를 세는 일반 지표' 구분 (v3 검증 · v4 서브쿼리 분리 공용, HCX 호출 없음)

  계산 단어   : 표의 항목 이름이 아니라 구하는 방법 ('구성비', '비율', '증감률', '평균', '총계' …)
                → 지표에서 빼고(그 값만 있을 때), 뜻이 분명하면 의도로 옮김. 검색·조건 확인에 넣지 않음
  일반 지표   : 무엇을 세는지만 말하는 지표 ('인구수', '가구수', '건수', '호수' …)
                → 대상('국제결혼 이주자')과 한 개념. 따로 서브쿼리를 만들지 않음

144문항 비교 결과(11-12): 지표에 계산 단어가 든 질문 53개, 대상·지표를 따로 나눈 한 단어 서브쿼리 130개
"""
import re

# 값 전체가 이 말이면 계산 단어 (띄어쓰기·괄호 무시)
MEASURE_WORDS = {"구성비", "비율", "비중", "평균", "합계", "총합계", "총계", "증감", "증감률", "증감량", "증가율", "감소율",
                 "증가량", "감소량", "변화폭", "변화량", "변화율", "차이", "순위", "비교", "추이", "값", "수치", "변화폭%p"}
# 계산 단어 → 의도 (뜻이 하나로 정해지는 것만. '차이'·'평균'은 비교·증감·합계 중 하나로 정할 수 없어 옮기지 않음)
MEASURE_INTENT = {"구성비": "구성비", "비율": "구성비", "비중": "구성비", "증감": "증감", "증감량": "증감", "증가량": "증감",
                  "감소량": "증감", "변화량": "증감", "증감률": "증감률", "증가율": "증감률", "감소율": "증감률",
                  "변화율": "증감률", "변화폭": "증감률", "변화폭%p": "증감률", "순위": "순위", "합계": "합계",
                  "총합계": "합계", "총계": "합계", "추이": "추이", "비교": "비교"}
# 값 끝에 붙은 의도성 계산 단어는 떼어 냄 ('전입 증감률' → '전입'). '비율'·'구성비'·'평균'은 표 이름에도 쓰여 떼지 않음
TRAILING_MEASURES = ("증감률", "증감량", "증감", "증가율", "감소율", "변화폭", "변화량", "변화율", "순위")
# 수를 세는 일반 지표
GENERIC_INDICATORS = {"인구수", "인구", "인원", "인원수", "명수", "사람수", "가구수", "가구", "건수", "호수", "세대수"}


def squash(v):
    return re.sub(r"[\s()（）\[\]_·]", "", str(v or ""))


def is_measure(v):
    """값 전체가 계산 단어인가 ('구성비', '변화폭(%p)')"""
    return squash(v) in MEASURE_WORDS


def strip_trailing_measure(v):
    """끝에 붙은 의도성 계산 단어를 뗌 ('전입 증감률' → '전입'). 떼고 남는 게 없으면 원래 값"""
    s = str(v).strip()
    for w in TRAILING_MEASURES:
        m = re.match(rf"^(.*\S)\s*{w}(?:\(%p?\))?$", s)
        if m and squash(m.group(1)) and not is_measure(m.group(1)):
            return m.group(1).strip()
    return s


def is_generic(v):
    """수를 세는 일반 지표인가 ('인구수', '가구 수')"""
    return squash(v) in GENERIC_INDICATORS


def _overlap(a, b):
    a, b = squash(a), squash(b)
    return bool(a and b) and (a in b or b in a)


def common_len(a, b):
    """두 말의 가장 긴 공통 부분 글자 수 (띄어쓰기 무시)"""
    a, b, best = squash(a), squash(b), 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = j - i
            else:
                break
    return best


def concept_groups(targets, indicators):
    """대상·지표 문자열 → 개념 목록 [{"지표": […], "대상": […]}] (서브쿼리 하나 = 개념 하나)
    1) 계산 단어('구성비')는 개념이 아님
    2) 구체적인 지표('혼인건수', '평균가구원수')는 이름이 겹치는 것끼리 한 개념 ('인구수'·'총인구수')
    3) 대상은 글자가 2자 이상 겹치는 구체 지표의 개념으로 ('이혼' → '이혼건수', '가구' → '평균가구원수').
       어느 구체 지표와도 안 겹치면 그 대상이 개념 하나 ('국제결혼 이주자')
    4) 일반 지표('인구수', '가구수')는 이름이 겹치는 구체 지표('총인구수'), 다음으로 글자가 겹치는 대상 개념에 붙임 ('인구수' → '인구').
       안 겹치면 아직 일반 지표가 없는 대상 개념에 붙이고, 그런 대상도 없으면 일반 지표가 개념 하나 ('주택수' + '인구수')
    예) 대상 [국제결혼 이주자] 지표 [인구수]           → 1개 (나누지 않음)
        대상 [외국인근로자, 국제결혼가정 자녀] 지표 [인구수, 증감률] → 2개
        대상 [주택, 인구] 지표 [가구수, 인구수]       → 2개 (주택+가구수, 인구+인구수)"""
    inds = [m for m in indicators or [] if not is_measure(m)]
    specific = [m for m in inds if not is_generic(m)]
    generic = [m for m in inds if is_generic(m)]
    concepts = []
    for m in specific:
        c = next((c for c in concepts if any(_overlap(m, x) for x in c["지표"])), None)
        c["지표"].append(m) if c else concepts.append({"지표": [m], "대상": []})
    free = []
    for d in targets or []:
        score = [max(common_len(d, m) for m in c["지표"]) for c in concepts]
        if score and max(score) >= 2:
            concepts[score.index(max(score))]["대상"].append(d)
        else:
            free.append({"지표": [], "대상": [d]})
    alone, pending = [], []
    for g in generic:                                    # 먼저 이름이 겹치는 구체 지표에 ('인구수' ⊂ '총인구수'), 다음 대상에 ('인구수' → '인구')
        host = next((c for c in concepts if any(_overlap(g, x) for x in c["지표"])), None)
        if host:
            host["지표"].append(g)
            continue
        score = [max(common_len(g, d) for d in c["대상"]) for c in free]
        if score and max(score) >= 2:
            free[score.index(max(score))]["지표"].append(g)
        else:
            pending.append(g)
    for g in pending:                                    # 남은 것은 일반 지표가 없는 대상에, 없으면 따로
        if lacking := [c for c in free if not c["지표"]]:
            lacking[0]["지표"].append(g) if len(pending) > 1 else [c["지표"].append(g) for c in lacking]
        else:
            alone.append({"지표": [g], "대상": []})
    return [c for c in concepts + free + alone if c["지표"] or c["대상"]]
