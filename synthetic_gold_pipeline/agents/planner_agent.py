"""PlannerAgent — 샘플된 View 들로 통계 분석 시나리오와 실행 가능한 구조화 연산 계획을 만든다.

- 수치를 계산하거나 답을 만들지 않는다. 결과는 OperationPlan(Pydantic) 하나.
- 전체 RAW 대신 ViewCard(스키마·항목·코드 후보·시점·단위·모집단·계층·샘플 3행)와 공통 Join Key 의 실제 값만 받는다.
- 고른 코드·항목이 실제로 있는지는 Calculation Tool · Statistical Validation Tool 이 따로 검사한다.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from typing import Any

from synthetic_gold_pipeline.agents.llm_client import BaseLLMClient, MockLLMClient
from synthetic_gold_pipeline.sampler.compatibility_graph import CompatibilityGraph
from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
from synthetic_gold_pipeline.schemas.planning import OperationPlan, PlannerContext, SampledCluster

TASK = "planner"

SYSTEM_PROMPT = """당신은 국가통계(KOSIS) 표를 결합하는 통계 분석 설계자입니다.
주어진 View 메타데이터만 보고, 계산 도구(Calculation Tool)가 그대로 실행할 '구조화된 연산 계획' JSON 하나를 만듭니다.

[절대 규칙]
1. 제공된 View 와 메타데이터에 실제로 있는 View ID · 항목 코드(itm_id) · 분류 레벨(C1~C8) · 분류 코드 · 시점(prd_de)만 사용한다.
2. 연산 결과 수치를 직접 계산하거나 추측하지 않는다. 계획 JSON 에 결과 숫자를 쓰지 않는다.
3. 단위와 모집단이 호환되지 않으면 연산 계획을 만들지 않는다.
4. 서로 다른 주기(월·분기·연)의 시점을 같은 기간으로 간주하지 않는다. PRD_DE 문자열이 같아도 주기가 다르면 다른 기간이다.
5. 총계·소계와 하위 분류를 중복 합산하지 않는다. 지역별 벡터를 합산·평균·순위할 때 exclude_totals=true.
6. 평균·비율(%)·지수는 단순 합산하지 않는다. 비율 값의 차이는 PERCENTAGE_POINT_DIFFERENCE(%p)를 쓴다.
7. 통계적으로 정당화된 가중치가 없으면 WEIGHTED_MEAN 을 쓰지 않는다.
8. 모든 Positive View 가 의미 있는 연산 또는 조건 필터링에 기여해야 한다 (쓰지 않는 View 금지).
9. 실측치와 추계치, 서로 다른 시나리오를 섞지 않는다.
10. 실행 가능한 연산을 만들 수 없으면 plan_status="REJECT_PLAN" 과 구체적인 reject_reason 을 반환한다.
11. 임의의 Python 코드나 SQL 을 쓰지 않는다 (sql_plan 은 비워 둔다).

[연산 계획 형식]
- operands: View 에서 값을 꺼내는 좌표. 스칼라는 group_by_level 없이 '값이 여러 개인 모든 분류'를 coordinates 로 고정한다.
  벡터는 group_by_level(예: 지역 레벨)을 지정하고 나머지 분류만 고정한다.
- filters: target_ref 벡터를 condition_ref 벡터(같은 키) 조건으로 거른다. 기준값을 모르면 threshold_mode="QUANTILE" 과 quantile 을 쓴다.
- operation.steps: 원자 연산 LOOKUP, DIFFERENCE, GROWTH_RATE(이후, 이전), SHARE_RATIO(분자, 분모; params.scale=100 또는 1000),
  SUM, MEAN, WEIGHTED_MEAN(값, 가중치), MIN, MAX, TOP_K(params.k, params.order), COUNT, PERCENTAGE_POINT_DIFFERENCE(이후, 이전).
  inputs 에는 operand_id · filter_id · step_id 를 쓴다. final_step_id 는 마지막 단계.
- 출력은 스키마에 맞는 JSON 하나뿐이다. 설명 문장을 붙이지 않는다."""

SUBTYPE_GUIDE = {
    "LOOKUP": "View 하나. 지역 코드 하나(또는 총계)를 고른 스칼라 하나 → LOOKUP. 값을 바꾸는 연산 없음.",   # [NEW 11-12]
    "GROWTH_RATE": "두 View 는 같은 표·항목의 이전/이후 시점. 같은 좌표의 스칼라 두 개 → GROWTH_RATE(이후, 이전).",
    "DIFFERENCE": "두 View 는 같은 표·항목의 이전/이후 시점. 같은 좌표의 스칼라 두 개 → DIFFERENCE(이후, 이전).",
    "PP_DIFFERENCE": "% 단위 항목의 두 시점. 같은 좌표 스칼라 두 개 → PERCENTAGE_POINT_DIFFERENCE(이후, 이전).",
    "SHARE": "같은 시점, 서로 다른 표. 공통 지역 코드의 분자·분모 스칼라 → SHARE_RATIO(분자, 분모, scale=100).",
    "RATE_PER": "같은 시점, 단위 계열이 다른 두 표. 분자 ÷ 분모(인구) → SHARE_RATIO(scale=1000, 분모 천 단위당).",
    "FILTER_SUM": "첫 View 는 지표, 둘째 View 는 조건. 지역별 벡터 두 개 + filter(조건) → SUM(필터된 지표).",
    "FILTER_COUNT": "첫 View 는 지표, 둘째 View 는 조건. 지역별 벡터 + filter → COUNT.",
    "FILTER_MEAN": "첫 View 는 지표(수량), 둘째 View 는 조건. 지역별 벡터 + filter → MEAN.",
    "FILTER_TOP_K": "첫 View 는 지표, 둘째 View 는 조건. 지역별 벡터 + filter → TOP_K(k).",
    "RATIO_TOP_K": "같은 시점 두 View 의 지역별 벡터 → SHARE_RATIO(원소별) → TOP_K(k).",
    "CLASS_DIFF_COUNT": "같은 표·항목·시점, 분류 코드만 다른 두 View. 지역별 벡터 차이 DIFFERENCE → filter(차이 > 0) → COUNT.",
    "FILTERED_GROWTH_TOP": "View1·View2 는 같은 표의 이전/이후 시점, View3 은 다른 표의 조건. 지역별 GROWTH_RATE 벡터 → View3 조건 filter → MAX.",
}


class PlannerAgent:
    def __init__(self, llm: BaseLLMClient, index: MetadataIndex, graph: CompatibilityGraph, cfg: dict | None = None):
        cfg = cfg or {}
        self.llm, self.index, self.graph = llm, index, graph
        self.max_codes = int(cfg.get("max_codes_in_card", 40))
        self.mock_error_rate = float(cfg.get("mock_inject_structural_error_rate", 0.0))
        # rule: 하위 유형마다 정해진 계산 틀을 코드가 채움 (LLM 호출 없음) — 실데이터에서 HCX 계획이 유형에 없는 계산
        #       (합계−합계 등)을 만들고 좌표를 비우는 문제가 탈락의 대부분이었음. llm: 예전 방식
        self.mode = str(cfg.get("mode", "rule")).lower()
        if isinstance(llm, MockLLMClient):
            llm.register(TASK, mock_plan_response)

    def build_context(self, cluster: SampledCluster, previous_errors: list[str] | None = None) -> PlannerContext:
        cards = [self.index.view_card(v, self.max_codes) for v in cluster.view_ids]
        common = []
        if cluster.common_codes and cluster.join_levels:
            v0 = self.index.view(cluster.view_ids[0])
            lv = cluster.join_levels.get(v0.view_id)
            cm = v0.code_map(lv) if lv else {}
            common = [{"code": c, "name": cm[c].name if c in cm else "", "is_total": bool(cm.get(c) and cm[c].is_total)}
                      for c in cluster.common_codes[:self.max_codes]]
            if len(cluster.common_codes) > self.max_codes:            # 읍면동이면 수천 개 → 프롬프트 하나가 분당 토큰 한도를 넘음
                common.append({"code": "...", "name": f"외 {len(cluster.common_codes) - self.max_codes}개 생략 (전체 "
                                                      f"{len(cluster.common_codes)}개)", "is_total": False})
        allowed = []
        for i, a in enumerate(cluster.view_ids):
            for b in cluster.view_ids[i + 1:]:
                e = self.graph.edge(a, b)
                allowed.append(f"{a} ↔ {b}: " + ", ".join(k for k, v in e.allowed.items() if v))
        return PlannerContext(sample_id=cluster.sample_id, random_seed=cluster.random_seed,
                              reasoning_type=cluster.reasoning_type, subtype=cluster.subtype, hop_type=cluster.hop_type,
                              views=cards, join_dimension_type=cluster.join_dimension_type, join_levels=cluster.join_levels,
                              common_join_codes=common, allowed_operations=allowed,
                              previous_errors=list(previous_errors or []))

    @staticmethod
    def user_prompt(ctx: PlannerContext) -> str:
        payload = ctx.model_dump(mode="json")
        return (f"<task>\n사전 할당 질문 유형: {ctx.reasoning_type.value} / 하위 유형: {ctx.subtype}\n"
                f"지침: {SUBTYPE_GUIDE.get(ctx.subtype, '')}\nView 순서대로 역할이 정해져 있습니다.\n</task>\n"
                f"<context>\n{json.dumps(payload, ensure_ascii=False)}\n</context>\n"
                + ("<previous_errors>\n" + "\n".join(ctx.previous_errors) + "\n</previous_errors>\n"
                   "위 오류를 고친 계획을 다시 만드세요.\n" if ctx.previous_errors else "")
                + "OperationPlan JSON 하나만 출력하세요.")

    def rule_plan(self, cluster: SampledCluster, attempt: int = 0) -> OperationPlan:
        """코드 계획: 전체 코드 목록으로 카드를 만들어 규칙 계획기에 넣음 (프롬프트가 아니므로 코드 수 제한 없음)"""
        cards = [self.index.view_card(v, 100_000) for v in cluster.view_ids]
        common = []
        if cluster.common_codes and cluster.join_levels:
            v0 = self.index.view(cluster.view_ids[0])
            lv = cluster.join_levels.get(v0.view_id)
            cm = v0.code_map(lv) if lv else {}
            common = [{"code": c, "name": cm[c].name if c in cm else "", "is_total": bool(cm.get(c) and cm[c].is_total)}
                      for c in cluster.common_codes]
        ctx = {"subtype": cluster.subtype, "reasoning_type": cluster.reasoning_type.value, "random_seed": cluster.random_seed,
               "views": [c.model_dump(mode="json") for c in cards], "common_join_codes": common,
               "join_levels": cluster.join_levels, "join_dimension_type": cluster.join_dimension_type,
               "_planner_attempt": attempt, "_attempt": 0, "_inject_error": False}
        plan = OperationPlan.model_validate(mock_plan_response(ctx))
        plan.plan_id = f"P_{cluster.sample_id}_{attempt}"
        used = list(dict.fromkeys(o.view_id for o in plan.operands))
        plan.required_view_ids = used
        plan.required_table_ids = list(dict.fromkeys(self.index.view(v).parent_table_id for v in used))
        return plan

    async def plan(self, cluster: SampledCluster, previous_errors: list[str] | None = None,
                   attempt: int = 0) -> tuple[OperationPlan, dict[str, Any]]:
        if self.mode == "rule" and not isinstance(self.llm, MockLLMClient):
            return self.rule_plan(cluster, attempt), {"attempts": 0, "mode": "rule"}
        ctx = self.build_context(cluster, previous_errors)
        mock_ctx = ctx.model_dump(mode="json")
        rng = random.Random(cluster.random_seed * 13 + 7)
        mock_ctx["_inject_error"] = attempt == 0 and rng.random() < self.mock_error_rate
        mock_ctx["_planner_attempt"] = attempt
        plan, meta = await self.llm.generate_structured(TASK, SYSTEM_PROMPT, self.user_prompt(ctx), OperationPlan,
                                                        context=mock_ctx)
        plan.plan_id = f"P_{cluster.sample_id}_{attempt}"
        used = list(dict.fromkeys(o.view_id for o in plan.operands))
        plan.required_view_ids = used
        plan.required_table_ids = list(dict.fromkeys(self.index.view(v).parent_table_id for v in used
                                                     if v in self.index.views))
        meta["injected_error"] = mock_ctx["_inject_error"]
        return plan, meta


# ═════════════════ Mock 응답 (Demo Mode: 결정론적 규칙 기반 — 실제 LLM 품질 검증 아님) ═════════════════

def _region_level(card: dict) -> str | None:
    d = next((d for d in card["dimensions"] if d["dim_type"] == "REGION"), None)
    return d["level"] if d else None


def _fixed_coords(card: dict, skip: set[str]) -> dict[str, str]:
    out = {}
    for d in card["dimensions"]:
        if d["level"] in skip or d["n_codes"] <= 1:
            continue
        tot = next((c for c in d["codes"] if c["is_total"]), None)
        out[d["level"]] = (tot or d["codes"][0])["code"]
    return out


# [NEW 11-12] 단순 조회에서 고를 지역 코드: 전국·시도 이름을 먼저 (시군구·읍면동은 쉬운 질문이 아님)
SIDO_NAMES = {"전국", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시",
              "세종특별자치시", "경기도", "강원도", "강원특별자치도", "충청북도", "충청남도", "전라북도", "전북특별자치도",
              "전라남도", "경상북도", "경상남도", "제주도", "제주특별자치도"}


def _lookup_code(card: dict, rng: random.Random, total_share: float = 0.3) -> str | None:
    """지역 분류에서 코드 하나: 총계(전국)를 total_share 확률로, 아니면 시도 이름인 코드 중 하나 (없으면 아무 코드)"""
    d = next((d for d in card["dimensions"] if d["dim_type"] == "REGION"), None)
    if not d or not d.get("codes"):
        return None
    tot = [c for c in d["codes"] if c.get("is_total")]
    sido = [c for c in d["codes"] if not c.get("is_total") and str(c.get("name", "")).strip() in SIDO_NAMES]
    seen = Counter(str(c.get("name", "")).strip() for c in d["codes"])
    rest = [c for c in d["codes"] if not c.get("is_total") and seen[str(c.get("name", "")).strip()] == 1]
    # 이름이 겹치는 시군구('중구'·'동구'·'고성군')는 어느 시도인지 질문만으로 알 수 없어 뺌
    if tot and (rng.random() < total_share or not (sido or rest)):
        return tot[0]["code"]
    pool = sido or rest or tot
    return pool[rng.randrange(len(pool))]["code"]


def mock_plan_response(ctx: dict) -> dict:
    sub = ctx["subtype"]
    rt = ctx["reasoning_type"]
    views = ctx["views"]
    rng = random.Random(int(ctx["random_seed"]) + 31 * int(ctx.get("_planner_attempt", 0)) + 7 * int(ctx.get("_attempt", 0)))
    ids = [v["view_id"] for v in views]
    item = lambda v: v["items"][0]["itm_id"]                    # noqa: E731
    per = lambda v: v["periods"][0]                             # noqa: E731
    common = ctx.get("common_join_codes") or []
    non_total = [c for c in common if not c["is_total"]]

    def scalar(oid, v, code, role):
        lv = _region_level(v)
        coords = _fixed_coords(v, {lv} if lv else set())
        if lv and code:
            coords[lv] = code
        return {"operand_id": oid, "view_id": v["view_id"], "itm_id": item(v), "prd_de": per(v), "coordinates": coords,
                "role": role}

    def vector(oid, v, role):
        lv = _region_level(v)
        return {"operand_id": oid, "view_id": v["view_id"], "itm_id": item(v), "prd_de": per(v),
                "coordinates": _fixed_coords(v, {lv}), "group_by_level": lv, "exclude_totals": True, "role": role}

    plan: dict[str, Any] = {"plan_status": "OK", "reasoning_type": rt, "subtype": sub, "operands": [], "filters": [],
                            "statistical_assumptions": [], "necessity_expectations": {}, "expected_cardinality": {}}
    code = None
    if non_total or common:
        pick = non_total if (non_total and rng.random() < 0.85) else common
        code = pick[rng.randrange(len(pick))]["code"]
    if sub == "LOOKUP":                                          # [NEW 11-12] 단순 조회
        v = views[0]
        plan["operands"] = [scalar("A", v, _lookup_code(v, rng), "조회 값")]
        plan["operation"] = {"steps": [{"step_id": "s1", "op": "LOOKUP", "inputs": ["A"], "params": {}}], "final_step_id": "s1"}
        plan["statistical_assumptions"] = ["View 하나의 값 하나를 그대로 읽음"]
    elif sub in ("GROWTH_RATE", "DIFFERENCE", "PP_DIFFERENCE"):
        old, new = views[0], views[1]
        plan["operands"] = [scalar("A", old, code, "이전 시점"), scalar("B", new, code, "이후 시점")]
        op = {"GROWTH_RATE": "GROWTH_RATE", "DIFFERENCE": "DIFFERENCE", "PP_DIFFERENCE": "PERCENTAGE_POINT_DIFFERENCE"}[sub]
        plan["operation"] = {"steps": [{"step_id": "s1", "op": op, "inputs": ["B", "A"], "params": {}}], "final_step_id": "s1"}
        plan["statistical_assumptions"] = ["같은 표·같은 항목·같은 좌표의 두 시점 비교"]
    elif sub in ("SHARE", "RATE_PER"):
        num, den = views[0], views[1]
        plan["operands"] = [scalar("A", num, code, "분자"), scalar("B", den, code, "분모")]
        scale = 100 if sub == "SHARE" else 1000
        plan["operation"] = {"steps": [{"step_id": "s1", "op": "SHARE_RATIO", "inputs": ["A", "B"], "params": {"scale": scale}}],
                             "final_step_id": "s1"}
        plan["statistical_assumptions"] = ["분자와 분모는 같은 시점·같은 지역", "분모는 분자를 포함하는 모집단" if sub == "SHARE"
                                           else "분모 인구 천 명당 비율"]
    elif sub in ("FILTER_SUM", "FILTER_COUNT", "FILTER_MEAN", "FILTER_TOP_K"):
        a, b = views[0], views[1]
        plan["operands"] = [vector("A", a, "지표"), vector("B", b, "조건")]
        q = rng.choice([0.4, 0.5, 0.6])
        cmp_ = rng.choice([">=", ">="] + ["<="])
        plan["filters"] = [{"filter_id": "f1", "target_ref": "A", "condition_ref": "B", "comparator": cmp_,
                            "threshold_mode": "QUANTILE", "quantile": q, "nice_round": True}]
        agg = {"FILTER_SUM": "SUM", "FILTER_COUNT": "COUNT", "FILTER_MEAN": "MEAN", "FILTER_TOP_K": "TOP_K"}[sub]
        params = {"k": rng.choice([1, 2]), "order": "DESC"} if agg == "TOP_K" else {}
        plan["operation"] = {"steps": [{"step_id": "s1", "op": agg, "inputs": ["f1"], "params": params}], "final_step_id": "s1"}
        plan["aggregation_specification"] = {"function": agg, "over_level": _region_level(a), "input_ref": "f1",
                                             "exclude_totals": True, "k": params.get("k"), "order": params.get("order")}
        plan["statistical_assumptions"] = ["총계·소계 제외", "조건 View 와 지표 View 는 같은 시점·같은 지역 코드 체계"]
    elif sub == "RATIO_TOP_K":
        a, b = views[0], views[1]
        same = a["units"] and b["units"] and a["units"][0].strip("천만") == b["units"][0].strip("천만")
        plan["operands"] = [vector("A", a, "분자"), vector("B", b, "분모")]
        plan["operation"] = {"steps": [{"step_id": "s1", "op": "SHARE_RATIO", "inputs": ["A", "B"],
                                        "params": {"scale": 100 if same else 1000}},
                                       {"step_id": "s2", "op": "TOP_K", "inputs": ["s1"], "params": {"k": rng.choice([1, 2, 3]),
                                                                                                    "order": "DESC"}}],
                             "final_step_id": "s2"}
        plan["aggregation_specification"] = {"function": "TOP_K", "over_level": _region_level(a), "input_ref": "s1",
                                             "exclude_totals": True}
    elif sub == "CLASS_DIFF_COUNT":
        a, b = views[0], views[1]
        plan["operands"] = [vector("A", a, "분류 1"), vector("B", b, "분류 2")]
        plan["operation"] = {"steps": [{"step_id": "d", "op": "DIFFERENCE", "inputs": ["A", "B"], "params": {}},
                                       {"step_id": "s1", "op": "COUNT", "inputs": ["f1"], "params": {}}], "final_step_id": "s1"}
        plan["filters"] = [{"filter_id": "f1", "target_ref": "d", "condition_ref": "d", "comparator": ">",
                            "threshold_mode": "ABSOLUTE", "threshold_value": "0"}]
        plan["aggregation_specification"] = {"function": "COUNT", "over_level": _region_level(a), "input_ref": "f1"}
    elif sub == "FILTERED_GROWTH_TOP":
        a1, a2, b = views[0], views[1], views[2]
        plan["operands"] = [vector("A1", a1, "이전 시점"), vector("A2", a2, "이후 시점"), vector("B", b, "조건")]
        plan["operation"] = {"steps": [{"step_id": "g", "op": "GROWTH_RATE", "inputs": ["A2", "A1"], "params": {}},
                                       {"step_id": "s1", "op": "MAX", "inputs": ["f1"], "params": {}}], "final_step_id": "s1"}
        plan["filters"] = [{"filter_id": "f1", "target_ref": "g", "condition_ref": "B", "comparator": ">=",
                            "threshold_mode": "QUANTILE", "quantile": 0.5, "nice_round": True}]
        plan["aggregation_specification"] = {"function": "MAX", "over_level": _region_level(a2), "input_ref": "f1"}
    else:
        return {"plan_status": "REJECT_PLAN", "reasoning_type": rt, "reject_reason": f"지원하지 않는 하위 유형 {sub}"}
    for o in plan["operands"]:
        plan["expected_cardinality"][o["operand_id"]] = "MANY" if o.get("group_by_level") else "ONE"
        plan["necessity_expectations"][o["view_id"]] = o["role"]
    if ctx.get("join_levels"):
        plan["join_specification"] = {"dimension_type": ctx.get("join_dimension_type") or "REGION",
                                      "levels": {k: v for k, v in ctx["join_levels"].items() if k in ids}}
    if ctx.get("_inject_error") and not ctx.get("previous_errors"):
        # 데모: 구조 오류(없는 코드)를 넣어 Self-Correction 경로를 실제로 통과시킨다
        o = plan["operands"][0]
        lv = o.get("group_by_level") or next(iter(o["coordinates"]), None)
        if lv and lv in o["coordinates"]:
            o["coordinates"][lv] = "ZZ_NOT_A_CODE"
        else:
            o["itm_id"] = "ITM_NOT_EXIST"
    return plan
