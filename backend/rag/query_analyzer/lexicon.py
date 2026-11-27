"""
동의어·유사어 조회 계층 — LLM·사용자가 쓸 수 있는 표현 → CSV 에 실제로 있는 값

조회 순서 (앞에서 찾으면 그 근거를 source 로 남김. CSV 에 근거가 있는 값만 '접지됨')
  1. learned  : 학습 사전 (storage/csv_index/learned_lexicon.json, status=active). 사람이 승인했거나 LLM 이 제안해 승인된 표현
  2. rule     : rule_dict.json (지역·성별·국적·축·이동·조건 — 뜻이 하나뿐인 확실한 표기)
  3. term     : term_dict.json (일상어 → 통계어: 신생아 → 출생아) → 바뀐 말로 다시 CSV 조회
  4. csv      : CSV 값 사전 정확·표기 변형 일치 (출생아 수 = 출생아수 = 출생아수(명))
  5. contains : CSV 값 포함 일치 (인구 ⊂ 총인구수) — 범위가 넓으므로 점수 낮음
  6. suggest  : 비슷한 이름 (difflib) — 접지가 아니라 되묻기 후보로만

  lex = get_lexicon()
  lex.resolve("신생아 수", slot="대상")  → [LexHit(value="출생아수", source="term>csv", n_tables=…), …]
  lex.suggest("출산아", slot="대상")       → ["출생아수", …]
  lex.learn("아기 수", "출생아수", slot="대상", source="llm")   # 승인 대기 → lex.approve("아기 수")
"""
import difflib
import json
import re
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path

from backend.rag.csv_index.store import norm

TARGET_CSV_SLOTS = ("항목", "분류")  # 대상·지표가 '행'에 해당하는가 = 항목 이름 또는 (지역·성별·연령 아닌) 분류 값
SLOT_CSV = {"지역": ("지역",), "전출지": ("지역",), "전입지": ("지역",), "성별": ("성별",), "연령": ("연령",),
            "국적": ("국적", "분류"), "대상": TARGET_CSV_SLOTS, "지표": TARGET_CSV_SLOTS,
            "조건": ("분류", "항목"), "이동": ("항목", "분류"), "비교축": ("열",)}
RULE_SLOT = {"지역": "지역", "전출지": "지역", "전입지": "지역", "성별": "성별", "국적": "국적", "비교축": "축",
             "이동": "이동", "조건": "조건", "연령": "연령"}
POSSESSIVE = re.compile(r"(\S)의(?=\s|$)")  # 낱말 끝 '의' (주민의 → 주민)
SCORE = {"learned": 1.0, "rule": 0.98, "csv": 0.95, "term>csv": 0.9, "contains": 0.6, "term": 0.5}


@dataclass
class LexHit:
    surface: str  # 입력 표현
    value: str  # 표준 값 (CSV 에 있는 이름 우선)
    slot: str | None
    source: str  # learned / rule / csv / term>csv / contains / term
    score: float
    match: str = ""  # exact / variant / contains
    n_tables: int = 0
    tables: list[str] = field(default_factory=list)
    csv: list[dict] = field(default_factory=list)  # 근거 행 (상위 몇 개): tbl_id · kind · obj_nm · name · code

    @property
    def grounded(self):
        return self.n_tables > 0

    def as_dict(self):
        d = asdict(self)
        d["grounded"] = self.grounded
        return d


def _load_rules():
    from backend.rag.query_analyzer.config import RULE_PATH
    raw = json.loads(Path(RULE_PATH).read_text(encoding="utf-8"))
    out = {}  # norm(표기) → [(규칙 슬롯, 대표값)]
    for slot, d in raw.items():
        if slot.endswith(("_묶음", "_제외", "_한글숫자")) or not isinstance(d, dict):
            continue
        for canon, aliases in d.items():
            for a in [canon, *(aliases if isinstance(aliases, list) else [])]:
                out.setdefault(norm(a), []).append((slot, canon))
    return out


QTERM_STOP = {"계", "합계", "총계", "전체", "소계", "전국", "기타", "미상", "남자", "여자", "남", "여", "비율", "구성비",
              "평균", "증감", "증감률", "이상", "이하", "미만", "초과", "지역", "기준", "현황", "조사", "통계", "연도", "시점",
              # 표를 가르지 못하는 흔한 말 ('원문표현' 으로 들어가면 검색 문장만 흐림)
              "인구", "인구수", "가구", "가구수", "총인구", "총인구수", "사람", "거주", "사용", "구성", "국내", "변화", "추이",
              "건수", "명수", "호수", "수", "합", "총", "전년", "대비"}

# 낱말 경계 — 표현은 띄어쓰기 낱말 하나 안에서, 낱말 처음부터 이어져야 하고 뒤에는 조사만 남아야 함
JOSA_TAIL = re.compile(r"(?:들)?(?:에서의|에서는|에서|에게|에는|으로는|으로|로는|로|까지|부터|보다|처럼|마다|이나|이랑|랑|하고|"
                       r"과의|와의|의|에|은|는|이|가|을|를|도|과|와|만|별|수|중|간)*")
# 낱말 앞에 붙어도 되는 꾸밈말 ('남성유학생' 의 '남성', '총인구' 의 '총')
PREFIX_OK = {"총", "전체", "남성", "여성", "남자", "여자", "남", "여", "외국인", "내국인", "한국", "국내", "해외", "신규", "연간",
             "월간", "일반", "전"}
# 단위 괄호 — 이것만 떼어 낸 이름은 같은 이름으로 봄 ('출생아수(명)' = '출생아수'). '(반)지하'·'영주(F-5)' 는 같은 이름이 아님
UNIT_PAREN = re.compile(r"\((?:천|만|백만|십억|억)?\s*(?:명|%|‰|개|개소|가구|원|호|건|세|년|대|톤|인|회|일|배|점|%p|명/㎢|㎡|㎢|"
                        r"명/천명|명/1,000명|퍼센트)\)\s*$")
OTHER_SLOTS = ("지역", "성별", "연령")


def _strip_josa(w):
    """낱말 끝 조사 떼기 ('남편의수는' → '남편의수'). 다 떼지면 그대로"""
    m = re.search(r"(?:들)?(?:에서의|에서는|에서|에게|에는|으로는|으로|로는|까지|부터|보다|처럼|마다|이나|과의|와의|의|에|은|는|이|가|을|를|"
                  r"도|과|와|만|로)+$", w)
    return w[:m.start()] if m and m.start() >= 2 else w


def same_name(name, key):
    """CSV 이름 name 이 질문 표현 key(norm) 와 같은 이름인가 — 정확 · 단위 괄호 · 끝 '수' 차이만 허용"""
    n, u = norm(name), norm(UNIT_PAREN.sub("", str(name or "")))
    if key in (n, u):
        return True
    return (len(u) > 2 and u.endswith("수") and key == u[:-1]) or key + "수" in (n, u)


class Lexicon:
    def __init__(self, idx=None, settings=None, learned_path=None):
        from backend.core.settings import get_settings
        from backend.rag.csv_index.store import index_dir, load_index
        from backend.rag.query_analyzer.terms import TERM_INDEX
        self.idx = idx or load_index()
        self.s = settings or get_settings()
        self.rules = _load_rules()
        self.terms = {norm(a): ts for a, ts in TERM_INDEX.items()}
        self.learned_path = Path(learned_path or index_dir() / "learned_lexicon.json")
        self.learned = json.loads(self.learned_path.read_text(encoding="utf-8")) if self.learned_path.exists() else {}
        self._lock = threading.Lock()

    @property
    def scope(self):
        return self.s.csv_scope

    # ── CSV 근거 ──
    def _csv(self, text, slot, contains=False):
        slots = SLOT_CSV.get(slot) if slot else None
        rows = self.idx.find(text, slots=slots, scope=self.scope)
        if not rows and contains and len(norm(text)) >= self.s.contain_min_len:
            rows = self.idx.contains(text, slots=slots, scope=self.scope, min_len=self.s.contain_min_len)
        return rows

    def _hit(self, surface, rows, slot, source, value=None, fallback=None):
        tables = sorted({r["tbl_id"] for r in rows})
        # 포함 일치뿐이면 CSV 이름으로 바꾸지 않음 (표 집합만 근거로 씀). 지역은 표준명
        if value is None and rows and slot not in ("지역", "전출지", "전입지") \
                and all(r.get("match") == "contains" for r in rows):
            value = fallback or surface
        if value is None:  # 표준 값: 가장 많은 표에 있는 CSV 이름 (지역은 표준명)
            cnt = {}
            exact = [r for r in rows if r.get("match") == "exact"]
            for r in exact or rows:
                k = (r.get("std") if r["slot"] == "지역" and r.get("std") else r["name"])
                cnt.setdefault(k, set()).add(r["tbl_id"])
            value = max(cnt, key=lambda k: (len(cnt[k]), -len(k))) if cnt else surface
        match = rows[0].get("match", "") if rows else ""
        seen, ev = set(), []
        for r in rows:
            key = (r["tbl_id"], r["kind"], r["name"])
            if key not in seen:
                seen.add(key)
                ev.append({k: r[k] for k in ("tbl_id", "kind", "slot", "obj_nm", "name", "code")})
        score = SCORE.get(source, 0.5) * (1.0 if match != "contains" else 0.7)
        return LexHit(surface, value, slot, source, round(score, 3), match, len(tables), tables, ev[:8])

    # ── 조회 ──
    def resolve(self, text, slot=None):
        """표현 하나 → 후보 LexHit 목록 (점수 순). 첫 번째가 가장 확실한 해석"""
        k = norm(text)
        out = []
        lv = self.learned.get(k)
        if lv and lv.get("status") == "active" and (slot is None or lv.get("slot") in (None, slot)):
            out.append(self._hit(text, self._csv(lv["value"], slot), slot, "learned", lv["value"]))
        rs = RULE_SLOT.get(slot)
        for rslot, canon in self.rules.get(k, []) if (slot is None or rs) else []:  # 대상·지표엔 rule_dict 를 쓰지 않음
            if rs is None or rslot == rs:
                out.append(self._hit(text, self._csv(canon, slot), slot, "rule", canon))
        rows = self._csv(text, slot)
        if rows:
            h = self._hit(text, rows, slot, "csv")
            if slot in ("대상", "지표"):  # 값은 정확·변형 일치로 정하고, 표 집합에는 포함 일치(인구수 ⊂ 총인구수)까지 넣음
                more = self.idx.contains(text, slots=SLOT_CSV[slot], scope=self.scope, min_len=max(3, self.s.contain_min_len))
                extra = sorted({r["tbl_id"] for r in more} - set(h.tables))
                h.tables += extra
                h.n_tables = len(h.tables)
            out.append(h)
        for t in self.terms.get(k, []):
            if norm(t) == k:
                continue
            rows_t = self._csv(t, slot) or self._csv(t, slot, contains=True)
            out.append(self._hit(text, rows_t, slot, "term>csv" if rows_t else "term", None if rows_t else t, fallback=t))
        if not any(h.grounded for h in out) and slot in ("대상", "지표"):
            # 구어 소유격: '외국인 주민의 자녀' → '외국인주민자녀'. '의' 를 뗀 값이 CSV 이름과 정확히 맞을 때만
            bare = POSSESSIVE.sub(r"\1", str(text))
            if bare != text:
                h = next((h for h in self.resolve(bare, slot) if h.source == "csv" and h.match == "exact"), None)
                if h:
                    out.append(replace(h, surface=text))
        if not any(h.grounded for h in out):
            rows = self._csv(text, slot, contains=True)
            if rows:
                out.append(self._hit(text, rows, slot, "contains"))
        out.sort(key=lambda h: (-h.grounded, -h.score, -h.n_tables))
        uniq, seen = [], set()
        for h in out:
            if (h.value, h.source) not in seen:
                seen.add((h.value, h.source))
                uniq.append(h)
        return uniq

    def best(self, text, slot=None):
        hits = self.resolve(text, slot)
        return hits[0] if hits else None

    def suggest(self, text, slot=None, k=10, tbl_ids=None):
        """비슷한 CSV 이름 (되묻기 후보). 포함 일치를 먼저, 다음 문자 유사도"""
        slots = SLOT_CSV.get(slot) or TARGET_CSV_SLOTS
        names = {}
        for sl in slots:
            for v in self.idx.values(sl, tbl_ids=tbl_ids, scope=self.scope):
                names[v["value"]] = max(names.get(v["value"], 0), v["n_tables"])
        q = norm(text)
        if not q:
            return sorted(names, key=lambda n: -names[n])[:k]
        contain = [n for n in names if q in norm(n) or (len(norm(n)) >= 2 and norm(n) in q)]
        close = difflib.get_close_matches(q, [norm(n) for n in names], n=k * 3, cutoff=self.s.fuzzy_cutoff)
        by_norm = {norm(n): n for n in names}
        out = list(dict.fromkeys(sorted(contain, key=lambda n: -names[n]) + [by_norm[c] for c in close]))
        return out[:k]

    def token_terms(self, text, slots=TARGET_CSV_SLOTS, exact=True):
        """질문 속 CSV 표현을 낱말 경계에 맞춰 찾기 → [(표현 norm, 행 목록)]
          - 띄어쓴 낱말 2~3개가 이어서 하나의 이름이면 그것 먼저 ('남편의 수', '국제결혼 이주자')
          - 낱말 하나 안에서는 처음부터 표현이 이어지고(앞에 꾸밈말 허용) 뒤에는 조사만 남아야 함
          - exact: 같은 이름만 (same_name). False 면 표기 변형까지 (scan_text 와 같음)"""
        toks = [norm(t) for t in str(text or "").split()]
        toks = [t for t in toks if t]
        ml = max(2, self.s.min_alias_len)

        def rows_of(key):
            rows = self.idx.find(key, slots=slots, scope=self.scope)
            return [r for r in rows if same_name(r["name"], key)] if exact else rows

        out, i = [], 0
        while i < len(toks):
            hit = None
            for n in (3, 2):
                if i + n > len(toks):
                    continue
                w = "".join(toks[i:i + n])
                for cand in dict.fromkeys([w, _strip_josa(w)]):
                    rows = rows_of(cand) if len(cand) >= ml else []
                    if rows:
                        hit = (cand, rows, n)
                        break
                if hit:
                    break
            if hit:
                out.append(hit[:2])
                i += hit[2]
                continue
            t = toks[i]
            i += 1
            spans = self.idx.scan_spans(t, slots=slots, scope=self.scope, min_len=ml)
            if not spans:
                continue
            start = spans[0][0]
            if start and t[:start] not in PREFIX_OK and t[:start] not in self.rules:
                continue
            acc, pos = [], start
            for s_, e_, key, rows in spans:
                if s_ != pos:
                    break
                rows = [r for r in rows if same_name(r["name"], key)] if exact else rows
                if not rows:
                    break
                acc.append((key, rows))
                pos = e_
            if acc and (pos == len(t) or JOSA_TAIL.fullmatch(t[pos:])):
                out += acc
        return out

    def question_terms(self, question, covered=(), max_share=0.15, max_terms=6):
        """질문 원문에 있는 '표를 가르는' CSV 표현 — 슬롯에 담기지 않은 것만
        재작성(HCX)이 '유학생'·'보증부월세'·'슬레이트' 같은 말을 '외국인 인구수' 로 뭉개도 원문에서 다시 찾아
        검색 문장과 View 자르기(build_view 의 보조 단어)에 쓴다. 대상·지표 슬롯은 건드리지 않음 (서브쿼리 분리에 영향 없음)
          - 두 글자 이상, 숫자·합계 말 제외, 전체 표의 max_share 이하에만 나오는 표현 (흔한 '인구'·'가구' 는 제외)
          - covered(슬롯 값들)와 서로 포함 관계면 이미 담긴 것으로 봄
        낱말 경계(token_terms) + 같은 이름만. 지역·성별·연령 값, 숫자로 시작하는 말은 넣지 않음"""
        n_all = max(len(self.idx.table_ids(self.scope)), 1)
        cov = [norm(c) for c in covered if c]
        out = []
        for key, rows in self.token_terms(question):
            n = len({r["tbl_id"] for r in rows})
            if key[:1].isdigit() or key in QTERM_STOP or re.fullmatch(r"[\d.,~\-년월세대]+", key) or n / n_all > max_share:
                continue
            if any(key in c or c in key for c in cov):
                continue
            if self.idx.find(key, slots=OTHER_SLOTS, scope="all", variant=False) \
                    or any(sl in ("지역", "성별", "국적") for sl, _ in self.rules.get(key, [])):
                continue  # 지역·성별·연령 값은 슬롯·검색 계수가 맡음
            same = [r["name"] for r in rows if norm(r["name"]) == key]
            name = min(same, key=len) if same else key
            if name not in out:
                out.append(name)
        return out[:max_terms]

    def scan(self, text):
        """자유 문장 속 사전 표현 (검색 문장 보강·지표 나열 확인용) → [(표현, 대표 CSV 이름, 표 수)]"""
        out = []
        for key, rows in self.token_terms(text, exact=False):
            h = self._hit(key, rows, "지표", "csv")
            out.append((key, h.value, h.n_tables))
        return out

    # ── 학습 사전 ──
    def learn(self, surface, value, slot=None, source="llm", status="pending", example=""):
        k = norm(surface)
        if len(k) < self.s.min_alias_len or k == norm(value):
            return None
        with self._lock:
            e = self.learned.setdefault(k, {"surface": surface, "value": value, "slot": slot, "source": source,
                                            "status": status, "count": 0, "examples": [], "added": _now()})
            e["count"] += 1
            if example and example not in e["examples"]:
                e["examples"] = (e["examples"] + [example])[-5:]
            if status == "active":
                e["status"] = "active"
        return e

    def approve(self, surface, value=None):
        e = self.learned.get(norm(surface))
        if e:
            e["status"] = "active"
            if value:
                e["value"] = value
            e["approved"] = _now()
        return e

    def reject(self, surface):
        return self.learned.pop(norm(surface), None)

    def save(self):
        self.learned_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.learned_path.write_text(json.dumps(self.learned, ensure_ascii=False, indent=1), encoding="utf-8")

    def expand_with_llm(self, names, chat_fn=None, per_name=5):
        """CSV 이름 목록 → LLM 이 낼 만한 다른 표현 (일상어·줄임말·띄어쓰기 변형) → 학습 사전 '승인 대기'
        사람이 확인 후 approve. 반환: 추가된 (표현, 값) 목록"""
        from backend.core.llm import chat
        chat_fn = chat_fn or chat
        schema = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "aliases"]}}}, "required": ["items"]}
        out = []
        for i in range(0, len(names), 20):
            chunk = names[i:i + 20]
            res = chat_fn([{"role": "system", "content":
                            f"국가통계 항목 이름마다, 사람이 질문할 때 쓸 만한 다른 표현을 최대 {per_name}개씩 적는다. "
                            "일상어·줄임말·띄어쓰기 변형·흔한 오타. 뜻이 달라지는 말(상위·하위 개념)은 쓰지 않는다. JSON 만."},
                           {"role": "user", "content": "\n".join(chunk)}], schema=schema, max_tokens=1500)
            for it in (res or {}).get("items") or []:
                if it.get("name") not in chunk:
                    continue
                for a in (it.get("aliases") or [])[:per_name]:
                    if self.learn(a, it["name"], slot="지표", source="llm"):
                        out.append((a, it["name"]))
        return out


def _now():
    return datetime.now().isoformat(timespec="seconds")


_LEX = {}


def get_lexicon(idx=None, settings=None) -> Lexicon:
    """같은 CSV 값 사전·설정이면 재사용"""
    from backend.core.settings import get_settings
    from backend.rag.csv_index.store import load_index
    idx = idx or load_index()
    s = settings or get_settings()
    key = (id(idx), s.model_dump_json())
    if key not in _LEX:
        _LEX.clear()
        _LEX[key] = Lexicon(idx, s)
    return _LEX[key]
