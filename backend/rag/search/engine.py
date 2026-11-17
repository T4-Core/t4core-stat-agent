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
from backend.rag.search.text import norm

DEFAULTS = {
    "dense": "hcx",  # 1단계부터 BM25 와 함께 (none 이면 어휘 채널만)
    "rrf_k": 20, "depth": 200,
    # 본 질의: 원문(q_*) + 재작성 문장(rw_*). 하위 질의: 그 단위 문장(q_*) + 원문은 약하게(ctx_*)
    # dense 를 어휘 채널보다 크게: 일상어 질문(concept)은 단어가 표와 겹치지 않아 임베딩이 주 신호
    "weights": {"q_value": 1.6, "q_title": 1.4, "q_lex": 1.0, "q_ngram": 0.8, "q_dense": 1.6,
                "rw_lex": 0.7, "rw_value": 0.5, "rw_ngram": 0.3,
                "ctx_value": 0.4, "ctx_lex": 0.3, "ctx_title": 0.4},
    # 가능성 계수 (곱). 시점: 하나도 못 담으면 year_floor, 일부라도 담으면 year_partial + (1 - year_partial) × 담은 비율
    # → 요청 연도를 다 담지 못한 표도 후보로 남고(2005·2025 를 서로 다른 연도판이 나눠 가진 경우), View 가 있는 연도만 줌
    "feas": {"year_floor": 0.12, "year_partial": 0.6, "stale": 0.5, "cycle_miss": 0.4,
             "sub_named": 1.0, "sub_level": 0.85, "sub_miss": 0.25, "sido_miss": 0.45, "axis_miss": 0.4,
             "age_miss": 0.5, "sex_miss": 0.65, "survey_hit": 1.35, "extra_dim": 0.12, "extra_dim_floor": 0.6,
             "latest_from": None},
    "llm_rerank": {"enabled": False, "top_n": 12, "add_siblings": 4},
    # 분모 단위: '인구'·'가구'·'주택' 뿐인 하위 질의(또는 filters.역할 = 분모)는 본 질의를 다시 찾지 않고
    # '그 말이 제목·항목에 있는 단순한 표' 를 찾는다. 본 질의 1위 표와 같은 조사면 더 앞에 (같은 조사·연도·수준의 인구 표)
    "roles": {"enabled": True, "den_miss": 0.35, "den_dim": 0.2, "den_dim_floor": 0.45, "den_survey": 1.5},
    # 개념 카탈로그 (concepts.py → <CSV 값 사전>/concepts.json): 같은 값을 주는 표 묶음.
    # 무리 안의 '바꿔치기' 에는 쓰지 않음 (같은 값은 합계 칸에서만 확인된 경우가 많음) — LLM 후보에 끌어오고 카드에 표시
    "concepts": {"enabled": True, "path": None, "add": 3},
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
        self.ch = Channels(corpus, self.facets, embedder, log)
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
        self.cfg = {"name": name, "top_k": 10}
        self._qcache, self._lock = {}, threading.Lock()

    def info(self):
        from collections import Counter
        return {"name": self.name, "corpus": self.corpus.signature(), "n_docs": len(self.docs), "settings": self.s,
                "facet_sources": dict(Counter(f.source for f in self.facets.values())),
                "dense": self.ch.dense is not None}

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
                ok = bool(qv.cycle & f.cycles) or ("Q" in qv.cycle and "M" in f.cycles) \
                    or ("H" in qv.cycle and (f.cycles & sub_cycle))
                if not ok:
                    out[i] *= fz["cycle_miss"]
                    notes.append("주기 없음")
            if qv.subs:
                named = [s for s in qv.subs if s in f.regions]
                if len(named) == len(qv.subs):
                    out[i] *= fz["sub_named"]
                elif not f.regions_full and (f.geo & {"시군구", "읍면동"}) and not all(s in URBAN for s in qv.subs):
                    out[i] *= fz["sub_level"]  # 이름은 모르지만 그 수준의 분류가 있음 (메타 프로필)
                else:
                    out[i] *= fz["sub_miss"]
                    notes.append("지역 없음")
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
                rw, found["rw"] = self.ch.score(rv.lex, rv.link, False)
                lists.update({f"rw_{c}": v for c, v in rw.items()})
        else:
            uv = parse_question(query, None, today, self.ch.region_dict)
            us, found["q"] = self.ch.score(uv.lex, uv.link, bool(qv.cohort), query)
            lists.update({f"q_{c}": v for c, v in us.items()})
            lists.update({f"ctx_{c}": v for c, v in base.items()})
        depth = self.s["depth"]
        rk = {n: ranks(sc, depth, floor=-1e9 if n.endswith("dense") else 0.0) for n, sc in lists.items()}
        feas, why = self.feasibility(qv, [k for ks in found.values() for k in ks])
        if den:
            feas, why = self._denominator(feas, why, den, question, filters, today)
        return {"scores": lists, "ranks": rk, "feas": feas, "why": why, "qv": qv, "found": found, "role": "분모" if den else role}

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
        n_head = max(top_k, int(lr.get("top_n", 12)) + int(lr.get("add_siblings", 0))) if self.llm else top_k
        ids = [self.docs[i].id for i in order[:max(n_head, int(sb.get("window", 12))) + 20] if final[i] > 0]
        sib_notes = {}
        if sb.get("enabled", True):  # 형제 표 해소
            allowed = {self.docs[i].id for i in np.nonzero(final > 0)[0]}
            ids, sib_notes = self.sib.resolve(ids, qv, sex_text, filters, int(sb.get("window", 12)), allowed)
        n_add = int(lr.get("add_siblings", 0)) + (int(self.s["concepts"].get("add", 0)) if self.concepts else 0)
        if self.llm and n_add:  # LLM 이 형제·같은 개념 표를 나란히 보게 끼움
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
        if self.llm and hits:  # (선택) LLM 재정렬 — 상위 top_n 을 표 구조 요약으로 다시 줄 세움
            from backend.rag.search.llm_rerank import rerank
            hits, llm_note = rerank(question, qv, hits, self.facets, len(hits) if n_add else lr.get("top_n", 12),
                                    self.chat_fn, sib=self.sib, concept_of=self.concept_of)
            if sb.get("enabled", True):  # 무리 안의 선택은 좌표 규칙이 마지막으로 (LLM 은 무리 사이 순서)
                by = {h["tbl_id"]: h for h in hits}
                again, more = self.sib.resolve([h["tbl_id"] for h in hits], qv, sex_text, filters, len(hits), set())
                hits = [dict(by[t], rank=r) for r, t in enumerate(again, 1)]
                for h in hits:
                    if h["tbl_id"] in more:
                        h["stages"] = {**h.get("stages", {}), "sibling_after_llm": more[h["tbl_id"]]}
        hits = hits[:top_k]
        if filters is not None:
            self._attach_conditions(hits, filters)
        return {"config": self.name, "query": query, "search_query": qv.lex, "question": question, "filters": filters,
                "top_k": top_k, "hits": hits, "pool_ids": pool_ids, "seconds": round(time.time() - t0, 3),
                "parsed": {"years": qv.years, "cohort": qv.cohort, "cycle": sorted(qv.cycle), "sido": qv.sido,
                           "subs": qv.subs, "added": qv.added, "linked": prep["found"], "axis": qv.axis,
                           "want_age": qv.want_age, "want_sex": qv.want_sex}, "llm": llm_note,
                "siblings": sib_notes, "trace": []}

    def _with_siblings(self, ids, top_n, extra, final, extra_concept=0):
        """상위 5개 안의 무리마다 빠진 형제를 그 무리 바로 뒤에 (모두 extra 개까지, 계수가 0 인 표는 빼고).
        다음 같은 개념(같은 값을 주는 표)도 extra_concept 개까지 — 가장 점수가 높은 것부터"""
        head, added = list(ids[:top_n]), 0
        for tid in list(head[:5]):
            for t in self.sib.siblings(tid):
                if added >= extra:
                    break
                if t not in head and final[self._pos[t]] > 0:
                    head.insert(head.index(tid) + 1, t)
                    added += 1
        added = 0
        for tid in list(head[:5]):
            k = self.concept_of.get(tid)
            if k is None:
                continue
            for t in sorted(self.concepts[k], key=lambda x: -final[self._pos[x]]):
                if added >= extra_concept:
                    break
                if t not in head and final[self._pos[t]] > 0:
                    head.insert(head.index(tid) + 1, t)
                    added += 1
        return head + [t for t in ids[top_n:] if t not in head]

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
        keep = ("rank", "tbl_id", "tbl_nm", "survey_nm", "score", "dense", "bm25_rank", "bm25", "unmet", "cover", "cost")
        return [{k: h[k] for k in keep if k in h}
                for h in self.search(query, filters, top_k, question=question, unit=unit)["hits"]]


_cache, _cache_lock = {}, threading.Lock()


def get_search(dense=None, settings=None, log=None, llm_rerank=None) -> TableSearch:
    """dense: hcx(HCX bge-m3) | hash(오프라인 확인용) | none. 비우면 configs/search.yaml 의 dense (기본 hcx)
    llm_rerank: True 면 상위 후보를 LLM 으로 다시 줄 세움 (질의 단위마다 HCX 1회). 비우면 설정값"""
    from backend.rag.search.index import embedder, table_corpus
    st = load_settings(settings)
    dense = dense or st.get("dense", "hcx")
    corpus = table_corpus()
    key = (dense, corpus.signature(), repr(settings), llm_rerank)
    with _cache_lock:
        if key not in _cache:
            name = f"search[{dense}]" + ("+llm" if llm_rerank else "")
            _cache[key] = TableSearch(corpus, name, embedder(dense), settings, log=log, llm_rerank=llm_rerank)
        return _cache[key]


def search_fn(dense=None, **kw):
    """run_query(search_fn=…) 모양: fn(query, top_k, filters=, question=, unit=) → 후보 목록"""
    s = get_search(dense, **kw)

    def fn(query, top_k=10, filters=None, question=None, unit="main"):
        return s.search_compat(query, top_k, filters=filters, question=question, unit=unit)
    return fn
