"""독립 Evaluation Tool — LLM 없이 동작.

두 가지 용도
  (1) 합성 Golden Set 생성 과정의 품질 검증: 모범 답변 수치 검증, View 필요성(Ablation), View 판정
  (2) 향후 실제 RAG 실행 결과 평가: Retriever 지표 · Generator 지표 · 단계별 실패 진단

수치 검증은 "정답 숫자가 문자열에 들어 있는가" 가 아니라 값·단위·부호·중간값·뒤바뀜·잘못된 지역/연도 연결·
근거 없는 숫자를 각각 검사한다. 구조화된 Claim 이 있으면 Claim 을 우선 비교한다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex, norm_item_name
from synthetic_gold_pipeline.schemas.calculation import CalculationResult, IntermediateFact
from synthetic_gold_pipeline.schemas.dataset import ExpectedClaim, GoldenRecord
from synthetic_gold_pipeline.schemas.metadata import ViewMetadata
from synthetic_gold_pipeline.schemas.planning import OperationPlan, SampledCluster
from synthetic_gold_pipeline.schemas.verification import (AblationOutcome, AblationResult, NumericCheck, ViewJudgement,
                                                           ViewLabel)
from synthetic_gold_pipeline.tools.units import conversion_factor, parse_value

# ═════════════════════════════ 숫자 추출 ═════════════════════════════
UNIT_ALIASES = {"%포인트": "%p", "퍼센트포인트": "%p", "%P": "%p", "퍼센트": "%", "프로": "%"}
_UNIT_RX = (r"%p|%포인트|퍼센트포인트|%P|%|퍼센트|‰|(?:명|건|가구|호|원)/[십백천만]*(?:명|가구|건)|천명|만명|백만명|명|천가구|만가구|가구|건|호|개소|개|곳|"
            r"십억원|백만원|천원|억원|만원|원|세|배")
_NUM_RX = re.compile(r"(?P<sign>[+\-−△▽]?)\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<man>만|억)?\s*"
                     rf"(?P<unit>{_UNIT_RX})?")
_PERIOD_RX = re.compile(r"^(?:년|년도|월|분기|반기|일|위|번째|차|세 이상)")
DECREASE = re.compile(r"감소|줄|하락|낮아|떨어|축소|마이너스")
INCREASE = re.compile(r"증가|늘|상승|높아|올라|확대|플러스")


@dataclass
class NumberMention:
    value: Decimal
    unit: str | None
    text: str
    start: int
    end: int
    sentence: int
    decimals: int
    is_period_token: bool = False


_PERIOD_TOKEN = re.compile(r"(\d{4})\s*년(?:\s*(\d{1,2})\s*월|\s*(\d)\s*분기|\s*(상|하)\s*반기)?")


def period_key(label: str | None):
    if not label:
        return None
    m = _PERIOD_TOKEN.search(label)
    if not m:
        d = re.sub(r"\D", "", label)
        return (d[:4], None, None, None) if len(d) >= 4 else None
    return (m.group(1), str(int(m.group(2))) if m.group(2) else None, m.group(3), m.group(4))


def nearest_period(text: str, sent_start: int, sent_end: int, pos: int):
    """값 위치에서 가장 가까운 '앞쪽' 시점 표기 (없으면 뒤쪽 첫 시점). 시점 표기가 없으면 None."""
    toks = [(m.start(), period_key(m.group(0))) for m in _PERIOD_TOKEN.finditer(text, sent_start, sent_end)]
    before = [t for t in toks if t[0] < pos]
    if before:
        return before[-1][1]
    after = [t for t in toks if t[0] > pos]
    return after[0][1] if after else None


def nearest_label(text: str, sent_start: int, pos: int, variants: dict[str, list[str]]):
    best, best_pos = None, -1
    for key, vs in variants.items():
        for v in vs:
            i = text.rfind(v, sent_start, pos)
            if i > best_pos:
                best, best_pos = key, i
    return best


def mask_text(text: str, labels: Iterable[str]) -> str:
    for lb in sorted({x for x in labels if x and re.search(r"\d", x)}, key=len, reverse=True):
        text = text.replace(lb, re.sub(r"\d", "□", lb))
    return text


def split_sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in re.finditer(r"(?<=[.!?。])\s+|\n+", text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def extract_numbers(text: str) -> list[NumberMention]:
    sents = split_sentences(text)
    out = []
    for m in _NUM_RX.finditer(text):
        num = m.group("num")
        after = text[m.end("num"):m.end("num") + 4]
        if re.match(r"\s*년(?!\s*간)|\s*월|\s*분기|\s*반기|\s*일\b|\s*위|\s*번째", after) and not m.group("unit"):
            is_period = True
        else:
            is_period = bool(m.group("unit") is None and _PERIOD_RX.match(text[m.end():m.end() + 3].lstrip()))
        if m.group("unit") == "세" and re.match(r"\s*(이상|이하|미만|~)", text[m.end():m.end() + 4]):
            is_period = True
        v = Decimal(num.replace(",", ""))
        dec = len(num.split(".")[1]) if "." in num else 0
        if m.group("man") == "만":
            v *= 10_000
        elif m.group("man") == "억":
            v *= 100_000_000
        sign = m.group("sign")
        if sign in ("-", "−", "▽") and not re.match(r"\d", text[max(0, m.start() - 1):m.start()] or " "):
            v = -v
        unit = m.group("unit")
        unit = UNIT_ALIASES.get(unit, unit)
        start = m.start("sign") if sign else m.start("num")     # 앞 공백을 빼고 실제 숫자 위치로 문장을 정함
        sid = next((i for i, (a, b) in enumerate(sents) if a <= start < max(b, a + 1)), len(sents) - 1)
        out.append(NumberMention(v, unit, m.group(0).strip(), start, m.end(), sid, dec, is_period))
    return out


def units_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    try:
        conversion_factor(a, b)
        return True
    except ValueError:
        return False


def value_matches(m: NumberMention, target: float, unit: str | None, policy: dict, strict_digits: bool = False) -> bool:
    """mention 이 target 과 같은 값인가: 단위 변환 후, mention 의 소수 자릿수로 반올림한 값이 일치하면 OK.
    strict_digits=True(최종값): 허용 반올림 자릿수(policy.rounding_digits)로 쓴 경우만 인정."""
    v = m.value
    if m.unit and unit and m.unit != unit:
        try:
            v = v * conversion_factor(m.unit, unit)
        except ValueError:
            return False
    allowed = set(policy.get("rounding_digits", [0, 1, 2]))
    if strict_digits and m.decimals not in allowed and not (m.decimals == 0 and float(v) == target):
        return False
    tol = max(float(policy.get("abs_tolerance", 0.0)), 0.5 * 10 ** (-m.decimals) + 1e-12)
    rel = float(policy.get("rel_tolerance", 0.0))
    return abs(float(v) - target) <= max(tol, rel * abs(target))


# ═════════════════════════════ 수치 검증 ═════════════════════════════

class NumericAnswerEvaluator:
    def __init__(self, region_aliases: dict[str, list[str]] | None = None):
        self.region_aliases = region_aliases or {}

    def label_variants(self, label: str | None) -> list[str]:
        if not label:
            return []
        out = {label, label.replace(" ", "")}
        short = re.sub(r"(특별자치시|특별자치도|특별시|광역시|자치시|자치도)$", "", label)
        if short != label:
            out.add(short)
        if label.endswith("도") and len(label) > 2:
            out.add(label[:-1])
        out.update(self.region_aliases.get(label, []))
        return [o for o in out if o]

    def evaluate(self, text: str, claims: list[ExpectedClaim], policy: dict, op: str | None = None,
                 allowed_extra: Iterable[float] = (), require_intermediates: bool = True,
                 mask_labels: Iterable[str] = ()) -> NumericCheck:
        """mask_labels: 표·항목·분류 이름 등 숫자가 들어 있는 고유명 (예: '1인가구', '65세 이상') — 수치로 세지 않음."""
        res = NumericCheck(passed=False)
        text = mask_text(text, mask_labels)
        mentions = [m for m in extract_numbers(text) if not m.is_period_token]
        finals = [c for c in claims if c.role == "FINAL" and c.value is not None]
        inters = [c for c in claims if c.role == "INTERMEDIATE" and c.value is not None]
        others = [c for c in claims if c.role in ("THRESHOLD", "ENTITY_VALUE") and c.value is not None]
        sents = split_sentences(text)
        # 최종값
        if finals:
            ok_f, unit_f, sign_f = True, True, True
            for c in finals:
                hit = [m for m in mentions if value_matches(m, c.value, c.unit if m.unit else None, policy, True)]
                hit_abs = [m for m in mentions if value_matches(NumberMention(abs(m.value), m.unit, m.text, m.start, m.end,
                                                                              m.sentence, m.decimals), abs(c.value),
                                                            c.unit if m.unit else None, policy, True)]
                if not hit and hit_abs and c.value != 0:
                    # 부호 없이 크기만 적고 '감소' 로 방향을 말한 경우
                    m = hit_abs[0]
                    s = text[sents[m.sentence][0]:sents[m.sentence][1]]
                    want_dec = c.value < 0
                    if (DECREASE.search(s) and want_dec) or (INCREASE.search(s) and not want_dec):
                        hit = hit_abs
                    else:
                        sign_f = False
                        res.details.append(f"최종값 {c.value_text}: 크기는 맞지만 증감 방향/부호가 다름")
                if not hit:
                    ok_f = False
                    res.details.append(f"최종값 {c.value_text} ({c.unit}) 를 찾지 못함")
                    continue
                with_unit = [m for m in hit if m.unit]
                if policy.get("unit_required", True) and c.unit and not with_unit:
                    unit_f = False
                    res.details.append(f"최종값 {c.value_text}: 단위 없음")
                elif with_unit and not any(units_compatible(m.unit, c.unit) for m in with_unit):
                    unit_f = False
                    res.details.append(f"최종값 {c.value_text}: 단위 불일치 {[m.unit for m in with_unit]}")
                if op in ("GROWTH_RATE", "DIFFERENCE", "PERCENTAGE_POINT_DIFFERENCE") and c.value != 0 and sign_f:
                    m = hit[0]
                    s = text[sents[m.sentence][0]:sents[m.sentence][1]]
                    dec, inc = bool(DECREASE.search(s)), bool(INCREASE.search(s))
                    neg = m.value < 0
                    if c.value < 0 and not (neg or dec) or c.value > 0 and (dec and not inc) and not neg:
                        sign_f = False
                        res.details.append(f"최종값 {c.value_text}: 증감 방향 표현 불일치")
            res.final_value_ok, res.unit_ok, res.sign_ok = ok_f, unit_f, sign_f
        # 중간값 + 연결(binding)
        ok_i = True
        for c in inters:
            hit = [m for m in mentions if value_matches(m, c.value, c.unit if m.unit else None, policy)]
            if not hit:
                if require_intermediates:
                    ok_i = False
                    res.details.append(f"중간값 {c.value_text} ({c.region or ''} {c.period or ''}) 누락")
                continue
            bound = False
            all_regions = {r for r in (x.region for x in inters) if r}
            for m in hit:
                a, b = sents[m.sentence]
                s = text[a:b]
                total_region = c.region in ("전국", "계", "총계", "합계", "전체")
                reg_ok = not c.region or total_region or any(v in s for v in self.label_variants(c.region))
                per_ok = not c.period or nearest_period(text, a, b, m.start) in (None, period_key(c.period))
                # 같은 문장에 지역이 여럿이면 값 바로 앞의 지역이 맞아야 함
                near = nearest_label(text, a, m.start, {r: self.label_variants(r) for r in all_regions})
                near_ok = not c.region or near in (None, c.region)
                if reg_ok and per_ok and near_ok:
                    bound = True
                    break
            if not bound:
                res.binding_errors.append(f"{c.value_text}: {c.region or ''} {c.period or ''} 와 연결되지 않음")
        res.intermediates_ok = ok_i if inters else None
        # 뒤바뀜
        if finals and not res.final_value_ok:
            for c in inters:
                if any(value_matches(m, c.value, finals[0].unit, policy) for m in mentions if m.unit == finals[0].unit):
                    res.swap_detected = True
        # 근거 없는 숫자
        known = [(c.value, c.unit) for c in claims if c.value is not None] + [(float(x), None) for x in allowed_extra]
        for m in mentions:
            if any(value_matches(m, v, u if m.unit else None, policy) or
                   value_matches(NumberMention(abs(m.value), m.unit, m.text, m.start, m.end, m.sentence, m.decimals),
                                 abs(v), u if m.unit else None, policy) for v, u in known):
                continue
            res.unsupported_numbers.append(m.text)
        res.passed = bool((res.final_value_ok is not False) and (res.unit_ok is not False) and (res.sign_ok is not False)
                          and (res.intermediates_ok is not False) and not res.binding_errors and not res.swap_detected
                          and not res.unsupported_numbers and (finals or inters or others))
        return res

    @staticmethod
    def evaluate_claims(pred: list[dict], expected: list[ExpectedClaim], policy: dict) -> dict[str, Any]:
        """구조화된 Claim 비교: role·값·단위·지역·시점 각각."""
        out = {"n_expected": len(expected), "matched": [], "missing": [], "wrong_binding": [], "wrong_unit": []}
        for c in expected:
            if c.value is None:
                continue
            cands = [p for p in pred if p.get("value") is not None and units_compatible(p.get("unit"), c.unit)
                     and value_matches(NumberMention(Decimal(str(p["value"])), p.get("unit"), "", 0, 0, 0,
                                                     _decimals(p["value"])), c.value, c.unit, policy)]
            if not cands:
                same_val = [p for p in pred if p.get("value") is not None and math.isclose(float(p["value"]), c.value,
                                                                                          rel_tol=1e-9, abs_tol=1e-9)]
                (out["wrong_unit"] if same_val else out["missing"]).append(c.claim_id)
                continue
            p = cands[0]
            if (c.region and p.get("region") and p["region"] != c.region) or (c.period and p.get("period")
                                                                                and p["period"] != c.period):
                out["wrong_binding"].append(c.claim_id)
            else:
                out["matched"].append(c.claim_id)
        n = max(1, len([c for c in expected if c.value is not None]))
        out["accuracy"] = len(out["matched"]) / n
        return out


def _decimals(x) -> int:
    s = str(x)
    return len(s.split(".")[1]) if "." in s else 0


# ═════════════════════════════ 대체 Fact · Ablation · View 판정 ═════════════════════════════

class FactMatcher:
    """다른 View 가 같은 통계 Fact(같은 정의·좌표·값)를 제공하는지 결정론적으로 확인."""

    def __init__(self, index: MetadataIndex):
        self.index = index

    def _level_map(self, src: ViewMetadata, cand: ViewMetadata) -> dict[str, str] | None:
        out = {}
        for d in src.dimension_definitions:
            m = [x for x in cand.dimension_definitions if x.dim_type == d.dim_type]
            if len(m) > 1:
                m = [x for x in m if x.obj_nm.replace(" ", "") == d.obj_nm.replace(" ", "")] or m[:1]
            if not m:
                return None
            out[d.level] = m[0].level
        return out

    def provides(self, cand_id: str, facts: list[IntermediateFact]) -> tuple[bool, str, dict]:
        """(제공 여부, 이유, 재바인딩 정보 {src_view: {levels, itm_id}})."""
        cand = self.index.view(cand_id)
        if not facts:
            return False, "필요 Fact 없음", {}
        src = self.index.view(facts[0].view_id)
        if cand.observed_or_projected != src.observed_or_projected:
            return False, f"실측/추계 다름 ({cand.observed_or_projected.value})", {}
        if cand.scenario != src.scenario:
            return False, f"시나리오 다름 ({cand.scenario})", {}
        if cand.population_scope != src.population_scope and "UNSPECIFIED" not in (cand.population_scope, src.population_scope):
            return False, f"모집단 다름 ({cand.population_scope})", {}
        if cand.period_frequency != src.period_frequency:
            return False, "주기 다름", {}
        lm = self._level_map(src, cand)
        if lm is None:
            return False, "분류 구조가 다름", {}
        df = self.index.load_frame(cand_id)
        itm_map = {}
        for f in facts:
            item = next((i for i in cand.indicator_definitions if norm_item_name(i.itm_nm) == norm_item_name(f.item_name)), None)
            if item is None:
                return False, f"필수 항목 '{f.item_name}' 없음", {}
            if f.coordinate.PRD_DE not in cand.available_periods:
                return False, f"필수 시점 {f.coordinate.PRD_DE} 없음", {}
            mask = (df["ITM_ID"] == item.itm_id) & (df["PRD_DE"] == f.coordinate.PRD_DE)
            for lv, code in f.coordinate.dims.items():
                clv = lm[lv]
                cm = cand.code_map(clv)
                if code not in cm:
                    return False, f"필수 좌표 {lv}={code}({f.coordinate.dim_names.get(lv)}) 없음", {}
                if cm[code].name.replace(" ", "") != (f.coordinate.dim_names.get(lv) or "").replace(" ", ""):
                    return False, f"코드 {code} 의 이름이 다름 (코드 체계 불일치)", {}
                mask &= df[clv] == code
            rows = df[mask]
            if len(rows) != 1:
                return False, f"좌표의 행 수 {len(rows)} (1 이어야 함)", {}
            pv = parse_value(rows.iloc[0]["DT"])
            if not pv.ok:
                return False, "값이 결측", {}
            try:
                fac = conversion_factor(rows.iloc[0]["UNIT_NM"] or "", f.coordinate.UNIT_NM or "")
            except ValueError:
                return False, "단위 비호환", {}
            if pv.value * fac != Decimal(parse_value(f.coordinate.raw_value).value):
                return False, f"같은 좌표의 값이 다름 ({rows.iloc[0]['DT']} vs {f.coordinate.raw_value}) — 다른 기준", {}
            itm_map[f.item_id] = item.itm_id
        return True, "같은 정의·좌표·값", {"levels": lm, "items": itm_map}


def rebind_plan(plan: OperationPlan, src_view: str, cand_view: str, info: dict) -> OperationPlan:
    p = plan.model_copy(deep=True)
    for o in p.operands:
        if o.view_id != src_view:
            continue
        o.view_id = cand_view
        o.itm_id = info["items"].get(o.itm_id, o.itm_id)
        o.coordinates = {info["levels"].get(lv, lv): c for lv, c in o.coordinates.items()}
        if o.group_by_level:
            o.group_by_level = info["levels"].get(o.group_by_level, o.group_by_level)
    p.required_view_ids = list(dict.fromkeys(o.view_id for o in p.operands))
    return p


class AblationChecker:
    def __init__(self, index: MetadataIndex, engine, cfg: dict | None = None):
        cfg = cfg or {}
        self.index, self.engine = index, engine
        self.matcher = FactMatcher(index)
        self.max_alt_candidates = int(cfg.get("max_alternative_candidates", 60))
        self.confirm = bool(cfg.get("confirm_alternatives_with_engine", True))

    def _candidates(self, facts: list[IntermediateFact], exclude: set[str]) -> list[str]:
        if not facts:
            return []
        v = self.index.view(facts[0].view_id)
        by_item = set()
        for f in facts:
            by_item |= self.index.inv_item.get(norm_item_name(f.item_name), set())
        per = set.intersection(*[self.index.inv_period.get((v.period_frequency, f.coordinate.PRD_DE), set()) for f in facts])
        return sorted((by_item & per) - exclude)[: self.max_alt_candidates]

    def run(self, plan: OperationPlan, calc: CalculationResult, cluster: SampledCluster) -> tuple[list[AblationResult], dict[str, list[str]]]:
        results, alternatives = [], {}
        positives = list(cluster.view_ids)
        final = calc.final.model_dump() if calc.final else None
        for vid in positives:
            facts = [f for f in calc.intermediate_facts if f.view_id == vid]
            if not any(o.view_id == vid for o in plan.operands):
                results.append(AblationResult(view_id=vid, outcome=AblationOutcome.NOT_CONTRIBUTING,
                                              detail="연산 계획에서 이 View 의 값을 쓰지 않음"))
                continue
            rest = [v for v in positives if v != vid]
            # (a) View 를 뺀 채 같은 계획 재실행 — 오류만으로는 필요성을 입증하지 않으므로 기록만
            rerun = self.engine.run(plan, rest, write_evidence=False)
            # (b) 남은 Positive View 가 같은 Fact 를 제공하는지
            repl = []
            for r in rest:
                ok, _, info = self.matcher.provides(r, facts)
                if ok and self._confirm(plan, vid, r, info, rest, final):
                    repl.append(r)
            # (c) 코퍼스 전체에서 대체 Positive 탐색
            alts = []
            for c in self._candidates(facts, set(positives)):
                ok, _, info = self.matcher.provides(c, facts)
                if ok and self._confirm(plan, vid, c, info, rest + [c], final):
                    alts.append(c)
            alternatives[vid] = alts
            outcome = AblationOutcome.REPLACEABLE if repl else AblationOutcome.NECESSARY
            results.append(AblationResult(
                view_id=vid, outcome=outcome, required_fact_ids=[f.fact_id for f in facts], replacement_view_ids=repl,
                rerun_success=rerun.success, rerun_error_code=rerun.error_code.value if rerun.error_code else None,
                detail=("남은 View 가 같은 Fact 를 제공 → 필수 아님" if repl else
                        f"남은 View 로 필수 Fact {len(facts)}개를 얻을 수 없음 (재실행: {rerun.error_code.value if rerun.error_code else 'OK'})")))
        return results, alternatives

    def _confirm(self, plan, src, cand, info, avail, final) -> bool:
        if not self.confirm:
            return True
        rp = rebind_plan(plan, src, cand, info)
        r = self.engine.run(rp, list(dict.fromkeys(avail + [cand])), write_evidence=False)
        return bool(r.success and r.final and final and r.final.model_dump() == final)


class ViewJudge:
    """질문·연산 계획 확정 후 후보 View 를 POSITIVE / ALTERNATIVE_POSITIVE / HARD_NEGATIVE / UNJUDGED 로 분류."""

    def __init__(self, index: MetadataIndex):
        self.index = index
        self.matcher = FactMatcher(index)

    def judge(self, cluster: SampledCluster, calc: CalculationResult, alternatives: dict[str, list[str]],
              candidates: list[str]) -> tuple[list[ViewJudgement], dict[str, dict]]:
        out: list[ViewJudgement] = []
        groups: dict[str, dict] = {}
        for i, vid in enumerate(cluster.view_ids, 1):
            v = self.index.view(vid)
            facts = [f for f in calc.intermediate_facts if f.view_id == vid]
            gid = f"R{i}"
            split = " ".join(v.code_map(lv)[cs[0]].name for lv, cs in v.source_coordinates.dim_filters.items()
                             if cs and cs[0] in v.code_map(lv) and not v.code_map(lv)[cs[0]].is_total)
            desc = "; ".join(sorted({f"{f.period} {f.item_name}" + (f" ({', '.join(f.coordinate_labels.values())})"
                                                                    if f.kind == 'SCALAR' else
                                                                    f" [{split + ', ' if split else ''}지역별]")
                                     for f in facts}))[:200]
            groups[gid] = {"description": desc or v.table_title, "acceptable_view_ids": [vid] + alternatives.get(vid, []),
                           "acceptable_table_ids": list(dict.fromkeys([v.parent_table_id] + [
                               self.index.view(a).parent_table_id for a in alternatives.get(vid, [])])),
                           "required_fact_ids": [f.fact_id for f in facts]}
            out.append(ViewJudgement(view_id=vid, parent_table_id=v.parent_table_id, label=ViewLabel.POSITIVE,
                                     evidence_group=gid, reason="연산 계획의 필수 근거"))
            for a in alternatives.get(vid, []):
                out.append(ViewJudgement(view_id=a, parent_table_id=self.index.view(a).parent_table_id,
                                         label=ViewLabel.ALTERNATIVE_POSITIVE, evidence_group=gid,
                                         reason="같은 정의·좌표·값의 Fact 를 제공 (계획 재실행으로 같은 정답 확인)"))
        judged = {j.view_id for j in out}
        for c in candidates:
            if c in judged:
                continue
            label, reason, grp = ViewLabel.UNJUDGED, "필수 조건 충족 여부를 검증하지 못함", None
            for gid, vid in zip(groups, cluster.view_ids):
                facts = [f for f in calc.intermediate_facts if f.view_id == vid]
                ok, why, _ = self.matcher.provides(c, facts)
                if ok:
                    label, reason, grp = ViewLabel.ALTERNATIVE_POSITIVE, "같은 Fact 제공 (엔진 미확인)", gid
                    break
                if self._verified_negative(why):
                    label, reason, grp = ViewLabel.HARD_NEGATIVE, f"{gid} 필수 조건 미충족: {why}", gid
            out.append(ViewJudgement(view_id=c, parent_table_id=self.index.view(c).parent_table_id, label=label,
                                     evidence_group=grp, reason=reason))
            judged.add(c)
        # 엔진으로 확인하지 못한 ALTERNATIVE 는 UNJUDGED 로 낮춤 (보수적)
        for j in out:
            if j.label == ViewLabel.ALTERNATIVE_POSITIVE and "엔진 미확인" in j.reason:
                j.label, j.reason = ViewLabel.UNJUDGED, "같은 Fact 로 보이나 계획 재실행으로 확인하지 않음"
        return out, groups

    @staticmethod
    def _verified_negative(why: str) -> bool:
        return any(k in why for k in ("필수 시점", "필수 항목", "필수 좌표", "실측/추계", "모집단 다름", "값이 다름", "시나리오 다름",
                                      "코드 체계"))


# ═════════════════════════════ Retriever / Generator 평가 ═════════════════════════════

def _groups(record: GoldenRecord, level: str) -> list[set[str]]:
    gs = record.retrieval_eval.required_evidence_groups
    key = "acceptable_view_ids" if level == "view" else "acceptable_table_ids"
    return [set(getattr(g, key)) for g in gs.values()]


def evaluate_retrieval(record: GoldenRecord, retrieved_view_ids: list[str] | None = None,
                       retrieved_table_ids: list[str] | None = None, ks: Iterable[int] = (1, 3, 5, 10)) -> dict[str, Any]:
    """대체 Positive 그룹 반영. UNJUDGED 는 오답으로 세지 않고 순위에서 제외(condensed list)한다.
    조사명 일치는 Hit 로 인정하지 않는다. 표 ID 기준과 정확한 View 기준을 따로 낸다."""
    out: dict[str, Any] = {"retrieval_eligible": record.retrieval_eval.retrieval_eligible}
    if not record.retrieval_eval.retrieval_eligible:
        out["note"] = "검색 평가 대상 아님"
        return out
    unj = set(record.retrieval_eval.unjudged_view_ids)
    for level, ranked in (("view", retrieved_view_ids), ("table", retrieved_table_ids)):
        if ranked is None:
            continue
        groups = _groups(record, level)
        if level == "view":
            ranked = [r for r in ranked if r not in unj]
            out["n_unjudged_removed"] = len([r for r in (retrieved_view_ids or []) if r in unj])
        rel_any = set().union(*groups) if groups else set()
        ranked = list(dict.fromkeys(ranked))
        first = next((i for i, r in enumerate(ranked, 1) if r in rel_any), None)
        out[f"{level}_MRR"] = 1.0 / first if first else 0.0
        for k in ks:
            top = ranked[:k]
            sat = [bool(g & set(top)) for g in groups]
            out[f"{level}_Hit@{k}"] = float(any(sat))
            out[f"{level}_Any_Hit@{k}"] = float(any(sat))
            out[f"{level}_All_Hit@{k}"] = float(all(sat)) if sat else 0.0
            out[f"{level}_Requirement_Coverage@{k}"] = sum(sat) / len(sat) if sat else 0.0
            out[f"{level}_Recall@{k}"] = sum(sat) / len(sat) if sat else 0.0
            dcg, used = 0.0, set()
            for i, r in enumerate(top, 1):
                gi = next((j for j, g in enumerate(groups) if r in g and j not in used), None)
                if gi is not None:
                    used.add(gi)
                    dcg += 1 / math.log2(i + 1)
            idcg = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(groups)) + 1))
            out[f"{level}_NDCG@{k}"] = dcg / idcg if idcg else 0.0
    out["Table_Hit@K"] = {k: out.get(f"table_Hit@{k}") for k in ks}
    out["View_Hit@K"] = {k: out.get(f"view_Hit@{k}") for k in ks}
    return out


ABSTAIN_RX = re.compile(r"답변(할 수|하기) 어렵|확인할 수 없|자료가 없|제공되지 않|알 수 없|근거가 부족|수록되어 있지 않|"
                        r"집계되지 않|어느 .*인지|명확하지 않|구체적으로 알려|범위를 벗어|추계|아직 공표")


def is_abstention(text: str) -> bool:
    return bool(ABSTAIN_RX.search(text or ""))


def evaluate_generation(record: GoldenRecord, answer_text: str, pred_claims: list[dict] | None = None,
                        pred_coordinates: list[dict] | None = None, pred_operation: str | None = None,
                        abstained: bool | None = None, region_aliases: dict | None = None) -> dict[str, Any]:
    ge = record.generation_eval
    policy = ge.comparison_policy.model_dump()
    out: dict[str, Any] = {}
    abst = is_abstention(answer_text) if abstained is None else abstained
    out["Abstention_Accuracy"] = float(abst == ge.expected_abstention)
    if ge.expected_abstention:
        out["note"] = "답변 불가 유형: 수치 정답 비교 생략"
        return out
    ev = NumericAnswerEvaluator(region_aliases)
    thr = [c.value for c in ge.expected_claims if c.role == "THRESHOLD" and c.value is not None]
    chk = ev.evaluate(answer_text, ge.expected_claims, policy, record.subtype and _final_op(record), allowed_extra=thr)
    out["Numeric_Accuracy"] = float(bool(chk.final_value_ok)) if chk.final_value_ok is not None else None
    out["Unit_Accuracy"] = float(bool(chk.unit_ok)) if chk.unit_ok is not None else None
    out["Intermediate_Fact_Accuracy"] = None
    inters = [c for c in ge.expected_claims if c.role == "INTERMEDIATE"]
    if inters:
        mentions = [m for m in extract_numbers(answer_text) if not m.is_period_token]
        found = sum(1 for c in inters if c.value is not None and
                    any(value_matches(m, c.value, c.unit if m.unit else None, policy) for m in mentions))
        out["Intermediate_Fact_Accuracy"] = found / len(inters)
    entity_claims = [c for c in ge.expected_claims if c.role == "ENTITY"]
    if entity_claims:
        hit = sum(1 for c in entity_claims if any(v in answer_text for v in ev.label_variants(c.value_text)))
        out["Entity_Accuracy"] = hit / len(entity_claims)
        if out["Numeric_Accuracy"] is None:
            out["Numeric_Accuracy"] = out["Entity_Accuracy"]
    parts = [x for x in (out.get("Numeric_Accuracy"), out.get("Intermediate_Fact_Accuracy")) if x is not None]
    out["Answer_Completeness"] = sum(parts) / len(parts) if parts else None
    if pred_claims is not None:
        out["claims"] = NumericAnswerEvaluator.evaluate_claims(pred_claims, ge.expected_claims, policy)
    if pred_coordinates is not None:
        exp = {(c.TBL_ID, c.PRD_DE, c.ITM_ID, tuple(sorted(c.dims.items()))) for c in record.module_eval.M2.expected_source_coordinates}
        got = {(p.get("TBL_ID"), p.get("PRD_DE"), p.get("ITM_ID"), tuple(sorted((p.get("dims") or {}).items())))
               for p in pred_coordinates}
        out["Evidence_Coordinate_Accuracy"] = len(exp & got) / len(exp) if exp else None
    if pred_operation is not None:
        out["Operation_Correctness"] = float(pred_operation.upper() == (_final_op(record) or "").upper())
    out["numeric_check"] = chk.model_dump()
    return out


def _final_op(record: GoldenRecord) -> str | None:
    f = record.module_eval.M1.expected_filters.get("operation")
    return f


# ═════════════════════════════ 단계별 실패 진단 ═════════════════════════════
STAGES = ["QUERY_CONDITION_ERROR", "SOURCE_DATA_MISSING", "RETRIEVAL_MISS", "PARTIAL_RETRIEVAL", "VIEW_GENERATION_ERROR",
          "VIEW_CONDITION_ERROR", "VALUE_MISMATCH", "FINAL_CONTEXT_MISS", "CALCULATION_ERROR", "ANSWER_GENERATION_ERROR",
          "ABSTENTION_ERROR"]


def diagnose_failure(record: GoldenRecord, run_log: dict | None, answer_eval: dict | None = None) -> dict[str, Any]:
    """run_log 형식 (있는 키만 사용):
      {"query_analysis": {"filters": {...}}, "retrieval": {"table_ids": [...], "view_ids": [...]},
       "views": [{"view_id", "tbl_id", "coordinates": [...], "values": [...], "error": str|None}],
       "final_context": {"view_ids": [...]}, "answer": {"text": str}}
    """
    if not run_log:
        return {"first_failure": "INSUFFICIENT_TRACE", "root_cause": "INSUFFICIENT_TRACE", "evidence": "실행 로그 없음"}
    ev: list[str] = []
    first = None
    root = None
    m1 = record.module_eval.M1.expected_filters
    gen = record.generation_eval
    if record.generation_eval.expected_abstention:
        text = (run_log.get("answer") or {}).get("text", "")
        if text and not is_abstention(text):
            return {"first_failure": "ABSTENTION_ERROR", "root_cause": "ABSTENTION_ERROR", "evidence": "근거 없는 답변 생성"}
        return {"first_failure": None, "root_cause": None, "evidence": "정상 Abstention"}
    sd = run_log.get("source_data") or {}
    if sd.get("missing"):
        first = first or "SOURCE_DATA_MISSING"
        ev.append(f"원본 데이터 없음: {sd.get('detail', '')}")
    qa = (run_log.get("query_analysis") or {}).get("filters")
    if qa is not None:
        want_periods = {p[:4] for p in m1.get("periods", [])}
        got_periods = {re.sub(r"\D", "", str(p))[:4] for p in (qa.get("시점") or qa.get("periods") or [])}
        want_regions = set(m1.get("regions", []))
        got_regions = set(qa.get("지역") or qa.get("regions") or [])
        if (want_periods and got_periods and not want_periods <= got_periods) or \
                (want_regions and got_regions and not want_regions & got_regions):
            first = first or "QUERY_CONDITION_ERROR"
            ev.append(f"조건 추출 불일치: 시점 {got_periods} vs {want_periods}, 지역 {got_regions} vs {want_regions}")
    r = run_log.get("retrieval")
    if r is not None:
        groups = _groups(record, "table")
        got = set(r.get("table_ids") or [])
        sat = [bool(g & got) for g in groups]
        if groups and not any(sat):
            first = first or "RETRIEVAL_MISS"
            ev.append("필수 표를 하나도 검색하지 못함")
        elif groups and not all(sat):
            first = first or "PARTIAL_RETRIEVAL"
            ev.append(f"필수 근거 그룹 {sum(sat)}/{len(sat)} 만 검색")
    vs = run_log.get("views")
    if vs is not None:
        if any(v.get("error") for v in vs):
            first = first or "VIEW_GENERATION_ERROR"
            ev.append("View 생성 오류")
        exp_vals = {(c.region, c.period): c.value for c in gen.expected_claims if c.role == "INTERMEDIATE"}
        got_vals = [x for v in vs for x in (v.get("values") or [])]
        if exp_vals and got_vals:
            vals = [float(x.get("value")) for x in got_vals if x.get("value") is not None]
            missing = [k for k, val in exp_vals.items() if not any(math.isclose(val, g, rel_tol=1e-9) for g in vals)]
            if missing:
                cond = [x for x in got_vals if (x.get("region"), x.get("period")) in exp_vals]
                code = "VALUE_MISMATCH" if cond else "VIEW_CONDITION_ERROR"
                first = first or code
                ev.append(f"{code}: 기대 원본값 {len(missing)}개를 View 에서 찾지 못함")
    fc = run_log.get("final_context")
    if fc is not None:
        groups = _groups(record, "view")
        got = set(fc.get("view_ids") or [])
        if groups and not all(g & got for g in groups):
            first = first or "FINAL_CONTEXT_MISS"
            ev.append("최종 문맥에 필수 근거 그룹 누락")
    ans = run_log.get("answer")
    if ans is not None:
        ae = answer_eval or evaluate_generation(record, ans.get("text", ""))
        if ae.get("Numeric_Accuracy") == 0.0:
            inter_ok = ae.get("Intermediate_Fact_Accuracy")
            code = "CALCULATION_ERROR" if inter_ok == 1.0 else "ANSWER_GENERATION_ERROR"
            first = first or code
            ev.append(f"{code}: 최종 수치 불일치")
    if first is None:
        return {"first_failure": None, "root_cause": None, "evidence": "; ".join(ev) or "실패 없음"}
    root = first
    if first in ("RETRIEVAL_MISS", "PARTIAL_RETRIEVAL") and any("조건 추출" in e for e in ev):
        root = "QUERY_CONDITION_ERROR"
    return {"first_failure": first, "root_cause": root, "evidence": "; ".join(ev)}
