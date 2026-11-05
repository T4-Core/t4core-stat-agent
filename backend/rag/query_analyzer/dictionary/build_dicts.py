"""원본 사전(dictionary_표명.json) → 사전 2개

  rule_dict.json : 규칙 사전. 뜻이 하나뿐인 확실한 표기만 (서울특별시 = 서울, 서울시). 2-2 코드 추출, 2-4 검증
                   기본 형식 {슬롯: {대표값: [대표값, 표기, ...]}}  리스트 첫 값은 대표값 자신
                     슬롯 = 지역 / 성별 / 국적 / 축 / 이동 / 조건 / 연령 / 연령_한글숫자
                   묶음 형식 {슬롯_묶음: {이름: {"표기": [...], "값": [대표값, ...]}}}  한 표현 → 값 여러 개
                     지역_묶음 (수도권 → 서울·인천·경기), 성별_묶음 (남녀 → 남자·여자)
                   지역_제외 {시도 표기: [뒤에 오면 지역이 아닌 말]}  ('경기 침체')
  term_dict.json : 일상어 → 통계어 사전. 범위가 넓거나 여러 뜻으로 읽히는 말 (영유아 = 0세~5세, 유아, 아기 …)
  term_dict.json : 일상어 → 통계어 사전. 뜻을 풀어야 하는 표현 (2-1 → 2-3 HCX 힌트, 2-4 대표 용어 통일)
                   형식 {대표 용어: [일상어, ...]}  → 노트북 load_term_dict(path, fmt="term") 로 바로 읽힘

원본은 고치지 않음. 원본을 고친 뒤 다시 실행하면 두 파일이 이 폴더에 새로 만들어짐
    python backend/rag/query_analyzer/dictionary/build_dicts.py
원본 위치: <저장소 루트>/dictionary_0/test2/results/dictionary_표명.json (작업용, git 에 없음) → 있으면 우선
          없으면 이 폴더의 dictionary_표명.json (git 에 올리는 복사본. 원본을 고쳤으면 이 파일도 같이 바꿀 것)

어느 쪽으로 보낼지는 아래 4개 목록으로 정함 (검토할 곳은 여기뿐)
  TERM_SECTIONS : 섹션 전체를 term_dict 로
  TO_TERM       : 규칙 섹션 안에서 term_dict 로 보낼 일상어
  EXCLUDE       : 어느 사전에도 넣지 않을 표현 (이유 포함)
  RENAME        : 대표 용어 이름 바꾸기
"""
import json
import re
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent                   # backend/rag/query_analyzer/dictionary
PROJECT_ROOT = OUT_DIR.parents[3]                           # 저장소 루트
SRC = next((p for p in [PROJECT_ROOT / "dictionary_0" / "test2" / "results" / "dictionary_표명.json",
                        PROJECT_ROOT / "dictionary" / "test2" / "results" / "dictionary_표명.json",   # 예전 폴더 이름
                        OUT_DIR / "dictionary_표명.json"] if p.exists()),
           OUT_DIR / "dictionary_표명.json")
MIN_ALIAS_LEN = 2          # 노트북과 같은 기준. 한 글자 표현은 다른 단어 안에서 잘못 잡힘

# ---- 섹션 → 어느 사전, 어느 슬롯 ----
TERM_SECTIONS = ["TARGET_ALIASES", "INDICATOR_ALIASES"]
RULE_SECTIONS = {"AXIS_ALIASES": "축", "REGION_LEVEL_ALIASES": "축",
                 "MOVE_ALIASES": "이동", "CONDITION_ALIASES": "조건", "AGE_TITLE_WORDS": "연령"}
SKIP_SECTIONS = {"UNSORTED": "토큰 조각(가지지, 취득한 …)이라 사전 항목이 아님"}

# 항목 전체를 다른 사전으로 (섹션이 잘못 들어간 것)
MOVE_ENTRY_TO_TERM = {
    ("AXIS_ALIASES", "이민자"): "비교축이 아니라 대상",
    ("MOVE_ALIASES", "이동"): "이동 슬롯 정해진 값(전입·전출·순이동·입국·출국·국제순이동)이 아님",
    ("MOVE_ALIASES", "국제이동"): "이동 슬롯 정해진 값이 아님",
}

# ---- 규칙 섹션 안에서 일상어로 보낼 표현 {(섹션, 대표값): [표현]} ----
TO_TERM = {
    ("AXIS_ALIASES", "혼인상태"): ["결혼 여부", "결혼상태", "결혼 상태"],
    ("AXIS_ALIASES", "가구원수"): ["가족 수", "식구 수"],
    ("AXIS_ALIASES", "교육정도"): ["교육 수준"],
    ("AXIS_ALIASES", "거주지"): ["사는 곳", "사는 지역"],
    ("AXIS_ALIASES", "체류자격"): ["비자", "비자 종류"],
    ("AXIS_ALIASES", "출산순위"): ["몇째"],
    ("AXIS_ALIASES", "다태아 여부"): ["쌍태아", "쌍태아 이상"],
    ("AXIS_ALIASES", "거처의 종류"): ["주택 유형", "집 종류", "주거 형태", "주거의 종류"],
    ("AXIS_ALIASES", "사용방수"): ["방수"],
    ("AXIS_ALIASES", "세대구성"): ["가족 구성", "가구 구성"],
    ("AXIS_ALIASES", "연령"): ["나이", "나이대"],
    ("AXIS_ALIASES", "혼인지속기간"): ["결혼생활기간", "동거기간"],
    ("AXIS_ALIASES", "가구주와의 관계"): ["가족관계"],
    ("AXIS_ALIASES", "출입국항"): ["공항", "항구"],
    ("AXIS_ALIASES", "주거면적"): ["연면적"],                     # 연면적은 건물 전체 바닥 면적이라 같지 않음
    # 유입·유출은 국내(전입·전출)와 국제(입국·출국) 둘 다로 읽힘
    ("MOVE_ALIASES", "전입"): ["이사 온", "들어온", "유입"],
    ("MOVE_ALIASES", "전출"): ["이사 간", "빠져나간", "떠난", "유출"],
    ("MOVE_ALIASES", "순이동"): ["순유입", "순유출"],
    ("CONDITION_ALIASES", "자료=장래인구추계"): ["장래", "미래", "전망", "예측", "앞으로"],
    ("AGE_TITLE_WORDS", "65세 이상"): ["노인", "어르신", "노년층"],
    ("AGE_TITLE_WORDS", "15~64세"): ["생산연령인구", "생산가능인구"],
}

# ---- 넣지 않을 표현 {(섹션, 대표값): {표현: 이유}} ----
EXCLUDE = {
    ("TARGET_ALIASES", "실업자"): {
        "비경제활동인구": "비경제활동인구는 실업자가 아님 (실업자는 경제활동인구)",
        "돈을 벌지 않는 사람": "비경제활동인구 뜻이 섞임",
        "경제활동 안하는 사람": "비경제활동인구 뜻",
    },
    ("TARGET_ALIASES", "세대"): {a: "'21대 국회', '1대 1' 등에서 잡힘" for a in ["1대", "2대", "3대"]},
    ("TARGET_ALIASES", "청소년"): {"학생": "'대학생', '초등학생' 안에서 잡힘"},
    ("AXIS_ALIASES", "자녀수"): {a: "자녀수의 일부만 세는 다른 지표" for a in ["미성년자녀수", "취학자녀수", "아동수"]},
    ("REGION_LEVEL_ALIASES", "전국"): {"전국": "축이 아니라 지역 값. 노트북 SIDO 대응표가 처리"},
    ("TARGET_ALIASES", "자녀"): {"아이": "아동에만 둠"},
    ("TARGET_ALIASES", "영유아"): {"어린 아이": "아동에만 둠",
                                   "0-5세": "AGE_WORD_TERMS 의 '0세~5세' 로 대신함",
                                   "0세": "'10세', '20세' 안에서 잡힘"},
    ("TARGET_ALIASES", "종사자"): {"일하는 사람": "취업자에만 둠"},
}

# ---- term_dict 대표 용어 합치기 {없앨 대표 용어: 남길 대표 용어}. 없앤 대표 용어는 남길 쪽의 일상어가 됨 ----
MERGE_TERM = {
    "65세 이상": "고령자",         # 노인·어르신·노년층·65세 이상 → 고령자
    "15~64세": "생산연령인구",     # 고령자와 같은 방식 (말이 대표 용어, 숫자 연령은 일상어)
}

# ---- 연령을 뜻하는 넓은 말 → term_dict {대표 용어: [일상어]} ----
# 노트북 2-2 AGE_WORDS 단어를 대표 용어에 붙임. 숫자 연령(1세 …)은 사용자 요청으로 영유아에 넣음
AGE_WORD_TERMS = {
    "고령자": ["노인", "어르신", "고령", "노년", "노령", "실버"],
    "영유아": ["0세~5세", "1세", "2세", "3세", "4세", "5세", "신생아", "영아", "유아", "미취학"],
    "아동": ["초등학생"],
    "유소년인구": ["유소년"],
    "학령인구": ["학령"],
    "청소년": ["미성년", "중학생", "고등학생"],
    "청년": ["젊은층", "청장년"],
    "중장년": ["중년", "장년", "베이비붐", "베이비부머"],
    "생산연령인구": ["생산연령", "생산가능"],
}

# ---- 노트북 2-2 대응표 (2026-11-05 기준 복사). 이제 이 파일이 원본 → 노트북은 rule_dict.json 을 읽게 바꿀 것 ----
SIDO_ALIASES = {
    "서울특별시": ["서울시", "서울"], "부산광역시": ["부산시", "부산"], "대구광역시": ["대구시", "대구"],
    "인천광역시": ["인천시", "인천"],
    "광주광역시": ["광주"],                       # '광주시'는 경기도 광주시 → 넣지 않음
    "대전광역시": ["대전시", "대전"], "울산광역시": ["울산시", "울산"], "세종특별자치시": ["세종시", "세종"],
    "경기도": ["경기"],                           # '경기 침체' 등은 지역_제외
    "강원특별자치도": ["강원도", "강원"], "충청북도": ["충북"], "충청남도": ["충남"],
    "전북특별자치도": ["전라북도", "전북"], "전라남도": ["전남"], "경상북도": ["경북"], "경상남도": ["경남"],
    "제주특별자치도": ["제주도", "제주"],         # '제주시'는 시군구 → 넣지 않음
    "전국": ["전체 지역", "우리나라", "국내 전체"],
}
_CAPITAL = ["서울특별시", "인천광역시", "경기도"]
_ALL_SIDO = [s for s in SIDO_ALIASES if s != "전국"]
SIDO_GROUPS = {   # {이름: ([표기], [시도])}
    "수도권": (["수도권"], _CAPITAL),
    "비수도권": (["비수도권"], [s for s in _ALL_SIDO if s not in _CAPITAL]),
    "충청권": (["충청권", "충청"], ["대전광역시", "세종특별자치시", "충청북도", "충청남도"]),
    "호남권": (["호남권", "호남"], ["광주광역시", "전북특별자치도", "전라남도"]),
    "영남권": (["영남권", "영남"], ["부산광역시", "대구광역시", "울산광역시", "경상북도", "경상남도"]),
    "동남권": (["동남권", "부울경"], ["부산광역시", "울산광역시", "경상남도"]),
    "대경권": (["대경권", "대구경북", "대구·경북"], ["대구광역시", "경상북도"]),
    "충청도": (["충청도"], ["충청북도", "충청남도"]),
    "전라도": (["전라도", "전라"], ["전북특별자치도", "전라남도"]),
    "경상도": (["경상도", "경상"], ["경상북도", "경상남도"]),
}
SIDO_BLOCK = {"경기": ["침체", "불황", "호황", "회복", "둔화", "부진", "하강", "상승", "악화", "개선", "동향", "전망", "부양",
                       "변동", "순환", "지수", "국면", "선행", "동행", "후행", "실사", "민감", "장", "력", "일정", "결과"]}
SEX = {"남자": ["남성"], "여자": ["여성"]}
# 두 뜻이 합쳐진 말 → term_dict 에서 대표 용어 여러 개를 가리킴 (HCX 힌트: '남중생 → 남자, 중학생')
# 규칙 사전에 '남자' 로 두면 '중학생' 이 빠진 채 성별만 확정되므로 뺌
COMPOUND_TERMS = {
    "남학생": ["남자", "학생"], "남중생": ["남자", "중학생"], "남고생": ["남자", "고등학생"],
    "여학생": ["여자", "학생"], "여중생": ["여자", "중학생"], "여고생": ["여자", "고등학생"],
}
SEX_BOTH = ["남녀", "남여", "여남", "남·여", "남/여", "남,여", "남과 여"]
KOR_TENS = {"90": ["구십"], "80": ["팔십"], "70": ["칠십"], "60": ["육십"], "50": ["오십"], "40": ["사십"],
            "30": ["삼십"], "20": ["이십"], "10": ["십"]}
COUNTRY_ALIASES = {   # 넣지 않은 이름: 이란·오만·가나·말리·차드·기니 (일반 단어와 겹침)
    "중국": ["중국인"], "한국계 중국": ["한국계중국", "조선족", "중국동포", "중국 동포"],
    "일본": ["일본인"], "대만": ["타이완"], "홍콩": [], "몽골": [],
    "베트남": [], "필리핀": [], "태국": [], "인도네시아": [], "캄보디아": [], "미얀마": ["버마"], "라오스": [],
    "말레이시아": [], "싱가포르": ["싱가폴"], "동티모르": [],
    "네팔": [], "스리랑카": [], "방글라데시": [], "파키스탄": [], "인도": [],
    "우즈베키스탄": ["우즈벡"], "카자흐스탄": ["카자흐"], "키르기스스탄": ["키르기스"], "타지키스탄": [],
    "투르크메니스탄": [], "러시아": [], "우크라이나": [],
    "미국": ["미국인"], "캐나다": [], "멕시코": [], "브라질": [], "호주": ["오스트레일리아"], "뉴질랜드": [],
    "영국": [], "프랑스": [], "독일": [], "이탈리아": [], "스페인": [], "네덜란드": [],
    "튀르키예": ["터키"], "이집트": [], "나이지리아": [], "남아프리카공화국": ["남아공"],
}
# 노트북 대응표 중 한 글자도 그대로 둘 것 (KOR_TENS '십'은 '삼십대' 같은 숫자 패턴 안에서만 씀)
KEEP_SHORT = {"십"}
# 여러 뜻으로 읽힐 수 있어 확인이 필요한 표기 (규칙 사전에 두되 보고서에 표시)
REVIEW = {
    "광주": "광주광역시 / 경기도 광주시",
    "충청": "충청권(대전·세종 포함) / 충청도(충북·충남)",
    "인도": "국가 / '인도(人道)', '인도하다'",
}

# ---- 대표 용어 이름 바꾸기 ----
RENAME = {
    ("MOVE_ALIASES", "이동"): "인구이동",                     # 노트북 TERM_DICT 와 맞춤
    ("CONDITION_ALIASES", "자료=장래인구추계"): "장래인구추계",  # term_dict 쪽만. HCX 힌트에 '자료=' 가 보이지 않게
}

# ---- 노트북 2-1 TERM_DICT (2026-11-05 기준 복사). 원본 사전과 겹치면 원본이 우선 ----
NOTEBOOK_TERM_DICT = {
    "65세 이상": ["노인", "어르신", "늙은이", "노년층", "고령자"],
    "고령인구비율": ["노인 비율", "고령자 비율", "늙은이 비율", "고령화율", "고령화"],
    "유소년인구": ["어린이 인구", "아이 인구"],
    "생산연령인구": ["일하는 나이 인구", "생산가능인구"],
    "평균연령": ["평균 나이"],
    "성비": ["남녀 비율", "여초", "남초"],
    "인구밀도": ["사람 밀도"],
    "지방소멸위험지수": ["지방소멸", "소멸위험"],
    "기대수명": ["평균 수명", "오래 사는", "수명"],
    "출생아수": ["애 낳는 사람", "애 낳는", "아기 태어", "애기 태어", "태어난 아이", "신생아 수", "출생 수"],
    "합계출산율": ["출산율", "애 낳는 비율"],
    "사망자수": ["죽은 사람", "사망 수"],
    "자연증가건수": ["자연감소", "자연증가"],
    "혼인건수": ["결혼", "시집", "장가", "결혼 건수"],
    "조혼인율": ["결혼율", "혼인율"],
    "평균초혼연령": ["결혼 나이", "결혼 연령", "초혼 나이", "처음 결혼 나이"],
    "이혼건수": ["이혼", "갈라서", "갈라선"],
    "조이혼율": ["이혼율"],
    "외국인과의 혼인건수": ["국제결혼"],
    "가구수": ["세대 수", "집 몇 채"],
    "1인가구": ["혼자 사는", "나홀로 가구", "독신 가구", "싱글 가구"],
    "다문화가구": ["다문화 가정"],
    "평균 가구원수": ["평균 가구원", "한 집에 몇 명"],
    "전출": ["빠져나가", "빠져나간", "이사 가", "이사가", "떠난 사람", "유출"],
    "전입": ["이사 온", "이사온", "들어온 사람", "유입"],
    "순이동": ["순유입", "순유출"],
    "인구이동": ["이사", "이주"],
    "외국인근로자": ["외노자", "외국인 노동자", "이주노동자"],
    "결혼이민자": ["결혼 이민자", "결혼이주여성", "결혼 이주민"],
    "체류외국인": ["머무는 외국인", "사는 외국인"],
    "장래인구추계": ["인구 전망", "미래 인구", "인구 예측", "앞으로 인구"],
    "장래가구추계": ["가구 전망", "미래 가구", "가구 예측"],
}


def ns(s):
    return re.sub(r"\s+", "", str(s))


def add(d, key, alias):
    """d[key] 에 alias 추가. 대표 용어와 띄어쓰기만 다르거나 이미 있으면 넣지 않음"""
    lst = d.setdefault(key, [])
    if ns(alias) != ns(key) and all(ns(alias) != ns(x) for x in lst):
        lst.append(alias)


def add_rule(d, key, alias):
    """rule_dict 용. 대표값 자신과 띄어쓰기만 다른 표기도 넣음 (같은 글자 그대로인 중복만 뺌)"""
    lst = d.setdefault(key, [key])
    if alias not in lst:
        lst.append(alias)


def build():
    src = json.loads(SRC.read_text(encoding="utf-8"))
    rule = defaultdict(dict)        # {슬롯: {대표값: [표기]}}
    term = {}                       # {대표 용어: [일상어]}
    log = defaultdict(list)         # 보고서

    # ---- 노트북 2-2 대응표 → rule_dict (앞쪽 섹션) ----
    for slot, table in [("지역", SIDO_ALIASES), ("성별", SEX), ("국적", COUNTRY_ALIASES), ("연령_한글숫자", KOR_TENS)]:
        for v, al in table.items():
            rule[slot].setdefault(v, [v])
            for a in al:
                if len(ns(a)) < MIN_ALIAS_LEN and a not in KEEP_SHORT:
                    log["한 글자라 뺀 표현"].append(f"{v}: '{a}'")
                    continue
                add_rule(rule[slot], v, a)
    rule["지역_묶음"] = {n: {"표기": names, "값": sidos} for n, (names, sidos) in SIDO_GROUPS.items()}
    rule["지역_제외"] = SIDO_BLOCK
    rule["성별_묶음"] = {"남녀": {"표기": SEX_BOTH, "값": ["남자", "여자"]}}

    for sec, entries in src.items():
        if sec in SKIP_SECTIONS:
            log["섹션 제외"].append(f"{sec} ({len(entries)}개): {SKIP_SECTIONS[sec]}")
            continue
        if sec not in TERM_SECTIONS and sec not in RULE_SECTIONS:
            log["모르는 섹션 (건너뜀)"].append(sec)
            continue
        for key, aliases in entries.items():
            k = (sec, key)
            excl, to_term = EXCLUDE.get(k, {}), set(TO_TERM.get(k, []))
            if key in excl:                    # 대표값 자체를 뺌 → 항목 전체 제외
                log["제외한 항목"].append(f"{sec}.{key} — {excl[key]}")
                continue
            whole_to_term = sec in TERM_SECTIONS or k in MOVE_ENTRY_TO_TERM
            if k in MOVE_ENTRY_TO_TERM:
                log["항목째 term_dict 로"].append(f"{sec}.{key}: {MOVE_ENTRY_TO_TERM[k]}")
            term_key = RENAME.get(k, key)
            rule_key = key                     # RENAME 은 term_dict 쪽만

            if whole_to_term:
                term.setdefault(term_key, [])
            else:
                rule[RULE_SECTIONS[sec]].setdefault(rule_key, [rule_key])

            for a in aliases:
                a = str(a).strip()
                if a in excl:
                    log["제외한 표현"].append(f"{key}: '{a}' — {excl[a]}")
                    continue
                if len(ns(a)) < MIN_ALIAS_LEN:
                    log["한 글자라 뺀 표현"].append(f"{key}: '{a}'")
                    continue
                if whole_to_term or a in to_term:
                    add(term, term_key, a)
                else:
                    add_rule(rule[RULE_SECTIONS[sec]], rule_key, a)
            for a in to_term - set(aliases):
                log["TO_TERM 에 있지만 원본에 없는 표현"].append(f"{key}: '{a}'")

    # ---- 노트북 TERM_DICT 합치기 (원본이 이미 다른 대표 용어로 쓰는 일상어는 건너뜀) ----
    owner = {ns(a): t for t, al in term.items() for a in [t, *al]}
    in_rule = {ns(a): f"{slot}:{v}" for slot, d in rule.items() for v, al in d.items() for a in [v, *al]}
    for t, al in NOTEBOOK_TERM_DICT.items():
        term.setdefault(t, [])
        for a in al:
            if ns(a) in in_rule:
                log["노트북 TERM_DICT 에서 건너뜀 (rule_dict 에 이미 있음)"].append(f"'{a}' → {in_rule[ns(a)]}")
                continue
            o = owner.get(ns(a))
            if o and o != t:
                log["노트북 TERM_DICT 에서 건너뜀 (원본 우선)"].append(f"'{a}': 노트북 {t} / 원본 {o}")
                continue
            add(term, t, a)
            owner.setdefault(ns(a), t)

    # ---- 연령을 뜻하는 넓은 말 ----
    for t, al in AGE_WORD_TERMS.items():
        if t not in term:
            log["AGE_WORD_TERMS 로 새로 만든 대표 용어"].append(f"{t}: {al}")
        term.setdefault(t, [])
        for a in al:
            add(term, t, a)

    # ---- 두 뜻이 합쳐진 말 ----
    for a, ts in COMPOUND_TERMS.items():
        for t in ts:
            add(term, t, a)
        log["두 뜻이 합쳐진 말 (대표 용어 여러 개, 의도한 것)"].append(f"'{a}' → {', '.join(ts)}")

    # ---- 대표 용어 합치기 ----
    for old, new in MERGE_TERM.items():
        if old not in term:
            log["MERGE_TERM 에 있지만 term_dict 에 없음"].append(old)
            continue
        for a in [old, *term.pop(old)]:
            add(term, new, a)
        log["대표 용어 합침"].append(f"{old} → {new}: {term[new]}")

    # ---- 검사 ----
    seen = defaultdict(set)                                  # term_dict 안: 일상어 → 대표 용어들
    for t, al in term.items():
        for a in al:
            seen[ns(a)].add(t)
    compound = {ns(a) for a in COMPOUND_TERMS}
    for a, ts in seen.items():
        if len(ts) > 1 and a not in compound:
            log["term_dict 충돌: 한 일상어가 대표 용어 여러 개 (to_canonical 이 바꾸지 않음)"].append(
                f"'{a}' → {', '.join(sorted(ts))}")
    rule_seen = defaultdict(set)
    for slot, d in rule.items():
        if slot == "지역_제외":                               # 표기가 아니라 '뒤에 오는 말' 목록
            continue
        for v, al in d.items():
            al = al["표기"] if isinstance(al, dict) else al
            for a in [v, *al]:
                rule_seen[ns(a)].add(f"{slot}:{v}")
    for a, vs in rule_seen.items():
        if len(vs) > 1:
            log["rule_dict 충돌"].append(f"'{a}' → {', '.join(sorted(vs))}")
    for a in seen:
        if a in rule_seen:
            log["두 사전에 모두 있음"].append(f"'{a}' → rule {sorted(rule_seen[a])} / term {sorted(seen[a])}")
    for a, why in REVIEW.items():
        log["규칙 사전에 두었지만 확인 필요 (여러 뜻)"].append(f"'{a}': {why}")

    return dict(rule), term, log


def main():
    rule, term, log = build()
    (OUT_DIR / "rule_dict.json").write_text(json.dumps(rule, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "term_dict.json").write_text(json.dumps(term, ensure_ascii=False, indent=2), encoding="utf-8")

    print("rule_dict.json : " + ", ".join(f"{s} {len(d)}" for s, d in rule.items()))
    print(f"term_dict.json : 대표 용어 {len(term)}개 / 일상어 {sum(len(a) for a in term.values())}개")
    for title, items in log.items():
        print(f"\n[{title}] {len(items)}건")
        for it in items:
            print("  -", it)


if __name__ == "__main__":
    main()
