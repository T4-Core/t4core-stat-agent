"""
개념 초안 모으기 — compare 결과에서 '일상어(P)라서 못 찾은' 문항을 골라, 일상어 표현 ↔ 정답 표의 코드·항목·표 짝을 만든다

  python -m backend.rag.okf drafts --runs <compare 폴더 또는 per_query.csv> [더…] [--split dev|heldout|all] [--write]

  1) 문항 고르기  같은 레코드의 O(공식 용어)·P(일상어) 중 P 가 1위를 놓쳤고(완화 지표) O 보다 순위가 나쁜 것
                  (둘 다 못 찾은 문항은 어휘 문제가 아니라서 뺌)
  2) 짝 만들기    O 에만 있는 말이 정답 표의 무엇과 맞는지 (OKF 표 파일 · 지금 빌드의 코드북)
                    먼저 코드·항목 이름이 O 에 통째로 있으면('미혼모의 자녀') 그것만 — 옆 항목('미혼부의 자녀')은 안 묶음
                    그다음 O 에만 있는 내용어(Kiwi 형태소)
                      코드·항목 1~2개      → '어휘'        개념 초안 (일상어 → 그 코드·항목). 이름의 낱말이 모두 O 에 있을 때만
                                                           ('거주지' 하나로 '1년 전 거주지_전국' 을 묶지 않음 → 표 이름 짝으로)
                      코드·항목 3개 이상   → '용어'        여러 코드에 두루 맞는 공식 용어('주택') — colloquial.yaml 후보
                      표 이름              → '어휘(표)'    개념 초안 (일상어 → 그 표 전체)
                      분류 이름('체류기간별')만 → '표를 못 정함 의심'  P 로 바꾸며 표를 정하는 말이 빠짐 — 골든셋 검토용
                      아무것도              → '기타'
                  묶을 표 넓히기: 코드·항목 짝은 같은 이름의 항목(또는 같은 분류의 같은 코드)이 있는 모든 표에 묶음
                    ('출생' 항목이 있는 표 9개) — 정답 표에만 묶으면 골든셋에 맞춘 개념이 됨. --gold-only 로 끔
                  일상어 후보 = P 에만 있는 내용어 1~2개 (동사로 끝나면 어절 끝까지: '아이를 낳은'). 빼는 것:
                    흔한 말 · 지역 · O 나 정답 표 이름에 있는 말
                    colloquial.yaml 이 여러 표에 흔한 용어로만 바꾸는 말 ('남성' → 남자: 성별 용어라 표 하나의 개념이 아님)
  3) 근거 더하기  같은 폴더의 analysis_cache.jsonl 에 C 모드 '[어휘 후보]' 기록이 있으면, 그 낱말의 벡터 후보가 짝의 이름과 같을 때 표시
                  colloquial.yaml 이 그 말을 짝의 이름으로 바꾸면 'colloquial → 출생' 표시 (검색어 확장은 이미 있음 — 개념은 표를 정해 줌)
  4) 결과         <out>/drafts.md (사람이 읽음) · drafts.json
                  --write: 개념마다 concepts/_inbox/draft-*.md (status: draft — 별칭이 쓰이지 않음) 또는 있는 개념에 '미승인' 별칭
                           (다시 돌리면 아직 draft 인 초안에 새로 찾은 묶을 표를 더함)
                           쓴 뒤 정의를 표에서 채움 (assist.refresh) · --hcx: HCX 제안까지 (assist.assist) — okf/assist.py
                  사람이 고친 뒤  python -m backend.rag.okf verify <개념 경로> --to <영역/영어-이름> [--alias 표현]
                           → stable + 승인 + _inbox 에서 concepts/<영역>/<이름>.md 로 옮김 → lint → build

  과적합 방지: 기본은 dev 레코드에서만 초안을 만든다 (heldout 은 보고서에만). 평가는 heldout 으로 (compare --split heldout)
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from backend.rag.csv_index.store import norm
from backend.rag.okf import tables as T
from backend.rag.okf.doc import Doc, concept_id, iter_docs, now

PRODUCER = "process:okf-drafts/1"
ALIAS_BY = "draft:compare"
_CAND = re.compile(r"^\[어휘 후보\] '([^']+)' 사전에 없음 · 후보 (.*?)(?: — |$)")
_CAND_ITEM = re.compile(r"([^,]+?)\((0\.\d+|1\.0+)\)")


# ── 입력 ────────────────────────────────────────────────────────
def per_query_files(paths):
    out = []
    for p in map(Path, paths):
        f = p / "per_query.csv" if p.is_dir() else p
        if f.exists():
            out.append(f)
    return out


def load_rows(f, config=None):
    with open(f, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    cfgs = list(dict.fromkeys(r["config"] for r in rows))
    config = config or (cfgs[0] if cfgs else None)  # 여러 구성이면 첫 구성(기준)
    return [r for r in rows if r["config"] == config], config


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _rank(r):
    v = _num(r.get("rank_alt")) if r.get("rank_alt") not in (None, "") else _num(r.get("rank"))
    return v if v is not None else 999.0


def gap_records(rows, split="dev"):
    """같은 레코드의 O·P → P 가 1위를 놓쳤고 O 보다 나쁜 레코드 [{record_id, O, P, gold, p_rank, o_rank, split, top1}]"""
    by = defaultdict(dict)
    for r in rows:
        by[r["record_id"]][r["variant"]] = r
    out = []
    for rid, v in by.items():
        o, p = v.get("O"), v.get("P")
        if not o or not p:
            continue
        pr, orr = _rank(p), _rank(o)
        if pr <= 1 or pr <= orr:
            continue
        if split != "all" and (p.get("split") or "") != split:
            continue
        out.append({"record_id": rid, "O": o["question"], "P": p["question"], "gold": str(p.get("gold") or "").split(),
                    "p_rank": None if pr == 999 else pr, "o_rank": None if orr == 999 else orr, "split": p.get("split") or "",
                    "top1": p.get("top1") or "", "top1_nm": p.get("top1_nm") or "", "fail": p.get("fail") or ""})
    return out


def vector_notes(cache_files):
    """analysis_cache.jsonl 의 '[어휘 후보]' 기록 → {낱말(norm): {후보 이름…}}"""
    out = defaultdict(set)
    for f in cache_files:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                units = json.loads(line).get("units") or []
            except ValueError:
                continue
            for u in units:
                for n in u.get("notes") or []:
                    m = _CAND.match(str(n))
                    if m:
                        out[norm(m.group(1))] |= {x.group(1).strip() for x in _CAND_ITEM.finditer(m.group(2))}
    return out


# ── 표 어휘 (OKF 표 파일 + 코드북) ──────────────────────────────
class TableVocab:
    def __init__(self, bundle, codebooks=None):
        self.bundle, self.codebooks = Path(bundle), codebooks or {}
        self.docs = {}
        for p in iter_docs(self.bundle, ("tables",)):
            d = Doc.read(p)
            xt = d.meta.get("x-t4-table") or {}
            if not d.error and xt.get("tbl_id"):
                self.docs[str(xt["tbl_id"])] = (p, d)

    def names(self, tid):
        """→ [(종류, 이름, bind)] 종류 = code · item · dim · title"""
        if tid not in self.docs:
            return []
        p, d = self.docs[tid]
        xt, path = d.meta["x-t4-table"], concept_id(self.bundle, p)
        out = [("title", d.meta.get("title") or "", {"table": path, "name": d.meta.get("title") or ""})]
        for it in xt.get("items") or []:
            out.append(("item", str(it.get("name")), {"table": path, "item": str(it.get("id")), "name": str(it.get("name"))}))
        for dm in xt.get("dims") or []:
            out.append(("dim", str(dm.get("name")), {"kind": dm.get("kind")}))
            if dm.get("kind") == "geo":
                continue
            codes = dm.get("codes")
            if codes is None:
                cid = str(dm.get("classification") or "").rsplit("/", 1)[-1].removesuffix(".md")
                codes = [{"code": c, "name": n} for c, n in (self.codebooks.get(cid) or {}).items()]
            for c in codes or []:
                if not c.get("total"):
                    out.append(("code", str(c.get("name")), {"table": path, "dim": str(dm.get("name")),
                                                             "code": str(c.get("code")), "name": str(c.get("name"))}))
        return out

    def title(self, tid):
        return self.docs[tid][1].meta.get("title", "") if tid in self.docs else ""

    def same(self, b, limit=30):
        """같은 이름의 항목 · 같은 분류(괄호 뺀 이름)의 같은 코드가 있는 모든 표의 bind (b 의 표 먼저). 표 이름 짝은 그대로"""
        key = self._key(b)
        if key is None:
            return [b]
        if not hasattr(self, "_by"):
            self._by = defaultdict(list)
            for tid in sorted(self.docs):
                for k, _, x in self.names(tid):
                    kk = self._key(x) if k in ("code", "item") else None
                    if kk is not None:
                        self._by[kk].append(x)
        out = [b] + [x for x in self._by.get(key, []) if x["table"] != b["table"]]
        return out if len(out) <= limit else [b]  # 너무 많은 표에 있는 이름이면 넓히지 않음 (용어 쪽)

    @staticmethod
    def _key(b):
        if "item" in b:
            return ("item", norm(b.get("name")))
        if "dim" in b:
            return ("code", norm(re.sub(r"\(.*?\)", "", str(b["dim"]))), norm(b.get("name")))
        return None


# 흔한 말 — 성별·합계 표현('남성' · '남녀' · '나라')도: 여러 표에 두루 있는 분류 값이라 표 하나의 개념이 될 수 없음
_GENERIC_WORDS = """년 월 일 분기 반기 수 명 건 가구 호 개 곳 총 총수 전체 전국 우리나라 대한민국 국내 사람 지역 비교 때 되 하 있 없 줄 늘
남성 여성 남녀 성별 나라 살 거주
변하 달라지 증가 감소 얼마 몇 정도 경우 기준 결과 조사 자료 통계 퍼센트 비율 수치 특정 이상 이하 중 후 전 다른 해 등 값 평균 합계 계
알 알리 보 궁금 구체 실시 변화 구하 나누 더하 포함 구분 차지 대비 대하 따르 관하 관련 해당 각 모든 가장 많 적 높 낮 크 작 이 그 저
때문 기간 시점 이번 지난 지나 어떻 어떠하 비하 정확 대략 무엇 누구 언제 어디 궁금하 알아보 확인"""  # 사람이 고치기 쉬운 공백 구분 목록
GENERIC = set(_GENERIC_WORDS.split())
_REGION_TAIL = re.compile(r"(?:특별시|광역시|특별자치시|특별자치도|[도시군구읍면동])$")
CONTENT = ("NNG", "NNP", "VV", "VA", "XR", "SL")


def morphs(text, tags=False):
    """내용어 형태소 [(형태, 시작, 끝)] (tags=True 면 품사도) — Kiwi (검색 색인과 같은 분석기)"""
    from backend.rag.ingestion import table_text as TT
    TT.tokenize("")  # Kiwi 준비
    with TT._kiwi_lock:
        toks = TT._kiwi.tokenize(str(text or ""))
    out = [(t.form, t.start, t.start + t.len, t.tag) for t in toks if t.tag.startswith(CONTENT) and not t.form.isdigit()]
    return out if tags else [x[:3] for x in out]


def colloquial_targets(text):
    """configs/colloquial.yaml 이 이 말을 바꾸는 통계어 ['출생'] (검색의 일상어 확장과 같은 규칙)"""
    from backend.rag.search import query as Q
    if Q._COLLOQUIAL is None:
        Q._COLLOQUIAL = Q._colloquial()
    return list(dict.fromkeys(t for pat, ts in Q._COLLOQUIAL if pat.search(str(text)) for t in ts))


def _regionish(f):
    """지역 이름 모양 ('세종특별자치시' · '포천시' · '청양군') — colloq_mine 의 지역 판정이 놓친 것까지"""
    from backend.rag.search.tuning.colloq_mine import _region
    return _region(f) or (len(f) >= 3 and bool(_REGION_TAIL.search(f)))


class Stats:
    """빈도 — 흔한 말을 거르는 기준 (사람이 정한 목록 대신)
      p_df     P 질문 전체에서 형태소가 나온 비율 (0.08 넘으면 흔한 말: '비해' · '어떻')
      name_df  코드·항목 이름이 나오는 표 수 (30 넘으면 개념이 아니라 용어: '여자' · '총인구')
      title_df 표 이름 형태소가 나오는 표 수 (5 이하일 때만 표 단위 짝: '쌍태아' 는 되고 '시군구' · '현황' 은 안 됨)"""

    def __init__(self, tv: TableVocab, p_questions, p_max=0.08, name_max=30, title_max=5):
        from collections import Counter
        self.p_max, self.name_max, self.title_max = p_max, name_max, title_max
        self.n_p = max(len(p_questions), 1)
        self.p_df = Counter(f for q in p_questions for f in {f for f, _, _ in morphs(q)})
        name_df, title_df = Counter(), Counter()
        for tid in tv.docs:
            ns, ts = set(), set()
            for k, n, _ in tv.names(tid):
                if k in ("code", "item"):
                    ns.add(norm(n))
                elif k == "title":
                    ts |= {f for f, _, _ in morphs(n)}
            name_df.update(ns)
            title_df.update(ts)
        self.name_df, self.title_df = name_df, title_df

    def common_p(self, f):
        return f in GENERIC or (self.n_p >= 20 and self.p_df[f] / self.n_p > self.p_max)


def _forms(name):
    return {f for f, _, _ in morphs(name)}


def _dim_word(token, dim_name):
    d = norm(re.sub(r"\(.*?\)", "", dim_name))
    t = norm(token)
    return len(t) >= 2 and (t == d or t == d.removesuffix("별") or (t in _forms(dim_name) and d.endswith("별")))


# ── 짝 만들기 ───────────────────────────────────────────────────
def analyze_record(rec, tv: TableVocab, st: Stats, max_phrases=3):
    om, pm = morphs(rec["O"]), morphs(rec["P"])
    of, pf = {f for f, _, _ in om}, {f for f, _, _ in pm}
    gold_names = [(k, n, b, _forms(n)) for tid in rec["gold"] for k, n, b in tv.names(tid)]
    o_only = [f for f in dict.fromkeys(f for f, _, _ in om) if f not in pf and f not in GENERIC and len(f) >= 2 and not _regionish(f)]
    binds, terms, structural = [], [], []
    # 분류 이름('세대구성별' · '체류기간별')이 O 에만 있으면 표를 정하는 구조 말 — 그 형태소는 짝 찾기에서 뺌
    o_n, p_n = norm(rec["O"]), norm(rec["P"])
    for k, n, b, fs in gold_names:
        base = norm(re.sub(r"\(.*?\)", "", n))
        if k == "dim" and (b or {}).get("kind") == "geo":
            continue  # 지역 분류('행정구역별')는 P 에도 지역 이름이 있어 표를 정하는 말이 아님
        if k == "dim" and len(base) >= 3 and (base in o_n or base.removesuffix("별") in o_n) and base.removesuffix("별") not in p_n:
            structural.append(n)
            exact = {norm(m) for kk, m, _, _ in gold_names if kk in ("code", "item")}
            o_only = [f for f in o_only if f not in fs or norm(f) in exact]  # '출생시 체중별' 의 '출생' 은 항목 이름이라 남김

    def add(t, k, n, b):
        if st.name_df[norm(n)] > st.name_max:
            terms.append(t)  # 많은 표에 있는 이름 ('여자' · '총인구') → 용어
        elif not any(x is b for _, _, x in binds):
            binds.append((t, k, b))

    for t in o_only:
        hits = [(k, n, b) for k, n, b, fs in gold_names if k in ("code", "item") and (norm(t) == norm(n) or t in fs)]
        exact = [h for h in hits if norm(h[1]) == norm(t)]
        full = [h for h in hits if _forms(h[1]) <= of]  # 이름의 낱말이 O 에 모두 있음
        whole = [h for h in hits if norm(h[1]) in o_n]  # 이름이 O 에 통째로 ('미혼모의 자녀' — '자녀' 가 같은 '미혼부의 자녀' 는 아님)
        pick = exact or whole or (full if len(full) <= 2 else [])
        if pick:
            for k, n, b in pick[:2]:
                add(t, k, n, b)
            continue
        if len(hits) > 2:
            terms.append(t)  # 여러 코드에 두루 맞는 말 ('주택')
            continue
        # 1~2개에 걸리지만 이름 일부만 맞음 ('거주지' ↔ '1년 전 거주지_전국') → 코드 짝이 아님 (아래 분류·표 이름으로)
        if any(k == "dim" and (b or {}).get("kind") != "geo" and _dim_word(t, n) for k, n, b, _ in gold_names):
            structural.append(t)
            continue
        if st.title_df[t] <= st.title_max:
            binds += [(t, k, b) for k, n, b, fs in gold_names if k == "title" and t in fs][:1]
    terms = list(dict.fromkeys(terms))
    # 일상어 후보: P 에만 있는 내용어 1~2개 (붙어 있는 것). 흔한 말 · 지역 · O 나 정답 표 이름에 이미 있는 말은 뺌
    #   한 글자 형태소는 동사·형용사 줄기('낳' · '살')나 한 어절에 붙은 것('싱글맘' 의 '맘')만 — 떨어진 한 글자 명사('시')는 지역 조각이기 쉬움
    pmt = morphs(rec["P"], tags=True)
    gold_text, o_text = norm(" ".join(n for _, n, _, _ in gold_names)), norm(rec["O"])
    phrases = []
    for n in (2, 1):
        for i in range(len(pmt) - n + 1):
            seg = pmt[i:i + n]
            fs = [f for f, _, _, _ in seg]
            glued = n == 2 and seg[1][1] == seg[0][2]  # 한 어절 안 ('싱글'+'맘')
            if any(f in of or st.common_p(f) or _regionish(f) or (len(f) < 2 and not tg.startswith(("VV", "VA")) and not glued)
                   for f, _, _, tg in seg):
                continue
            if n == 2 and seg[1][1] - seg[0][2] > 3:
                continue
            end = seg[-1][2]
            if seg[-1][3].startswith(("VV", "VA")):  # 동사 줄기로 끝나면 어절 끝까지 ('아이를 낳' → '아이를 낳은')
                while end < len(rec["P"]) and re.match(r"[가-힣]", rec["P"][end]):
                    end += 1
            text = rec["P"][seg[0][1]:end]
            if len(norm(text)) < 2 or norm(text) in gold_text or norm(text) in o_text or all(f in gold_text for f in fs):
                continue
            targets = colloquial_targets(text)
            if targets and all(st.name_df[norm(x)] > st.name_max for x in targets):
                continue  # colloquial.yaml 이 흔한 용어로만 바꾸는 말 ('남성' → 남자)
            if not any(norm(text) in norm(x) for x in phrases):
                phrases.append(text)
    phrases = phrases[:max_phrases]
    structural = list(dict.fromkeys(structural))
    kind = "어휘" if any(k in ("code", "item") for _, k, _ in binds) else "어휘(표)" if binds else \
        "용어" if terms else "표를 못 정함 의심" if structural else "기타"
    return {**rec, "kind": kind, "official": o_only, "binds": binds, "terms": terms, "structural": structural,
            "phrases": phrases, "gold_titles": [tv.title(t) for t in rec["gold"]]}


def collect(runs, bundle, split="dev", config=None, codebooks=None, gold_only=False):
    """→ (문항 분석 목록, 개념 초안 [{name, dim, kind, binds[], gold[], aliases[]}], 용어 후보 [{phrase, term, records}], 사용한 파일들)
    gold_only: 묶을 표를 정답 표로만 (기본은 같은 이름의 코드·항목이 있는 표 모두)"""
    tv = TableVocab(bundle, codebooks)
    files = per_query_files(runs)
    caches = [f.parent / "analysis_cache.jsonl" for f in files if (f.parent / "analysis_cache.jsonl").exists()]
    vec = vector_notes(caches)
    loaded = [(f, *load_rows(f, config)) for f in files]
    st = Stats(tv, [r["question"] for _, rows, _ in loaded for r in rows if r["variant"] == "P"])
    recs, used = [], []
    for f, rows, cfg in loaded:
        used.append({"file": str(f), "config": cfg})
        recs += [analyze_record(r, tv, st) for r in gap_records(rows, split)]
    drafts, terms = {}, {}
    for r in recs:
        for ph in r["phrases"]:
            for t in r["terms"]:
                e = terms.setdefault((norm(ph), t), {"phrase": ph, "term": t, "records": []})
                e["records"].append(r["record_id"])
        if r["kind"] not in ("어휘", "어휘(표)"):
            continue
        for _, k, b in r["binds"]:
            key = (b.get("dim") or ("항목" if "item" in b else "표"), norm(b["name"]))
            d = drafts.setdefault(key, {"name": b["name"], "dim": b.get("dim") or "", "kind": k, "binds": [], "gold": [],
                                        "aliases": defaultdict(list), "evidence": defaultdict(list)})
            if b not in d["gold"]:
                d["gold"].append(b)
            for ph in r["phrases"]:
                if r["record_id"] not in d["aliases"][ph]:
                    d["aliases"][ph].append(r["record_id"])
                if any(norm(c) == norm(b["name"]) for c in vec.get(norm(ph)) or ()):
                    d["evidence"][ph].append("벡터 후보 일치")
                cq = colloquial_targets(ph)  # 검색의 일상어 확장이 이 말을 무엇으로 바꾸는지 — 짝과 같은 쪽이면 근거, 다르면 경고
                same = [c for c in cq if norm(c) in norm(b["name"])]
                other = [c for c in cq if c not in same]
                if same:
                    d["evidence"][ph].append(f"colloquial → {same[0]}")
                if other:
                    d["evidence"][ph].append(f"⚠ colloquial 은 '{', '.join(other)}' 로도 바꿈 — 뜻이 넓거나 다름")
    for d in drafts.values():  # 정답 표 먼저, 그다음 같은 이름이 있는 다른 표
        for b in d["gold"]:
            for x in ([b] if gold_only else tv.same(b, st.name_max)):
                if x not in d["binds"]:
                    d["binds"].append(x)
    pq = {r["record_id"]: r["P"] for r in recs}
    out = []
    for d in sorted(drafts.values(), key=lambda d: -max([len(v) for v in d["aliases"].values()] or [0])):
        out.append({"name": d["name"], "dim": d["dim"], "kind": d["kind"], "binds": d["binds"], "gold": d["gold"],
                    "aliases": [{"text": a, "records": rs, "support": len(rs), "evidence": sorted(set(d["evidence"].get(a, []))),
                                 "example": pq.get(rs[0], "")}
                                for a, rs in sorted(d["aliases"].items(), key=lambda x: -len(x[1]))]})
    term_list = sorted(terms.values(), key=lambda e: -len(e["records"]))
    return recs, out, term_list, used


# ── 보고서 · 쓰기 ───────────────────────────────────────────────
def report_md(recs, drafts, used, split, terms=()):
    from collections import Counter
    kinds = Counter(r["kind"] for r in recs)
    L = ["# 개념 초안 — 일상어(P) 때문에 못 찾은 문항", "",
         f"- 만든 시각: {datetime.now().isoformat(timespec='seconds')} · 문항 split: {split}",
         *[f"- 입력: `{u['file']}` (구성 {u['config']})" for u in used],
         f"- 고른 문항 {len(recs)}개 (P 가 1위를 놓쳤고 O 보다 순위가 나쁨): " + " · ".join(f"{k} {n}" for k, n in kinds.most_common()), "",
         "## 초안 (개념 = 묶일 코드·항목·표)", "",
         "| 개념(정규 이름) | 분류 | 묶일 표 | 일상어 후보 (레코드 수 · 근거) |", "|---|---|---|---|"]
    tid = lambda b: b["table"].rsplit("/", 1)[-1].removesuffix(".md")
    for d in drafts:
        gold = list(dict.fromkeys(tid(b) for b in d.get("gold") or d["binds"]))
        more = len({tid(b) for b in d["binds"]} - set(gold))
        tabs = ", ".join(gold) + (f" 외 {more}개 (같은 이름)" if more else "")
        als = "; ".join(f"{a['text']} ({a['support']}{' · ' + ', '.join(a['evidence']) if a['evidence'] else ''})" for a in d["aliases"][:6])
        L.append(f"| {d['name']} | {d['dim'] or d['kind']} | {tabs} | {als or '(일상어 후보 없음)'} |")
    if terms:
        L += ["", "## 용어 후보 (여러 코드에 두루 맞는 공식 용어 — 개념이 아니라 configs/colloquial.yaml 후보)", "",
              "| 일상어 | 공식 용어 | 레코드 |", "|---|---|---|"]
        L += [f"| {e['phrase']} | {e['term']} | {len(e['records'])} |" for e in terms[:40]]
    for title, kind in (("표를 못 정함 의심 (골든셋 검토용 — P 로 바꾸며 표를 정하는 분류 이름이 빠짐)", "표를 못 정함 의심"),
                        ("기타 (O 에만 있는 말이 정답 표 어디에도 안 맞음 — 시점·분기·조건 문제일 수 있음)", "기타")):
        rs = [r for r in recs if r["kind"] == kind]
        if rs:
            L += ["", f"## {title}", "", "| 레코드 | P 순위 | O 순위 | O 에만 있는 말 | P | 정답 표 | P 1위 |", "|---|---|---|---|---|---|---|"]
            for r in rs:
                L.append(f"| {r['record_id']} | {r['p_rank'] or '-'} | {r['o_rank'] or '-'} | "
                         f"{', '.join(r['structural'] or r['official'][:4])} | {r['P'][:60]} | {' · '.join(r['gold_titles'])[:60]} | {r['top1_nm'][:40]} |")
    L += ["", "## 문항별", ""]
    for r in recs:
        L.append(f"- **{r['record_id']}** [{r['kind']}] P {r['p_rank'] or '-'}위 / O {r['o_rank'] or '-'}위 — P: {r['P']}")
        L.append(f"  - O: {r['O']}")
        L.append("  - 짝: " + (", ".join(f"{t} → {b['name']}" for t, _, b in r["binds"]) or "-") +
                 (f" · 용어: {', '.join(r['terms'])}" if r["terms"] else "") + f" · 일상어 후보: {', '.join(r['phrases']) or '-'}")
    return "\n".join(L) + "\n"


def write_drafts(bundle, drafts, min_support=1, log=print, hcx=False, chat_fn=None):
    """개념마다 _inbox/draft-*.md (status draft) 또는 있는 개념에 미승인 별칭 → [(개념 경로, 별칭, 결과)]
    draft 개념은 쓴 뒤 사실 정의를 채움 (assist.refresh). hcx=True 면 HCX 제안까지 (assist.assist)"""
    from backend.rag.okf import assist as A
    from backend.rag.okf.curate import add_alias, concept_doc, find_concept, write_new
    out, touched = [], {}
    for d in drafts:
        aliases = [a for a in d["aliases"] if a["support"] >= min_support]
        if not aliases:
            continue
        path = find_concept(bundle, d["name"], d["dim"] or None)
        entries = [{"text": a["text"], "by": ALIAS_BY, "at": now(), "records": a["records"][:5],
                    **({"example": a["example"][:160]} if a.get("example") else {}),
                    **({"evidence": a["evidence"]} if a["evidence"] else {})} for a in aliases]
        if path is None:
            b0 = d["binds"][0]
            tbl = b0["table"].rsplit("/", 1)[-1].removesuffix(".md")
            rel = f"_inbox/draft-{T.slugify(tbl)}-{T.slugify(b0.get('code') or b0.get('item') or 'table')}"
            if (Path(bundle) / "concepts" / f"{rel}.md").exists():
                path = Path(bundle) / "concepts" / f"{rel}.md"
            else:
                desc = f"{DRAFT_MARK} 일상어 질문에서 못 찾은 문항으로 만든 개념. {d['dim'] + ' ' if d['dim'] else ''}'{d['name']}'"
                doc = concept_doc(d["name"], desc, d["binds"], by=PRODUCER, status="draft",
                                  tags=[t for t in [(d["dim"] or "").rstrip("별")] if t])
                path = write_new(bundle, rel, doc)
                log(f"+ {concept_id(bundle, path)} (binds {len(d['binds'])})")
        n = merge_binds(path, d["binds"])  # 아직 draft 인 개념이면 새로 찾은 묶을 표를 더함 (승인된 개념은 그대로)
        if n:
            log(f"~ {concept_id(bundle, path)} (binds +{n})")
        for e in entries:
            out.append((concept_id(bundle, path), e["text"], add_alias(path, e)))
        fill_examples(path, entries)
        touched[str(path)] = path
    for path in touched.values():  # draft 만 (승인된 개념은 refresh 가 건너뜀)
        r = A.assist(bundle, path, chat_fn=chat_fn) if hcx else A.refresh(bundle, path)
        if r["definition"] != "skip":
            log(f"  정의 {r['definition']}" + (f" · HCX {r.get('hcx')}" if hcx else "") + f" — {r['concept']}")
    T.write_dir_indexes(bundle)
    return out


def fill_examples(path, entries) -> None:
    """draft 개념의 별칭에 예문(P 질문)이 없으면 채움 — 사람 검토와 HCX 판정에 씀"""
    d = Doc.read(path)
    if d.error or d.meta.get("status") != "draft":
        return
    ex = {norm(e["text"]): e["example"] for e in entries if e.get("example")}
    changed = False
    for a in (d.meta.get("x-t4-concept") or {}).get("aliases") or []:
        if isinstance(a, dict) and not a.get("example") and norm(a.get("text")) in ex:
            a["example"] = ex[norm(a["text"])]
            changed = True
    if changed:
        Path(path).write_text(d.text(), encoding="utf-8", newline="\n")


def merge_binds(path, binds) -> int:
    """아직 draft 인 개념 파일에 없는 bind 를 더함 → 더한 수 (사람이 승인한 개념은 건드리지 않음)"""
    d = Doc.read(path)
    if d.error or d.meta.get("status") != "draft":
        return 0
    c = d.meta.setdefault("x-t4-concept", {})
    have = c.setdefault("binds", [])
    key = lambda b: (b.get("table"), b.get("dim"), str(b.get("code") or b.get("item") or ""))
    seen = {key(b) for b in have if isinstance(b, dict)}
    new = [b for b in binds if key(b) not in seen]
    if new:
        from backend.rag.okf.curate import bind_lines
        have += new
        head, sep, rest = d.body.partition("# 표\n")
        if sep:  # 본문 '# 표' 목록도 다시 (그다음 제목 전까지)
            m = re.search(r"^# ", rest, re.MULTILINE)
            d.body = head + sep + "\n" + "\n".join(bind_lines(have)) + "\n" + ("\n" + rest[m.start():] if m else "")
        Path(path).write_text(d.text(), encoding="utf-8", newline="\n")
    return len(new)


DRAFT_MARK = "(초안)"
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)+$")


def _dest(bundle, to):
    rel = str(to).strip().strip("/").removesuffix(".md")
    rel = rel.removeprefix("concepts/")
    if not _SLUG.match(rel):
        raise ValueError(f"--to 는 '영역/영어-이름' 모양 (소문자·숫자·-): '{to}' (예: population/birth)")
    if rel.startswith("_inbox/"):
        raise ValueError("--to 는 _inbox 밖이어야 함")
    return Path(bundle) / "concepts" / f"{rel}.md"


def verify(bundle, path, aliases=None, by=None, to=None) -> dict:
    """사람이 확인한 개념 → status stable + verified (개념) · 별칭 승인 (aliases 를 주면 그것만, 아니면 미승인 전부)
    to='population/birth' 이면 concepts/population/birth.md 로 옮김 (_inbox 초안을 제자리로). 경고는 결과의 warnings"""
    from backend.rag.okf.curate import who
    by = who(by)
    p = Path(path) if Path(path).exists() else Path(bundle) / str(path).lstrip("/")
    d = Doc.read(p)
    if d.error or d.type != "Stat Concept":
        raise ValueError(f"개념 파일이 아님: {p} ({d.error or d.type})")
    dest = _dest(bundle, to) if to else None
    if dest is not None and dest.resolve() != p.resolve() and dest.exists():
        raise FileExistsError(f"이미 있음: {concept_id(bundle, dest)} (그 개념에 별칭을 옮겨 적거나 다른 이름으로)")
    ev = {"by": by, "at": now()}
    if d.meta.get("status") == "draft":
        d.meta["status"] = "stable"
    v = d.meta.get("verified")
    d.meta["verified"] = (v if isinstance(v, list) else [v] if isinstance(v, dict) else []) + [ev]
    from backend.rag.okf.assist import SKIP_VERDICTS
    want = {norm(a) for a in aliases} if aliases else None
    done, skipped = [], []
    for a in (d.meta.get("x-t4-concept") or {}).get("aliases") or []:
        if not (isinstance(a, dict) and a.get("by") and not a.get("verified")):
            continue
        if want is not None:
            ok = norm(a.get("text")) in want
        else:  # 고르지 않으면 HCX 가 broad·wrong 으로 본 것은 빼고
            ok = (a.get("review") or {}).get("verdict") not in SKIP_VERDICTS
            if not ok:
                skipped.append(f"{a['text']} ({a['review']['verdict']}: {a['review'].get('reason', '')})")
        if ok:
            a["verified"] = ev
            done.append(a["text"])
    warnings = draft_warnings(bundle, dest or p, d)
    if dest is not None and dest.resolve() != p.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(d.text(), encoding="utf-8", newline="\n")
        p.unlink()
        p = dest
    else:
        p.write_text(d.text(), encoding="utf-8", newline="\n")
    T.write_dir_indexes(bundle)
    return {"concept": concept_id(bundle, p), "status": d.meta["status"], "verified_aliases": done, "skipped_aliases": skipped,
            "warnings": warnings}


def draft_warnings(bundle, path, d) -> list:
    """승인된(draft 아닌) 개념에 초안 흔적이 남았는지 — verify 결과와 lint 가 같이 씀"""
    if d.meta.get("status") in ("draft", "deprecated"):
        return []
    out = []
    body = re.sub(r"^\s*#\s*정의\s*", "", d.body or "")
    if str(d.meta.get("description") or "").startswith(DRAFT_MARK) or body.startswith(DRAFT_MARK):
        out.append("정의가 아직 '(초안) …' 문장 — description 과 본문 '# 정의' 를 고치세요")
    if concept_id(bundle, path).startswith("/concepts/_inbox/"):
        out.append("승인된 개념이 _inbox 에 있음 — python -m backend.rag.okf verify <경로> --to <영역/영어-이름> 으로 옮기세요")
    if any(isinstance(a, dict) and a.get("by") == ALIAS_BY and not a.get("verified")
           for a in (d.meta.get("x-t4-concept") or {}).get("aliases") or []):
        out.append("승인 안 된 초안 별칭이 남음 (쓰이지 않음) — 틀린 것이면 지우세요")
    return out
