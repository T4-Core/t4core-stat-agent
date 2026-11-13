"""합성 View ID ↔ 원본 기관_통계표 ID ↔ 원본 좌표 ↔ 기존 RAG View ID (확인 가능한 경우) 매핑.

기존 RAG View 는 읽기 전용으로만 조회한다 (기존 view_builder 가 만든 views.jsonl 의 source 좌표).
  source = {table_key, prd_se, itm_id:[…], dims:{c1:{codes:[…]} | {depth:n}}, period:{} | {in:[…]} | {from,to}}

매핑 상태
  MAPPED_EXACT        기존 View 선택 조건이 합성 View 와 정확히 같음
  MAPPED_CONTAINING   기존 View 가 합성 View 의 필요한 좌표를 모두 포함 (조건이 더 넓음)
  UNMAPPED            확인할 수 없음 (추정·임의 생성하지 않음) — reason 에 이유 기록
기존 RAG 의 온라인 동적 View(view::표key::주기::질문ID-순위::종류)는 질의마다 만들어지므로 매핑하지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from synthetic_gold_pipeline.schemas.metadata import ViewMetadata
from synthetic_gold_pipeline.utils import REPO_ROOT, display_path, normalize_frequency, period_digits, resolve_path

log = logging.getLogger(__name__)

DEFAULT_CANDIDATES = ["storage/kosis_data/rag_views/views.jsonl", "kosis_data/rag_views/views.jsonl"]


class ViewMappingAdapter:
    def __init__(self, views_jsonl: str | Path | None = None, max_records: int = 500_000):
        self.path = self._resolve(views_jsonl)
        self.by_table: dict[str, list[dict[str, Any]]] = {}
        self.n_loaded = 0
        if self.path:
            self._load(max_records)

    @staticmethod
    def _resolve(p) -> Path | None:
        cands = []
        if p:
            cands.append(resolve_path(p))
        if os.getenv("RAG_VIEWS_DIR"):
            cands.append(resolve_path(os.getenv("RAG_VIEWS_DIR")) / "views.jsonl")
        cands += [REPO_ROOT / c for c in DEFAULT_CANDIDATES]
        return next((c for c in cands if c and c.is_file()), None)

    def _load(self, max_records: int):
        with open(self.path, encoding="utf-8") as f:       # 읽기 전용
            for i, line in enumerate(f):
                if i >= max_records:
                    break
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                src = d.get("source") or {}
                key = src.get("table_key")
                if d.get("id") and key:
                    self.by_table.setdefault(key, []).append({"id": d["id"], "source": src})
                    self.n_loaded += 1

    @property
    def available(self) -> bool:
        return self.path is not None

    def map_view(self, vm: ViewMetadata, required: dict[str, Any] | None = None) -> dict[str, Any]:
        """required: {"itm_ids": [...], "periods": [...], "codes": {C레벨: [코드]}} — 질문에 필요한 좌표 (없으면 View 전체)."""
        base = {"synthetic_view_id": vm.view_id, "org_table_id": vm.parent_table_id,
                "source_coordinates": vm.source_coordinates.model_dump(), "existing_rag_view_ids": [],
                "status": "UNMAPPED", "reason": ""}
        if not self.available:
            base["reason"] = "기존 RAG views.jsonl 을 찾지 못함 (매핑 불가, 추정하지 않음)"
            return base
        req = required or {"itm_ids": vm.source_coordinates.itm_ids, "periods": vm.available_periods,
                           "codes": {lv: [c.code for c in cs] for lv, cs in vm.dimension_codes.items()}}
        exact, containing, reasons = [], [], set()
        for cand in self.by_table.get(vm.parent_table_id, []):
            ok, is_exact, why = self._covers(cand["source"], vm, req)
            if ok:
                (exact if is_exact else containing).append(cand["id"])
            elif why:
                reasons.add(why)
        if exact:
            base.update(status="MAPPED_EXACT", existing_rag_view_ids=exact)
        elif containing:
            base.update(status="MAPPED_CONTAINING", existing_rag_view_ids=containing[:20])
        else:
            base["reason"] = ("같은 표의 기존 View 없음" if vm.parent_table_id not in self.by_table
                              else "좌표를 포함하는 기존 View 없음: " + "; ".join(sorted(reasons))[:300])
        base["views_jsonl"] = display_path(self.path)
        return base

    @staticmethod
    def _covers(src: dict, vm: ViewMetadata, req: dict) -> tuple[bool, bool, str]:
        if normalize_frequency(src.get("prd_se")) != vm.period_frequency:
            return False, False, "주기 다름"
        itms = set(src.get("itm_id") or [])
        if not set(req["itm_ids"]) <= itms:
            return False, False, "항목 미포함"
        per = src.get("period") or {}
        want = {period_digits(p) for p in req["periods"]}
        if "in" in per:
            have = {period_digits(p) for p in per["in"]}
            if not want <= have:
                return False, False, "시점 미포함"
        elif "from" in per or "to" in per:
            lo, hi = period_digits(per.get("from") or "0"), period_digits(per.get("to") or "9" * 8)
            if not all(lo[:len(w)] <= w <= hi[:len(w)] + "99" for w in want):
                return False, False, "시점 범위 밖"
        exact = set(req["itm_ids"]) == itms
        dims = src.get("dims") or {}
        for lv, codes in req["codes"].items():
            d = dims.get(lv.lower())
            if d is None:
                continue                     # 기존 View 가 이 분류를 제한하지 않음 = 전체 포함
            if "codes" not in d:
                return False, False, "분류를 깊이(depth)로만 지정해 코드 포함 여부를 확인할 수 없음"
            if not set(codes) <= {str(c) for c in d["codes"]}:
                return False, False, "분류 코드 미포함"
            exact = exact and set(codes) == {str(c) for c in d["codes"]}
        return True, exact, ""
