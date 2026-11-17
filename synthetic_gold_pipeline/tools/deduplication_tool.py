"""독립 Deduplication Tool — 결정론적 1차 중복 제거.

판정 규칙
  1) Fact Signature(연산 종류 + 실제 원본 좌표 + 최종 결과 형태)가 같으면 표현만 바꾼 중복 → 폐기
  2) 텍스트 유사도(토큰 Jaccard, 문자 n-gram TF-IDF Cosine)의 최댓값이 임계값 이상이고
     엔티티 서명(지역·시점·항목·연산)까지 같으면 근접 중복 → 폐기
  3) 텍스트가 비슷해도 지역·기간·지표·연산이 다르면 중복이 아님 (평가 목적이 다름)
같은 레코드 안의 question_original / question_paraphrased 는 의도된 변형 쌍이라 서로 비교하지 않는다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from synthetic_gold_pipeline.utils import stable_hash

JOSA = ("에서는", "으로는", "에서", "으로", "에는", "보다", "까지", "부터", "이고", "이며", "은", "는", "이", "가", "을", "를", "의",
        "에", "로", "과", "와", "도", "만")


def normalize_question(q: str) -> str:
    q = unicodedata.normalize("NFKC", q or "").lower()
    q = re.sub(r"(\d),(\d)", r"\1\2", q)
    q = re.sub(r"[^\w\s%.]", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def tokens(q: str) -> set[str]:
    out = set()
    for t in normalize_question(q).split():
        for j in JOSA:
            if len(t) > len(j) + 1 and t.endswith(j):
                t = t[: -len(j)]
                break
        out.add(t)
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def fact_signature(subtype: str, final_op: str, facts: list[dict[str, Any]], final_kind: str) -> str:
    coords = sorted((f.get("TBL_ID"), f.get("ITM_ID"), f.get("PRD_SE"), f.get("PRD_DE"), tuple(sorted((f.get("dims") or {}).items())))
                    for f in facts)
    return "fs_" + stable_hash({"subtype": subtype, "op": final_op, "coords": coords, "kind": final_kind}, 20)


def entity_signature(regions: list[str], periods: list[str], items: list[str], op: str) -> str:
    return stable_hash({"r": sorted(set(regions)), "p": sorted(set(periods)), "i": sorted(set(items)), "op": op}, 16)


@dataclass
class DedupDecision:
    is_duplicate: bool
    reason: str
    matched_id: str | None
    max_jaccard: float
    max_cosine: float
    max_score: float


@dataclass
class _Entry:
    rid: str
    questions: list[str]
    tokens: list[set[str]]
    fact_sig: str
    entity_sig: str


@dataclass
class DedupIndex:
    threshold: float = 0.85
    ngram_range: tuple[int, int] = (2, 4)
    entries: list[_Entry] = field(default_factory=list)

    def _cos(self, qs: list[str]) -> list[list[float]]:
        if not self.entries:
            return [[] for _ in qs]
        corpus = [normalize_question(q) for e in self.entries for q in e.questions]
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=self.ngram_range, min_df=1)
        m = vec.fit_transform(corpus + [normalize_question(q) for q in qs])
        sims = cosine_similarity(m[len(corpus):], m[:len(corpus)])
        return [list(r) for r in sims]

    def check(self, rid: str, questions: list[str], fact_sig: str, entity_sig: str) -> DedupDecision:
        best = DedupDecision(False, "UNIQUE", None, 0.0, 0.0, 0.0)
        if not self.entries:
            return best
        for e in self.entries:
            if e.fact_sig == fact_sig:
                return DedupDecision(True, "SAME_FACT_SIGNATURE", e.rid, 1.0, 1.0, 1.0)
        cos = self._cos(questions)
        owner = [e for e in self.entries for _ in e.questions]
        tks = [tokens(q) for q in questions]
        for qi, q in enumerate(questions):
            for j, e in enumerate(owner):
                jac = max(jaccard(tks[qi], t) for t in e.tokens)
                c = float(cos[qi][j])
                score = max(jac, c)
                if jac > best.max_jaccard:
                    best.max_jaccard = jac
                if c > best.max_cosine:
                    best.max_cosine = c
                if score > best.max_score:
                    best.max_score, best.matched_id = score, e.rid
                if score >= self.threshold and e.entity_sig == entity_sig:
                    return DedupDecision(True, "NEAR_DUPLICATE_SAME_ENTITIES", e.rid, best.max_jaccard, best.max_cosine, score)
        best.max_jaccard, best.max_cosine, best.max_score = (round(best.max_jaccard, 4), round(best.max_cosine, 4),
                                                             round(best.max_score, 4))
        if best.max_score >= self.threshold:
            best.reason = "SIMILAR_TEXT_DIFFERENT_ENTITIES (유지)"
        return best

    def add(self, rid: str, questions: list[str], fact_sig: str, entity_sig: str):
        self.entries.append(_Entry(rid, list(questions), [tokens(q) for q in questions], fact_sig, entity_sig))
