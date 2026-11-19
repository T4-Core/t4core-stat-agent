"""
dense 카드 — 표마다 dense(임베딩) 검색용 문서 두 개를 '질문 쪽과 같은 틀' 로 만든다

  slot  슬롯 정규문. 질문 분석기와 같은 슬롯(대상·지표·조건·이동·비교축·성별·연령)을 표 쪽에서 채우고,
        질문 쪽 렌더러(query_analyzer.sentence.slots_to_sentence)로 이어 붙인 명사구 + 표 이름
        → 재작성 문장 · 하위 질문 · 검색 문장(search_text) 과 같은 모양
  def   정의 서술문. 무엇을 어떤 단위로 세었는지 · 어떤 분류로 나뉘는지 · 주석의 정의·포함·제외·기준 ·
        주기 · 실적/추계 를 객관적으로 서술. 연도 숫자와 지역 이름은 쓰지 않는다 (지역은 '시군구 단위' 처럼 수준만).
        예상 질문 · 일상어 바꿔 말하기는 넣지 않는다

  두 문서 모두 첫머리에 '구분' — 이름이 비슷한 표(같은 무리·같은 조사)와 무엇이 다른지. LLM 이 아니라 코드가
  메타데이터 차이(제목에만 있는 말 · 성별판 · 지역 수준 · 연령 구간 · 실적/추계 · 주기 · 분류)로 만든다.
  LLM 에게는 비슷한 표의 이름을 주지 않는다 (그 표의 말이 이 표 문서에 섞이지 않게)

  같은 파일에 두 벌: LLM 판(slot · def)과 코드 템플릿판(tslot · tmpl) → 비교 실험에서 LLM 이 더하는 몫을 따로 볼 수 있음

입력  검색 코퍼스의 표 · 표 단면(facets: CSV 값 사전 > 메타 프로필) · 메타 프로필(주석·주기·조사 구분) ·
      CSV 값 사전의 항목·분류 주석(있으면) · 질문 쪽 표준 용어(query_analyzer/dictionary/dictionary_표명.json)
출력  STORAGE_DIR/indices/dense_cards/cards.jsonl   (표 하나 = 한 줄. 끊겨도 이어서 — 재료가 같으면 다시 부르지 않음)

검사 (LLM 결과를 그대로 믿지 않음)
  · 슬롯 값: 표준 용어이거나 이 표의 재료(이름·항목·분류·주석)에 있는 말만. 성별·연령 슬롯은 표 전체가 그 값일 때만
  · 정의 문장: 연도 · 지역 이름 · 비슷한 표에만 있는 말 · '다른 표' '질문' 같은 말이 든 문장은 버림.
    재료·표준 용어·일반 통계 낱말 어디에도 없는 명사가 둘 이상인 문장도 버림 (하나면 flags 에 기록)
  · 다 버려지면 코드 템플릿 정의로 (flags: def_fallback)
버전  재료 해시 = 재료 + 프롬프트 버전 + 질문 쪽 사전 해시. 사전이 바뀌면 check 가 '오래된 카드' 로 보여 줌

  python -m backend.rag.ingestion.dense_cards build --limit 20           # 앞 20개 (먼저 눈으로 확인)
  python -m backend.rag.ingestion.dense_cards build --workers 4          # 전체 (표당 HCX 1회)
  python -m backend.rag.ingestion.dense_cards build --no-llm             # 코드 템플릿만 (HCX 없음)
  python -m backend.rag.ingestion.dense_cards show DT_1B85003            # 재료 · 구분 · 카드
  python -m backend.rag.ingestion.dense_cards check                      # 범위 · 검사 · 길이 · 오래된 카드
  python -m backend.rag.ingestion.dense_cards recheck                    # 저장된 LLM 정의문에 지금 검사 규칙을 다시 (LLM 호출 없음)
  python -m backend.rag.ingestion.dense_cards vals DT_1IN1502            # 값 조각 + 표의 값 중 무엇이 조각에 들고 빠졌나
검색에 쓰기  configs/search.yaml 의 dense_docs (rule | def | slot | tmpl | tslot | kos14 | vals)
            '+' = 한 채널 안에서 표마다 최댓값 · ',' = 채널을 따로 두고 RRF 로 합침 (점수 크기가 다른 묶음은 ',' 로)
            vals = 항목·분류 값 조각 (value_chunks — 카드 없이 표 단면으로 만듦). 예: compare --dense-docs rule rule,def def,vals
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend.core.config import STORAGE_DIR

CARDS_PATH = STORAGE_DIR / "indices" / "dense_cards" / "cards.jsonl"
PROMPT_VER = "d1"  # LLM 프롬프트 버전 (검사 규칙만 바뀌면 그대로 — recheck 로 다시 검사)
DOC_SLOTS = ["대상", "지표", "조건", "이동", "비교축", "성별", "연령"]
MAX_SLOT_VALUES = 6
MAX_DEF_CHARS = 420
MAX_NOTES = 6
N_NEIGHBORS = 6

YEAR_RE = re.compile(r"(?<!\d)(?:1[89]\d{2}|20\d{2})(?!\d)")
AGE_LIMIT = re.compile(r"\d+\s*세\s*(?:이상|이하|미만|초과)")
YEAR_PAREN = re.compile(r"\(\s*~?\s*(?:19|20)\d{2}[^()]*\)")
BAD_PHRASE = re.compile(r"다른\s*표|비교했을\s*때|질문|예를\s*들|예시|일상|흔히|사람들이|검색|찾을\s*수|알\s*수\s*있")
NOTE_NOISE = re.compile(r"문의|전화|연락처|https?://|www\.|@|담당|홈페이지|출처\s*:")
SENT_SPLIT = re.compile(r"(?<=[.다요])\s+")
GEO_WORD = {"시도": "시도", "시군구": "시군구", "읍면동": "읍면동", "동읍면부": "동·읍·면부"}
CYCLE_WORD = {"Y": "연간", "H": "반기", "Q": "분기", "M": "월간"}
# 정의문에 나와도 되는 일반 통계 낱말 (재료에 없어도 '모르는 명사' 로 치지 않음)
ALLOW = set("""표 통계 자료 집계 기준 분류 구분 단위 대상 포함 제외 조사 결과 전망 추계 예측 실적 연간 월간 분기 반기 매년 매월 주기
수치 비율 구성 구성비 합계 전체 수준 지역 성별 연령 연령대 연령별 값 건수 수 명 개 호 가구 인구 남자 여자 남녀 시도 시군구 읍면동
전국 행정구역 항목 종류 유형 현황 규모 정도 상태 기간 시점 해당 각 별 이상 이하 미만 경우 내용 정의 의미 방식 산출 계산 측정 추정
기록 신고 등록 발생 기준일 현재 시기 조사구 표본 전수 행정 자료원 집단 부문 범주 세부 대표 주요 일반 총 계 총계 평균 비 율
제공 기반 다양 데이터 작성 정보 각각 시작 실시 그룹 업데이트 지표 관련 형태 분포 범위 수집 일환 실제 여부 분석 표시 확인 인원
설정 성격 응답 별도 적용 유무 세분 구간 남성 여성 성인 사람 국가 나라 수록 공표 발표 보고 기간별 연도별 이후 이전 최근 단계 경우
특징 목적 활용 내용 구성원 개수 숫자 수량 규모별 유형별 종류별 대상자 해당자 비중 비교 변화 추이 증감 차이""".split())  # noqa: SIM905


AGE_WIDTH = re.compile(r"(\d+)\s*세\s*\)")
PROJECTION = re.compile(r"장래|추계")


def age_width(nm):
    """'연령(5세)별' → '5' (제목에 없으면 None) — ingestion/series.py 와 같은 규칙 (그 모듈 없이도 돌게 여기 둠)"""
    m = AGE_WIDTH.search(str(nm or ""))
    return m.group(1) if m else None


def is_projection(p):
    return bool(PROJECTION.search(f"{p.get('tbl_nm') or ''} {p.get('survey_nm') or ''}"))


# ── 재료 ─────────────────────────────────────────────────────────
def _n(s):
    from backend.rag.search.text import norm
    return norm(s)


def josa(word, a, b):
    """받침 있으면 a, 없으면 b ('을'/'를', '은'/'는', '이'/'가')"""
    w = re.sub(r"[\s)\]」』'\"]+$", "", str(word or ""))
    if not w:
        return b
    c = w[-1]
    if "가" <= c <= "힣":
        return a if (ord(c) - 0xAC00) % 28 else b
    return a if c in "0136789lmnr" else b


def clean_title(nm):
    """제목에서 기간 괄호('(2008~2015)')를 뺀다 — 기간은 dense 가 아니라 시점 계수·연결 표(series)의 일"""
    return re.sub(r"\s+", " ", YEAR_PAREN.sub("", str(nm or ""))).strip(" -_")


def _path(p):
    s = str((p or {}).get("path") or "")
    return re.sub(r"\s+", " ", YEAR_RE.sub("", s)).strip(" >/") or ""


class Vocab:
    """질문 쪽 표준 용어 (dictionary_표명.json 의 대표 용어) — 문서 쪽 슬롯도 이 말로 쓰게"""

    def __init__(self, path=None):
        from backend.rag.query_analyzer.config import DICT_DIR
        self.path = Path(path or DICT_DIR / "dictionary_표명.json")
        raw = self.path.read_bytes() if self.path.exists() else b"{}"
        self.hash = hashlib.sha1(raw).hexdigest()[:12]
        d = json.loads(raw.decode("utf-8") or "{}")
        self.target = list(d.get("TARGET_ALIASES") or {})
        self.indicator = list(d.get("INDICATOR_ALIASES") or {})
        self.axis = d.get("AXIS_ALIASES") or {}
        self.move = list(d.get("MOVE_ALIASES") or {})
        self.condition = list(d.get("CONDITION_ALIASES") or {})
        self.age_words = list(d.get("AGE_TITLE_WORDS") or [])
        self.levels = list(d.get("REGION_LEVEL_ALIASES") or {})
        self.all = {_n(x) for x in [*self.target, *self.indicator, *self.axis, *self.move, *self.levels,
                                    *(c.split("=", 1)[-1] for c in self.condition)] if _n(x)}
        self.axis_of = {}
        for k, vs in self.axis.items():
            for v in [k, *(vs or [])]:
                if len(_n(v)) >= 2:
                    self.axis_of.setdefault(_n(v), k)

    def axis_name(self, obj, kind):
        if kind == "sex":
            return "성별"
        if kind == "ages":
            return "연령"
        base = re.sub(r"\([^()]*\)", "", str(obj or "")).strip()
        base = re.sub(r"별$", "", base).strip() or str(obj or "")
        return self.axis_of.get(_n(base), base)


_regions_lock, _region_words = threading.Lock(), None


def region_words(facets=None):
    """정의문에 나오면 안 되는 지역 이름 (시도 표기 전부 + 시군구 이름 세 글자 이상)"""
    global _region_words
    with _regions_lock:
        if _region_words is None:
            from backend.rag.query_analyzer.config import RULE_PATH
            words = set()
            try:
                rd = json.loads(RULE_PATH.read_text(encoding="utf-8"))
                for k, vs in (rd.get("지역") or {}).items():
                    if k != "전국":  # '전국'·'우리나라' 는 지역 이름이 아니라 범위
                        words |= {_n(x) for x in [k, *vs] if len(_n(x)) >= 2}
            except Exception:  # noqa: BLE001, S110  (사전이 없으면 표 단면의 지역 이름만)
                pass
            _region_words = words
        out = set(_region_words)
    from backend.rag.search.facets import URBAN
    for f in (facets or {}).values():  # 실제 행정구역 이름만 ('시군구'·'읍면동' 같은 수준 말이 지역 값으로 든 표가 있음)
        out |= {r for r in f.regions if len(r) >= 3 and r not in URBAN and REGION_NAME.search(r) and not LEVEL_NAME.search(r)
                and not NOT_REGION.search(r)}
    return out - {"전국"}


REGION_NAME = re.compile(r"(?:시|군|구|읍|면|동|리|가)$")
NOT_REGION = re.compile(r"가구|인구|세대|주택|가족|구분|지구|연구|부부|본부|자녀|남녀|연령")  # '1세대가구' 처럼 끝이 '구'인 분류 값
LEVEL_NAME = re.compile(r"^(?:전국|시도|시군구|구시군|시군|읍면동|읍면|동읍면|행정구역|지역|도시|농촌|대도시|중소도시)")


NOTE_MARK = re.compile(r"^\s*(?:[○●◦·※\-*]+|주\s*\d*\s*\)|\d+\s*[).]|[가-하]\s*[).])\s*")
NOTE_USEFUL = re.compile(r"포함|제외|대상|기준|정의|집계|의미|해당|말함|말한다|뜻|이상|이하|산출|추계|조사")


NOTE_START = re.compile(r"^\s*(?:[○●◦※*]|-\s|주\s*\d*\s*\)|\d+\s*[).]|[가-하]\s*[).]|\[)")


def join_fragments(lines):
    """KOSIS 주석(CMMT)은 한 문장이 고정 폭으로 여러 줄에 나뉘어 온다 ('…5세 이' + '상 시군구간 …') → 머리 기호에서만 끊고 이어 붙임"""
    out = []
    for line in lines:
        line = re.sub(r"\s+", " ", str(line or "")).strip()
        if not line:
            continue
        if not out or NOTE_START.match(line):
            out.append(line)
        else:
            out[-1] += line
    return out


def raw_notes(prof):
    """메타 JSON 의 CMMT 전부 (메타 프로필은 앞 다섯 줄만 들고 있음). 없으면 프로필의 notes"""
    key = (prof or {}).get("table_key")
    if key:
        try:
            from backend.rag.ingestion import meta_profile as mp
            f = mp.KOSIS_DATA_DIR / "meta" / f"{key}.json"
            if f.exists():
                meta = json.loads(f.read_text(encoding="utf-8"))
                return [c.get("CMMT_DC") for c in meta.get("CMMT") or []
                        if isinstance(c, dict) and c.get("CMMT_NM") in ("통계표", None, "") and c.get("CMMT_DC")]
        except Exception:  # noqa: BLE001, S110  (메타 파일을 못 읽으면 프로필의 주석으로)
            pass
    return list((prof or {}).get("notes") or [])


def note_sentences(text):
    """주석 하나 → 문장들 (머리 기호 '○' '주1)' '1)' 를 떼고, 줄·마침표로 나눔)"""
    out = []
    for line in re.split(r"[\r\n]+|(?<=[.다])\s+(?=[○●※]|\d+\)|주\d*\))", str(text or "")):
        line = NOTE_MARK.sub("", line).strip()
        for sent in re.split(r"(?<=[.다])\s+", line):
            sent = sent.strip(" ,;")
            if len(sent) >= 6:
                out.append(sent)
    return out


def notes_of(tid, prof, csv_table=None):
    """표 주석(통계표) + 항목·분류 주석 → 문의처·링크를 뺀 짧은 문장들 (정의·포함·제외·기준을 말하는 문장 먼저)"""
    notes = join_fragments(raw_notes(prof))
    by_target = {}
    for fn in (csv_table or {}).get("footnotes") or []:
        if fn.get("type") in ("항목", "분류") and fn.get("text"):
            by_target.setdefault(fn.get("target") or "", []).append(fn["text"])
    for tgt, lines in by_target.items():
        notes += [f"{tgt}: {x}" if tgt else x for x in join_fragments(lines)]
    sents = []
    for t in notes:
        sents += [x[:160] for x in note_sentences(t) if not NOTE_NOISE.search(x)]
    sents = list(dict.fromkeys(sents))
    sents.sort(key=lambda x: not NOTE_USEFUL.search(x))  # 안정 정렬: 쓸모 있는 문장 먼저, 그 안에서는 원래 순서
    return sents[:MAX_NOTES]


def _restricted_sex(f):
    from backend.rag.search.siblings import table_sex
    s = table_sex(f.tbl_nm)
    return {"남": "남자", "여": "여자"}.get(s)


def _restricted_age(f, vocab):
    t = clean_title(f.tbl_nm)
    m = AGE_LIMIT.search(t)
    if m:
        return re.sub(r"\s+", "", m.group(0)).replace("세", "세 ")
    nt = _n(t)
    return next((w for w in sorted(vocab.age_words, key=len, reverse=True) if _n(w) and _n(w) in nt), None)


def _deepest_level(f):
    from backend.rag.search.siblings import table_level
    return table_level(f)


def template_slots(f, prof, vocab):
    """코드로 채운 슬롯 (LLM 없이도 같은 틀). 값은 표준 용어 또는 표 재료의 말"""
    title = clean_title(f.tbl_nm)
    head = _n(" ".join([title, *f.items[:30]]))
    slots = {k: [] for k in DOC_SLOTS}
    slots["대상"] = [t for t in vocab.target if len(_n(t)) >= 2 and _n(t) in head]
    from backend.rag.search.facets import AGE_NAME
    from backend.rag.search.text import TOTALS
    items = [re.sub(r"\s*\([^()]*\)\s*$", "", i) for i in f.items if _n(i) not in TOTALS and not AGE_NAME.search(i)]
    cand = [t for t in vocab.indicator if len(_n(t)) >= 3 and _n(t) in head]
    if not cand:  # 표준 지표가 없으면 제목 끝 덩어리 ('…별 이동인구' → 이동인구) — 항목은 분류 값처럼 잘게 나뉜 표가 많아 쓰지 않음
        segs = list(title_segments(f.tbl_nm).values())
        cand = [segs[-1]] if segs else []
    if 0 < len(items) <= 3 and all(len(_n(i)) <= 12 for i in items):  # 항목이 몇 개뿐이면 그 이름도 (출생아수, 합계출산율)
        cand += items
    slots["지표"] = _no_contained(cand)
    slots["대상"] = _no_contained(slots["대상"])
    slots["이동"] = [m for m in vocab.move if len(_n(m)) >= 2 and _n(m) in _n(title)
                    and not any(_n(m) in _n(i) for i in slots["지표"])]
    sv = _n(f.survey_nm)
    for c in vocab.condition:
        k, _, v = c.partition("=")
        if (k == "자료" and _n(v) and _n(v) in sv) or (k != "자료" and _n(v) and _n(v) in _n(title)):
            slots["조건"].append(c)
    axes = []
    for obj, kind, names in f.dims:
        axes.append("시나리오" if kind == "scenario" else vocab.axis_name(obj, kind))
    lvl = [g for g in ("시도", "시군구", "읍면동") if g in f.geo]
    axes += lvl
    slots["비교축"] = list(dict.fromkeys(a for a in axes if a))
    sx, ag = _restricted_sex(f), _restricted_age(f, vocab)
    if sx:
        slots["성별"] = [sx]
        slots["비교축"] = [a for a in slots["비교축"] if a != "성별"]
    if ag:
        slots["연령"] = [ag]
    return {k: v[:MAX_SLOT_VALUES] for k, v in slots.items()}


def _no_contained(xs):
    """다른 값 안에 들어 있는 짧은 값은 뺌 ('출산율' ⊂ '합계출산율'). 순서 유지"""
    xs = list(dict.fromkeys(x for x in xs if _n(x)))
    return [x for x in xs if not any(_n(x) != _n(y) and _n(x) in _n(y) for y in xs)]


def slot_sentence(slots):
    from backend.rag.query_analyzer.sentence import slots_to_sentence
    return slots_to_sentence({**{k: list(v or []) for k, v in slots.items()}, "의도": "값 조회"})


def slot_doc(f, slots):
    s = slot_sentence(slots)
    t = clean_title(f.tbl_nm)
    return f"{s} | {t}" if s and _n(s) != _n(t) else t


# ── 구분 (비슷한 표와의 차이 — 코드) ───────────────────────────────
def _bigrams(s):
    s = _n(s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def neighbors(facets, k=N_NEIGHBORS, min_sim=0.34):
    """{tbl_id: [비슷한 표 tbl_id …]} — 같은 형제 무리 + 표 이름(기간·성별·수준 괄호를 뺀 것) 글자쌍 유사도"""
    from backend.rag.search.siblings import build_groups, core_title
    of, groups = build_groups(facets, max_size=40)
    ids = list(facets)
    core = {t: core_title(facets[t].tbl_nm) for t in ids}
    grams = {t: _bigrams(core[t]) for t in ids}
    post = {}
    for t in ids:
        for g in grams[t]:
            post.setdefault(g, []).append(t)
    out = {}
    for t in ids:
        cand = Counter()
        for g in grams[t]:
            if len(post[g]) <= 200:
                for u in post[g]:
                    if u != t:
                        cand[u] += 1
        scored = []
        for u, c in cand.items():
            sim = c / max(1, len(grams[t] | grams[u]))
            same_survey = _n(facets[t].survey_nm) == _n(facets[u].survey_nm)
            if sim >= min_sim or (same_survey and sim >= min_sim * 0.7):
                scored.append((sim + (0.1 if same_survey else 0), u))
        sib = [u for u in groups.get(of.get(t), []) if u != t]
        ranked = list(dict.fromkeys(sib + [u for _, u in sorted(scored, reverse=True)]))
        out[t] = ranked[:k]
    return out


def _axis_set(f, vocab):
    return {vocab.axis_name(o, kind) for o, kind, _ in f.dims}


SEG_SPLIT = re.compile(r"\s*(?:[/,·_\-–]|\s및\s|(?<=별)\s+)\s*")
LEVEL_SEG = re.compile(r"^(?:전국|시도|시군구|읍면동|행정구역|지역|시군|구시군)(?:별|단위)?$")


def title_segments(nm):
    """표 이름 → 분류·대상 덩어리 ('시도/가구주의 연령/거처의 점유형태별 가구' → {가구주의 연령, 거처의 점유형태, 가구})
    괄호(성별·기간·단위)와 지역 수준 말은 뺌"""
    s = re.sub(r"\([^()]*\)", " ", clean_title(nm))
    out = {}
    for seg in SEG_SPLIT.split(s):
        seg = re.sub(r"\s+", " ", seg).strip()
        seg = re.sub(r"별$", "", seg).strip()
        if len(_n(seg)) >= 2 and not LEVEL_SEG.match(seg) and not YEAR_RE.search(seg):
            out[_n(seg)] = seg
    return out


def _own_only(own: dict, other: dict):
    """다른 표의 어느 덩어리와도 같거나 서로 포함되지 않는 내 덩어리 (포함은 짧은 쪽이 세 글자 이상일 때만: '가구' ⊂ '가구주의연령' 은 다름)"""
    def same(a, b):
        short, long_ = sorted((a, b), key=len)
        return a == b or (len(short) >= 3 and short in long_)
    return [v for k, v in own.items() if not any(same(k, o) for o in other)]


def distinct(f, nbs, facets, profiles, vocab):
    """→ (구분 낱말 목록, 비슷한 표에만 있는 말 집합)"""
    from backend.rag.search.facets import AGE_NAME
    from backend.rag.search.siblings import table_sex
    from backend.rag.search.text import TOTALS
    if not nbs:
        return [], set()
    own_terms = title_segments(f.tbl_nm)
    own_axes = _axis_set(f, vocab)
    from backend.rag.search.facets import SEX_NAME
    own_items = {_n(i): i for i in f.items if _n(i) not in TOTALS and not AGE_NAME.search(i) and not SEX_NAME.search(i)} \
        if len(f.items) <= 5 else {}
    own_level, own_sex = _deepest_level(f), table_sex(f.tbl_nm) or "계"
    own_age, own_proj = age_width(f.tbl_nm), is_projection({"tbl_nm": f.tbl_nm, "survey_nm": f.survey_nm})
    feats, other_terms = Counter(), set()
    order = {}

    def add(key, label):
        feats[key] += 1
        order.setdefault(key, (len(order), label))
    for u in nbs:
        g = facets[u]
        tt = title_segments(g.tbl_nm)
        other_terms |= set(_own_only(tt, own_terms))
        for w in _own_only(own_terms, tt):
            add(("t", _n(w)), w)
        sx = table_sex(g.tbl_nm) or "계"
        if sx != own_sex:
            add(("sex",), {"남": "남자", "여": "여자"}.get(own_sex, "남녀 전체"))
        lv = _deepest_level(g)
        if lv != own_level:
            add(("lv",), f"{GEO_WORD.get(own_level, own_level)} 단위" if own_level != "전국" else "전국 단위")
        aw = age_width(g.tbl_nm)
        if own_age and aw != own_age:
            add(("age",), f"{own_age}세 연령 구간")
        if is_projection({"tbl_nm": g.tbl_nm, "survey_nm": g.survey_nm}) != own_proj:
            add(("proj",), "장래 추계(전망)" if own_proj else "실적 자료")
        for c in sorted(f.cycles - g.cycles):
            add(("cyc", c), f"{CYCLE_WORD.get(c, c)} 자료")
        for a in sorted(own_axes - _axis_set(g, vocab)):
            add(("ax", _n(a).removesuffix("별")), a if a.endswith("별") else f"{a}별")
        if _n(g.survey_nm) == _n(f.survey_nm):
            gi = {_n(i) for i in g.items}
            for k in list(own_items)[:20]:
                if k not in gi and len(k) >= 2:
                    add(("it", k), own_items[k])
    ranked = sorted(feats, key=lambda k: (-feats[k] if k[0] != "t" else -feats[k] - 0.5, order[k][0]))
    if any(k[0] == "t" for k in feats):  # 제목 차이가 있으면 항목 차이는 쓰지 않음 (항목은 잡음이 많음)
        ranked = [k for k in ranked if k[0] != "it"]
    else:
        its = [k for k in ranked if k[0] == "it"][:2]
        ranked = [k for k in ranked if k[0] != "it" or k in its]
    labels, seen = [], set()
    for k in ranked:
        lab = order[k][1]
        key = _n(lab).removesuffix("별")
        if lab and key not in seen and not any(key in x or x in key for x in seen if len(x) >= 2):
            labels.append(lab)
            seen.add(key)
    own_blob = _n(" ".join([f.tbl_nm, f.survey_nm, *f.items, *(o for o, _, _ in f.dims),
                            *(n for _, _, ns in f.dims for n in ns[:200])]))
    banned = {t for t in other_terms if len(_n(t)) >= 2 and _n(t) not in own_blob}
    return labels[:6], banned


# ── 값 조각 (vals) ───────────────────────────────────────────────
VAL_CHUNK = 30       # 조각 하나에 넣을 값 수
MAX_CHUNKS = 16      # 표 하나의 조각 상한 (값이 수천 개인 표가 dense 를 독차지하지 않게)


def value_chunks(f, vocab=None, region_set=frozenset(), chunk=VAL_CHUNK, max_chunks=MAX_CHUNKS):
    """표 하나 → dense 글 여러 개: '조사 | 표 이름' + 항목 또는 분류 하나의 값 묶음.
    정의문은 '무엇을 세는 표인가' 를, 이 조각들은 '표 안에 어떤 값이 있는가' 를 맡는다 (항목·분류 값이 많은 표도 빠짐없이).
    지역 분류 · 연령·출생연도 · 합계 · 연도 값은 넣지 않음 (지역·시점은 View 조건, 연령은 구조 계수가 맡음)"""
    vocab = vocab or Vocab()
    head = f"{f.survey_nm} | {clean_title(f.tbl_nm)}"
    groups = []
    items = [re.sub(r"\s*\([^()]*\)\s*$", "", i) for i in f.items]
    items = _plain_values(list(dict.fromkeys(x for x in items if x)), region_set)
    if items:
        groups.append(("항목", items))
    for obj, kind, names in f.dims:
        if kind in ("ages", "cohort", "sex"):
            continue
        vals = _plain_values(list(dict.fromkeys(names)), region_set)
        if vals:
            groups.append((vocab.axis_name(obj, kind), vals))
    out = []
    for label, vals in groups:
        for i in range(0, len(vals), chunk):
            out.append(f"{head}\n{label}: {', '.join(vals[i:i + chunk])}")
    return out[:max_chunks] or [head]


def value_coverage(f, vocab=None, region_set=frozenset(), chunk=VAL_CHUNK, max_chunks=MAX_CHUNKS):
    """조각이 표의 값을 얼마나 담는지 → [{분류, 종류, 값 수, 조각에 든 값, 빠진 이유}] (확인용)"""
    vocab = vocab or Vocab()
    rows, used = [], 0
    groups = [("항목", "item", [re.sub(r"\s*\([^()]*\)\s*$", "", i) for i in f.items])] + \
        [(vocab.axis_name(o, k), k, list(ns)) for o, k, ns in f.dims]
    for label, kind, names in groups:
        names = list(dict.fromkeys(x for x in names if x))
        if kind in ("ages", "cohort", "sex"):
            rows.append({"분류": label, "종류": kind, "값 수": len(names), "조각에 든 값": 0,
                         "빠진 이유": "연령·출생연도·성별은 구조 계수가 맡음"})
            continue
        vals = _plain_values(names, region_set)
        n_chunks = -(-len(vals) // chunk) if vals else 0
        room = max(0, max_chunks - used)
        took = min(len(vals), room * chunk)
        used += min(n_chunks, room)
        why = []
        if len(vals) < len(names):
            why.append(f"합계·지역 이름·연도 {len(names) - len(vals)}개")
        if took < len(vals):
            why.append(f"표당 조각 상한({max_chunks})으로 {len(vals) - took}개")
        rows.append({"분류": label, "종류": kind, "값 수": len(names), "조각에 든 값": took, "빠진 이유": " · ".join(why)})
    if f.geo:
        rows.append({"분류": "지역", "종류": "regions", "값 수": len(f.regions) or "-", "조각에 든 값": 0,
                     "빠진 이유": "지역은 View 조건·구조 계수가 맡음"})
    return rows


# ── 정의문 ───────────────────────────────────────────────────────
def _items_phrase(f, n=4):
    from backend.rag.search.facets import AGE_NAME
    from backend.rag.search.text import TOTALS
    xs = [re.sub(r"\s*\([^()]*\)\s*$", "", i) for i in f.items if _n(i) not in TOTALS and not AGE_NAME.search(i)]
    xs = list(dict.fromkeys(x for x in xs if x))
    return ", ".join(xs[:n]) + (f" 등 {len(xs)}개 항목" if len(xs) > n else "")


def _plain_values(names, region_set):
    """분류 값 중 정의문에 쓸 것: 합계·지역 이름(옛 시도 포함)·연도·동부/읍부 빼고"""
    from backend.rag.search.facets import URBAN, _is_sido
    from backend.rag.search.text import TOTALS
    def regional(v):  # '부산-계' · '5년전거주지:전국-계' 처럼 지역 이름이 붙은 값
        parts = [x for x in re.split(r"[-:_·/\s]+", str(v)) if x]
        return any(_is_sido(x) or _n(x) in region_set or _n(x) == "전국" for x in parts)
    return [v for v in names if _n(v) not in TOTALS and _n(v) not in region_set and not _is_sido(v) and _n(v) not in URBAN
            and not YEAR_RE.search(str(v)) and not regional(v)]


def _dim_phrase(f, vocab, region_set, small=8):
    out = []
    for obj, kind, names in f.dims:
        a = vocab.axis_name(obj, kind)
        vals = _plain_values(names, region_set)
        if kind in ("cohort",) or not vals:
            out.append(a)
        elif len(vals) <= small:
            out.append(f"{a}({', '.join(vals[:small])})")
        else:
            out.append(f"{a}({', '.join(vals[:4])} 등 {len(vals)}개)")
    return out


def template_def(f, prof, vocab, labels, region_set):
    """코드 템플릿 정의문 (LLM 없이). 연도·지역 이름 없음"""
    title = clean_title(f.tbl_nm)
    what = ", ".join(template_slots(f, prof, vocab)["지표"]) or title
    unit = ", ".join(u for u in f.units[:3] if u)
    s = [f"{f.survey_nm}의 {title} 통계로, {what}{josa(what, '을', '를')} 집계한다"
         + (f" (단위: {unit})." if unit else ".")]
    items = _items_phrase(f)
    if items and _n(items) != _n(what):
        s.append(f"항목은 {items}{josa(items, '이다', '다')}.")
    dims = _dim_phrase(f, vocab, region_set)
    lv = [GEO_WORD[g] for g in ("시도", "시군구", "읍면동", "동읍면부") if g in f.geo]
    if dims:
        s.append(f"{', '.join(dims)} 분류로 나뉜다.")
    if lv:
        s.append(f"지역은 {', '.join(lv)} 단위로 나뉜다.")
    cyc = [CYCLE_WORD[c] for c in ("Y", "H", "Q", "M") if c in f.cycles]
    proj = is_projection({"tbl_nm": f.tbl_nm, "survey_nm": f.survey_nm})
    nature = "장래 추계(전망) 자료" if proj else "실적 자료"
    s.append(f"{'·'.join(cyc) or '연간'} {nature}이다.")
    for n in notes_of(f.tbl_id, prof)[:3]:
        if NOTE_USEFUL.search(n) and len(n) < 160 and not YEAR_RE.search(n) and not any(r in _n(n) for r in region_set):
            s.append(n.rstrip(".") + ".")
            break
    return " ".join(s)[:MAX_DEF_CHARS]


def def_doc(f, labels, body):
    head = f"{f.survey_nm} | {clean_title(f.tbl_nm)}"
    return "\n".join(x for x in [head, f"구분: {' · '.join(labels)}" if labels else "", body] if x)


# ── LLM ─────────────────────────────────────────────────────────
SYSTEM = """너는 국가통계(KOSIS) 표의 검색용 정의를 쓴다. 주어진 [재료]에 있는 사실만 쓴다. 추측하지 않는다.
두 가지를 만든다.

1) slots — 질문 분석기와 같은 슬롯으로 '이 표가 담는 것'을 쓴다. 값은 [표준 용어]에 있는 말 또는 [재료]에 실제로 있는 말만 쓴다.
 - 대상: 무엇(누구)을 세는가. 표준 용어 우선 (인구, 가구, 혼인, 이혼, 출생, 주택 …)
 - 지표: 표가 주는 값의 통계 용어 (혼인건수, 이동자수, 합계출산율, 가구수 …). 항목 이름을 그대로 써도 된다
 - 조건: 표 전체에 걸린 조건만 "축=값" (혼인종류=초혼, 자료=장래인구추계). 분류로 나뉘는 값은 조건이 아니다
 - 이동: 전입·전출·순이동·입국·출국 같은 이동 종류 (해당할 때만)
 - 비교축: 표가 나뉘는 기준 (성별, 연령, 시도, 시군구, 교육정도, 점유형태 …)
 - 성별: 표 전체가 한 성별일 때만 "남자" 또는 "여자". 남녀로 나뉘면 비교축에 성별
 - 연령: 표 전체가 특정 연령대일 때만 ("65세 이상"). 연령으로 나뉘면 비교축에 연령
2) 정의 — 2~4문장의 객관적 서술.
 ① 무엇을(누구를) 어떤 단위로 세었는가 ② 어떤 분류로 나뉘는가 (대표 값 몇 개를 이름 그대로)
 ③ [재료]의 주석에 있는 정의·포함·제외·기준 ④ 주기(연간·월간·분기)와 실적/추계 (추계는 '전망')
 [구분]에 있는 특징은 첫 문장에 반드시 넣는다.

규칙
- 연도·기간 숫자, 지역 이름(서울·경기·신안군 등)을 쓰지 않는다. 지역은 '시도별', '시군구 단위'처럼 수준만 쓴다
- 예상 질문, 일상어·구어로 바꿔 말하기, 활용 예시, 검색 안내를 쓰지 않는다
- 다른 표의 이름이나 '다른 표와 달리' 같은 비교 문장을 쓰지 않는다
- JSON 으로만 답한다: {"slots": {"대상": [], "지표": [], "조건": [], "이동": [], "비교축": [], "성별": [], "연령": []}, "정의": "..."}"""

_ARR = {"type": "array", "items": {"type": "string"}}
SCHEMA = {"type": "object", "properties": {
    "slots": {"type": "object", "properties": {k: _ARR for k in DOC_SLOTS}, "required": DOC_SLOTS},
    "정의": {"type": "string"}}, "required": ["slots", "정의"]}


def facts(f, prof, vocab, labels, tslots, region_set, csv_table=None):
    from backend.rag.search.text import TOTALS
    dims = []
    for obj, kind, names in f.dims:
        vals = _plain_values(names, region_set)
        dims.append({"이름": obj, "종류": {"sex": "성별", "ages": "연령", "cohort": "출생연도", "scenario": "시나리오"}.get(kind, "분류"),
                     "값": vals[:12], "값 수": len(names)})
    return {"조사명": f.survey_nm, "표 이름": clean_title(f.tbl_nm), "메뉴 경로": _path(prof),
            "항목": [i for i in f.items if _n(i) not in TOTALS][:30], "항목 수": len(f.items), "분류": dims,
            "지역 수준": [GEO_WORD[g] for g in ("시도", "시군구", "읍면동", "동읍면부") if g in f.geo] or ["전국"],
            "단위": f.units[:5], "주기": [CYCLE_WORD[c] for c in ("Y", "H", "Q", "M") if c in f.cycles] or ["연간"],
            "자료 성격": "장래 추계(전망)" if is_projection({"tbl_nm": f.tbl_nm, "survey_nm": f.survey_nm}) else "실적",
            "조사 구분": (prof or {}).get("survey_type") or "",
            "주석": notes_of(f.tbl_id, prof, csv_table), "구분": labels, "코드가 찾은 슬롯": tslots}


def user_msg(fx, vocab):
    std = {"대상": vocab.target, "지표": vocab.indicator, "비교축": list(vocab.axis)[:80], "이동": vocab.move,
           "조건": vocab.condition}
    return "[재료]\n" + json.dumps(fx, ensure_ascii=False, indent=1) + "\n\n[표준 용어]\n" + json.dumps(std, ensure_ascii=False)


# ── 검사 ─────────────────────────────────────────────────────────
_kiwi, _kiwi_lock = None, threading.Lock()


def nouns(text):
    global _kiwi
    try:
        with _kiwi_lock:
            if _kiwi is None:
                from kiwipiepy import Kiwi
                _kiwi = Kiwi()
            return [t.form for t in _kiwi.tokenize(str(text or "")) if t.tag in ("NNG", "NNP") and len(t.form) >= 2]
    except Exception:  # noqa: BLE001  (형태소 분석기가 없으면 낱말 검사는 건너뜀)
        return []


def blob_of(fx, f):
    parts = [fx["조사명"], fx["표 이름"], fx["메뉴 경로"], *fx["항목"], *(d["이름"] for d in fx["분류"]),
             *(v for d in fx["분류"] for v in d["값"]), *fx["단위"], *fx["주석"], *fx["구분"],
             *(n for _, _, ns in f.dims for n in ns[:300])]
    return _n(" ".join(map(str, parts)))


def check_slots(raw, tslots, f, vocab, blob, region_set):
    """LLM 슬롯 → 검사한 슬롯 (코드 슬롯과 합침), 버린 값"""
    out, dropped = {k: [] for k in DOC_SLOTS}, []
    raw = raw if isinstance(raw, dict) else {}
    sx, ag = _restricted_sex(f), _restricted_age(f, vocab)
    for k in DOC_SLOTS:
        vals = raw.get(k) or []
        for v in (vals if isinstance(vals, list) else [vals]):
            v = re.sub(r"\s+", " ", str(v or "")).strip()
            if not v:
                continue
            core = v.split("=", 1)[-1] if k == "조건" else v
            from backend.rag.search.text import variants
            forms = variants(core) | {_n(core)}            # '일반가구수' → 일반가구 도 재료에 있으면 됨
            ok = bool(_n(core)) and any(x and (x in vocab.all or x in blob) for x in forms) and not YEAR_RE.search(v) \
                and _n(core) not in region_set
            if k == "조건" and "=" not in v:
                ok = False
            if k == "성별":
                ok = ok and sx is not None and _n(v) == _n(sx)
            if k == "연령":
                ok = ok and ag is not None
                v = ag or v
            if ok:
                out[k].append(v)
            else:
                dropped.append(f"{k}:{v}")
    if raw.get("성별") and not sx and f.has_sex and "성별" not in out["비교축"]:
        out["비교축"].append("성별")
    for k in DOC_SLOTS:  # 코드 슬롯은 항상 남김 (LLM 이 빠뜨려도 같은 틀이 유지되게)
        out[k] = list(dict.fromkeys([*out[k], *(tslots.get(k) or [])]))[:MAX_SLOT_VALUES]
    if out["성별"]:
        out["비교축"] = [a for a in out["비교축"] if a != "성별"]
    return out, dropped


def check_def(text, blob, vocab, banned, region_set, max_unknown=1, own=""):
    """정의문 → (남긴 문장, flags). own: 이 표의 제목·조사명 — 제목에 든 지역(예: '충청남도 총조사인구')은 표의 범위라 허용"""
    keep, flags = [], []
    own_n = _n(own)
    region_set = {r for r in region_set if r not in own_n}
    for s in SENT_SPLIT.split(re.sub(r"\s+", " ", str(text or "")).strip()):
        s = s.strip()
        if not s:
            continue
        ns = _n(s)
        why = None
        if YEAR_RE.search(s):
            why = "연도"
        elif any(r in ns for r in region_set):
            why = "지역 이름"
        elif any(_n(b) in ns for b in banned):
            why = "비슷한 표의 말:" + ",".join(sorted(b for b in banned if _n(b) in ns))[:40]
        elif BAD_PHRASE.search(s):
            why = "금지 표현"
        else:
            unk = [w for w in dict.fromkeys(nouns(s)) if w not in ALLOW and _n(w) not in blob and _n(w) not in vocab.all]
            if len(unk) > max_unknown:
                why = "모르는 말:" + ",".join(unk[:4])
            elif unk:
                flags.append("unknown:" + ",".join(unk))
        if why:
            flags.append(f"drop[{why}]")
        else:
            keep.append(s)
    body = " ".join(keep)
    if len(body) > MAX_DEF_CHARS:
        cut = body[:MAX_DEF_CHARS]
        body = cut[:cut.rfind(".") + 1] if "." in cut else cut
    return body, flags


# ── 카드 ─────────────────────────────────────────────────────────
class Builder:
    """코퍼스 전체의 재료(단면·프로필·이웃)를 한 번 준비하고, 표마다 카드를 만든다"""

    def __init__(self, docs, facets=None, profiles=None, csv_tables=None, vocab=None, log=print, facets_source="auto"):
        """facets_source: auto (CSV 값 사전 > 메타 프로필) | meta (문서가 든 프로필·메타 프로필만 — 테스트용)
        csv_tables: {} 를 주면 CSV 값 사전의 주석을 읽지 않음"""
        from backend.rag.search.facets import build_facets
        self.docs = list(docs)
        self.facets = facets or build_facets(self.docs, facets_source, log)
        self.profiles = profiles if profiles is not None else self._profiles()
        self.csv = csv_tables if csv_tables is not None else self._csv()
        self.vocab = vocab or Vocab()
        self.regions = region_words(self.facets)
        self.nbs = neighbors(self.facets)

    def _profiles(self):
        out = {d.id: d.meta["profile"] for d in self.docs if d.meta.get("profile")}
        if len(out) < len(self.docs):
            try:
                from backend.rag.ingestion.meta_profile import load_meta_profiles
                for p in load_meta_profiles():
                    out.setdefault(p["tbl_id"], p)
            except FileNotFoundError:
                pass
        return out

    def _csv(self):
        try:
            from backend.rag.csv_index import load_index
            idx = load_index()
            return {d.id: idx.table(d.id) for d in self.docs}
        except Exception:  # noqa: BLE001  (CSV 값 사전이 없으면 메타 프로필의 통계표 주석만)
            return {}

    def material(self, tid):
        f, p = self.facets[tid], self.profiles.get(tid) or {}
        labels, banned = distinct(f, self.nbs.get(tid, []), self.facets, self.profiles, self.vocab)
        ts = template_slots(f, p, self.vocab)
        fx = facts(f, p, self.vocab, labels, ts, self.regions, self.csv.get(tid))
        h = hashlib.sha1((PROMPT_VER + self.vocab.hash + json.dumps(fx, ensure_ascii=False, sort_keys=True))
                         .encode()).hexdigest()[:16]
        return {"f": f, "p": p, "labels": labels, "banned": banned, "tslots": ts, "facts": fx, "hash": h}

    def card(self, tid, use_llm=True, chat_fn=None):
        m = self.material(tid)
        f, fx = m["f"], m["facts"]
        tdef = template_def(f, m["p"], self.vocab, m["labels"], self.regions)
        card = {"tbl_id": tid, "tbl_nm": f.tbl_nm, "survey_nm": f.survey_nm, "구분": m["labels"],
                "tslots": m["tslots"], "tslot_text": slot_doc(f, m["tslots"]), "tmpl_text": def_doc(f, m["labels"], tdef),
                "hash": m["hash"], "prompt": PROMPT_VER, "vocab": self.vocab.hash, "flags": []}
        if not use_llm:
            card.update(mode="tmpl", slots=m["tslots"], slot_text=card["tslot_text"], def_text=card["tmpl_text"])
            return card
        if chat_fn is None:
            from backend.core.llm import chat as chat_fn
        t0 = time.time()
        try:
            res = chat_fn([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_msg(fx, self.vocab)}],
                          schema=SCHEMA, temperature=0.1, max_tokens=900)
        except Exception as e:  # noqa: BLE001  (표 하나가 실패해도 나머지는 계속 — 템플릿으로 채우고 표시)
            res = {"_raw": f"{e.__class__.__name__}: {e}"}
        card["sec"] = round(time.time() - t0, 1)
        if not isinstance(res, dict) or "_raw" in res:
            card.update(mode="llm_error", slots=m["tslots"], slot_text=card["tslot_text"], def_text=card["tmpl_text"],
                        error=str((res or {}).get("_raw", res))[:300])
            card["flags"].append("llm_error")
            return card
        blob = blob_of(fx, f)
        slots, dropped = check_slots(res.get("slots"), m["tslots"], f, self.vocab, blob, self.regions)
        body, flags = check_def(res.get("정의"), blob, self.vocab, m["banned"], self.regions,
                                own=f"{f.tbl_nm} {f.survey_nm}")
        card["flags"] += [f"slot_drop:{d}" for d in dropped] + flags
        if not body:
            body = tdef
            card["flags"].append("def_fallback")
        card.update(mode="llm", slots=slots, slot_text=slot_doc(f, slots), def_text=def_doc(f, m["labels"], body),
                    llm_def=str(res.get("정의") or "")[:600])
        return card


def load_cards(path=None) -> dict:
    p = Path(path or CARDS_PATH)
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["tbl_id"]] = r
    return out


def save_cards(cards: dict, path=None):
    p = Path(path or CARDS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fo:
        for v in cards.values():
            fo.write(json.dumps(v, ensure_ascii=False) + "\n")
    tmp.replace(p)


def build(docs, out=None, use_llm=True, ids=None, limit=None, workers=1, force=False, chat_fn=None, builder=None,
          log=print):
    """→ {tbl_id: 카드}. 재료 해시가 같고 오류가 아닌 카드는 다시 만들지 않음"""
    b = builder or Builder(docs, log=log)
    done = load_cards(out)
    want = [d.id for d in b.docs if (not ids or d.id in set(ids))]
    if limit:
        want = want[:limit]
    todo = []
    for t in want:
        c = done.get(t)
        mode_ok = c and (c.get("mode") == "llm" if use_llm else c.get("mode") in ("tmpl", "llm"))
        if force or not c or c.get("hash") != b.material(t)["hash"] or not mode_ok:
            todo.append(t)
    log(f"[dense 카드] 대상 {len(want)}개 · 새로 {len(todo)}개 ({'LLM' if use_llm else '템플릿'}) → {out or CARDS_PATH}")
    t0, lock = time.time(), threading.Lock()

    def one(t):
        return b.card(t, use_llm, chat_fn)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(one, t): t for t in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            t = futs[fu]
            try:
                c = fu.result()
            except Exception as e:  # noqa: BLE001
                c = {"tbl_id": t, "mode": "error", "error": repr(e)[:300]}
            with lock:
                done[t] = c
                if i % 20 == 0 or i == len(todo):
                    save_cards(done, out)
                    log(f"  {i}/{len(todo)} · {time.time() - t0:.0f}초")
    if not todo:
        save_cards(done, out)
    return done


def recheck(cards, builder, log=print):
    """LLM 을 다시 부르지 않고, 저장된 LLM 정의문(llm_def)에 지금의 검사 규칙을 다시 적용해 def_text 를 고침
    (검사 규칙을 고친 뒤 — 예: 지역 이름 목록에서 '시군구' 같은 수준 말 빼기)"""
    n = changed = 0
    for t, c in cards.items():
        if c.get("mode") != "llm" or not c.get("llm_def") or t not in builder.facets:
            continue
        n += 1
        m = builder.material(t)
        body, flags = check_def(c["llm_def"], blob_of(m["facts"], m["f"]), builder.vocab, m["banned"], builder.regions,
                                own=f"{m['f'].tbl_nm} {m['f'].survey_nm}")
        keep = [x for x in c.get("flags") or [] if x.startswith("slot_drop:")]
        if not body:
            body = template_def(m["f"], m["p"], builder.vocab, m["labels"], builder.regions)
            flags.append("def_fallback")
        new = def_doc(m["f"], m["labels"], body)
        if new != c.get("def_text"):
            changed += 1
        c.update(def_text=new, flags=keep + flags)
    log(f"[dense 카드] 다시 검사 {n}개 · 정의문이 바뀐 카드 {changed}개 (LLM 호출 없음)")
    return cards


def stats(cards, builder=None):
    cs = list(cards.values())
    flags = Counter(x.split(":", 1)[0].split("[", 1)[0] for c in cs for x in c.get("flags") or [])
    drops = Counter(x.split("[", 1)[1].split(":", 1)[0].rstrip("]") for c in cs for x in c.get("flags") or []
                    if x.startswith("drop["))
    out = {"n": len(cs), "mode": dict(Counter(c.get("mode") for c in cs)), "flags": dict(flags), "def_drops": dict(drops),
           "with_구분": sum(bool(c.get("구분")) for c in cs)}
    for k in ("slot_text", "def_text", "tmpl_text"):
        ls = sorted(len(c.get(k) or "") for c in cs if c.get(k))
        if ls:
            out[f"len_{k}"] = {"median": ls[len(ls) // 2], "p90": ls[int(len(ls) * .9)], "max": ls[-1]}
    if builder is not None:
        ids = {d.id for d in builder.docs}
        out["coverage"] = f"{len(ids & set(cards))}/{len(ids)}"
        out["stale"] = sum(1 for t, c in cards.items() if t in ids and c.get("hash") != builder.material(t)["hash"])
    return out


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m backend.rag.ingestion.dense_cards")
    ap.add_argument("cmd", choices=["build", "show", "check", "recheck", "vals"])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--out", default=None, help=f"카드 파일 (기본 {CARDS_PATH})")
    ap.add_argument("--no-llm", action="store_true", help="코드 템플릿만 (HCX 없음)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    from backend.rag.search.index import table_corpus
    docs = table_corpus().docs()
    b = Builder(docs, log=lambda m: print(m, flush=True))
    if a.cmd == "build":
        cards = build(docs, a.out, not a.no_llm, a.ids or None, a.limit, a.workers, a.force, builder=b,
                      log=lambda m: print(m, flush=True))
        print(json.dumps(stats(cards, b), ensure_ascii=False, indent=1))
    elif a.cmd == "show":
        cards = load_cards(a.out)
        for t in a.ids or [docs[0].id]:
            m = b.material(t)
            print(f"\n=== {t} {m['f'].tbl_nm}")
            print("구분:", m["labels"], "| 비슷한 표:", [b.facets[u].tbl_nm for u in b.nbs.get(t, [])])
            print("비슷한 표에만 있는 말:", sorted(m["banned"]))
            print("재료:", json.dumps(m["facts"], ensure_ascii=False, indent=1))
            c = cards.get(t)
            if c:
                print(f"카드 ({c.get('mode')}, {'최신' if c.get('hash') == m['hash'] else '오래됨'}):")
                for k in ("slot_text", "def_text", "tslot_text", "tmpl_text", "flags"):
                    print(f"  [{k}]", c.get(k))
            else:
                print("카드 없음 → build", t)
    elif a.cmd == "vals":
        for t in a.ids or [docs[0].id]:
            f = b.facets.get(t)
            if f is None:
                print(f"\n=== {t}: 검색 코퍼스에 없는 표")
                continue
            ch = value_chunks(f, b.vocab, b.regions)
            print(f"\n=== {t} {f.tbl_nm} · 조각 {len(ch)}개 (표 점수 = 조각 중 가장 높은 코사인)")
            for r in value_coverage(f, b.vocab, b.regions):
                print(f"  {r['분류']:14s} 값 {r['값 수']!s:>5} → 조각에 {r['조각에 든 값']!s:>5}  {r['빠진 이유']}")
            for i, x in enumerate(ch, 1):
                print(f"  [{i}] " + x.replace("\n", " / ")[:300])
    elif a.cmd == "recheck":
        cards = recheck(load_cards(a.out), b)
        save_cards(cards, a.out)
        print(json.dumps(stats(cards, b), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(stats(load_cards(a.out), b), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
