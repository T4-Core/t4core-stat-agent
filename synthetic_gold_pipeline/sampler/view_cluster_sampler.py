"""Compatibility Graph 기반 2~3 View 클러스터 샘플링 + Hard Negative 후보 탐색.

- 샘플마다 고유 sample_id 와 random seed (base_seed, attempt_index 로 결정 → 재현 가능)
- 조사명·원본 표·연산 유형(subtype)·지역·시점 분포를 세어 적게 뽑힌 쪽에 가중치를 준다
- 같은 표가 너무 많이 뽑히지 않도록 표·조사별 상한을 둔다
- SINGLE_TABLE_MULTI_VIEW / MULTI_TABLE_MULTI_VIEW 를 구분한다 (View 가 여러 개라도 표가 하나면 SINGLE_TABLE)
"""
from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field

from synthetic_gold_pipeline.sampler.compatibility_graph import CompatibilityGraph, EdgeInfo, items_match
from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex, norm_item_name
from synthetic_gold_pipeline.schemas.metadata import DimensionType, ValueKind, ViewMetadata
from synthetic_gold_pipeline.schemas.planning import HopType, ReasoningType, SampledCluster
from synthetic_gold_pipeline.tools.units import name_is_additive, unit_info

SUBTYPES: dict[ReasoningType, list[str]] = {
    ReasoningType.SIMPLE_LOOKUP: ["LOOKUP"],                        # [NEW 11-12] View 1개에서 값 하나 (쉬운 평가셋)
    ReasoningType.TIME_SERIES_COMPARISON: ["GROWTH_RATE", "DIFFERENCE", "PP_DIFFERENCE"],
    ReasoningType.CROSS_TABLE_RATIO: ["SHARE", "RATE_PER"],
    ReasoningType.CONDITIONAL_AGGREGATION: ["FILTER_SUM", "FILTER_COUNT", "FILTER_MEAN", "FILTER_TOP_K", "RATIO_TOP_K",
                                            "CLASS_DIFF_COUNT", "FILTERED_GROWTH_TOP"],
}


def seed_for(base_seed: int, attempt_index: int) -> int:
    return (int(base_seed) * 1_000_003 + int(attempt_index) * 7919) % (2 ** 31 - 1)


def view_kind(v: ViewMetadata) -> ValueKind:
    if len(v.units) != 1:
        return ValueKind.UNKNOWN
    k = unit_info(v.units[0]).kind
    if k in (ValueKind.COUNT, ValueKind.AMOUNT) and not all(name_is_additive(i.itm_nm) for i in v.indicator_definitions):
        return ValueKind.MEAN if any(re.search(r"평균|중위", i.itm_nm or "") for i in v.indicator_definitions) else ValueKind.RATE
    return k


COMPLEX_ITEM = re.compile(r"\bt\s*\+\s*\d|\bt\s*년|변화\s*비율|전이|코호트")


def n_conditions(v: ViewMetadata) -> int:
    """질문에 반드시 써야 하는 비총계 조건 수 = 분할 조건(비총계) + 총계가 없는 자유 분류 (지역 제외)"""
    n = 0
    split = v.source_coordinates.dim_filters
    for d in v.dimension_definitions:
        if d.dim_type == DimensionType.REGION:
            continue
        cm = v.code_map(d.level)
        if d.level in split:
            n += any(c in cm and not cm[c].is_total for c in split[d.level])
        elif len(cm) > 1 and not any(c.is_total for c in cm.values()):
            n += 1
    return n


UNKNOWN_LABEL = re.compile(r"^\s*(미상|기타|불명|무응답|모름|알\s*수\s*없음|해당\s*없음|해당사항\s*없음)\s*$|\(미상\)|_미상$")


def has_unknown_label(v: ViewMetadata) -> bool:
    """항목이나 고정 분류가 '미상·기타' 인 View — 질문으로 만들면 뜻이 없음 (실데이터: '공식 항목명 미상 누락' 탈락)"""
    if any(UNKNOWN_LABEL.search(i.itm_nm or "") for i in v.indicator_definitions):
        return True
    for lv, cs in v.source_coordinates.dim_filters.items():
        cm = v.code_map(lv)
        if any(c in cm and UNKNOWN_LABEL.search(cm[c].name or "") for c in cs):
            return True
    return False


def region_level(v: ViewMetadata) -> str | None:
    d = v.dims_of_type(DimensionType.REGION)
    return d[0].level if d else None


def single_item_period(v: ViewMetadata) -> bool:
    return len(v.source_coordinates.itm_ids) == 1 and len(v.available_periods) == 1


@dataclass
class SamplerState:
    by_table: Counter = field(default_factory=Counter)
    by_survey: Counter = field(default_factory=Counter)
    by_subtype: Counter = field(default_factory=Counter)
    by_period: Counter = field(default_factory=Counter)
    by_region: Counter = field(default_factory=Counter)
    attempts_by_table: Counter = field(default_factory=Counter)

    def to_json(self) -> dict:
        return {k: dict(v) for k, v in self.__dict__.items()}

    @classmethod
    def from_json(cls, d: dict) -> "SamplerState":
        return cls(**{k: Counter(v) for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


class ViewClusterSampler:
    def __init__(self, index: MetadataIndex, graph: CompatibilityGraph, cfg: dict | None = None,
                 base_seed: int = 42, state: SamplerState | None = None):
        cfg = cfg or {}
        self.index, self.graph = index, graph
        self.base_seed = base_seed
        self.state = state or SamplerState()
        self.max_per_table = int(cfg.get("max_samples_per_table", 6))
        self.max_per_survey = int(cfg.get("max_samples_per_survey", 20))
        self.max_attempts_per_table = int(cfg.get("max_attempts_per_table", 40))
        self.alpha = float(cfg.get("diversity_alpha", 1.0))
        # 표 균형: View 가중치를 그 표의 View 수로 나눠 '표마다 같은 확률' 로 (안 하면 View 60개 표가 1개 표보다 60배 자주 뽑힘)
        self.table_balance = bool(cfg.get("table_balance", True))
        self.attempt_decay = float(cfg.get("attempt_decay", 0.3))      # 시도했지만 탈락한 표는 조금씩 덜 뽑음
        self.views_per_table = Counter(v.parent_table_id for v in index.views.values())
        # 사람이 물을 만한 질문만: 조건이 너무 많은 View · 패널 전이표(t+3년 변화 비율 등) · 이름이 너무 긴 항목 제외
        self.max_conditions = int(cfg.get("max_conditions_per_view", 2))
        self.max_item_len = int(cfg.get("max_item_name_length", 30))
        self.anchor_tries = int(cfg.get("max_anchor_tries", 25))
        self.hn_per_view = int(cfg.get("hard_negative_candidates_per_view", 6))
        self.subtype_weights = cfg.get("subtype_weights", {})
        # [NEW 11-12] 쉬운 평가셋용 View 거르기 (기본은 모두 꺼짐 = 예전과 같음)
        #   min_year: 이 해보다 옛 시점 View 제외 · exclude_table_title_patterns: 표 이름이 맞으면 제외 (연도·항목별로 쪼갠 표 묶음 등)
        #   lookup_kinds: 단순 조회에 쓸 값 종류 (COUNT·AMOUNT·RATE·MEAN …)
        self.min_year = int(cfg["min_year"]) if cfg.get("min_year") else None
        self.title_exclude = [re.compile(x) for x in cfg.get("exclude_table_title_patterns") or []]
        self.lookup_kinds = tuple(ValueKind(k) for k in cfg.get("lookup_kinds") or ["COUNT", "AMOUNT", "RATE"])
        self.min_common = graph.min_common
        rr = cfg.get("ratio_rules", {})
        import re as _re
        self.share_inc = [_re.compile(x) for x in rr.get("share_denominator_include_patterns", [])]
        self.share_exc = [_re.compile(x) for x in rr.get("share_denominator_exclude_patterns", [])]
        self.rate_den_families = set(rr.get("rate_per_denominator_families", ["PERSON"]))
        # 단위당 비율의 분모는 '인구·가구 기반' 만 (혼인건수 ÷ 외국인 입국자 같은 억지 조합 방지)
        self.rate_inc = [_re.compile(x) for x in rr.get("rate_per_denominator_include_patterns",
                                                        ["총인구", "^인구수?$", "주민등록인구", "추계인구", "^총?가구수?$",
                                                         "^일반가구(수)?$"])]
        self.rate_exc = [_re.compile(x) for x in rr.get("rate_per_denominator_exclude_patterns",
                                                        ["외국인", "입국", "출국", "남자", "여자"])]
        self.indicator_families = cfg.get("indicator_families") or [["인구", "주민"], ["가구"], ["혼인"], ["출생"], ["사망"],
                                                                    ["전입", "전출", "이동"], ["취업", "경제활동"]]

    @staticmethod
    def _narrower(a: ViewMetadata, b: ViewMetadata) -> bool:
        """분모 View(b)의 분할 조건이 비총계이고 분자(a)와 다르면 True (분모가 분자를 포함하지 않음)."""
        for lv, cs in b.source_coordinates.dim_filters.items():
            d = b.dim(lv)
            c = b.code_map(lv).get(cs[0]) if cs else None
            if not d or not c or c.is_total or d.dim_type == DimensionType.SCENARIO:
                continue
            same = [x for x in a.source_coordinates.dim_filters.items() if a.dim(x[0]) and a.dim(x[0]).dim_type == d.dim_type]
            if not same or a.code_map(same[0][0]).get(same[0][1][0]) is None or \
                    a.code_map(same[0][0])[same[0][1][0]].name != c.name:
                return True
        return False

    def _denominator_ok(self, b: ViewMetadata, same_family: bool) -> bool:
        nm = b.indicator_definitions[0].itm_nm if b.indicator_definitions else ""
        if same_family:
            if self.share_inc and not any(p.search(nm) for p in self.share_inc):
                return False
            return not any(p.search(nm) for p in self.share_exc)
        if len(b.units) != 1:
            return False
        if unit_info(b.units[0]).family not in self.rate_den_families:
            return False
        nm = nm.strip()
        return any(p.search(nm) for p in self.rate_inc) and not any(p.search(nm) for p in self.rate_exc)

    # ── 가중치 ────────────────────────────────────────────────────
    def _w(self, v: ViewMetadata) -> float:
        s = self.state
        if s.by_table[v.parent_table_id] >= self.max_per_table or s.by_survey[v.survey_name] >= self.max_per_survey:
            return 0.0
        if s.attempts_by_table[v.parent_table_id] >= self.max_attempts_per_table:
            return 0.0
        w = 1.0 / ((1 + s.by_table[v.parent_table_id]) ** self.alpha * (1 + 0.5 * s.by_survey[v.survey_name])
                   * (1 + 0.3 * sum(s.by_period[p] for p in v.available_periods)))
        if self.table_balance:
            w /= max(1, self.views_per_table[v.parent_table_id])
        if self.attempt_decay:
            w /= 1 + self.attempt_decay * s.attempts_by_table[v.parent_table_id]
        return w

    def _pick(self, rng: random.Random, views: list[ViewMetadata]) -> ViewMetadata | None:
        ws = [self._w(v) for v in views]
        if not views or sum(ws) <= 0:
            return None
        return rng.choices(views, weights=ws, k=1)[0]

    def _choose_subtype(self, rng: random.Random, rt: ReasoningType) -> list[str]:
        subs = list(SUBTYPES[rt])
        w = [float(self.subtype_weights.get(s, 1.0)) / (1 + self.state.by_subtype[s]) for s in subs]
        order = []
        while subs:
            i = rng.choices(range(len(subs)), weights=w, k=1)[0] if sum(w) > 0 else 0
            order.append(subs.pop(i))
            w.pop(i)
        return order

    # ── 샘플링 ────────────────────────────────────────────────────
    def sample(self, rt: ReasoningType, attempt_index: int) -> SampledCluster | None:
        seed = seed_for(self.base_seed, attempt_index)
        rng = random.Random(seed)
        for sub in self._choose_subtype(rng, rt):
            res = getattr(self, f"_s_{sub.lower()}")(rng)
            if res is None:
                continue
            views, join, notes = res
            if any(len(v.units) != 1 for v in views):        # 단위가 비었거나 여러 개인 View 는 단위 검증·변환 불가 → 다른 조합
                continue
            if any(has_unknown_label(v) for v in views):     # '미상·기타' 항목·분류는 질문 대상에서 제외
                continue
            if any(self._too_complex(v) for v in views):      # 조건이 많거나 패널 전이표 → 사람이 묻지 않을 질문
                continue
            tables = list(dict.fromkeys(v.parent_table_id for v in views))
            hop = (HopType.SINGLE_TABLE_SINGLE_VIEW if len(views) == 1 else
                   HopType.SINGLE_TABLE_MULTI_VIEW if len(tables) == 1 else HopType.MULTI_TABLE_MULTI_VIEW)
            ids = [v.view_id for v in views]
            for v in views:
                self.state.attempts_by_table[v.parent_table_id] += 1
            return SampledCluster(
                sample_id=f"S{attempt_index:06d}_{seed % 100000:05d}", attempt_index=attempt_index, random_seed=seed,
                reasoning_type=rt, subtype=sub, hop_type=hop, view_ids=ids, table_ids=tables,
                join_dimension_type=join[0] if join else None, join_levels=join[1] if join else {},
                common_codes=join[2] if join else [], hard_negative_candidates=self.hard_negative_candidates(ids),
                notes=notes)
        return None

    def register_accepted(self, cluster: SampledCluster, regions: list[str] | None = None,
                          periods: list[str] | None = None):
        for t in cluster.table_ids:
            self.state.by_table[t] += 1
        for s in {self.index.view(v).survey_name for v in cluster.view_ids}:
            self.state.by_survey[s] += 1
        self.state.by_subtype[cluster.subtype] += 1
        for p in periods or []:
            self.state.by_period[p] += 1
        for r in regions or []:
            self.state.by_region[r] += 1

    def _too_complex(self, v: ViewMetadata) -> bool:
        if n_conditions(v) > self.max_conditions:
            return True
        return any(COMPLEX_ITEM.search(i.itm_nm or "") or len(i.itm_nm or "") > self.max_item_len
                   for i in v.indicator_definitions)

    def _easy_ok(self, v: ViewMetadata) -> bool:
        """[NEW 11-12] min_year · exclude_table_title_patterns (설정이 없으면 늘 True)"""
        if self.min_year:
            years = [int(m.group(0)) for p in v.available_periods for m in [re.match(r"\d{4}", str(p))] if m]
            if not years or min(years) < self.min_year:
                return False
        return not any(rx.search(v.table_title or "") for rx in self.title_exclude)

    # 공통: 1차원 View 목록
    def _base(self, pred) -> list[ViewMetadata]:
        return [v for v in self.index.views.values()
                if single_item_period(v) and len(v.units) == 1 and self._easy_ok(v) and pred(v)]

    def _s_lookup(self, rng):
        """[NEW 11-12] SIMPLE_LOOKUP: View 하나 (값 하나를 그대로 읽음). 지역 코드는 계획 단계가 고름"""
        anchors = self._base(lambda v: view_kind(v) in self.lookup_kinds)
        a = self._pick(rng, anchors)
        return ([a], None, ["LOOKUP: View 하나의 값 하나"]) if a is not None else None

    def _join_tuple(self, edges: list[tuple[ViewMetadata, ViewMetadata, EdgeInfo]]):
        levels, common = {}, None
        dim = None
        for va, vb, e in edges:
            j = e.best_join(self.min_common) if e.join else None
            if j is None:
                if va.parent_table_id == vb.parent_table_id and region_level(va):
                    lv = region_level(va)
                    levels.setdefault(va.view_id, lv)
                    levels.setdefault(vb.view_id, lv)
                    cc = sorted(set(va.code_map(lv)) & set(vb.code_map(lv)))
                    common = cc if common is None else sorted(set(common) & set(cc))
                    dim = DimensionType.REGION.value
                continue
            dim = dim or j.dim_type
            levels.setdefault(va.view_id, j.level_a)
            levels.setdefault(vb.view_id, j.level_b)
            common = j.common_codes if common is None else sorted(set(common) & set(j.common_codes))
        return (dim, levels, common or []) if dim else None

    def _s_growth_rate(self, rng, kinds=(ValueKind.COUNT, ValueKind.AMOUNT), sub="GROWTH_RATE"):
        anchors = self._base(lambda v: view_kind(v) in kinds)
        for _ in range(self.anchor_tries):
            a = self._pick(rng, anchors)
            if a is None:
                return None
            nb = [self.index.view(o) for o, _ in self.graph.neighbors(a.view_id, "TIME_SERIES")
                  if single_item_period(self.index.view(o)) and self._easy_ok(self.index.view(o))]
            if not nb:
                anchors = [x for x in anchors if x.view_id != a.view_id]
                continue
            b = nb[rng.randrange(len(nb))]
            old, new = sorted([a, b], key=lambda v: v.available_periods[0])
            j = self._join_tuple([(old, new, self.graph.edge(old.view_id, new.view_id))])
            return [old, new], j, [f"{sub}: 같은 표·항목의 두 시점"]
        return None

    def _s_difference(self, rng):
        r = self._s_growth_rate(rng, sub="DIFFERENCE")
        return r

    def _s_pp_difference(self, rng):
        return self._s_growth_rate(rng, kinds=(ValueKind.RATE,), sub="PP_DIFFERENCE")

    def _ratio_pair(self, rng, same_family: bool | None, cross_table: bool = True):
        anchors = self._base(lambda v: view_kind(v) in (ValueKind.COUNT, ValueKind.AMOUNT))
        for _ in range(self.anchor_tries):
            a = self._pick(rng, anchors)
            if a is None:
                return None
            cands = []
            for o, e in self.graph.neighbors(a.view_id, "RATIO"):
                b = self.index.view(o)
                if not single_item_period(b) or not self._easy_ok(b) or (cross_table and b.parent_table_id == a.parent_table_id):
                    continue
                if b.available_periods != a.available_periods or len(b.units) != 1:
                    continue
                if view_kind(b) not in (ValueKind.COUNT, ValueKind.AMOUNT):       # 분모도 개수·금액만
                    continue
                fa, fb = unit_info(a.units[0]).family, unit_info(b.units[0]).family
                if same_family is not None and (fa == fb) != same_family:
                    continue
                if not self._denominator_ok(b, fa == fb):
                    continue
                if items_match(a, b):          # 같은 지표끼리의 비율(예: 신·구 표의 총인구)은 의미 없음
                    continue
                if fa == fb and self._narrower(a, b):
                    continue
                if e.best_join(1) is None and not (not cross_table and e.same_table):
                    continue
                cands.append((b, e))
            if not cands:
                anchors = [x for x in anchors if x.view_id != a.view_id]
                continue
            ws = [self._w(b) or 0.01 for b, _ in cands]
            b, e = rng.choices(cands, weights=ws, k=1)[0]
            return a, b, e
        return None

    def _s_share(self, rng):
        r = self._ratio_pair(rng, same_family=True)
        if not r:
            return None
        a, b, e = r
        return [a, b], self._join_tuple([(a, b, e)]), ["SHARE: 같은 단위 계열, 서로 다른 표의 분자/분모"]

    def _s_rate_per(self, rng):
        r = self._ratio_pair(rng, same_family=False)
        if not r:
            return None
        a, b, e = r
        return [a, b], self._join_tuple([(a, b, e)]), ["RATE_PER: 서로 다른 단위 계열 (예: 건/천명)"]

    def _cond_pair(self, rng, metric_kinds, cross_table_first=True):
        anchors = self._base(lambda v: view_kind(v) in metric_kinds and region_level(v) is not None)
        for _ in range(self.anchor_tries):
            a = self._pick(rng, anchors)
            if a is None:
                return None
            cands = []
            for o, e in self.graph.neighbors(a.view_id, "CONDITIONAL"):
                b = self.index.view(o)
                if not single_item_period(b) or b.available_periods != a.available_periods:
                    continue
                if b.parent_table_id == a.parent_table_id and b.source_coordinates.itm_ids == a.source_coordinates.itm_ids:
                    continue
                j = e.best_join(self.min_common)
                if j is None or j.dim_type != DimensionType.REGION.value or len(j.common_non_total) < 3:
                    continue
                cands.append((b, e))
            if cross_table_first and any(b.parent_table_id != a.parent_table_id for b, _ in cands):
                cands = [(b, e) for b, e in cands if b.parent_table_id != a.parent_table_id]
            if not cands:
                anchors = [x for x in anchors if x.view_id != a.view_id]
                continue
            ws = [self._w(b) or 0.01 for b, _ in cands]
            b, e = rng.choices(cands, weights=ws, k=1)[0]
            return a, b, e
        return None

    def _cond(self, rng, sub, kinds):
        r = self._cond_pair(rng, kinds)
        if not r:
            return None
        a, b, e = r
        return [a, b], self._join_tuple([(a, b, e)]), [f"{sub}: 지표 View + 조건 View (공통 지역 코드)"]

    def _s_filter_sum(self, rng):
        return self._cond(rng, "FILTER_SUM", (ValueKind.COUNT, ValueKind.AMOUNT))

    def _s_filter_count(self, rng):
        return self._cond(rng, "FILTER_COUNT", tuple(ValueKind))

    def _s_filter_mean(self, rng):
        return self._cond(rng, "FILTER_MEAN", (ValueKind.COUNT, ValueKind.AMOUNT))

    def _s_filter_top_k(self, rng):
        return self._cond(rng, "FILTER_TOP_K", tuple(ValueKind))

    def _s_ratio_top_k(self, rng):
        r = self._ratio_pair(rng, same_family=None, cross_table=False)
        if not r:
            return None
        a, b, e = r
        j = self._join_tuple([(a, b, e)])
        if not j or j[0] != DimensionType.REGION.value or len([c for c in j[2]
                                                               if not a.code_map(j[1][a.view_id])[c].is_total]) < 3:
            return None
        return [a, b], j, ["RATIO_TOP_K: 지역별 비율 상위 K"]

    def _s_class_diff_count(self, rng):
        """같은 표·항목·시점, 분류 코드만 다른 두 View (예: 가구주 성별 남/여) → 지역별 차이의 부호로 집계."""
        groups: dict[tuple, list[ViewMetadata]] = {}
        def class_levels(v):        # 시나리오 분할은 '분류'가 아님 (시나리오 혼합 금지)
            return tuple(sorted(lv for lv in v.source_coordinates.dim_filters
                                if v.dim(lv) and v.dim(lv).dim_type != DimensionType.SCENARIO))
        for v in self._base(lambda v: bool(class_levels(v)) and region_level(v) is not None):
            k = (v.parent_table_id, tuple(v.source_coordinates.itm_ids), tuple(v.available_periods), class_levels(v),
                 v.scenario)
            groups.setdefault(k, []).append(v)
        opts = []
        for g in groups.values():
            non_total = [v for v in g if not any(
                c.is_total for lv, codes in v.source_coordinates.dim_filters.items()
                for c in v.dimension_codes.get(lv, []) if c.code in codes)]
            if len(non_total) >= 2:
                opts.append(sorted(non_total, key=lambda v: v.view_id))
        if not opts:
            return None
        ws = [self._w(g[0]) for g in opts]
        if sum(ws) <= 0:
            return None
        g = rng.choices(opts, weights=ws, k=1)[0]
        a, b = rng.sample(g, 2)
        a, b = sorted([a, b], key=lambda v: str(v.source_coordinates.dim_filters))
        lv = region_level(a)
        common = sorted(set(a.code_map(lv)) & set(b.code_map(lv)))
        return [a, b], (DimensionType.REGION.value, {a.view_id: lv, b.view_id: lv}, common), \
            ["CLASS_DIFF_COUNT: 같은 표의 서로 다른 분류 View"]

    def _s_filtered_growth_top(self, rng):
        """A(t1), A(t2) [같은 표] + 조건 B(t2) [다른 표] → 3 View."""
        anchors = self._base(lambda v: view_kind(v) in (ValueKind.COUNT, ValueKind.AMOUNT) and region_level(v) is not None)
        for _ in range(self.anchor_tries):
            a2 = self._pick(rng, anchors)
            if a2 is None:
                return None
            olds = [self.index.view(o) for o, _ in self.graph.neighbors(a2.view_id, "TIME_SERIES")]
            olds = [o for o in olds if single_item_period(o) and o.available_periods[0] < a2.available_periods[0]]
            conds = []
            for o, e in self.graph.neighbors(a2.view_id, "CONDITIONAL"):
                b = self.index.view(o)
                j = e.best_join(self.min_common)
                if (single_item_period(b) and b.parent_table_id != a2.parent_table_id and j
                        and j.dim_type == DimensionType.REGION.value and len(j.common_non_total) >= 3
                        and b.available_periods == a2.available_periods):
                    conds.append((b, e))
            if not olds or not conds:
                anchors = [x for x in anchors if x.view_id != a2.view_id]
                continue
            a1 = olds[rng.randrange(len(olds))]
            b, e = conds[rng.randrange(len(conds))]
            j = self._join_tuple([(a1, a2, self.graph.edge(a1.view_id, a2.view_id)), (a2, b, e)])
            if not j or len(j[2]) < 3:
                continue
            return [a1, a2, b], j, ["FILTERED_GROWTH_TOP: 두 시점 증감률 + 다른 표 조건"]
        return None

    # ── Hard Negative 후보 ───────────────────────────────────────
    def similar_indicator(self, a: ViewMetadata, b: ViewMetadata) -> bool:
        """같은 단위 계열 + 같은 지표 계열 키워드 (예: 인구·주민 / 가구 / 혼인 / 전입·전출)."""
        if not (a.units and b.units) or unit_info(a.units[0]).family != unit_info(b.units[0]).family:
            return False
        na = " ".join(i.itm_nm for i in a.indicator_definitions)
        nb = " ".join(i.itm_nm for i in b.indicator_definitions)
        return any(any(k in na for k in fam) and any(k in nb for k in fam) for fam in self.indicator_families)

    def hard_negative_candidates(self, positive_ids: list[str]) -> list[str]:
        pos = set(positive_ids)
        out: list[str] = []
        for pid in positive_ids:
            p = self.index.view(pid)
            cand: list[str] = []
            same_tbl = [self.index.view(o) for o in sorted(self.index.inv_table.get(p.parent_table_id, ())) if o not in pos]
            cand += [v.view_id for v in same_tbl if v.source_coordinates.itm_ids == p.source_coordinates.itm_ids
                     and v.available_periods != p.available_periods]                 # 같은 표 다른 시점
            cand += [v.view_id for v in same_tbl if v.source_coordinates.itm_ids != p.source_coordinates.itm_ids
                     and v.available_periods == p.available_periods]                 # 같은 표 다른 항목(하위 분류)
            cand += [v.view_id for v in same_tbl if v.input_mode != p.input_mode]   # 저장된 View(지역 부분집합 등)
            others = set()
            for i in p.indicator_definitions:
                others |= self.index.inv_item.get(norm_item_name(i.itm_nm), set())
            for per in p.available_periods:
                others |= {o for o in self.index.inv_period.get((p.period_frequency, per), set())
                           if items_match(p, self.index.view(o)) or self.similar_indicator(p, self.index.view(o))}
            rl = region_level(p)
            pcodes = set(p.code_map(rl)) if rl else set()
            for o in sorted(others - pos - {pid}):
                v = self.index.view(o)
                if v.parent_table_id == p.parent_table_id:
                    continue
                vl = region_level(v)
                if rl and vl and not (pcodes & set(v.code_map(vl))):
                    continue
                cand.append(o)
            seen = list(dict.fromkeys(c for c in cand if c not in pos))
            out += seen[: self.hn_per_view]
        return list(dict.fromkeys(out))
