"""표 검색 — 표 전체에 채널 점수를 매겨 합치고(가중 RRF) 표 구조 계수(시점·주기·지역 수준 …)를 곱한다

  1) 원문과 재작성 문장을 둘 다 검색해 채널별 순위를 합친다
  2) 후보를 먼저 자르지 않는다: 표 전체(약 1,100개)에 채널 점수·구조 계수를 계산
  3) 조건은 정렬 1순위가 아니라 곱하는 계수: 잘못 뽑힌 슬롯 하나가 정답 표를 통째로 밀어내지 않게.
     계수는 원문에서 규칙으로 확인되는 것만 (시점=실제 수록 연도 · 주기 · 지역 수준 · 연령·성별 분류 · 조사 이름)
  4) 지표 슬롯은 순위에 쓰지 않는다 (unmet 은 표시용으로만 붙임)
  5) 형제 표 해소 · 분모 단위 · (선택) LLM 재정렬

  s = get_search()
  s.search(search_query, filters, top_k, question=원문, unit="main")
"""
from __future__ import annotations

import copy
import threading
import time

import numpy as np

from backend.rag.search.channels import Channels, ranks
from backend.rag.search.facets import URBAN, build_facets
from backend.rag.search.query import parse_question
from backend.rag.search.text import TOTALS, norm

DEFAULTS = {
    "dense": "hcx",  # 1단계부터 BM25 와 함께 (none 이면 어휘 채널만)
    # dense 에 넣을 표 문서 (index.dense_doc_views): rule = 표 설명문(BM25 와 같은 글) · def / slot = dense 카드의
    # 정의문 / 슬롯 정규문 (ingestion/dense_cards.py) · tmpl / tslot = 그 코드 템플릿판 · kos14 = 팀 카드(kos14_cards).
    # '+' 로 여러 개 = 표마다 최댓값. 끝에 '+rw' = 재작성 문장(검색 문장)으로도 dense 를 한 번 더 (rw_dense 채널)
    # ',' 로 나누면 묶음마다 dense 채널을 따로 (RRF 로 합침 — 점수 크기가 다른 묶음을 공정하게). 둘째 채널부터 가중치 q_dense_<묶음>
    # (없으면 dense_extra_weight). vals = 표의 항목·분류 값 조각 (표 하나 = 여러 글, 표마다 최댓값)
    # okf = 표 설명문 + OKF 개념 별칭 줄 (okf_terms.py — 별칭 없는 표는 rule 과 같은 글)
    "dense_docs": "rule", "dense_cards": None, "kos14_cards": None, "dense_extra_weight": 1.0,
    "rrf_k": 20, "depth": 200,
    # OKF 지식 카탈로그 (storage/okf_build/CURRENT): 개념의 승인된 별칭을 그 개념이 묶인 표의 값 표현으로 (값 채널)
    # 질문에 '싱글맘' → '모+미혼자녀' 코드가 있는 표. 빌드가 없으면 아무것도 안 함. 비교: compare --okf on off
    "okf": {"enabled": True, "value_weight": 0.9},
    # 본 질의: 원문(q_*) + 재작성 문장(rw_*). 하위 질의: 그 단위 문장(q_*) + 원문은 약하게(ctx_*)
    # dense 를 어휘 채널보다 크게: 일상어 질문(concept)은 단어가 표와 겹치지 않아 임베딩이 주 신호
    "weights": {"q_value": 1.6, "q_title": 1.4, "q_lex": 1.0, "q_ngram": 0.8, "q_dense": 1.6,
                "rw_lex": 0.7, "rw_value": 0.5, "rw_ngram": 0.3, "rw_dense": 1.0,  # rw_dense 는 dense_docs 에 +rw 일 때만
                "ctx_value": 0.4, "ctx_lex": 0.3, "ctx_title": 0.4},
    # 가능성 계수 (곱). 시점: 하나도 못 담으면 year_floor, 일부라도 담으면 year_partial + (1 - year_partial) × 담은 비율
    # → 요청 연도를 다 담지 못한 표도 후보로 남고(2005·2025 를 서로 다른 연도판이 나눠 가진 경우), View 가 있는 연도만 줌
    "feas": {"year_floor": 0.12, "year_partial": 0.6, "stale": 0.5, "cycle_miss": 0.4,
             "sub_named": 1.0, "sub_level": 0.85, "sub_miss": 0.25, "sido_miss": 0.45, "axis_miss": 0.4,
             "age_miss": 0.5, "sex_miss": 0.65, "survey_hit": 1.35, "extra_dim": 0.12, "extra_dim_floor": 0.6,
             "latest_from": None,
             # 주기: 분기를 물었는데 분기가 없고 월만 있음(계산으로 얻음) → cycle_derived (반기 ← 분기·월도 같음)
             "cycle_derived": 0.9,
             # 인구 이동 범위·방향 (movement.py): 묻는 이동이 표에 없음 → move_miss · 전출지×전입지 행렬로 계산 가능 → move_derived
             "move_miss": 0.6, "move_derived": 0.9,
             # 시군구 이름만 물었는데(읍면동 수준을 묻지 않음) 읍면동까지 나뉜 표 → geo_finer (같은 값을 더 단순한 표에서)
             "geo_finer": 0.92,
             # 조건 누락: 질문의 드문 표현(값 사전에서 cond_df 개 이하 표에만 있는 말, 3자 이상)을 가진 표가 있으면,
             # 같은 조사의 그 말이 없는 표에 cond_miss (말마다 곱, 바닥 cond_floor). '쌍태아' 를 물었는데 일반 출생 표가 1위이던 문제
             "cond_miss": 0.8, "cond_floor": 0.64, "cond_df": 8},
    # LLM 재정렬: 끼워 넣는 형제·같은 개념 표는 상위 top_n 의 '뒤' 에 붙임 (앞 순위를 밀어내지 않음).
    # 하위 단위는 그 단위 문장으로, 원래 질문은 맥락으로만. skip_roles 의 단위(분모)는 규칙이 고른 순서를 그대로 둠
    "llm_rerank": {"enabled": False, "top_n": 12, "add_siblings": 4, "skip_roles": ["분모"],
                   "okf": False, "keep_if_unsure": False,  # okf: 카드에 표 정의·개념 (llm_rerank.py) · 불확실하면 원래 순서
                   "traits": False, "thinking": None, "think_tokens": None},  # 구분 줄 (traits.py) · HCX-007 추론 low|medium|high
    # (선택) 교차 인코더 재정렬 — ce_rerank.py. 상위 top_n 을 [질문, 표 글] 쌍으로 다시 채점해 순위 융합(blend)
    "ce_rerank": {"enabled": False, "model": "bge-reranker-ko", "top_n": 20, "mode": "blend", "k": 5, "weight": 1.0,
                  "base_weight": 1.0, "doc": "struct+def", "max_length": 512, "batch": 16, "skip_roles": ["분모"]},
    # 분모 단위: '인구'·'가구'·'주택' 뿐인 하위 질의(또는 filters.역할 = 분모)는 본 질의를 다시 찾지 않고
    # '그 말이 제목·항목에 있는 단순한 표' 를 찾는다. 본 질의 1위 표와 같은 조사면 더 앞에 (같은 조사·연도·수준의 인구 표)
    "roles": {"enabled": True, "den_miss": 0.35, "den_dim": 0.2, "den_dim_floor": 0.45, "den_survey": 1.5},
    # 개념 카탈로그 (concepts.py → <CSV 값 사전>/concepts.json): 같은 값을 주는 표 묶음.
    # 무리 안의 '바꿔치기' 에는 쓰지 않음 (같은 값은 합계 칸에서만 확인된 경우가 많음) — LLM 후보에 끌어오고 카드에 표시
    "concepts": {"enabled": True, "path": None, "add": 3},
    # 기간 이어붙이기 (period_groups.py): 같은 통계의 연도판 묶음. 순위는 그대로 두고 결과마다 있는/없는 연도와
    # 이어붙일 표 계획(stitch)을 붙임 — View 단계가 view_stitch 일 때 그 계획으로 View 를 더 만듦.
    # links = 사람이 확인한 '이름이 바뀐 같은 통계' 연결 CSV (비우면 configs/period_links.csv)
    "stitch": {"enabled": True, "links": None},
    # 형제 표 해소 (siblings.py): 상위 window 안의 무리마다 좌표(성별·지역 수준·연도)로 하나를 앞에
    "siblings": {"enabled": True, "window": 12, "margin": 0.75, "max_outside": 3},
    "generic_units": ["인구", "인구수", "가구", "가구수", "비율", "구성비", "총계", "합계", "계", "평균", "건수", "명수", "호수",
                      "교육", "남자", "여자", "남자 여자", "총인구", "총인구수"],
}


def load_settings(overrides=None):
    s = copy.deepcopy(DEFAULTS)
    from backend.core.config import CONFIGS_DIR
    f = CONFIGS_DIR / "search.yaml"
    if f.exists():
        import yaml
        _merge(s, yaml.safe_load(f.read_text(encoding="utf-8")) or {})
    _merge(s, overrides or {})
    return s


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v


DEN_BASE = {"인구": "인구", "인구수": "인구", "총인구": "인구", "총인구수": "인구", "전체인구": "인구", "주민등록인구": "인구",
            "사람": "인구", "사람수": "인구", "가구": "가구", "가구수": "가구", "일반가구": "가구", "총가구": "가구",
            "총가구수": "가구", "전체가구": "가구", "주택": "주택", "주택수": "주택", "총주택": "주택", "총주택수": "주택",
            "세대": "세대", "세대수": "세대"}


def _is_sido_key(key):
    from backend.rag.ingestion.normalize import SIDO_ALIAS
    return bool(SIDO_ALIAS.get(key))


def den_base(lex_text, role=None):
    """분모로 볼 하위 질의인가 → 기준 말('인구'·'가구'·'주택'·'세대') 또는 None"""
    keys = [norm(t) for t in str(lex_text or "").split() if norm(t) and not norm(t).endswith("별")]
    if keys and all(k in DEN_BASE for k in keys):
        return DEN_BASE[keys[0]]
    if role == "분모" and keys:
        return next((DEN_BASE[k] for k in keys if k in DEN_BASE), None)
    return None


class TableSearch:
    def __init__(self, corpus, name="search", embedder=None, settings=None, facets_source="auto", log=None,
                 llm_rerank=None, chat_fn=None):
        self.name, self.corpus, self.s = name, corpus, load_settings(settings)
        self.llm = self.s["llm_rerank"].get("enabled") if llm_rerank is None else bool(llm_rerank)
        self.chat_fn = chat_fn
        self.docs = corpus.docs()
        self.docs_by_id = {d.id: d for d in self.docs}
        self.facets = build_facets(self.docs, facets_source, log)
        from backend.rag.search.index import dense_doc_views, group_name, parse_docs
        groups, self.dense_rw = parse_docs(self.s.get("dense_docs"))
        groups_in = None
        if embedder is not None:
            texts = dense_doc_views(corpus, self.s.get("dense_docs"), self.s.get("dense_cards"), self.s.get("kos14_cards"),
                                    log, facets=self.facets)
            groups_in = [(group_name(g), [(v, texts[v]) for v in g]) for g in groups]
            for g in groups_in[1:]:  # 둘째 채널부터: 가중치가 없으면 dense_extra_weight
                self.s["weights"].setdefault(f"q_dense_{g[0]}", float(self.s.get("dense_extra_weight", 1.0)))
        self.okf = {"enabled": bool(self.s["okf"].get("enabled", True)), "build": None, "n_alias": 0, "n_tables": 0}
        aliases = None
        if self.okf["enabled"]:
            from backend.rag.search.okf_terms import table_aliases
            al = table_aliases()
            aliases = al["by_tbl"] or None
            self.okf.update(build=al["build"], n_alias=al["n_alias"], n_tables=al["n_tables"])
        self.ch = Channels(corpus, self.facets, embedder, log, groups_in, aliases,
                           float(self.s["okf"].get("value_weight", 0.9)))
        if log and self.okf["build"]:
            log(f"[search] OKF 빌드 {self.okf['build']} · 별칭 {self.okf['n_alias']}개 → 표 {self.okf['n_tables']}개")
        from backend.rag.search.siblings import SiblingResolver
        sb = self.s["siblings"]
        self.sib = SiblingResolver(self.facets, sb.get("margin", 0.75), sb.get("max_outside", 3))
        self._pos = {d.id: i for i, d in enumerate(self.docs)}
        self.concept_of, self.concepts = {}, []
        if self.s["concepts"].get("enabled", True):
            from backend.rag.search.concepts import load
            try:
                self.concepts = [[t for t in ts if t in self._pos] for ts in load(self.s["concepts"].get("path"))]
            except Exception as e:  # noqa: BLE001  (카탈로그가 깨져 있어도 검색은 계속)
                if log:
                    log(f"[search] 개념 카탈로그를 읽지 못함: {e.__class__.__name__}: {e}")
            self.concepts = [ts for ts in self.concepts if len(ts) >= 2]
            self.concept_of = {t: k for k, ts in enumerate(self.concepts) for t in ts}
        if log:
            log(f"[search] 형제 표 무리 {self.sib.info()} · 개념 {len(self.concepts)}개")
        from backend.rag.search.movement import table_move
        self.move = [table_move(f) for f in self.ch.facets]  # 표마다 이동 범위·방향 (이동 표가 아니면 move=False)
        self.periods = {}
        if (self.s.get("stitch") or {}).get("enabled", True):
            from backend.rag.search.period_groups import build_groups, load_links, summary
            try:
                self.periods = build_groups(self.facets, load_links(self.s["stitch"].get("links")))
            except Exception as e:  # noqa: BLE001  (연결 파일이 깨져 있어도 검색은 계속)
                if log:
                    log(f"[search] 기간 묶음을 만들지 못함: {e.__class__.__name__}: {e}")
            if log and self.periods:
                log(f"[search] 기간 묶음 {summary(self.periods)}")
        self.cfg = {"name": name, "top_k": 10}
        self._qcache, self._lock = {}, threading.Lock()

    def info(self):
        from collections import Counter
        return {"name": self.name, "corpus": self.corpus.signature(), "n_docs": len(self.docs), "settings": self.s,
                "facet_sources": dict(Counter(f.source for f in self.facets.values())),
                "dense": self.ch.dense is not None,
                "dense_docs": [g for g, _ in self.ch.denses] or None, "dense_rw": self.dense_rw, "okf": self.okf}

    def _ce_cards(self, ce):
        """교차 인코더 표 글에 붙일 dense 카드 (doc 이 struct+def 일 때만, 한 번 읽음. 없으면 빈 사전)"""
        if ce.get("doc", "struct+def") != "struct+def":
            return None
        if not hasattr(self, "_ce_cards_cache"):
            try:
                from backend.rag.ingestion.dense_cards import load_cards
                self._ce_cards_cache = load_cards(self.s.get("dense_cards"))
            except Exception:  # noqa: BLE001  (카드가 없으면 struct 만)
                self._ce_cards_cache = {}
        return self._ce_cards_cache

    def dense_scores(self, query, question=None, unit="main"):
        """dense 채널만의 점수 (평가용: 'dense 혼자 정답을 얼마나 찾나') → {"q": [채널마다 배열], "rw": 배열 또는 None}
        q = prepare 와 같은 글 (본 질의·뜻 없는 하위 질의는 원 질문, 그 밖의 하위 질의는 그 문장),
        rw = 본 질의의 검색 문장 (dense_docs 에 +rw 일 때만 — 아니면 임베딩을 더 부르지 않음)"""
        if self.ch.dense is None:
            return {"q": None, "rw": None}
        question = question or query
        main = unit == "main" or self._generic(query)
        text = question if main else query
        q = [np.asarray(r.scores(text), dtype=float) for _, r in self.ch.denses]
        rw = self.ch.dense.scores(query) if self.dense_rw and unit == "main" and query and norm(query) != norm(question) \
            else None
        return {"q": q, "rw": None if rw is None else np.asarray(rw, dtype=float)}

    # ── 가능성 계수 (표 구조 확인) ─────────────────────────────────
    def feasibility(self, qv, linked=()):
        """표마다 '이 질문에 답할 수 있는 구조인가' → (계수 배열, 이유 목록)
          시점   실제 수록 연도와 요청 연도 — 일부만 담아도 후보로 남김
          주기   월·분기·반기를 물었으면 그 주기(또는 더 잘게 나뉜) 자료
          지역   시군구 이름 / 시군구·읍면동 수준 / 시도. '시군구별' 처럼 수준을 물으면 그 수준의 분류
          분류   연령·성별을 물었으면 그 분류가 있는 표
          조사   질문에 조사 이름('인구총조사')이 있으면 그 조사의 표
          간결   질문이 건드리지 않은 분류가 많은 표는 뒤로 (조건이 적은 질문에 '체중·출산순위별' 같은 세부 표가 먼저 오던 문제)"""
        fz = self.s["feas"]
        latest = fz.get("latest_from")
        if latest is None:
            from backend.rag.search.resolve import LATEST_FROM
            latest = LATEST_FROM
        linked = set(linked)
        out = np.ones(self.ch.n)
        why = [None] * self.ch.n
        sub_cycle = {"M", "Q", "H"}
        from backend.rag.search.movement import move_factor
        from backend.rag.search.query import SUB_RE
        # 시군구 이름만 (읍면동·동읍면부 이름이 아니고, 읍면동 수준을 묻지 않음) → 읍면동까지 나뉜 표는 조금 뒤로
        finer = bool(qv.subs) and qv.axis != "읍면동" and fz.get("geo_finer", 1.0) < 1.0 \
            and all(SUB_RE.match(x) for x in qv.subs)
        for i, f in enumerate(self.ch.facets):
            notes = []
            if qv.years:
                c = f.year_cover(qv.years)
                out[i] *= fz["year_floor"] if c == 0 else fz["year_partial"] + (1 - fz["year_partial"]) * c
                if c < 1:
                    notes.append(f"시점 {round(c, 2)}")
            elif (f.last_year() or 0) < latest:
                out[i] *= fz["stale"]
                notes.append("최신 자료 없음")
            if qv.cycle:
                exact = bool(qv.cycle & f.cycles)
                ok = exact or ("Q" in qv.cycle and "M" in f.cycles) or ("H" in qv.cycle and (f.cycles & sub_cycle))
                if not ok:
                    out[i] *= fz["cycle_miss"]
                    notes.append("주기 없음")
                elif not exact and fz.get("cycle_derived", 1.0) < 1.0:
                    out[i] *= fz["cycle_derived"]
                    notes.append("주기 계산")
            if qv.move:
                fac, note = move_factor(qv.move, self.move[i], fz, regional=bool(qv.sido or qv.subs))
                if note:
                    out[i] *= fac
                    notes.append(note)
            if qv.subs:
                named = [s for s in qv.subs if s in f.regions]
                if len(named) == len(qv.subs):
                    out[i] *= fz["sub_named"]
                elif not f.regions_full and (f.geo & {"시군구", "읍면동"}) and not all(s in URBAN for s in qv.subs):
                    out[i] *= fz["sub_level"]  # 이름은 모르지만 그 수준의 분류가 있음 (메타 프로필)
                else:
                    out[i] *= fz["sub_miss"]
                    notes.append("지역 없음")
                if finer and "읍면동" in f.geo:
                    out[i] *= fz["geo_finer"]
                    notes.append("읍면동까지 나뉨")
            elif qv.sido and not all(s in f.sido for s in qv.sido):
                out[i] *= fz["sido_miss"]
                notes.append("시도 없음")
            if qv.axis == "지역":
                if not f.geo:
                    out[i] *= fz["axis_miss"]
                    notes.append("지역 분류 없음")
            elif qv.axis and qv.axis not in f.geo:
                out[i] *= fz["axis_miss"]
                notes.append(f"{qv.axis} 수준 없음")
            if qv.want_age and not f.has_age:
                out[i] *= fz["age_miss"]
                notes.append("연령 분류 없음")
            if qv.want_sex and not f.has_sex:
                out[i] *= fz["sex_miss"]
                notes.append("성별 분류 없음")
            sv = norm(f.survey_nm)
            if len(sv) >= 4 and (sv in qv.link or (len(sv) >= 6 and sv[:4] in qv.link)):
                out[i] *= fz["survey_hit"]
            extra = 0
            for kind, keys in self.ch.dim_keys[i]:
                used = (kind == "ages" and qv.want_age) or (kind == "sex" and qv.want_sex) \
                    or (kind == "cohort" and qv.cohort) or bool(keys & linked) or kind == "scenario"
                extra += not used
            if extra:
                out[i] *= max(fz["extra_dim_floor"], 1.0 / (1.0 + fz["extra_dim"] * extra))
                notes.append(f"안 쓰는 분류 {extra}")
            why[i] = notes
        return out, why

    # ── 검색 ───────────────────────────────────────────────────────
    def _view(self, question, filters, today):
        key = (question, repr(sorted((filters or {}).items(), key=str)), str(today))
        with self._lock:
            if key not in self._qcache:
                if len(self._qcache) > 2000:
                    self._qcache.clear()
                self._qcache[key] = parse_question(question, filters, today, self.ch.region_dict)
            return self._qcache[key]

    def _generic(self, text):
        t = " ".join(str(text or "").split())
        return not t or t in self.s["generic_units"] or len(norm(t)) <= 1

    def prepare(self, query, filters=None, question=None, unit="main", today=None):
        """채널 점수·순위와 가능성 계수 (가중치와 무관한 부분 — tune 이 한 번만 계산해 다시 씀)"""
        question = question or query
        qv = self._view(question, filters, today)
        role = (filters or {}).get("역할")
        den = None
        if unit != "main" and self.s["roles"].get("enabled", True):
            den = den_base(parse_question(query, None, today, self.ch.region_dict).lex, role)
        main = unit == "main" or (self._generic(query) and not den)  # 뜻 없는 하위 질의('비율')는 본 질의처럼 검색
        lists, found = {}, {}
        base, found["q"] = self.ch.score(qv.lex, qv.link, bool(qv.cohort), question)
        if main:
            lists.update({f"q_{c}": v for c, v in base.items()})
            if query and norm(query) != norm(question):
                rv = parse_question(query, None, today, self.ch.region_dict)
                rw, found["rw"] = self.ch.score(rv.lex, rv.link, False, query if self.dense_rw else None)
                lists.update({f"rw_{c}": v for c, v in rw.items()})
        else:
            uv = parse_question(query, None, today, self.ch.region_dict)
            us, found["q"] = self.ch.score(uv.lex, uv.link, bool(qv.cohort), query)
            lists.update({f"q_{c}": v for c, v in us.items()})
            lists.update({f"ctx_{c}": v for c, v in base.items()})
        depth = self.s["depth"]
        rk = {n: ranks(sc, depth, floor=-1e9 if "dense" in n else 0.0) for n, sc in lists.items()}
        feas, why = self.feasibility(qv, [k for ks in found.values() for k in ks])
        # 조건 누락은 질문(단위 문장)에 실제로 쓴 말로만 — 일상어 사전이 더한 말('남자가' → '자가' → 자기집)은 빼고
        core = (qv.link if main else uv.link).split("|", 1)[0]
        feas, why = self._conditions(feas, why, self.ch.value.link(core), filters)
        if den:
            feas, why = self._denominator(feas, why, den, question, filters, today)
        return {"scores": lists, "ranks": rk, "feas": feas, "why": why, "qv": qv, "found": found, "role": "분모" if den else role}

    def specific_terms(self, keys, filters=None):
        """질문의 드문 표현 → {표현: 그 말을 가진 표 번호 집합}. 값 사전 표현(keys) 과 filters 의 원문표현·조건 값 중,
        그 말을 항목·분류 값·표 이름에 가진 표가 cond_df 개 이하인 3자 이상의 말
        (지역·합계·연령·성별 값은 뺌 — 다른 계수가 맡음)"""
        fz = self.s["feas"]
        table, dfmax = self.ch.value.table, int(fz.get("cond_df", 8))
        if not hasattr(self, "_titles"):
            self._titles = [norm(f.tbl_nm) for f in self.ch.facets]
        cand = list(keys)
        for k in ("원문표현", "조건"):
            for v in (filters or {}).get(k) or []:
                n = norm(v)
                cand += [n] + list(self.ch.value.link(n))
        from backend.rag.search.facets import AGE_NAME, SEX_NAME
        regions = self.ch.region_dict or set()
        out = {}
        for key in dict.fromkeys(cand):
            if len(key) < 3 or key in TOTALS or key in regions or key.isdigit() or AGE_NAME.search(key) \
                    or SEX_NAME.search(key) or _is_sido_key(key):
                continue
            hold = set(table.get(key) or ()) | {i for i, t in enumerate(self._titles) if key in t}
            if hold and len(hold) <= dfmax:
                out[key] = hold
        return out

    def _conditions(self, feas, why, keys, filters):
        """조건 누락 감점 — 드문 표현을 가진 표와 같은 조사인데 그 말이 없는 표 (조사가 다른 표는 그대로:
        재작성·바꿔 말하기로 우연히 들어온 말이 다른 조사의 정답 표를 깎지 않게)"""
        fz = self.s["feas"]
        miss = float(fz.get("cond_miss", 1.0))
        if miss >= 1.0:
            return feas, why
        terms = self.specific_terms(keys, filters)
        if not terms:
            return feas, why
        feas = feas.copy()
        floor = float(fz.get("cond_floor", 0.0))
        lost = {}
        for key, hold in terms.items():
            surveys = {norm(self.ch.facets[i].survey_nm) for i in hold} - {""}
            for i, f in enumerate(self.ch.facets):
                if i not in hold and norm(f.survey_nm) in surveys:
                    lost.setdefault(i, []).append(key)
        for i, ks in lost.items():
            feas[i] *= max(floor, miss ** len(ks))
            why[i] = list(why[i] or []) + [f"조건 없음({', '.join(ks)})"]
        return feas, why

    def _main_survey(self, question, filters, today):
        """본 질의 1위 표의 조사명 (분모 단위가 같은 조사의 인구 표를 고르게). 질문마다 한 번"""
        key = ("main_survey", question, repr(sorted((filters or {}).items(), key=str)), str(today))
        with self._lock:
            if key in self._qcache:
                return self._qcache[key]
        prep = self.prepare(question, filters, question, "main", today)
        final, _, order = self.fuse(prep)
        sv = norm(self.ch.facets[order[0]].survey_nm) if len(order) and final[order[0]] > 0 else ""
        with self._lock:
            self._qcache[key] = sv
        return sv

    def _denominator(self, feas, why, base, question, filters, today):
        rz = self.s["roles"]
        sv = self._main_survey(question, filters, today)
        feas = feas.copy()
        for i, f in enumerate(self.ch.facets):
            has = base in norm(f.tbl_nm) or any(base in norm(it) for it in f.items[:30])
            fac = 1.0 if has else rz["den_miss"]
            fac *= max(rz["den_dim_floor"], 1.0 / (1.0 + rz["den_dim"] * len(f.dims)))
            if sv and norm(f.survey_nm) == sv:
                fac *= rz["den_survey"]
            feas[i] *= fac
            why[i] = list(why[i] or []) + [f"분모({base})" + ("" if has else " 말 없음")]
        return feas, why

    def fuse(self, prep, weights=None, rrf_k=None):
        """가중 RRF × 가능성 계수 → (최종 점수, 계수 곱하기 전 점수, 순서)"""
        w, k = weights or self.s["weights"], rrf_k or self.s["rrf_k"]
        fused = np.zeros(self.ch.n)
        for name, r in prep["ranks"].items():
            wt = float(w.get(name, 0))
            if wt:
                fused += np.where(r > 0, wt / (k + r), 0.0)
        final = fused * prep["feas"]
        return final, fused, np.lexsort((-prep["scores"]["q_lex"], -final))

    def search(self, query, filters=None, top_k=None, tracer=None, question=None, unit="main", today=None):
        t0 = time.time()
        top_k = int(top_k or self.cfg["top_k"])
        question = question or query
        prep = self.prepare(query, filters, question, unit, today)
        qv, lists, rk, feas, why = prep["qv"], prep["scores"], prep["ranks"], prep["feas"], prep["why"]
        final, fused, order = self.fuse(prep)
        pool_ids = [self.docs[i].id for i in np.argsort(-fused, kind="stable")[:50] if fused[i] > 0]
        used = {n for n in rk if float(self.s["weights"].get(n, 0))}
        lr, sb = self.s["llm_rerank"], self.s["siblings"]
        sex_text = question if unit == "main" or self._generic(query) else query  # 하위 질의는 그 문장의 성별로
        role = prep.get("role")
        use_llm = bool(self.llm) and role not in set(lr.get("skip_roles") or [])
        ce = self.s.get("ce_rerank") or {}
        use_ce = bool(ce.get("enabled")) and role not in set(ce.get("skip_roles") or [])
        n_head = max(top_k, int(lr.get("top_n", 12)) + int(lr.get("add_siblings", 0))) if use_llm else top_k
        if use_ce:
            n_head = max(n_head, int(ce.get("top_n", 20)))
        ids = [self.docs[i].id for i in order[:max(n_head, int(sb.get("window", 12))) + 20] if final[i] > 0]
        sib_notes = {}
        if sb.get("enabled", True):  # 형제 표 해소
            allowed = {self.docs[i].id for i in np.nonzero(final > 0)[0]}
            ids, sib_notes = self.sib.resolve(ids, qv, sex_text, filters, int(sb.get("window", 12)), allowed)
        n_add = int(lr.get("add_siblings", 0)) + (int(self.s["concepts"].get("add", 0)) if self.concepts else 0)
        if use_llm and n_add:  # LLM 이 형제·같은 개념 표를 나란히 보게 상위 top_n 뒤에 붙임
            ids = self._with_siblings(ids, int(lr.get("top_n", 12)), int(lr.get("add_siblings", 0)), final,
                                      int(self.s["concepts"].get("add", 0)))
            n_head = max(top_k, int(lr.get("top_n", 12)) + n_add)

        def hit(rnk, tid):
            i = self._pos[tid]
            d = self.docs[i]
            h = {"rank": rnk, "tbl_id": d.id, "tbl_nm": d.meta.get("tbl_nm", ""), "survey_nm": d.meta.get("survey_nm", ""),
                 "score": round(float(final[i]), 5), "dense": None, "feas": round(float(feas[i]), 3),
                 "bm25_rank": int(rk["q_lex"][i]) or None, "bm25": round(float(lists["q_lex"][i]), 3),
                 "stages": {n: {"rank": int(rk[n][i]), "score": round(float(lists[n][i]), 4)} for n in sorted(used) if rk[n][i]},
                 "feas_notes": why[i]}
            if "q_dense" in lists:
                h["dense"] = round(float(lists["q_dense"][i]), 4)
            if tid in sib_notes:
                h["stages"]["sibling"] = sib_notes[tid]
            return h

        hits = [hit(r, t) for r, t in enumerate(ids[:n_head], 1)]
        llm_note = None
        main_like = unit == "main" or (self._generic(query) and role != "분모")
        if use_ce and hits:  # (선택) 교차 인코더 재정렬 → 형제 무리 안의 선택은 좌표 규칙이 마지막으로
            from backend.rag.search.ce_rerank import rerank as ce_rerank
            hits, ce_note = ce_rerank(question if main_like else query, hits, self.facets, ce, self._ce_cards(ce),
                                      getattr(self, "ce_score_fn", None))
            llm_note = ce_note
            if sb.get("enabled", True):
                by = {h["tbl_id"]: h for h in hits}
                again, more = self.sib.resolve([h["tbl_id"] for h in hits], qv, sex_text, filters, len(hits), set())
                hits = [dict(by[t], rank=r) for r, t in enumerate(again, 1)]
                for h in hits:
                    if h["tbl_id"] in more:
                        h["stages"] = {**h.get("stages", {}), "sibling_after_ce": more[h["tbl_id"]]}
        if self.llm and not use_llm:
            llm_note = f"건너뜀 (역할 {role})"
        if use_llm and hits:  # (선택) LLM 재정렬 — 상위 top_n 을 표 구조 요약으로 다시 줄 세움
            from backend.rag.search.llm_rerank import rerank
            target, context = (question, None) if main_like else (query, question)
            n_rr = len(hits) if n_add else lr.get("top_n", 12)
            okf_notes = None
            if lr.get("okf"):
                from backend.rag.search.okf_terms import rerank_notes
                okf_notes = rerank_notes([h["tbl_id"] for h in hits[:n_rr]], question, query)
            hits, llm_note = rerank(target, qv, hits, self.facets, n_rr, self.chat_fn, sib=self.sib,
                                    concept_of=self.concept_of, context=context, role=role, okf_notes=okf_notes,
                                    keep_if_unsure=bool(lr.get("keep_if_unsure")), traits=bool(lr.get("traits")),
                                    traits_own_defs=not lr.get("okf"), thinking=lr.get("thinking"),
                                    think_tokens=lr.get("think_tokens"))
            from backend.rag.search.llm_rerank import UNSURE
            kept = bool(llm_note) and llm_note.endswith(UNSURE)
            # 불확실 → 원래 순서 그대로 (형제 규칙을 다시 돌리면 top_n 뒤에 끼운 형제가 정답 자리를 차지 — 11/24 keep 버그)
            if sb.get("enabled", True) and not kept:  # 무리 안의 선택은 좌표 규칙이 마지막으로 (LLM 은 무리 사이 순서)
                by = {h["tbl_id"]: h for h in hits}
                again, more = self.sib.resolve([h["tbl_id"] for h in hits], qv, sex_text, filters, len(hits), set())
                hits = [dict(by[t], rank=r) for r, t in enumerate(again, 1)]
                for h in hits:
                    if h["tbl_id"] in more:
                        h["stages"] = {**h.get("stages", {}), "sibling_after_llm": more[h["tbl_id"]]}
        hits = hits[:top_k]
        if filters is not None:
            self._attach_conditions(hits, filters)
        self._attach_periods(hits, qv.years)
        return {"config": self.name, "query": query, "search_query": qv.lex, "question": question, "filters": filters,
                "top_k": top_k, "hits": hits, "pool_ids": pool_ids, "seconds": round(time.time() - t0, 3),
                "parsed": {"years": qv.years, "cohort": qv.cohort, "cycle": sorted(qv.cycle), "sido": qv.sido,
                           "subs": qv.subs, "added": qv.added, "linked": prep["found"], "axis": qv.axis,
                           "want_age": qv.want_age, "want_sex": qv.want_sex}, "llm": llm_note,
                "siblings": sib_notes, "trace": []}

    def _with_siblings(self, ids, top_n, extra, final, extra_concept=0):
        """상위 5개 안의 무리마다 빠진 형제(모두 extra 개까지), 다음 같은 개념(같은 값을 주는 표, extra_concept 개까지)을
        상위 top_n '뒤' 에 붙임 — 앞 순위는 그대로 두고 LLM 이 나란히 보고 고르게. 계수가 0 인 표는 빼고"""
        head, extras = list(ids[:top_n]), []

        def take(t):
            if t not in head and t not in extras and final[self._pos[t]] > 0:
                extras.append(t)
                return True
            return False
        added = 0
        for tid in head[:5]:
            for t in self.sib.siblings(tid):
                if added >= extra:
                    break
                added += take(t)
        added = 0
        for tid in head[:5]:
            k = self.concept_of.get(tid)
            if k is None:
                continue
            for t in sorted(self.concepts[k], key=lambda x: -final[self._pos[x]]):
                if added >= extra_concept:
                    break
                added += take(t)
        return head + extras + [t for t in ids[top_n:] if t not in extras]

    def _attach_periods(self, hits, want):
        """요청 연도가 있으면 결과마다 있는/없는 연도 + 이어붙이기 계획 (표시·View 용 — 순위에는 쓰지 않음)"""
        if not want:
            return
        from backend.rag.search.period_groups import facet_years, stitch_plan, year_split
        for h in hits:
            f = self.facets.get(h["tbl_id"])
            h["years_have"], h["years_missing"] = year_split(facet_years(f) if f else None, want)
            if self.periods:
                h["stitch"] = stitch_plan(h["tbl_id"], want, self.periods)

    def _attach_conditions(self, hits, filters):
        """View 단계·화면이 읽는 unmet·cover·cost 를 붙임 (표시용 — 순위에는 쓰지 않음)"""
        try:
            from backend.rag.search.resolve import cost, period_cover, profile, unmet
        except Exception:  # noqa: BLE001
            return
        for h in hits:
            try:
                p = self.docs_by_id[h["tbl_id"]].meta.get("profile") or profile(h["tbl_id"])
            except Exception:  # noqa: BLE001  (메타 프로필 파일이 없는 환경)
                p = None
            if p:
                h["unmet"] = unmet(p, filters)
                h["cover"] = round(period_cover(p, filters), 2)
                h["cost"] = round(cost(h["unmet"], h["cover"]), 3)

    def search_compat(self, query, top_k=10, filters=None, question=None, unit="main"):
        keep = ("rank", "tbl_id", "tbl_nm", "survey_nm", "score", "dense", "bm25_rank", "bm25", "unmet", "cover", "cost",
                "years_have", "years_missing", "stitch")
        return [{k: h[k] for k in keep if k in h}
                for h in self.search(query, filters, top_k, question=question, unit=unit)["hits"]]


_cache, _cache_lock = {}, threading.Lock()


def get_search(dense=None, settings=None, log=None, llm_rerank=None) -> TableSearch:
    """dense: hcx(HCX bge-m3) | arctic-ko | bge-m3-ko | ens-ko (로컬, search/embedders.py) | hash(오프라인 확인용) | none.
    비우면 configs/search.yaml 의 dense (기본 hcx)
    llm_rerank: True 면 상위 후보를 LLM 으로 다시 줄 세움 (질의 단위마다 HCX 1회). 비우면 설정값"""
    from backend.rag.search.index import embedder, table_corpus
    st = load_settings(settings)
    dense = dense or st.get("dense", "hcx")
    corpus = table_corpus()
    from backend.rag.search.okf_terms import current_build
    key = (dense, corpus.signature(), repr(settings), llm_rerank, current_build())  # OKF 빌드가 바뀌면 새 검색기
    with _cache_lock:
        if key not in _cache:
            docs = st.get("dense_docs") or "rule"
            ce_on = bool((st.get("ce_rerank") or {}).get("enabled"))
            name = f"search[{dense}" + (f"|{docs}" if docs != "rule" and dense != "none" else "") + "]" \
                + ("+ce" if ce_on else "") + ("+llm" if llm_rerank else "")
            _cache[key] = TableSearch(corpus, name, embedder(dense), settings, log=log, llm_rerank=llm_rerank)
        return _cache[key]


def search_fn(dense=None, **kw):
    """run_query(search_fn=…) 모양: fn(query, top_k, filters=, question=, unit=) → 후보 목록"""
    s = get_search(dense, **kw)

    def fn(query, top_k=10, filters=None, question=None, unit="main"):
        return s.search_compat(query, top_k, filters=filters, question=question, unit=unit)
    return fn
