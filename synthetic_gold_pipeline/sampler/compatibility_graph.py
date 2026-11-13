"""View 간 Compatibility Graph — 구조적 호환성과 의미적 호환성을 구분해 기록한다.

전체 View 쌍을 비교하지 않는다. 역색인(MetadataIndex.inv_*)으로 후보 이웃만 찾고,
간선은 필요할 때 계산해 캐시한다 (대용량 코퍼스 대응). 소규모 코퍼스는 build_all() 로 전부 계산 가능.

연산 계열(op family)별로 허용 여부와 이유를 따로 둔다:
  TIME_SERIES   같은 지표의 서로 다른 시점 비교 (증감량·증감률·%p)
  RATIO         같은 시점의 두 지표 비율 (분자·분모 모집단·단위·시점 검증)
  CONDITIONAL   같은 시점, 공통 키로 한 View 의 조건을 다른 View 에 적용 (필터·집계·순위)
  SIDE_BY_SIDE  산술 결합 없이 나란히 제시 (조사 기준이 달라도 가능할 수 있음)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex, norm_item_name
from synthetic_gold_pipeline.schemas.metadata import DimensionType, ObservationType, ViewMetadata
from synthetic_gold_pipeline.tools.units import name_is_additive, unit_info
from synthetic_gold_pipeline.utils import norm_text, write_jsonl

JOIN_DIM_TYPES = [DimensionType.REGION, DimensionType.SEX, DimensionType.AGE, DimensionType.HOUSEHOLD,
                  DimensionType.NATIONALITY, DimensionType.INDUSTRY]
OP_FAMILIES = ("TIME_SERIES", "RATIO", "CONDITIONAL", "SIDE_BY_SIDE")


def norm_code_name(s: str) -> str:
    return norm_text(s).replace(" ", "")


@dataclass
class JoinCandidate:
    dim_type: str
    level_a: str
    level_b: str
    common_codes: list[str]
    common_non_total: list[str]
    name_mismatches: list[dict[str, str]]
    structural_ok: bool
    reason: str = ""


@dataclass
class EdgeInfo:
    a: str
    b: str
    same_table: bool
    same_frequency: bool
    period_relation: str            # SAME | DIFFERENT | INCOMPARABLE_FREQUENCY
    join: list[JoinCandidate]
    same_item: bool
    unit_families: tuple[str | None, str | None]
    observed: tuple[str, str]
    scopes: tuple[str, str]
    scenarios: tuple[str | None, str | None]
    duplicate_risk: bool
    allowed: dict[str, bool] = field(default_factory=dict)
    reasons: dict[str, list[str]] = field(default_factory=dict)

    def best_join(self, min_common: int = 2) -> JoinCandidate | None:
        ok = [j for j in self.join if j.structural_ok and len(j.common_non_total) >= min_common]
        ok.sort(key=lambda j: (j.dim_type != DimensionType.REGION.value, -len(j.common_non_total)))
        return ok[0] if ok else None

    def to_json(self) -> dict[str, Any]:
        return {"a": self.a, "b": self.b, "same_table": self.same_table, "same_frequency": self.same_frequency,
                "period_relation": self.period_relation, "same_item": self.same_item,
                "unit_families": list(self.unit_families), "observed": list(self.observed), "scopes": list(self.scopes),
                "scenarios": list(self.scenarios), "duplicate_risk": self.duplicate_risk,
                "join": [j.__dict__ for j in self.join], "allowed": self.allowed, "reasons": self.reasons}


class CompatibilityGraph:
    def __init__(self, index: MetadataIndex, cfg: dict | None = None):
        cfg = cfg or {}
        self.index = index
        self.min_common = int(cfg.get("min_common_join_codes", 2))
        self.max_name_mismatch = float(cfg.get("max_join_name_mismatch_ratio", 0.0))
        self.incompatible_scopes = {frozenset(p) for p in cfg.get("incompatible_population_scopes", [])}
        self.equivalent_tables = [set(g) for g in cfg.get("time_series_equivalent_tables", [])]
        self.max_neighbors = int(cfg.get("max_neighbor_candidates", 400))
        self._edges: dict[tuple[str, str], EdgeInfo] = {}

    # ── 후보 이웃 (역색인) ────────────────────────────────────────
    def candidate_neighbors(self, view_id: str) -> list[str]:
        v = self.index.view(view_id)
        score: dict[str, int] = {}
        for d in v.dimension_definitions:
            if d.dim_type not in JOIN_DIM_TYPES:
                continue
            for c in v.dimension_codes.get(d.level, []):
                if c.is_total:
                    continue
                for o in self.index.inv_code.get((d.dim_type.value, c.code), ()):
                    if o != view_id:
                        score[o] = score.get(o, 0) + 1
        for o in self.index.inv_table.get(v.parent_table_id, ()):
            if o != view_id:
                score[o] = score.get(o, 0) + 1000
        ranked = sorted(score, key=lambda o: (-score[o], o))
        return ranked[: self.max_neighbors]

    def edge(self, a: str, b: str) -> EdgeInfo:
        key = (a, b) if a <= b else (b, a)
        if key not in self._edges:
            self._edges[key] = self._evaluate(self.index.view(key[0]), self.index.view(key[1]))
        e = self._edges[key]
        if (e.a, e.b) != (a, b):
            return EdgeInfo(a=a, b=b, same_table=e.same_table, same_frequency=e.same_frequency,
                            period_relation=e.period_relation,
                            join=[JoinCandidate(j.dim_type, j.level_b, j.level_a, j.common_codes, j.common_non_total,
                                                j.name_mismatches, j.structural_ok, j.reason) for j in e.join],
                            same_item=e.same_item, unit_families=e.unit_families[::-1], observed=e.observed[::-1],
                            scopes=e.scopes[::-1], scenarios=e.scenarios[::-1], duplicate_risk=e.duplicate_risk,
                            allowed=e.allowed, reasons=e.reasons)
        return e

    def neighbors(self, view_id: str, family: str) -> list[tuple[str, EdgeInfo]]:
        out = []
        for o in self.candidate_neighbors(view_id):
            e = self.edge(view_id, o)
            if e.allowed.get(family):
                out.append((o, e))
        return out

    def build_all(self) -> int:
        for v in sorted(self.index.views):
            for o in self.candidate_neighbors(v):
                self.edge(v, o)
        return len(self._edges)

    def save(self, path) -> None:
        write_jsonl(path, [e.to_json() for _, e in sorted(self._edges.items())])

    # ── 간선 평가 ─────────────────────────────────────────────────
    def _join_candidates(self, va: ViewMetadata, vb: ViewMetadata) -> list[JoinCandidate]:
        out = []
        for da in va.dimension_definitions:
            if da.dim_type not in JOIN_DIM_TYPES:
                continue
            for db in vb.dimension_definitions:
                if db.dim_type != da.dim_type:
                    continue
                ca, cb = va.code_map(da.level), vb.code_map(db.level)
                common = sorted(set(ca) & set(cb))
                mism = [{"code": c, "name_a": ca[c].name, "name_b": cb[c].name} for c in common
                        if norm_code_name(ca[c].name) != norm_code_name(cb[c].name)]
                non_total = [c for c in common if not (ca[c].is_total or cb[c].is_total)]
                ratio = len(mism) / len(common) if common else 0.0
                ok, why = True, ""
                if not common:
                    ok, why = False, "공통 코드 없음"
                elif ratio > self.max_name_mismatch:
                    ok, why = False, f"같은 코드의 이름이 다름 {len(mism)}/{len(common)} → 코드 체계 불일치"
                out.append(JoinCandidate(da.dim_type.value, da.level, db.level, common, non_total, mism, ok, why))
        return out

    def _evaluate(self, va: ViewMetadata, vb: ViewMetadata) -> EdgeInfo:
        same_table = va.parent_table_id == vb.parent_table_id
        same_freq = va.period_frequency == vb.period_frequency
        if not same_freq:
            prel = "INCOMPARABLE_FREQUENCY"
        elif set(va.available_periods) & set(vb.available_periods):
            prel = "SAME" if va.available_periods == vb.available_periods else "OVERLAP"
        else:
            prel = "DIFFERENT"
        joins = self._join_candidates(va, vb)
        items_a = {i.itm_id for i in va.indicator_definitions}
        items_b = {i.itm_id for i in vb.indicator_definitions}
        same_item = same_table and bool(items_a & items_b)
        fam_a = unit_info(va.units[0]).family if len(va.units) == 1 else None
        fam_b = unit_info(vb.units[0]).family if len(vb.units) == 1 else None
        dup = va.duplicate_coordinate_rows > 0 or vb.duplicate_coordinate_rows > 0
        e = EdgeInfo(a=va.view_id, b=vb.view_id, same_table=same_table, same_frequency=same_freq,
                     period_relation=prel, join=joins, same_item=same_item, unit_families=(fam_a, fam_b),
                     observed=(va.observed_or_projected.value, vb.observed_or_projected.value),
                     scopes=(va.population_scope, vb.population_scope), scenarios=(va.scenario, vb.scenario),
                     duplicate_risk=dup)
        common_reasons = []
        if va.observed_or_projected != vb.observed_or_projected:
            common_reasons.append("실측치와 추계치 혼합")
        if va.scenario != vb.scenario:
            common_reasons.append(f"시나리오 다름 ({va.scenario} vs {vb.scenario})")
        if dup:
            common_reasons.append("같은 원본 좌표의 중복 행 → Join 행 증폭 위험")
        if ObservationType.UNKNOWN in (va.observed_or_projected, vb.observed_or_projected):
            common_reasons.append("실측/추계 여부 미상")
        scope_bad = frozenset({va.population_scope, vb.population_scope}) in self.incompatible_scopes
        # TIME_SERIES
        r = list(common_reasons)
        equivalent = same_table or any({va.parent_table_id, vb.parent_table_id} <= g for g in self.equivalent_tables)
        if not equivalent:
            r.append("서로 다른 표의 지표를 같은 시계열로 간주하지 않음 (동등성 설정 없음)")
        if not same_item:
            r.append("같은 항목(ITM_ID)이 아님")
        if not same_freq:
            r.append(f"주기 다름 ({va.period_frequency} vs {vb.period_frequency})")
        elif prel not in ("DIFFERENT",):
            r.append("시점이 겹침 (서로 다른 시점 비교가 아님)")
        if va.units != vb.units:
            r.append(f"단위 다름 {va.units} vs {vb.units}")
        if va.source_coordinates.dim_filters != vb.source_coordinates.dim_filters:
            r.append("분류 조건이 다름 — 시계열은 같은 분류의 두 시점만 비교")
        e.allowed["TIME_SERIES"], e.reasons["TIME_SERIES"] = not r, r
        # RATIO
        r = list(common_reasons)
        if not same_freq:
            r.append(f"주기 다름 ({va.period_frequency} vs {vb.period_frequency}) — 같은 기간으로 간주 금지")
        elif not (set(va.available_periods) & set(vb.available_periods)):
            r.append("공통 시점 없음")
        if not (fam_a and fam_b):
            r.append("단위 미상 또는 View 안에 단위가 여러 개")
        elif not (unit_info(va.units[0]).additive and unit_info(vb.units[0]).additive):
            r.append("비율·평균·지수 단위는 분자/분모로 결합하지 않음")
        elif not all(name_is_additive(i.itm_nm) for v in (va, vb) for i in v.indicator_definitions):
            r.append("항목이 평균·비율·지수 (단위가 명·가구여도 분자/분모로 결합하지 않음)")
        if scope_bad:
            r.append(f"모집단 비호환 ({va.population_scope} vs {vb.population_scope})")
        if same_item and same_table:
            r.append("같은 표·같은 항목 (비율의 분자·분모가 아님)")
        if not any(j.structural_ok for j in joins) and not (same_table and not joins):
            r.append("구조적으로 맞는 공통 Join Key 없음")
        e.allowed["RATIO"], e.reasons["RATIO"] = not r, r
        # CONDITIONAL
        r = list(c for c in common_reasons if c != "실측/추계 여부 미상")
        if not same_freq:
            r.append("주기 다름")
        elif not (set(va.available_periods) & set(vb.available_periods)):
            r.append("공통 시점 없음")
        bj = e.best_join(self.min_common)
        if bj is None:
            r.append(f"공통 비총계 코드가 {self.min_common}개 이상인 Join Key 없음")
        e.allowed["CONDITIONAL"], e.reasons["CONDITIONAL"] = not r, r
        # SIDE_BY_SIDE
        r = []
        if not any(j.structural_ok for j in joins):
            r.append("공통 Join Key 없음")
        e.allowed["SIDE_BY_SIDE"], e.reasons["SIDE_BY_SIDE"] = not r, r
        return e


def items_match(va: ViewMetadata, vb: ViewMetadata) -> bool:
    na = {norm_item_name(i.itm_nm) for i in va.indicator_definitions}
    nb = {norm_item_name(i.itm_nm) for i in vb.indicator_definitions}
    return bool(na & nb)
