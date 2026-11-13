"""
카드 데이터 읽기 — table_card / table_card_expend 결과 → 검색 문서 + 조건 확인용 프로필

검색 방식은 기존 그대로 두고 '읽는 데이터'만 바꾸는 부분이 여기 모여 있다.
  기존(baseline)        Doc.text = 표 설명문 1개 (BM25·dense 공용)       조건 = meta_profiles.jsonl
  table_card            Doc.text = bm25_text, meta.dense_text = dense_text   조건 = conditions.jsonl (+ pieces.jsonl)
  table_card_expend     Doc.text = bm25_text, meta.dense_text = dense_text   조건 = conditions.jsonl 의 '프로필'

프로필 = backend.rag.ingestion.resolve.unmet 이 읽는 모양 {tbl_nm, periods, levels, items, units}
  → 조건 확인 점수(cost)는 기존 resolve.unmet · period_cover · cost 함수가 그대로 계산 (규칙을 새로 만들지 않음)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from backend.rag.retrieval.interfaces import Doc

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = {
    ("table_card", "full"): REPO_ROOT / "table_cards" / "full",
    ("table_card", "sample"): REPO_ROOT / "table_cards" / "sample_cards",
    ("table_card_expend", "full"): REPO_ROOT / "table_card_expend" / "out" / "full",
    ("table_card_expend", "sample"): REPO_ROOT / "table_card_expend" / "out" / "sample",
}
AXIS_KIND = {"성별": "sex", "연령": "ages", "국적": "nationality", "출생연도": "cohort", "추계 가정": "scenario"}


def _jsonl(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["tbl_id"]] = r
    return out


def _mtime(*paths):
    return ";".join(f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}" if p.exists() else f"{p.name}:-" for p in paths)


def resolve_dirs(kind, dirs=None, set_name="full"):
    """dirs: 경로 하나 | 경로 목록 | None(기본 위치). 상대 경로는 저장소 기준"""
    if dirs is None:
        dirs = [DEFAULT_DIRS[(kind, s)] for s in (["full", "sample"] if set_name == "both" else [set_name])]
    elif isinstance(dirs, (str, Path)):
        dirs = [dirs]
    return [(Path(d) if Path(d).is_absolute() else REPO_ROOT / d) for d in dirs]


# ── table_card 조건표 → 프로필 ───────────────────────────────────
def table_card_profile(card, cond, piece=None):
    """table_card 가 가진 정보만으로 프로필 (pieces.jsonl 이 있으면 축 값·항목 이름까지)"""
    periods = []
    for p in cond.get("시점") or []:
        if p.get("시작") is None:
            continue
        se_raw = str(p.get("주기") or "")
        periods.append({"se": "Y" if se_raw in ("년", "연") else ("F" if se_raw.endswith("년") else se_raw),
                        "se_raw": se_raw, "year_from": p.get("시작"), "year_to": p.get("끝") or p.get("시작")})
    levels = []
    regions = cond.get("지역") or []
    if regions:
        from backend.rag.ingestion.normalize import SIDO_CANON
        sido = sorted({n.split(" ")[0] for n in regions if n.split(" ")[0] in SIDO_CANON})
        levels.append({"kind": "regions", "obj_nm": "지역", "names": ["전국", *sido] if "전국" in regions else sido,
                       "sido": sido})
    if cond.get("지역2") and cond["지역2"].get("이름"):
        levels.append({"kind": "other", "obj_nm": cond["지역2"].get("역할") or "지역2", "names": cond["지역2"]["이름"]})
    axes = (piece or {}).get("축")
    if axes:
        for a in axes:
            levels.append({"kind": AXIS_KIND.get(a.get("표준") or "", "other"), "obj_nm": a.get("원래"),
                           "names": a.get("값") or []})
    else:
        for name in card.get("축") or []:
            levels.append({"kind": AXIS_KIND.get(name, "other"), "obj_nm": name, "names": []})
    if piece and piece.get("항목"):
        items = [{"name": n, "unit": ""} for n in piece["항목"]]
    else:                                            # pieces 가 없으면 bm25_text 단어로 대신 (지표 단어 확인용)
        items = [{"name": w, "unit": ""} for w in dict.fromkeys(re.split(r"\s+", card.get("bm25_text") or "")) if w]
    return {"tbl_id": card["tbl_id"], "tbl_nm": (piece or {}).get("제목_원래") or card.get("제목") or card["tbl_id"],
            "periods": periods, "levels": levels, "items": items, "units": cond.get("단위") or [],
            "profile_from": "table_card"}


class CardCorpus:
    """카드 폴더(들) → Doc 목록. kind = table_card | table_card_expend"""

    def __init__(self, kind="table_card", dirs=None, set_name="full", name=None):
        self.kind, self.set_name = kind, set_name
        self.dirs = resolve_dirs(kind, dirs, set_name)
        self.name = name or kind
        self._docs, self._sig = None, None

    def _files(self):
        return [d / n for d in self.dirs for n in ("cards.jsonl", "conditions.jsonl", "pieces.jsonl")]

    def signature(self):
        return f"{self.kind}:{_mtime(*self._files())}"

    def docs(self):
        sig = self.signature()
        if self._docs is not None and self._sig == sig:
            return self._docs
        docs, seen = [], set()
        for d in self.dirs:
            cards, conds, pieces = _jsonl(d / "cards.jsonl"), _jsonl(d / "conditions.jsonl"), _jsonl(d / "pieces.jsonl")
            if not cards:
                raise FileNotFoundError(f"{self.kind} 카드 없음: {d / 'cards.jsonl'}")
            for tid, k in cards.items():
                if "오류" in k or tid in seen or not k.get("bm25_text"):
                    continue
                seen.add(tid)
                c = conds.get(tid) or {}
                p = pieces.get(tid)
                profile = c.get("프로필") if self.kind == "table_card_expend" and c.get("프로필") else \
                    table_card_profile(k, c, p)
                docs.append(Doc(tid, k["bm25_text"], {
                    "tbl_nm": (p or {}).get("제목_원래") or k.get("제목_원래") or k.get("제목", ""),
                    "survey_nm": k.get("조사명", ""), "dense_text": k.get("dense_text") or k["bm25_text"],
                    "profile": profile, "set": k.get("set") or d.name}))
        self._docs, self._sig = docs, sig
        return docs


class TableCardCorpus(CardCorpus):
    def __init__(self, dirs=None, set_name="full", **kw):
        super().__init__("table_card", dirs, set_name, **kw)


class ExpendCardCorpus(CardCorpus):
    def __init__(self, dirs=None, set_name="full", **kw):
        super().__init__("table_card_expend", dirs, set_name, **kw)
