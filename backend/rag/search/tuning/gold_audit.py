"""
골든셋 정답 표시 검토 — 질문 글과 정답 표가 어긋난 레코드를 찾아, 대체 정답 후보 · 평가에서 뺄 변형을 제안한다

  왜  합성 골든셋의 정답은 '생성에 쓴 표 하나' 라서, 질문이 그 표를 고를 말을 잃으면 다른 표를 고른 검색을 오답으로 셈
      (P 문항 실패의 상당수가 검색이 아니라 정답 표시 문제 — docs/OKF_FORMAT.md '개념 초안 모으기' 분석)
  무엇을 보나 (HCX 없음 · 골든셋 + OKF 표 파일만)
    SEX       정답 표가 성별로 나뉜 표('…(남)')인데 질문에 성별 말이 없음 → 같은 무리의 (계)·분할 없는 표를 대체 정답으로
    UNIVERSE  정답 표의 모집단이 '(15세이상)' 처럼 좁은데 질문에 'N세' 가 없음 → 그 변형은 평가에서 뺌
              (질문은 전체 인구를 묻는데 정답은 15세 이상 — 맞는 표를 골라도 오답이 되고, 대체 정답도 값이 달라 정할 수 없음)
    P_DRIFT   (P 만 · 검토 제안) 정답 표를 형제 표와 가르는 주제 말('당해연도' ↔ '누적', '장기')이 O 에는 있는데 P 에는 없고,
              P 가 형제 표 쪽 말도 쓰지 않음 → 형제 표도 P 의 정답일 수 있음. 형제 = 같은 조사 · 제목 낱말이 대부분 겹침
              · 정답 사실의 시점을 모두 가짐 · 정답 사실의 항목 이름을 가짐 (표 파일로 확인)
              분류 이름('연령별' · '행정구역별')만 다른 형제는 보지 않음 — 그건 값으로 확인하는 alt_gold 가 맡음
              낱말이 없다고 뜻이 같다고 할 수는 없어서('아이를 낳은 비율' 은 '출산' 이 없어도 출산 비율) 자동으로 쓰지 않고,
              human 에 "accept" 를 적은 것만 '검토 반영' 지표에 넣음 (SEX · UNIVERSE 는 기본 반영, "strict" 로 끔)
  결과  <골든셋 옆>/gold_audit.jsonl (레코드마다) · gold_audit.md (사람이 읽음)
        {dataset_id, split, gold, O: {flags, alt, exclude}, P: {…}, human: {}}
        human 에 변형별 판단을 적으면 다시 돌려도 남음:  "human": {"P": "exclude" | "strict" | "accept"}
          exclude = 평가에서 뺌 · strict = 제안을 쓰지 않음(원래 정답만) · accept = 제안대로 (없을 때와 같음)
  쓰기  python -m backend.rag.search.tuning.gold_audit --golden <synthetic_gold_dataset.jsonl>
        python -m backend.rag.search.tuning.compare --golden … --alt … --audit <gold_audit.jsonl> …
          → 기존 엄격·완화 지표는 그대로, '검토 반영' 지표(제안 대체 정답 포함 · 뺀 변형 제외)를 따로 보여 줌
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

AGE_UNIVERSE = re.compile(r"\(\s*(\d+)\s*세\s*이상\s*\)")
HUMAN_CHOICES = ("accept", "exclude", "strict")
REVIEW_ONLY = ("P_DRIFT",)   # 사람이 accept 해야 반영
_TITLE_NOISE_WORDS = "현황 기타 월간 연간 발생 반영 부가 추이 주요 지표 총괄 관련 내역 전체 일반 구분 분류 항목 수 별 행정 구역"
_TITLE_NOISE = set(_TITLE_NOISE_WORDS.split())  # 표 이름의 흔한 말 (형제 표를 가르는 말이 아님)
MIN_OVERLAP = 0.5
MAX_DIFF = 3
MAX_ALT = 6


def _tid(x):
    m = re.match(r"^\d{2,4}_(.+)$", str(x))
    return m.group(1) if m else str(x)


# ── 표 정보 (OKF 표 파일) ───────────────────────────────────────
class Tables:
    def __init__(self, bundle=None, docs=None):
        """docs: {tbl_id: {title, survey, periods:set, names:set}} 를 직접 줄 수도 있음 (시험용)"""
        if docs is None:
            docs = {}
            from backend.rag.okf.doc import Doc, iter_docs
            if bundle is None:
                from backend.rag.okf.build import bundle_dir
                bundle = bundle_dir()
            for p in iter_docs(Path(bundle), ("tables",)):
                d = Doc.read(p)
                xt = d.meta.get("x-t4-table") or {}
                if d.error or not xt.get("tbl_id"):
                    continue
                names = {str(i.get("name")) for i in xt.get("items") or []}
                dims = [str(dm.get("name")) for dm in xt.get("dims") or []]
                for dm in xt.get("dims") or []:
                    names |= {str(c.get("name")) for c in dm.get("codes") or []}
                    names |= {str(x) for x in dm.get("examples") or []}
                docs[str(xt["tbl_id"])] = {"title": str(d.meta.get("title") or ""), "survey": str(xt.get("survey") or ""),
                                           "periods": {str(x) for v in (xt.get("periods") or {}).values() for x in v or []},
                                           "names": names, "dims": dims}
        self.docs = docs
        self._forms = {}
        self.by_survey = defaultdict(list)
        for t, x in docs.items():
            self.by_survey[x["survey"]].append(t)

    def title(self, t):
        return (self.docs.get(t) or {}).get("title", "")

    def forms(self, t):
        """제목의 내용 낱말 (성별·연도 괄호 · 지역 수준 꼬리 · 흔한 말 · 지역 이름 뺌)"""
        if t not in self._forms:
            from backend.rag.okf.drafts import GENERIC, _regionish, morphs
            from backend.rag.search.siblings import (
                LEVEL_TAIL,
                LEVELS,
                SEX_PAREN,
                YEAR_PAREN,
            )
            title = LEVEL_TAIL.sub("", YEAR_PAREN.sub("", SEX_PAREN.sub("", self.title(t))))
            dim_forms = {f for dn in (self.docs.get(t) or {}).get("dims") or [] for f, _, _ in morphs(dn)}
            self._forms[t] = {f for f, _, _ in morphs(title) if len(f) >= 2 and f not in GENERIC and f not in LEVELS
                              and f not in _TITLE_NOISE and f not in dim_forms and not _regionish(f)}
        return self._forms[t]

    def has_facts(self, t, facts) -> bool:
        """정답 사실의 시점을 모두 갖고, 항목 이름(총계가 아니면)이 표의 항목·코드 이름에 있음"""
        from backend.rag.search.tuning.alt_gold import TOTALS
        x = self.docs.get(t)
        if not x:
            return False
        for f in facts:
            if f["prd_de"] and f["prd_de"] not in x["periods"]:
                return False
            item = re.sub(r"\s+", "", f["item"] or "")
            if item and item not in TOTALS and not any(re.sub(r"\s+", "", n) == item for n in x["names"]):
                return False
        return True


def record_facts(rec):
    """레코드의 정답 사실 → [{tbl_id, prd_de, item}]"""
    out = []
    for f in (rec.get("generation_eval") or {}).get("intermediate_facts") or []:
        c = f.get("coordinate") or {}
        out.append({"tbl_id": _tid(f.get("parent_table_id") or c.get("TBL_ID") or ""),
                    "prd_de": str(c.get("PRD_DE") or re.sub(r"\D", "", str(f.get("period") or ""))[:4] or ""),
                    "item": str(c.get("ITM_NM") or f.get("item_name") or "")})
    return out


def gold_of(rec):
    re_ = rec.get("retrieval_eval") or {}
    return sorted({_tid(t) for t in re_.get("golden_table_ids") or []})


# ── 검사 ────────────────────────────────────────────────────────
def _qwords(q, expand=True):
    """질문의 낱말 — 형태소 (+ expand: 일상어 → 통계어 · colloquial.yaml · 용어 사전: '결혼' → 혼인)"""
    from backend.rag.okf.drafts import morphs
    from backend.rag.search.query import synonyms
    from backend.rag.search.text import norm
    extra = " ".join(synonyms(q) or []) if expand else ""
    return {f for f, _, _ in morphs(q + " " + extra)}, norm(q + " " + extra)


def _has(words, text, w):
    from backend.rag.search.text import norm
    return w in words or norm(w) in text


def check_sex(tables, gold, facts, q):
    from backend.rag.search.query import WANT_SEX_RE
    from backend.rag.search.siblings import core_title, table_sex
    if WANT_SEX_RE.search(q):
        return None
    alt = []
    for g in gold:
        if table_sex(tables.title(g)) not in ("남", "여"):
            continue
        core, sv = core_title(tables.title(g)), tables.docs[g]["survey"]
        fs = [f for f in facts if f["tbl_id"] == g] or facts
        alt += [t for t in tables.by_survey[sv] if t != g and core_title(tables.title(t)) == core
                and table_sex(tables.title(t)) in (None, "계") and tables.has_facts(t, fs)]
    if not alt:
        return None
    return {"code": "SEX", "alt": sorted(set(alt) - set(gold))[:MAX_ALT],
            "reason": "정답 표가 성별로 나뉜 표인데 질문에 성별 말이 없음 → (계) 형제 표가 질문에 맞는 답"}


def check_universe(tables, gold, q):
    from backend.rag.search.text import norm
    for g in gold:
        m = AGE_UNIVERSE.search(tables.title(g))
        if m and f"{m.group(1)}세" not in norm(q):
            return {"code": "UNIVERSE", "alt": [], "exclude": True,
                    "reason": f"정답 표의 모집단이 '{m.group(1)}세 이상'인데 질문에 없음 ({g}) — 맞는 표를 골라도 값이 다름"}
    return None


def near_siblings(tables, g):
    """같은 조사에서 제목 주제 낱말(분류 이름 뺌)이 대부분 겹치는 표 → [(표, 정답 표에만 있는 낱말, 형제에만 있는 낱말, 겹침)]"""
    a = tables.forms(g)
    if not a:
        return []
    out = []
    for t in tables.by_survey[tables.docs[g]["survey"]]:
        if t == g:
            continue
        b = tables.forms(t)
        if not b or a == b:
            continue
        ov = len(a & b) / min(len(a), len(b))
        diff = a - b
        if ov >= MIN_OVERLAP and 1 <= len(diff) <= MAX_DIFF:
            out.append((t, diff, b - a, ov))
    out.sort(key=lambda x: (-x[3], x[0]))
    return out


def check_p_drift(tables, gold, facts, o, p):
    ow, ot = _qwords(o)
    pw, pt = _qwords(p)
    rw, rt = _qwords(p, expand=False)  # 형제 쪽 말은 P 가 직접 쓴 것만 (검색의 용어 사전이 '결혼 비율' 을 '누적 혼인' 으로 바꿈)
    alt, lost = [], set()
    for g in gold:
        fs = [f for f in facts if f["tbl_id"] == g] or facts
        for t, diff, other, _ in near_siblings(tables, g):
            if t in gold:
                continue
            if any(_has(ow, ot, d) for d in diff) and not any(_has(pw, pt, d) for d in diff) \
                    and not any(_has(rw, rt, d) for d in other) and tables.has_facts(t, fs):
                alt.append(t)
                lost |= {d for d in diff if _has(ow, ot, d)}
    if not alt:
        return None
    return {"code": "P_DRIFT", "alt": list(dict.fromkeys(alt))[:MAX_ALT], "lost": sorted(lost), "review": True,
            "reason": f"O 에 있던 형제 표와 가르는 말({', '.join(sorted(lost))})이 P 에 없음 → 형제 표도 P 의 정답일 수 있음 (검토)"}


def audit_record(rec, tables) -> dict:
    gold = [g for g in gold_of(rec) if g in tables.docs]
    facts = record_facts(rec)
    qs = {"O": rec.get("question_original") or "", "P": rec.get("question_paraphrased") or ""}
    from backend.rag.search.tuning.splits import split_of
    out = {"dataset_id": rec.get("dataset_id"), "split": split_of(rec["dataset_id"]) if rec.get("dataset_id") else "",
           "gold": gold_of(rec)}
    for v, q in qs.items():
        flags = []
        if q and gold:
            for f in (check_sex(tables, gold, facts, q), check_universe(tables, gold, q),
                      check_p_drift(tables, gold, facts, qs["O"], q) if v == "P" else None):
                if f:
                    flags.append(f)
        out[v] = {"flags": flags, "alt": list(dict.fromkeys(t for f in flags for t in f.get("alt") or [])),
                  "exclude": any(f.get("exclude") for f in flags)}
    out["human"] = {}
    return out


# ── 쓰기 · 읽기 ─────────────────────────────────────────────────
def load_audit(path):
    """gold_audit.jsonl → {(dataset_id, 변형): {"alt": [...], "exclude": bool, "flags": [코드…]}} (human 판단 반영)"""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        for v in ("O", "P"):
            x = r.get(v) or {}
            h = (r.get("human") or {}).get(v) or ""
            flags = x.get("flags") or []
            codes = [f["code"] for f in flags]
            use = [f for f in flags if h == "accept" or f["code"] not in REVIEW_ONLY]  # 검토 제안은 사람이 accept 해야
            if h == "strict":
                use = []
            out[(r["dataset_id"], v)] = {"alt": [] if h == "exclude" else list(dict.fromkeys(t for f in use for t in f.get("alt") or [])),
                                         "exclude": h == "exclude" or any(f.get("exclude") for f in use), "flags": codes,
                                         "human": h or "-", "pending": [f["code"] for f in flags if f not in use and h != "strict"]}
    return out


def report_md(rows, golden):
    n = Counter()
    for r in rows:
        for v in ("O", "P"):
            for f in r[v]["flags"]:
                n[(v, f["code"])] += 1
    L = ["# 골든셋 정답 표시 검토", "", f"- 골든셋: `{golden}` · 레코드 {len(rows)}개", "",
         "| 변형 | 검사 | 문항 수 | 처리 |", "|---|---|---|---|"]
    how = {"SEX": "(계) 형제 표를 대체 정답으로 (기본 반영)", "UNIVERSE": "평가에서 뺌 (기본 반영)",
           "P_DRIFT": "형제 표를 대체 정답으로 — human 에 \"accept\" 를 적어야 반영"}
    for (v, c), k in sorted(n.items()):
        L.append(f"| {v} | {c} | {k} | {how.get(c, '')} |")
    L += ["", "판단은 jsonl 의 \"human\": {\"P\": \"accept\" | \"exclude\" | \"strict\"} 에 (다시 돌려도 남음).",
          "accept = 제안(검토 제안 포함)대로 · exclude = 그 변형을 평가에서 뺌 · strict = 제안을 쓰지 않음", "",
          "## 문항별", ""]
    for r in rows:
        fl = [(v, f) for v in ("O", "P") for f in r[v]["flags"]]
        if not fl:
            continue
        L.append(f"- **{r['dataset_id']}** ({r['split']}) 정답 {' '.join(r['gold'])}" + (f" · human {r['human']}" if r["human"] else ""))
        for v, f in fl:
            L.append(f"  - {v} [{f['code']}] {f['reason']}" + (f" → {' '.join(f['alt'])}" if f.get("alt") else ""))
    return "\n".join(L) + "\n"


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="python -m backend.rag.search.tuning.gold_audit")
    ap.add_argument("--golden", required=True, help="synthetic_gold_dataset.jsonl")
    ap.add_argument("--out", default=None, help="기본: 골든셋 옆 gold_audit.jsonl (+ .md)")
    ap.add_argument("--bundle", default=None, help="OKF 번들 (기본 storage/okf)")
    a = ap.parse_args(argv)
    golden = Path(a.golden)
    out = Path(a.out) if a.out else golden.with_name("gold_audit.jsonl")
    human = {}
    if out.exists():  # 사람이 적은 판단은 남김
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("human"):
                    human[r["dataset_id"]] = {k: v for k, v in r["human"].items() if v in HUMAN_CHOICES}
    tables = Tables(a.bundle)
    recs = [json.loads(x) for x in golden.read_text(encoding="utf-8").splitlines() if x.strip()]
    recs = [r for r in recs if r.get("answerability_type") == "ANSWERABLE"]
    rows = []
    for r in recs:
        x = audit_record(r, tables)
        x["human"] = human.get(x["dataset_id"], {})
        rows.append(x)
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    md = out.with_suffix(".md")
    md.write_text(report_md(rows, golden), encoding="utf-8")
    c = Counter(f"{v}:{f['code']}" for x in rows for v in ("O", "P") for f in x[v]["flags"])
    print(f"[검토] 레코드 {len(rows)}개 · " + (" · ".join(f"{k} {n}" for k, n in sorted(c.items())) or "걸린 것 없음"))
    print(f"→ {out}\n→ {md}")
    return out


if __name__ == "__main__":
    main()
