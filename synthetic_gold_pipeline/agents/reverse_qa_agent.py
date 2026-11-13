"""ReverseQAGeneratorAgent — 검증된 Fact 와 계산 결과로부터 질문·모범 답변을 '역방향'으로 만든다.

- LLM 에는 숫자 값을 주지 않는다. 값은 자리표시자({FINAL}, {V1}, {E1}, {T1}, {K} …)로만 쓰게 하고,
  Calculation Tool 의 표시값을 코드가 그대로 끼워 넣는다 (재계산·재반올림 금지).
- 질문에 새로운 숫자·조건·기간·단위·지표를 추가하지 못하도록 결정론적으로 검사하고, 위반하면 오류를 붙여 다시 요청한다.
- 근거(Evidence Trace)는 내부 사고 과정이 아니라 실제 조회 좌표·계산식·결과를 기록한다.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from synthetic_gold_pipeline.agents.llm_client import BaseLLMClient, MockLLMClient
from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
from synthetic_gold_pipeline.schemas.calculation import CalculationResult
from synthetic_gold_pipeline.schemas.metadata import DimensionType
from synthetic_gold_pipeline.schemas.planning import OperationPlan, SampledCluster
from synthetic_gold_pipeline.utils import period_label

TASK = "reverse_qa"
PLACEHOLDER_RX = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


class ReverseQAOutput(BaseModel):
    question_original: str = Field(..., description="공식 통계 용어와 명확한 조건을 담은 질문 (자리표시자 {T1},{K} 가능)")
    question_paraphrased: str = Field(..., description="같은 의미의 일상 표현 질문 (조건·시점·지역·비교 기준 유지)")
    answer_template: str = Field(..., description="모범 답변 문장 — 숫자 대신 자리표시자만 사용")
    limitations: list[str] = Field(default_factory=list, description="통계적 비교의 한계 (숫자 없이)")


SYSTEM_PROMPT = """당신은 국가통계 질의응답 평가셋을 만드는 출제자입니다.
이미 계산 도구가 확정한 사실(Fact)을 정답으로 갖는 질문을 거꾸로 만듭니다.

[절대 규칙]
1. 숫자 값을 직접 쓰지 않는다. 값은 반드시 제공된 자리표시자({FINAL}, {V1}, {E1}, {E1_VALUE}, {T1}, {K} 등)로만 쓴다.
   시점(예: 2023년)과 표·항목 이름에 들어 있는 숫자만 그대로 쓸 수 있다.
2. 제공되지 않은 조건·기간·지역·단위·통계 지표·모집단을 추가하지 않는다.
3. 질문은 제공된 모든 필수 근거(View)가 있어야만 답할 수 있어야 한다. 무관한 두 질문을 이어 붙이지 않는다.
4. question_original 은 공식 통계 용어(표 이름·항목명·조사명)와 시점·지역·비교 기준·집계 조건을 모두 명시한다.
5. question_paraphrased 는 표현만 일상어로 바꾼다. 시점·지역·지표·모집단·비교 기준·집계 조건·연산 의미는 그대로 유지한다.
6. 인과관계를 주장하지 않는다. 통계적 비교의 한계가 있으면 limitations 에 숫자 없이 적는다.
7. answer_template 에는 최종 정답 자리표시자와, 각 근거 값 자리표시자(그 값의 시점·지역·항목과 함께)를 넣는다.
8. facts.question_intent 의 계산 의미(무엇을 무엇과 비교·집계하는지, 답이 비율인지 개수인지 합계인지)를 두 질문 모두 그대로 지킨다.
   예: '…보다 많은 지역의 개수' 를 '차이는 얼마' 로 바꾸지 않는다. 질문은 명령문('구하라')이 아니라 물음으로 쓴다.
9. 분류 값이 '계·합계·총계'인 조건은 질문에 쓰지 않는다 ('계 세대', '합계 연령' 같은 표현 금지).
10. answer_template 은 질문에 바로 답하는 자연스러운 한국어 문장 1~2개로 쓴다 ('…은 {FINAL}입니다.').
    수식('{FINAL} = {V1} - {V2}')으로 쓰지 않는다. 자리표시자 값에는 단위가 이미 붙어 있으므로 뒤에 단위를 또 쓰지 않는다.
JSON 하나만 출력한다."""


def josa(word: str, pair: str) -> str:
    """받침 유무로 조사 선택. pair 예: '은/는', '이/가', '을/를', '과/와', '으로/로'."""
    a, b = pair.split("/")
    if not word:
        return word + b
    ch = word.strip()[-1]
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        if pair == "으로/로" and jong == 8:
            return word + b
        return word + (a if jong else b)
    if ch.isdigit():
        return word + (a if ch in "013678" else b)
    return word + b


def region_short(name: str) -> str:
    s = re.sub(r"(특별자치시|특별자치도|특별시|광역시)$", "", name)
    return s if s else name


LABEL_SYNONYMS = {"남자": ["남자", "남성"], "여자": ["여자", "여성"], "중위추계": ["중위추계", "중위"], "고위추계": ["고위추계", "고위"],
                  "저위추계": ["저위추계", "저위"]}
CASUAL = {"총인구수": "전체 인구", "혼인건수": "결혼 건수", "경제활동인구": "경제활동을 하는 인구", "1인가구": "혼자 사는 가구",
          "일반가구": "일반 가구 수", "취업자": "일하는 사람 수", "총전입": "전입해 온 사람 수", "총전출": "빠져나간 사람 수",
          "순이동": "순유입 인구", "추계인구": "예상 인구", "경제활동참가율": "경제활동 참가율", "남자인구수": "남자 인구",
          "여자인구수": "여자 인구", "사망자수": "사망자 수", "종사자수": "종사자 수", "외국인주민수": "외국인 주민 수", "인구": "인구"}


def dim_label(obj_nm: str) -> str:
    """분류 이름 → 조건 앞말: '가구주의 성별' → '가구주', '특성별' → '특성', '기업규모별' → '기업규모'
    (예전 규칙은 끝의 '성별' 을 먼저 지워 '특성별' 이 '특' 이 됐음)"""
    n = re.sub(r"\([^()]*\)", "", str(obj_nm)).strip()
    m = re.match(r"^(.*?)\s*의\s*성별$", n)
    if m:
        return m.group(1).strip()
    return re.sub(r"별$", "", n).strip()


TOTAL_REGION = {"전국", "계", "총계", "합계", "전체", "소계"}


def label_present(lab: str, qn: str) -> bool:
    """조건 라벨의 핵심 값이 질문에 있는가. '대기업·중견기업' 처럼 묶인 값은 각 부분이 모두 있으면 인정"""
    core = lab.split()[-1]
    if any(v in qn for v in LABEL_SYNONYMS.get(core, [core])):
        return True
    parts = [p for p in re.split(r"[·,/및\s]+", core) if len(p) >= 2]
    return len(parts) > 1 and all(any(v in qn for v in LABEL_SYNONYMS.get(p, [p, re.sub(r"기업$", "", p)])) for p in parts)


def condition_labels(v, o) -> list[str]:
    """질문에 반드시 들어가야 하는 비총계 고정 조건 (시나리오·성별 등). 지역 레벨은 별도 검사."""
    out = []
    sel = {lv: c for lv, c in o.coordinates.items()}
    for lv, cs in v.source_coordinates.dim_filters.items():
        if cs:
            sel.setdefault(lv, cs[0])
    for lv, code in sel.items():
        d, c = v.dim(lv), v.code_map(lv).get(code)
        if not d or not c or c.is_total or d.dim_type == DimensionType.REGION:
            continue
        plain = re.sub(r"\s+", "", d.obj_nm) in ("성별", "성", "시나리오별", "시나리오", "연령별", "국적별")
        dim_word = dim_label(d.obj_nm)
        out.append(c.name if plain or not dim_word else f"{dim_word} {c.name}")
    return out


CMP_WORD = {">": "초과", ">=": "이상", "<": "미만", "<=": "이하"}
_TOTALS = {"계", "합계", "총계", "전체", "전국", "소계"}


REGION_OBJ = re.compile(r"행정구역|시도|시군구|읍면동|지역")


def _op_phrase(o: dict) -> str:
    """operand 설명 → '1인가구(가구주의 성별 남자, 광주광역시)' (총계 조건 생략, 지역은 이름만)"""
    labs = {**o.get("split_labels", {}), **o.get("fixed_labels", {})}
    cond = []
    for k, v in labs.items():
        if re.sub(r"\s+", "", v) in _TOTALS:
            continue
        cond.append(v if REGION_OBJ.search(k) else f"{dim_label(k)} {v}".strip())
    return f"{o['item']}" + (f"({', '.join(cond)})" if cond else "")


def _j(word: str, pair: str) -> str:
    """끝의 괄호는 빼고 받침을 봄: '증감률(%)' + 을/를 → '증감률(%)을'"""
    m = re.match(r"^(.*?)(\([^()]*\))?$", word)
    head, tail = m.group(1), m.group(2) or ""
    return head + tail + josa(head, pair)[len(head):]


def _group_word(grp: str | None) -> str:
    g = re.sub(r"\([^()]*\)", "", grp or "").strip()
    g = re.sub(r"별$", "", g).strip()
    return "지역" if not g or g in ("행정구역", "시도", "지역") or REGION_OBJ.fullmatch(g) else g


def _cond_phrase(t: dict, grp_w: str) -> str:
    item = t["condition_item"] or "조건 항목"
    return (f"{josa(item, '이/가')} 기준값 {{{t['placeholder']}}} {CMP_WORD.get(t['comparator'], t['comparator'])}인 "
            f"{grp_w}들의 ")


def question_intent(cluster: SampledCluster, plan: OperationPlan, operands: list[dict], thresholds: list[dict],
                    k: int | None) -> str:
    """계산 의미를 한 문장으로 (숫자 없음) — LLM 이 '개수' 문제를 '차이' 질문으로 바꾸는 식의 의미 이탈을 막는 기준"""
    by = {o["operand"]: o for o in operands}
    steps = plan.operation.steps
    last = steps[-1].op.value if steps else ""
    ops = [s.op.value for s in steps]
    grp_w = _group_word(next((o["group_by"] for o in operands if o.get("group_by")), None))
    periods = sorted({o["period"] for o in operands})
    cond = _cond_phrase(thresholds[0], grp_w) if thresholds else ""
    pick = {"TOP_K": f"상위 {k}개 {grp_w}", "MAX": f"가장 큰 {grp_w}", "MIN": f"가장 작은 {grp_w}"}.get(last)
    share = next((s for s in steps if s.op.value == "SHARE_RATIO"), None)

    def ratio_words(s0):
        a = by.get(s0.inputs[0], operands[0])
        b = by.get(s0.inputs[1], operands[-1]) if len(s0.inputs) > 1 else operands[-1]
        scale = str(s0.params.get("scale", 100))
        if scale in ("100", "100.0"):
            return f"{_op_phrase(b)} 가운데 {_op_phrase(a)}가 차지하는 비율(%)"
        unit = b.get("unit") if b.get("unit") in ("명", "가구", "호", "개") else ""
        return f"{_op_phrase(b)} {int(float(scale)):,}{unit}당 {_op_phrase(a)}"

    if ops == ["LOOKUP"] and len(operands) == 1:                # [NEW 11-12] 단순 조회
        return f"{_op_phrase(operands[0])}의 {periods[0]} {_j('값', '을/를')} 묻는다."
    if last in ("GROWTH_RATE", "DIFFERENCE", "PERCENTAGE_POINT_DIFFERENCE") and len(periods) == 2 and "COUNT" not in ops:
        what = {"GROWTH_RATE": "증감률(%)", "DIFFERENCE": "증감량", "PERCENTAGE_POINT_DIFFERENCE": "변화폭(%p)"}[last]
        return f"{_op_phrase(operands[0])}의 {periods[0]} 대비 {periods[1]} {_j(what, '을/를')} 묻는다."
    if last == "SHARE_RATIO" and len(operands) >= 2:
        return f"{_j(ratio_words(steps[-1]), '을/를')} 묻는다."
    if last == "COUNT":
        flt = plan.filters[0] if plan.filters else None
        diff = next((s for s in steps if s.op.value == "DIFFERENCE"), None)
        if diff and len(diff.inputs) == 2 and flt and diff.step_id in (flt.condition_ref, flt.target_ref):
            a, b = by.get(diff.inputs[0]), by.get(diff.inputs[1])
            if a and b:
                word = "많은" if flt.comparator in (">", ">=") else "적은"
                return f"{grp_w} 가운데 {_op_phrase(a)}가 {_op_phrase(b)}보다 {word} {josa(grp_w, '이/가')} 몇 곳인지(개수) 묻는다."
        if thresholds:
            t = thresholds[0]
            item = t["condition_item"] or "조건 항목"
            return (f"{josa(item, '이/가')} 기준값 {{{t['placeholder']}}} {CMP_WORD.get(t['comparator'], t['comparator'])}인 "
                    f"{josa(grp_w, '이/가')} 몇 곳인지(개수) 묻는다.")
    if pick and "GROWTH_RATE" in ops and len(periods) >= 2:
        target = next((o for o in operands if o.get("vector")), operands[0])
        return f"{cond}{target['item']} {periods[0]} 대비 {periods[-1]} 증감률이 {josa(pick, '을/를')} 묻는다."
    if pick and share is not None:
        return f"{cond}{_j(ratio_words(share), '이/가')} {josa(pick, '을/를')} 묻는다."
    agg = {"SUM": "합계", "MEAN": "평균"}.get(last)
    if agg or pick:
        target = next((o for o in operands if o.get("vector")), operands[0] if operands else None)
        tail = f"{agg}를" if agg else f"값이 {josa(pick, '을/를')}"
        return f"{cond}{_op_phrase(target) if target else ''} {tail} 묻는다."
    return f"{' → '.join(ops)} 순서로 계산한 값을 묻는다."


def build_fact_bundle(cluster: SampledCluster, plan: OperationPlan, calc: CalculationResult, index: MetadataIndex) -> dict[str, Any]:
    """LLM 입력(숫자 없음)과 자리표시자 → 표시값 매핑(코드가 채움)."""
    values: dict[str, str] = {}
    facts_desc = []
    reg_levels = {}
    for vid in cluster.view_ids:
        v = index.view(vid)
        r = v.dims_of_type(DimensionType.REGION)
        reg_levels[vid] = r[0].obj_nm if r else None
    op_order = {o.operand_id: i for i, o in enumerate(plan.operands)}
    scalar_facts = sorted([f for f in calc.intermediate_facts if f.kind == "SCALAR"],
                          key=lambda f: (op_order.get(f.operand_id, 99), f.fact_id))
    for i, f in enumerate(scalar_facts, 1):
        ph = f"V{i}"
        values[ph] = f.value.display
        region = next((f.coordinate.dim_names[lv] for lv, d in f.coordinate.dims.items()
                       if (index.view(f.view_id).dim(lv) and index.view(f.view_id).dim(lv).dim_type == DimensionType.REGION)), None)
        if region in TOTAL_REGION:
            region = "전국"
        facts_desc.append({"placeholder": ph, "operand": f.operand_id, "period": f.period, "region": region,
                           "item": f.item_name, "unit": f.unit, "labels": f.coordinate_labels,
                           "table": index.view(f.view_id).table_title, "survey": index.view(f.view_id).survey_name})
    fin = calc.final
    final_kind = fin.kind if fin else "NONE"
    entities = []
    if fin and fin.kind == "SCALAR":
        values["FINAL"] = fin.value.display
    elif fin and fin.kind == "ENTITY":
        values["E1"], values["E1_VALUE"] = fin.entity.key_name, fin.entity.value.display
        entities.append({"placeholder": "E1", "value_placeholder": "E1_VALUE", "rank": 1})
    elif fin and fin.kind == "RANKING":
        for e in fin.ranking:
            values[f"E{e.rank}"] = e.key_name
            values[f"E{e.rank}_VALUE"] = e.value.display
            entities.append({"placeholder": f"E{e.rank}", "value_placeholder": f"E{e.rank}_VALUE", "rank": e.rank})
    thresholds = []
    for i, (fid, nr) in enumerate(calc.resolved_thresholds.items(), 1):
        f = next(x for x in plan.filters if x.filter_id == fid)
        cond_ref = f.condition_ref
        cop = next((o for o in plan.operands if o.operand_id == cond_ref), None)
        cond_item = index.view(cop.view_id).item(cop.itm_id).itm_nm if cop and index.view(cop.view_id).item(cop.itm_id) else None
        values[f"T{i}"] = nr.display
        thresholds.append({"placeholder": f"T{i}", "comparator": f.comparator, "condition_item": cond_item,
                           "condition_table": index.view(cop.view_id).table_title if cop else None,
                           "condition_period": period_label(index.view(cop.view_id).period_frequency, cop.prd_de) if cop else None,
                           "is_difference_sign": cop is None})
    k = None
    for s in plan.operation.steps:
        if s.op.value == "TOP_K":
            k = int(s.params.get("k", 3))
            values["K"] = str(k)
    count_members = []
    if fin and fin.kind == "SCALAR" and plan.operation.steps[-1].op.value == "COUNT":
        flt = next((sr for sr in calc.step_results if sr.op == "FILTER"), None)
        if flt:
            count_members = [e.key_name for e in flt.vector]
            values["MEMBERS"] = ", ".join(count_members)
    ops_desc = [{"step": s.step_id, "op": s.op.value, "inputs": s.inputs, "params": s.params} for s in plan.operation.steps]
    operands = []
    for o in plan.operands:
        v = index.view(o.view_id)
        it = v.item(o.itm_id)
        operands.append({"operand": o.operand_id, "role": o.role, "vector": bool(o.group_by_level),
                         "period": period_label(v.period_frequency, o.prd_de), "item": it.itm_nm if it else o.itm_id,
                         "unit": it.unit_nm if it else None, "table": v.table_title, "survey": v.survey_name,
                         "fixed_labels": {v.dim(lv).obj_nm: v.code_map(lv)[c].name for lv, c in o.coordinates.items()
                                          if v.dim(lv) and c in v.code_map(lv)},
                         "group_by": v.dim(o.group_by_level).obj_nm if o.group_by_level and v.dim(o.group_by_level) else None,
                         "split_labels": {v.dim(lv).obj_nm: v.code_map(lv)[cs[0]].name
                                          for lv, cs in v.source_coordinates.dim_filters.items()
                                          if v.dim(lv) and cs and cs[0] in v.code_map(lv)},
                         "condition_labels": condition_labels(v, o)})
    intent = question_intent(cluster, plan, operands, thresholds, k)
    direction = None
    if fin and fin.kind == "SCALAR" and plan.operation.steps[-1].op.value in ("GROWTH_RATE", "DIFFERENCE",
                                                                              "PERCENTAGE_POINT_DIFFERENCE"):
        direction = "증가" if fin.value.raw > 0 else ("감소" if fin.value.raw < 0 else "변화 없음")
    return {
        "llm_input": {"question_intent": intent, "reasoning_type": cluster.reasoning_type.value, "subtype": cluster.subtype,
                      "hop_type": cluster.hop_type.value, "operands": operands, "operations": ops_desc,
                      "scalar_facts": facts_desc, "final_kind": final_kind, "final_unit": fin.unit if fin else None,
                      "entities": entities, "thresholds": thresholds, "k": k, "direction": direction,
                      "count_members_placeholder": "MEMBERS" if count_members else None,
                      "available_placeholders": sorted(values), "region_dimension": list(dict.fromkeys(
                          x for x in reg_levels.values() if x))},
        "values": values,
    }


class ReverseQAGeneratorAgent:
    def __init__(self, llm: BaseLLMClient, index: MetadataIndex, cfg: dict | None = None):
        self.llm, self.index = llm, index
        self.cfg = cfg or {}
        self.max_len_o = int(self.cfg.get("max_question_original_chars", 160))      # 공식 표 이름이 들어가 더 김
        self.max_len_p = int(self.cfg.get("max_question_paraphrased_chars", 90))    # 사람이 실제로 치는 길이
        if isinstance(llm, MockLLMClient):
            llm.register(TASK, mock_reverse_qa_response)

    @staticmethod
    def allowed_numbers(bundle: dict) -> set[str]:
        li = bundle["llm_input"]
        txt = json.dumps({k: li[k] for k in ("operands", "scalar_facts", "thresholds")}, ensure_ascii=False)
        nums = set(re.findall(r"\d+", txt))
        for o in li["operands"]:
            nums |= set(re.findall(r"\d+", o["period"]))
        if li.get("k"):
            nums.add(str(li["k"]))
        nums |= {str(e["rank"]) for e in li.get("entities", [])}
        return nums

    def validate(self, out: ReverseQAOutput, bundle: dict) -> list[str]:
        li, values = bundle["llm_input"], bundle["values"]
        errs = []
        allowed = self.allowed_numbers(bundle)
        q_ph_allowed = {p for p in values if p.startswith("T") or p == "K"}
        if len(out.question_paraphrased) > self.max_len_p:
            errs.append(f"question_paraphrased: {len(out.question_paraphrased)}자 — {self.max_len_p}자 이내의 짧은 일상 질문으로")
        if len(out.question_original) > self.max_len_o:
            errs.append(f"question_original: {len(out.question_original)}자 — {self.max_len_o}자 이내로")
        for name in ("question_original", "question_paraphrased"):
            q = getattr(out, name)
            phs = set(PLACEHOLDER_RX.findall(q))
            bad = phs - q_ph_allowed
            if bad:
                errs.append(f"{name}: 질문에 정답 자리표시자 사용 금지 {sorted(bad)}")
            raw_nums = re.findall(r"\d[\d,.]*", PLACEHOLDER_RX.sub("", q))
            extra = [n for n in raw_nums if n.replace(",", "").split(".")[0] not in allowed]
            if extra:
                errs.append(f"{name}: 제공되지 않은 숫자 {extra}")
            periods = {o["period"] for o in li["operands"]}
            for p in periods:
                yr = re.sub(r"\D", "", p)[:4]
                if yr and yr not in q:
                    errs.append(f"{name}: 시점 {p} 누락")
            for f in li["scalar_facts"]:
                if f.get("region") in TOTAL_REGION:                 # 전국 값은 지역을 말하지 않아도 같은 뜻
                    continue
                if f.get("region") and not any(v in q for v in {f["region"], region_short(f["region"])}):
                    errs.append(f"{name}: 지역 {f['region']} 누락")
            for t in li["thresholds"]:
                if not t["is_difference_sign"] and f"{{{t['placeholder']}}}" not in q:
                    errs.append(f"{name}: 조건 기준값 {{{t['placeholder']}}} 누락")
            if li.get("k") and "{K}" not in q and str(li["k"]) not in q and li["k"] != 1:
                errs.append(f"{name}: 상위 개수 {{K}} 누락")
            qn = re.sub(r"\s+", "", q)
            for o in li["operands"]:
                for lab in o.get("condition_labels", []):
                    if not label_present(lab, qn):
                        errs.append(f"{name}: 필수 분류 조건 '{lab}' 누락 (빠지면 다른 정답 가능)")
        for f in li["scalar_facts"]:
            core = re.sub(r"\s+", "", f["item"])
            if core and core not in re.sub(r"\s+", "", out.question_original):
                errs.append(f"question_original: 공식 항목명 '{f['item']}' 누락")
        tpl = out.answer_template.strip()
        if re.search(r"\}\s*=|=\s*\{|\}\s*[−\-×÷/]\s*\{", tpl) or not re.search(r"[가-힣]{2}", PLACEHOLDER_RX.sub("", tpl)):
            errs.append("answer_template: 수식이 아니라 질문에 답하는 문장으로 ('…은 {FINAL}입니다.')")
        phs = set(PLACEHOLDER_RX.findall(out.answer_template))
        unknown = phs - set(values)
        if unknown:
            errs.append(f"answer_template: 알 수 없는 자리표시자 {sorted(unknown)}")
        need = {"FINAL"} if "FINAL" in values else {e["placeholder"] for e in li["entities"]}
        if not need <= phs:
            errs.append(f"answer_template: 최종 정답 자리표시자 {sorted(need - phs)} 누락")
        raw = re.findall(r"\d[\d,.]*", PLACEHOLDER_RX.sub("", out.answer_template))
        extra = [n for n in raw if n.replace(",", "").split(".")[0] not in allowed]
        if extra:
            errs.append(f"answer_template: 숫자를 직접 씀 {extra} (자리표시자 사용)")
        for lim in out.limitations:
            if re.search(r"\d", PLACEHOLDER_RX.sub("", lim)) and any(n not in allowed for n in re.findall(r"\d+", lim)):
                errs.append("limitations: 숫자 금지")
        final_nums = {values.get("FINAL", ""), values.get("E1_VALUE", "")} - {""}
        for name in ("question_original", "question_paraphrased"):
            q = fill(getattr(out, name), values)
            for fv in final_nums:
                core = re.sub(r"[^\d.]", "", fv)
                if core and len(core) >= 2 and core in re.sub(r"[^\d.]", " ", q).split():
                    errs.append(f"{name}: 정답 값이 질문에 노출됨")
        return errs

    async def generate(self, bundle: dict) -> tuple[ReverseQAOutput, dict]:
        user = ("<facts>\n" + json.dumps(bundle["llm_input"], ensure_ascii=False) + "\n</facts>\n"
                "위 Fact 를 정답으로 갖는 question_original, question_paraphrased, answer_template, limitations 를 JSON 으로 출력하세요.")
        out, meta = await self.llm.generate_structured(TASK, SYSTEM_PROMPT, user, ReverseQAOutput,
                                                       context={"bundle": bundle["llm_input"]},
                                                       validator=lambda o: self.validate(o, bundle))
        return out, meta


def fill(text: str, values: dict[str, str]) -> str:
    """자리표시자 치환. 표시값에 이미 단위가 붙어 있으므로 LLM 이 뒤에 또 쓴 같은 단위는 지움 ('{FINAL}%' → '13.9%%' 방지)"""
    def rep(m):
        v = values.get(m.group(1))
        if v is None:
            return m.group(0)
        return v
    out = text
    for ph, v in values.items():
        unit = re.sub(r"^[-+]?[\d,]*\.?\d*", "", str(v)).strip()
        if unit:
            # 단위 뒤가 조사·서술어·문장부호일 때만 중복으로 봄 ('{V1}가구주' 처럼 새 낱말이 이어지면 그대로)
            out = re.sub(r"\{" + re.escape(ph) + r"\}\s?" + re.escape(unit) +
                         r"(?=$|[\s.,)\]!?]|입|이|가|은|는|을|를|로|으로|에|의|와|과|씩|정도|임|예요|이에요)", "{" + ph + "}", out)
    return PLACEHOLDER_RX.sub(rep, out)


def assemble_reference_answer(out: ReverseQAOutput, bundle: dict, calc: CalculationResult,
                              index: MetadataIndex) -> tuple[str, list[dict], str]:
    """모범 답변 = LLM 문장(자리표시자 치환) + 결정론적 근거·계산식 블록. 숫자는 모두 Tool 표시값."""
    values = bundle["values"]
    body = fill(out.answer_template, values).strip()
    trace, lines = [], []
    for f in calc.intermediate_facts:
        v = index.view(f.view_id)
        labels = ", ".join(f"{k} {x}" for k, x in f.coordinate_labels.items())
        lines.append(f"- {v.survey_name} 「{v.table_title}」({v.parent_table_id}) {f.period} {labels} {f.item_name}: "
                     f"{f.value.display} (원본 {f.coordinate.source_path} {f.coordinate.row_number}행)")
        trace.append({"type": "LOOKUP", "fact_id": f.fact_id, "view_id": f.view_id, "parent_table_id": f.parent_table_id,
                      "period": f.period, "labels": f.coordinate_labels, "item": f.item_name, "value": f.value.display,
                      "source_path": f.coordinate.source_path, "row_number": f.coordinate.row_number})
    for s in calc.step_results:
        trace.append({"type": "OPERATION", "step_id": s.step_id, "op": s.op, "formula": s.formula, "inputs": s.input_refs})
    for t in calc.unit_conversion_trace:
        trace.append({"type": "UNIT_CONVERSION", **t.model_dump()})
    lim = [x for x in out.limitations if x.strip()]
    text = body + "\n\n[근거]\n" + "\n".join(lines) + "\n[계산]\n" + calc.executed_formula
    if lim:
        text += "\n[유의사항]\n" + "\n".join(f"- {x}" for x in lim)
    return text, trace, body


# ═════════════════ Mock 응답 (Demo Mode — 템플릿 기반, 실제 LLM 품질 검증 아님) ═════════════════

def mock_reverse_qa_response(ctx: dict) -> dict:
    """템플릿 기반 질문 생성. 값은 자리표시자로만 쓰고, 필수 분류 조건(시나리오·성별 등)을 질문에 넣는다."""
    b = ctx["bundle"]
    sub = b["subtype"]
    ops = b["operands"]
    sf = b["scalar_facts"]
    cmpw = {">=": "이상", ">": "초과", "<=": "이하", "<": "미만"}

    def cas(it):
        return CASUAL.get(it.replace(" ", ""), it)

    def cond(o):
        c = " ".join(o.get("condition_labels") or [])
        return f"{c} " if c else ""

    def subj(o, casual=False):                       # '여자 가구주 1인가구는' 처럼 조건 + 항목 + 조사
        return josa(cond(o) + (cas(o["item"]) if casual else o["item"]), "은/는")

    geo = re.sub(r"별$", "", (b["region_dimension"] or ["지역"])[0]) or "지역"
    reg = sf[0]["region"] if sf and sf[0].get("region") else ""
    rs = region_short(reg) if reg else ""
    lims: list[str] = []
    if sub == "LOOKUP":                                          # [NEW 11-12] 단순 조회 (데모 템플릿)
        o1 = ops[0]
        q1 = f"{o1['survey']} 「{o1['table']}」 기준 {o1['period']} {reg} {josa(cond(o1) + o1['item'], '은/는')} 얼마인가요?"
        q2 = f"{o1['period']} {rs} {cond(o1)}{cas(o1['item'])} 얼마야?"
        tmpl = f"{o1['period']} {reg} {cond(o1)}{josa(o1['item'], '은/는')} {{FINAL}}입니다."
        lims = []
    elif sub in ("GROWTH_RATE", "DIFFERENCE", "PP_DIFFERENCE"):
        o1, o2 = ops[0], ops[1]
        what = {"GROWTH_RATE": "몇 % 증가 또는 감소했나요", "DIFFERENCE": f"몇 {o1['unit'] or ''} 증가 또는 감소했나요",
                "PP_DIFFERENCE": "몇 %p 변했나요"}[sub]
        how = {"GROWTH_RATE": "몇 퍼센트나 달라졌어", "DIFFERENCE": "얼마나 늘거나 줄었어", "PP_DIFFERENCE": "몇 퍼센트포인트 바뀌었어"}[sub]
        word = {"GROWTH_RATE": "증감률", "DIFFERENCE": "증감량", "PP_DIFFERENCE": "변화폭"}[sub]
        q1 = f"{o1['survey']} 「{o1['table']}」 기준 {reg} {subj(o1)} {o1['period']} 대비 {o2['period']}에 {what}?"
        q2 = f"{rs} {cond(o1)}{cas(o1['item'])}, {o1['period']}이랑 비교하면 {o2['period']}에는 {how}?"
        tmpl = (f"{reg} {cond(o1)}{o1['item']}: {o1['period']} {{V1}}, {o2['period']} {{V2}}. "
                f"{o1['period']} 대비 {o2['period']} {josa(word, '은/는')} {{FINAL}}입니다"
                + (f" ({b['direction']})." if b.get("direction") else "."))
        lims = ["같은 통계표·같은 항목의 두 시점 비교이며 변화의 원인을 뜻하지 않습니다."]
    elif sub in ("SHARE", "RATE_PER"):
        n, d = ops[0], ops[1]
        nl, dl = cond(n) + n["item"], cond(d) + d["item"]
        if sub == "SHARE":
            q1 = (f"{n['period']} {reg}의 {n['survey']} 「{n['table']}」 {josa(nl, '은/는')} {d['survey']} 「{d['table']}」 "
                  f"{dl}의 몇 %인가요?")
            q2 = f"{n['period']} {rs} {cond(d)}{cas(d['item'])} 가운데 {cond(n)}{cas(n['item'])} 비중은 퍼센트로 얼마야?"
            tmpl = f"{n['period']} {reg}: {nl} {{V1}}, {dl} {{V2}}. {dl} 대비 {nl} 비율은 {{FINAL}}입니다."
        else:
            q1 = (f"{n['period']} {reg}의 {n['survey']} 「{n['table']}」 {josa(nl, '을/를')} {d['survey']} 「{d['table']}」 "
                  f"{dl} 천 명당 값으로 나타내면 얼마인가요?")
            q2 = f"{n['period']} {rs}에서 {cond(d)}{cas(d['item'])} 천 명당 {cond(n)}{cas(n['item'])}는 얼마나 돼?"
            tmpl = f"{n['period']} {reg}: {nl} {{V1}}, {dl} {{V2}}. {dl} 천 명당 {josa(nl, '은/는')} {{FINAL}}입니다."
        lims = ["분자와 분모가 서로 다른 통계표에서 왔으므로 조사·집계 기준 차이가 있을 수 있습니다."]
    elif sub.startswith("FILTER_"):
        a, c = ops[0], ops[1]
        t = b["thresholds"][0]
        cw = cmpw.get(t["comparator"], t["comparator"])
        al, cl = cond(a) + a["item"], cond(c) + c["item"]
        head = f"{c['period']} {c['survey']} 「{c['table']}」의 {josa(cl, '이/가')} {{T1}} {cw}인 {geo} 지역"
        head2 = f"{c['period']} {cond(c)}{cas(c['item'])}가 {{T1}} {cw}인 곳"
        if sub == "FILTER_SUM":
            q1, q2 = head + f"의 {a['period']} {al} 합계는 얼마인가요? (총계 제외)", head2 + f"들의 {cond(a)}{cas(a['item'])}를 모두 더하면 얼마야? 합계 행은 빼고."
            tmpl = f"조건을 만족하는 {geo} 지역의 {a['period']} {al} 합계는 {{FINAL}}입니다."
        elif sub == "FILTER_COUNT":
            q1, q2 = head + "은 모두 몇 곳인가요? (총계 제외)", head2 + "은 몇 군데야? 전국 같은 합계는 빼고."
            tmpl = "조건을 만족하는 지역은 {MEMBERS}, 모두 {FINAL}입니다."
        elif sub == "FILTER_MEAN":
            q1, q2 = head + f"의 {a['period']} {al} 단순 평균은 얼마인가요? (총계 제외)", head2 + f"들의 {cond(a)}{cas(a['item'])} 평균(단순 평균)은 얼마야?"
            tmpl = f"조건을 만족하는 지역의 {a['period']} {al} 단순 평균은 {{FINAL}}입니다."
        else:
            k = b.get("k") or 1
            ents = ", ".join(f"{e['rank']}위 {{{e['placeholder']}}}({{{e['value_placeholder']}}})" for e in b["entities"])
            if k == 1:
                q1, q2 = head + f" 중 {a['period']} {josa(al, '이/가')} 가장 많은 곳은 어디인가요?", head2 + f" 중에서 {cond(a)}{cas(a['item'])}가 제일 많은 곳은 어디야?"
            else:
                q1, q2 = head + f" 중 {a['period']} {josa(al, '이/가')} 가장 많은 상위 {{K}}곳은 어디인가요?", head2 + f" 중에서 {cond(a)}{cas(a['item'])}가 제일 많은 {{K}}곳은 어디야?"
            tmpl = f"조건을 만족하는 지역 중 {a['period']} {al} 상위 지역은 {ents}입니다."
        lims = ["조건 기준값은 계산 도구가 조건 지표 분포에서 정한 값입니다.", "총계·소계는 집계에서 제외했습니다."]
    elif sub == "RATIO_TOP_K":
        n, d = ops[0], ops[1]
        nl, dl = cond(n) + n["item"], cond(d) + d["item"]
        k = b.get("k") or 1
        top = "가장 높은 곳은" if k == 1 else "가장 높은 상위 {K}곳은"
        q1 = (f"{n['period']} {geo}별 {n['survey']} {josa(nl, '을/를')} {d['survey']} 「{d['table']}」 {dl}로 나눈 비율이 "
              f"{top} 어디인가요? (총계 제외)")
        q2 = (f"{n['period']} {cond(d)}{cas(d['item'])} 대비 {cond(n)}{cas(n['item'])} 비율이 "
              + ("제일 높은 데는 어디야?" if k == 1 else "높은 {K}곳 알려줘."))
        ents = ", ".join(f"{e['rank']}위 {{{e['placeholder']}}}({{{e['value_placeholder']}}})" for e in b["entities"])
        tmpl = f"{n['period']} {nl} ÷ {dl} 비율 기준 {ents}입니다."
        lims = ["서로 다른 통계표의 비율이므로 집계 기준 차이에 유의해야 합니다."] if n["table"] != d["table"] else []
    elif sub == "CLASS_DIFF_COUNT":
        a, c = ops[0], ops[1]
        sa, sc = " ".join(a.get("condition_labels") or []) or "분류 1", " ".join(c.get("condition_labels") or []) or "분류 2"
        q1 = (f"{a['period']} {a['survey']} 「{a['table']}」에서 {sa} {josa(a['item'], '이/가')} {sc} {a['item']}보다 많은 "
              f"{geo} 지역은 몇 곳인가요? (총계 제외)")
        q2 = f"{a['period']}에 {cas(a['item'])}가 {sc}보다 {sa} 쪽이 더 많은 지역은 몇 군데야? 전국 합계는 빼고."
        tmpl = f"{sa} {josa(a['item'], '이/가')} {sc}보다 많은 지역은 {{MEMBERS}}, 모두 {{FINAL}}입니다."
        lims = ["같은 통계표 안에서 분류만 다른 두 값을 비교했습니다."]
    elif sub == "FILTERED_GROWTH_TOP":
        a1, a2, c = ops[0], ops[1], ops[2]
        t = b["thresholds"][0]
        cw = cmpw.get(t["comparator"], t["comparator"])
        al, cl = cond(a1) + a1["item"], cond(c) + c["item"]
        q1 = (f"{c['period']} {c['survey']} 「{c['table']}」의 {josa(cl, '이/가')} {{T1}} {cw}인 {geo} 지역 중 "
              f"{a1['survey']} {al}의 {a1['period']} 대비 {a2['period']} 증감률이 가장 높은 곳은 어디인가요?")
        q2 = (f"{c['period']} {cond(c)}{cas(c['item'])}가 {{T1}} {cw}인 곳들 가운데 {cond(a1)}{cas(a1['item'])}가 "
              f"{a1['period']}보다 {a2['period']}에 가장 많이 늘어난(증감률 기준) 곳은?")
        tmpl = f"조건을 만족하는 지역 중 {al}의 {a1['period']} 대비 {a2['period']} 증감률이 가장 높은 곳은 {{E1}}({{E1_VALUE}})입니다."
        lims = ["증감률은 같은 통계표의 두 시점으로 계산했고, 조건은 다른 통계표의 값입니다."]
    else:
        q1 = q2 = tmpl = ""
    if "{MEMBERS}" in tmpl and "MEMBERS" not in b["available_placeholders"]:
        tmpl = tmpl.replace("{MEMBERS}, ", "")
    clean = lambda x: re.sub(r"\s+", " ", x).strip()   # noqa: E731
    return {"question_original": clean(q1), "question_paraphrased": clean(q2), "answer_template": tmpl, "limitations": lims}
