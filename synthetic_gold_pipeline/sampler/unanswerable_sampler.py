"""답변 불가 / Abstention 레코드 생성 (최종 데이터셋의 약 10~15%).

  CONTEXT_UNANSWERABLE  채택된 레코드에서 필수 근거 그룹 하나를 문맥에서 뺌 (전체 코퍼스에는 정답이 있음)
  CORPUS_UNANSWERABLE   수집된 전체 스냅샷(모든 표의 항목·시점)에 없는 시점 — 검증 범위를 기록
  AMBIGUOUS             같은 이름의 지역 코드가 여러 개(예: 중구) 또는 시점 누락으로 정답이 하나가 아님 → 되묻기 기대
  OUT_OF_SCOPE          수집 범위 밖 주제 (카탈로그 표 이름·항목에 키워드 없음을 확인)
  FUTURE_OBSERVATION    오늘 이후 시점의 실측치 (추계표가 있으면 그 사실을 기대 답변에 명시)
질문 문장은 결정론적 템플릿으로 만든다 (LLM 미사용). 수치 정답은 강제하지 않는다.
"""
from __future__ import annotations

import random
import re
from datetime import date

from synthetic_gold_pipeline import __version__
from synthetic_gold_pipeline.agents.reverse_qa_agent import josa, region_short
from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
from synthetic_gold_pipeline.schemas.dataset import (GenerationEval, GoldenRecord, M1Eval, M2Eval, M3Eval, ModuleEval,
                                                      Provenance, RetrievalEval, VerificationMetrics)
from synthetic_gold_pipeline.schemas.metadata import DimensionType, ObservationType
from synthetic_gold_pipeline.schemas.planning import AnswerabilityType, ReasoningType
from synthetic_gold_pipeline.schemas.verification import VerificationStatus
from synthetic_gold_pipeline.tools.units import parse_value
from synthetic_gold_pipeline.utils import now_iso, period_year, stable_hash

TYPES = ["CONTEXT_UNANSWERABLE", "CORPUS_UNANSWERABLE", "AMBIGUOUS", "OUT_OF_SCOPE", "FUTURE_OBSERVATION"]


class UnanswerableBuilder:
    def __init__(self, index: MetadataIndex, snapshot_id: str, cfg: dict | None = None, today: date | None = None,
                 base_seed: int = 42):
        cfg = cfg or {}
        self.index, self.snapshot_id = index, snapshot_id
        self.weights = cfg.get("type_weights", {t: 1.0 for t in TYPES})
        self.topics = cfg.get("out_of_scope_topics", ["아파트 매매가격지수", "코스피 지수", "연평균 기온"])
        self.today = today or date.today()
        self.base_seed = base_seed
        self.scope = index.catalog_scope()

    def _rec(self, kind: str, q1: str, q2: str, answer: str, *, seed: int, sid: str, m1_intent: str, ambiguity: str,
             filters: dict, retrieval_eligible: bool, golden_views=None, golden_tables=None, context_views=None,
             groups=None, base: GoldenRecord | None = None, notes: list[str] | None = None,
             surveys: list[str] | None = None) -> GoldenRecord:
        did = "SU-" + stable_hash({"k": kind, "q": q1, "c": context_views}, 12)
        vm = VerificationMetrics(deterministic_passed=True, numeric_validation_passed=None, unit_validation_passed=None,
                                 statistical_validation_passed=None, ablation_passed=None, semantic_validation_passed=None,
                                 paraphrase_equivalence_passed=None, validation_warnings=notes or [],
                                 verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW, human_review_required=True,
                                 check_states={"answerability_verified": "PASS"})
        return GoldenRecord(
            dataset_id=did, data_snapshot_id=self.snapshot_id, reasoning_type=ReasoningType.UNANSWERABLE_ABSTENTION,
            subtype=kind, hop_type=base.hop_type if base else None, survey_names=surveys or (base.survey_names if base else []),
            answerability_type=AnswerabilityType(kind), difficulty="medium", question_original=q1, question_paraphrased=q2,
            question_ids={"original": f"{did}-O", "paraphrased": f"{did}-P"}, random_seed=seed,
            retrieval_eval=RetrievalEval(golden_view_ids=golden_views or [], golden_table_ids=golden_tables or [],
                                         golden_org_table_ids=list(dict.fromkeys(
                                             self.index.view(v).parent_table_id for v in (golden_views or []))),
                                         required_evidence_groups=groups or {}, retrieval_eligible=retrieval_eligible,
                                         context_view_ids=context_views),
            generation_eval=GenerationEval(exact_numeric_ground_truth=None, reference_answer=answer, reference_answer_text=answer, expected_abstention=True,
                                           abstention_reason=kind),
            module_eval=ModuleEval(M1=M1Eval(expected_intent=m1_intent, expected_filters=filters, ambiguity_handling=ambiguity,
                                             pass_criteria=["근거 없는 수치를 만들지 않음", "답변 불가 사유 또는 되묻기"]),
                                   M2=M2Eval(pass_criteria=["존재하지 않는 좌표의 값을 만들지 않음"]),
                                   M3=M3Eval(expected_view_ids=golden_views or [], expected_final_context=context_views or [],
                                             pass_criteria=["검색 결과가 불충분함을 판단"])),
            verification_metrics=vm,
            provenance=Provenance(sample_id=sid, attempt_index=-1, created_at=now_iso(), pipeline_version=__version__,
                                  llm_provider="none(template)", source_record_id=base.dataset_id if base else None),
            fact_signature=f"un_{stable_hash({'k': kind, 'f': filters}, 16)}|{stable_hash(q1, 12)}")

    # ── 유형별 ──
    def context_unanswerable(self, base: GoldenRecord, rng: random.Random, i: int):
        groups = base.retrieval_eval.required_evidence_groups
        if len(groups) < 2:
            return None
        gid = rng.choice(sorted(groups))
        removed = set(groups[gid].acceptable_view_ids)
        ctx = [v for v in base.retrieval_eval.golden_view_ids if v not in removed]
        ans = (f"제공된 자료만으로는 답할 수 없습니다. 필요한 근거 중 '{groups[gid].description}' 자료가 문맥에 없습니다. "
               f"(전체 통계 자료에는 해당 통계표가 있을 수 있으므로 추가 검색이 필요합니다.)")
        return self._rec("CONTEXT_UNANSWERABLE", base.question_original, base.question_paraphrased, ans,
                         seed=base.random_seed, sid=f"U{i:05d}", m1_intent=base.module_eval.M1.expected_intent,
                         ambiguity="NONE", filters=base.module_eval.M1.expected_filters, retrieval_eligible=True,
                         golden_views=base.retrieval_eval.golden_view_ids, golden_tables=base.retrieval_eval.golden_table_ids,
                         context_views=ctx, groups={k: v.model_dump() for k, v in groups.items()}, base=base,
                         notes=[f"문맥에서 제거한 근거 그룹 {gid}: {sorted(removed)}", "전체 코퍼스에는 정답 존재 (원 레코드 참조)"])

    def corpus_unanswerable(self, rng: random.Random, i: int):
        items = [(k, v) for k, v in self.scope["items"].items() if v["periods"]]
        rng.shuffle(items)
        for key, e in items:
            years = sorted({period_year(p) for p in e["periods"] if period_year(p)})
            if not years:
                continue
            y = years[0] - rng.randint(2, 6)
            # 검증: 전체 표 중 같은 항목명(정규화)을 가진 표의 어떤 시점에도 y 가 없음
            hit = [t for t in e["tables"] if any(period_year(p) == y for ps in self.index.tables[t].periods.values() for p in ps)]
            if hit:
                continue
            tbl = self.index.tables[sorted(e["tables"])[0]]
            reg = self._some_region(tbl.parent_table_id, rng)
            name = sorted(e["names"])[0]
            q1 = f"{y}년 {tbl.survey_name} 기준 {reg + '의 ' if reg else ''}{josa(name, '은/는')} 얼마인가요?"
            q2 = f"{y}년에 {region_short(reg) + ' ' if reg else ''}{name} 얼마였어?"
            ans = (f"현재 수집된 통계 자료에는 {y}년 {name} 자료가 없어 답할 수 없습니다. "
                   f"수록 시점은 {years[0]}년~{years[-1]}년입니다.")
            return self._rec("CORPUS_UNANSWERABLE", q1, q2, ans, seed=rng.randrange(10 ** 9), sid=f"U{i:05d}",
                             m1_intent="ABSTAIN: 수록되지 않은 시점", ambiguity="NONE",
                             filters={"periods": [str(y)], "items": [name], "regions": [reg] if reg else []},
                             retrieval_eligible=False, surveys=[tbl.survey_name],
                             notes=[f"검증 범위: 표 {self.scope['n_tables']}개 전체 메타·실제 시점 스캔 (스냅샷 {self.snapshot_id})",
                                    f"같은 항목명 표 {sorted(e['tables'])} 의 수록 연도 {years[0]}~{years[-1]}",
                                    "수집되지 않은 KOSIS 표에는 있을 수 있음 — '수집 스냅샷 기준' 답변 불가"])
        return None

    def _some_region(self, table_id: str, rng) -> str | None:
        t = self.index.tables[table_id]
        d = next((d for d in t.dimension_definitions if d.dim_type == DimensionType.REGION), None)
        if not d:
            return None
        cs = [c for c in t.dimension_codes.get(d.level, []) if not c.is_total]
        names = [c.name for c in cs]
        cs = [c for c in cs if names.count(c.name) == 1]       # 같은 이름이 여러 코드면 모호하므로 제외
        return rng.choice(cs).name if cs else None

    def ambiguous(self, rng: random.Random, i: int):
        for tid in sorted(self.index.tables):
            t = self.index.tables[tid]
            for d in t.dimension_definitions:
                if d.dim_type != DimensionType.REGION or d.code_name_unique:
                    continue
                by_name: dict[str, list] = {}
                for c in t.dimension_codes.get(d.level, []):
                    by_name.setdefault(c.name, []).append(c)
                dup = {n: cs for n, cs in by_name.items() if len(cs) > 1}
                if not dup:
                    continue
                name = sorted(dup)[0]
                cands = dup[name]
                cmap = {c.code: c for c in t.dimension_codes.get(d.level, [])}
                labels = [f"{cmap[c.parent_code].name if c.parent_code in cmap else '상위 미상'} {c.name}({c.code})" for c in cands]
                itm = t.indicator_definitions[0]
                per = sorted({p for ps in t.periods.values() for p in ps})[-1]
                vals = self._values(tid, itm.itm_id, per, d.level, [c.code for c in cands])
                if len({v for v in vals.values() if v is not None}) < 2:
                    continue
                q1 = f"{per}년 {t.survey_name} 「{t.table_title}」에서 {name}의 {josa(itm.itm_nm, '은/는')} 얼마인가요?"
                q2 = f"{per}년 {name} {itm.itm_nm} 알려줘"
                ans = f"'{name}'은(는) 여러 지역에 있어 하나로 정할 수 없습니다: {', '.join(labels)}. 어느 지역인지 알려 주세요."
                return self._rec("AMBIGUOUS", q1, q2, ans, seed=rng.randrange(10 ** 9), sid=f"U{i:05d}",
                                 m1_intent="CLARIFY: 같은 이름의 지역 코드가 여러 개", ambiguity="ASK_CLARIFICATION",
                                 filters={"periods": [per], "regions": [name], "items": [itm.itm_nm],
                                          "candidate_interpretations": labels}, retrieval_eligible=True,
                                 golden_views=[v.view_id for v in self.index.views_of_table(tid) if per in v.available_periods][:3],
                                 golden_tables=[t.tbl_id], surveys=[t.survey_name],
                                 notes=[f"검증: 같은 이름 '{name}' 코드 {[c.code for c in cands]} 의 값이 서로 다름"])
        # 대안: 시점 누락
        for tid in sorted(self.index.tables):
            t = self.index.tables[tid]
            ps = sorted({p for x in t.periods.values() for p in x})
            if len(ps) < 2 or not t.indicator_definitions:
                continue
            reg = self._some_region(tid, rng)
            itm = t.indicator_definitions[0]
            q1 = f"{t.survey_name} 「{t.table_title}」 기준 {reg + '의 ' if reg else ''}{josa(itm.itm_nm, '은/는')} 얼마인가요?"
            q2 = f"{region_short(reg) + ' ' if reg else ''}{itm.itm_nm} 얼마야?"
            ans = f"시점이 지정되지 않았습니다. 이 통계표에는 {ps[0]}~{ps[-1]} 자료가 있으니 어느 시점인지 알려 주세요."
            return self._rec("AMBIGUOUS", q1, q2, ans, seed=rng.randrange(10 ** 9), sid=f"U{i:05d}",
                             m1_intent="CLARIFY: 시점 누락", ambiguity="ASK_CLARIFICATION",
                             filters={"periods": [], "regions": [reg] if reg else [], "items": [itm.itm_nm]},
                             retrieval_eligible=True, golden_tables=[t.tbl_id], surveys=[t.survey_name],
                             notes=["검증: 같은 조건의 시점이 2개 이상"])
        return None

    def _values(self, tid, itm, per, level, codes):
        out = {}
        for v in self.index.views_of_table(tid):
            if per not in v.available_periods or itm not in v.source_coordinates.itm_ids:
                continue
            df = self.index.load_frame(v.view_id)
            for c in codes:
                r = df[(df["ITM_ID"] == itm) & (df["PRD_DE"] == per) & (df[level] == c)]
                if len(r) == 1 and parse_value(r.iloc[0]["DT"]).ok:
                    out[c] = parse_value(r.iloc[0]["DT"]).value
        return out

    def out_of_scope(self, rng: random.Random, i: int):
        topics = list(self.topics)
        rng.shuffle(topics)
        titles = " ".join(self.scope["titles"].values())
        names = " ".join(n for e in self.scope["items"].values() for n in e["names"])
        for tp in topics:
            words = [w for w in re.split(r"\s+", tp) if len(w) >= 2]
            if any(w in titles or w in names for w in words):
                continue
            y = self.today.year - 1
            q1 = f"{y}년 서울특별시의 {josa(tp, '은/는')} 얼마인가요?"
            q2 = f"작년({y}년) 서울 {tp} 어느 정도였어?"
            ans = f"'{tp}'는 현재 서비스가 다루는 통계(수집된 KOSIS 인구 분야 통계표) 범위 밖이라 답할 수 없습니다."
            return self._rec("OUT_OF_SCOPE", q1, q2, ans, seed=rng.randrange(10 ** 9), sid=f"U{i:05d}",
                             m1_intent="ABSTAIN: 서비스 범위 밖", ambiguity="NONE", filters={"topic": tp, "periods": [str(y)]},
                             retrieval_eligible=False,
                             notes=[f"검증: 표 {self.scope['n_tables']}개 제목·항목에 '{tp}' 키워드 없음"])
        return None

    def future_observation(self, rng: random.Random, i: int):
        obs = [t for t in self.index.tables.values() if t.observed_or_projected == ObservationType.OBSERVED and t.indicator_definitions]
        rng.shuffle(obs)
        for t in obs:
            y = self.today.year + rng.randint(1, 4)
            if any(period_year(p) == y for ps in t.periods.values() for p in ps):
                continue
            itm = t.indicator_definitions[0]
            reg = self._some_region(t.parent_table_id, rng)
            proj = [p for p in self.index.tables.values() if p.observed_or_projected == ObservationType.PROJECTED and
                    any(period_year(x) == y for ps in p.periods.values() for x in ps)]
            note = (f" 다만 추계 자료({', '.join(p.table_title for p in proj)})에는 {y}년 전망치가 있으며 이는 실측치가 아닙니다."
                    if proj else "")
            q1 = f"{y}년 {t.survey_name} 기준 {reg + '의 ' if reg else ''}{itm.itm_nm} 실측치는 얼마인가요?"
            q2 = f"{y}년 {region_short(reg) + ' ' if reg else ''}{itm.itm_nm} 실제로 몇이야?"
            ans = f"{y}년은 아직 실측 통계가 공표되지 않은 미래 시점이라 답할 수 없습니다.{note}"
            return self._rec("FUTURE_OBSERVATION", q1, q2, ans, seed=rng.randrange(10 ** 9), sid=f"U{i:05d}",
                             m1_intent="ABSTAIN: 미래 실측 시점", ambiguity="NONE",
                             filters={"periods": [str(y)], "items": [itm.itm_nm], "regions": [reg] if reg else []},
                             retrieval_eligible=False, surveys=[t.survey_name],
                             notes=[f"기준일 {self.today.isoformat()}", f"추계표 존재: {[p.parent_table_id for p in proj]}"])
        return None

    def build(self, n: int, base_records: list[GoldenRecord], start_index: int = 0,
              exclude_ids: set[str] | None = None) -> list[GoldenRecord]:
        rng = random.Random(self.base_seed * 7 + 3)
        out, seen = [], set(exclude_ids or ())
        order = []
        w = [float(self.weights.get(t, 1.0)) for t in TYPES]
        i, tries = start_index, 0
        while len(out) < n and tries < n * 20:
            tries += 1
            kind = rng.choices(TYPES, weights=w, k=1)[0]
            if kind == "CONTEXT_UNANSWERABLE":
                cands = [b for b in base_records if len(b.retrieval_eval.required_evidence_groups) >= 2]
                r = self.context_unanswerable(rng.choice(cands), rng, i) if cands else None
            else:
                r = getattr(self, kind.lower())(rng, i)
            i += 1
            if r is None or r.dataset_id in seen:
                order.append((kind, "skip"))
                continue
            seen.add(r.dataset_id)
            out.append(r)
        return out
