"""
실행 중 조회 — 지금 빌드(okf_build/CURRENT)의 파생물을 읽음. 빌드가 없으면 None (기존 동작 그대로)

  cat = Catalog.current(settings)
  cat.table("DT_1JC1516")                        표 요약 (분류·항목·기간·형제)
  cat.has_code("DT_1JC1516", "세대구성별", name="모+미혼자녀")   코드북 조회 (큰 차원도) → {code, name} | None
  cat.concepts_for(["DT_1JC1516"], "세종 싱글맘 식구")    후보 표를 링크한 개념 중 질문에 이름·별칭·not 이 나온 것만
                                                          (에이전트 컨텍스트 · 답변 주의사항용. 역링크 전부를 붙이지 않음)
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from backend.rag.csv_index.store import norm
from backend.rag.okf.build import build_root, current

_CACHE, _LOCK = {}, threading.Lock()


class Catalog:
    def __init__(self, d: Path):
        self.dir = Path(d)
        self.hash = self.dir.name
        self._data = {}

    def _j(self, name):
        if name not in self._data:
            p = self.dir / name
            self._data[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return self._data[name]

    @classmethod
    def current(cls, settings=None):
        """CURRENT 가 가리키는 빌드 (요청마다 한 번 부르면 됨 — 해시가 바뀌면 새 객체)"""
        if settings is not None and not getattr(settings, "okf_use", True):
            return None
        root = build_root(settings)
        h = current(root)
        if not h or not (root / h / "manifest.json").exists():
            return None
        with _LOCK:
            key = str(root / h)
            if key not in _CACHE:
                _CACHE.clear()
                _CACHE[key] = cls(root / h)
            return _CACHE[key]

    @property
    def manifest(self):
        return self._j("manifest.json")

    def table(self, tbl_id):
        return self._j("catalog.json").get(str(tbl_id))

    def has_code(self, tbl_id, dim, code=None, name=None):
        t = self.table(tbl_id)
        if not t:
            return None
        d = next((x for x in t["dims"] if norm(x.get("name")) == norm(dim)), None)
        if d is None:
            return None
        codes = {str(c["code"]): c["name"] for c in d["codes"]} if d.get("codes") is not None \
            else self._j("codebooks.json").get(d.get("classification") or "", {})
        if code is not None:
            return {"code": str(code), "name": codes[str(code)]} if str(code) in codes else None
        n = norm(name)
        hit = next((c for c, nm in codes.items() if norm(nm) == n), None)
        return {"code": hit, "name": codes[hit]} if hit is not None else None

    def concepts(self):
        return self._j("concepts.json")

    def concept(self, cid):
        return next((c for c in self.concepts() if c["id"] == cid), None)

    def concepts_for(self, tbl_ids, *texts, limit=5):
        """후보 표를 링크한 개념(+ dim_kind 규칙 개념) 중, 질문·재작성에 제목·별칭·not·묶인 이름이 나온 것"""
        t = norm(" ".join(str(x or "") for x in texts))
        back = self._j("backlinks.json")
        ids = list(dict.fromkeys([c for tid in tbl_ids for c in back.get("tables", {}).get(str(tid), [])] +
                                 back.get("rules", [])))
        out = []
        for cid in ids:
            c = self.concept(cid)
            if not c or c["status"] == "deprecated":
                continue
            words = [("제목", c["title"])] + [("별칭", a) for a in c["aliases"]] + \
                    [("같은 뜻 아님", n["text"]) for n in c["not"]] + \
                    [("묶인 이름", b["name"]) for b in c["binds"] if b.get("name")]
            hit = next(((why, w) for why, w in words if len(norm(w)) >= 2 and norm(w) in t), None)
            if not hit:
                continue
            out.append({"id": cid, "title": c["title"], "description": c["description"], "matched": {hit[0]: hit[1]},
                        "not": c["not"], "calc": c["calc"], "trust": c["trust"],
                        "binds": [b for b in c["binds"] if not b.get("tbl_id") or b["tbl_id"] in {str(x) for x in tbl_ids}]})
        return out[:limit]
