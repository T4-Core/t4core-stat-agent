"""
[2] 설명 — 카드 재료 → 표 설명 (table_card 와 따로 만든다. table_card 의 LLM 설명을 가져다 쓰지 않음)

  template (기본)  규칙으로 만든 설명. LLM 없이 같은 입력이면 같은 글 → 재현 가능, 지어낸 내용 없음
  hcx              HCX 로 2~3문장 설명 (backend.core.llm.chat). 금지 규칙(연도·지역 이름·재료에 없는 숫자)을 어기면
                   그 표는 template 설명으로 대체하고 '검사' 칸에 남김. 재료가 같으면 다시 부르지 않음(descriptions.jsonl)

비슷한 표와의 차이는 규칙으로 계산 (같은 조사·같은 메뉴 경로의 다른 표에 없는 축·모집단·지표)
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from table_card_expend import rules as R

PROMPT_VER = "x1"
YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
NUM_RE = re.compile(r"\d+")

SYSTEM = """너는 통계표 검색용 설명을 쓰는 사람이다. 사용자는 일상어로 질문하고, 너의 설명이 그 질문과 표를 이어 준다.
주어진 사실만 쓴다. 표에 없는 내용을 추측하지 않는다.
규칙
- 연도, 기간, 지역 이름을 쓰지 않는다. 지역은 '시도별', '시군구별'처럼 수준으로만 말한다.
- 숫자는 주어진 사실에 있는 것(예: '12세 이상')만 쓴다.
- 2~3문장: ① 무엇을(누구를) 어떤 값으로 셌는지 ② 어떤 기준으로 나뉘는지 — 사람들이 찾을 만한 대표 값을 이름 그대로
  ③ '비슷한 표와 다른 점'이 있으면 그것. '모집단'과 '용어 정의'가 있으면 쉬운 말로 녹여 쓴다.
- 반드시 JSON 으로만 답한다: {"설명": "..."}"""
SCHEMA = {"type": "object", "properties": {"설명": {"type": "string"}}, "required": ["설명"]}


def josa(word, a, b):
    """받침에 따라 조사 고르기 ('가구수' + 을/를 → 를)"""
    ch = (word or " ")[-1]
    if "가" <= ch <= "힣":
        return a if (ord(ch) - 0xAC00) % 28 else b
    return f"{a}({b})"


def siblings_diff(P):
    """표마다 같은 조사·같은 주제(메뉴 경로)의 다른 표와 비교한 차이 → {tbl_id: [문구]}"""
    groups = {}
    for p in P.values():
        groups.setdefault((p["조사명"], tuple(p["주제"])), []).append(p)
    out = {}
    for grp in groups.values():
        for p in grp:
            others = [q for q in grp if q["tbl_id"] != p["tbl_id"] and R.title_core(q["제목"]) != R.title_core(p["제목"])]
            if not others:
                continue
            ax = lambda q: {a["표준"] or a["원래"] for a in q["축"] if a["kind"] != "regions_like"}  # noqa: E731
            mine, theirs = ax(p), set().union(*(ax(q) for q in others))
            diff = [f"{a}별로 나뉨" for a in sorted(mine - theirs)][:3]
            pop = set(p["모집단"]) - set().union(*(set(q["모집단"]) for q in others))
            diff += [f"대상 범위 {x}" for x in sorted(pop)][:2]
            ind = set(p["지표"]) - set().union(*(set(q["지표"]) for q in others))
            diff += [f"{x} 수록" for x in sorted(ind)][:2]
            if diff:
                out[p["tbl_id"]] = diff
    return out


def facts(p, c, diff):
    axes = [a for a in p["축"] if a["kind"] != "regions_like"]
    return {"조사명": p["조사명"], "표 이름": p["제목"], "주제": " > ".join(p["주제"]), "조사구분": c.get("조사구분"),
            "지역 수준": p["지역수준"], "두 번째 지역": (c.get("지역2") or {}).get("역할"),
            "나뉘는 기준": [{"이름": a["원래"], "표준": a["표준"], "대표 값": a["값"][:12], "값 수": a["값_수"]} for a in axes],
            "항목": [f"{i['name']}({i['unit']})" if i["unit"] else i["name"] for i in p["항목_상세"][:25]],
            "대상": p["대상"], "지표": p["지표"], "모집단": p["모집단"],
            "용어 정의": [f"{d['용어']}: {d['정의'][:120]}" for d in p["정의"][:3]],
            "조사 설명": {k: v[:150] for k, v in (p.get("조사설명") or {}).items() if k in ("조사목적", "조사대상범위")},
            "비슷한 표와 다른 점": diff}


def template_description(p, c, diff):
    title = p["제목"]
    vals = p["지표"][:3] or [i["name"] for i in p["항목_상세"] if i["kind"] in ("count", "ratio", "average")][:3] \
        or p["항목"][:3]
    units = sorted({i["unit"] for i in p["항목_상세"] if i["unit"]})[:3]
    subj = "·".join(p["대상"][:3])
    if vals:
        v = "·".join(vals)
        s = [f"{p['조사명']}의 「{title}」 표로, {subj + '에 관한 ' if subj else ''}{v}"
             f"{'(' + ', '.join(units) + ')' if units else ''}{josa(vals[-1], '을', '를')} 담고 있다."]
    else:
        s = [f"{p['조사명']}의 「{title}」 표이다."]
    axes = [a for a in p["축"] if a["kind"] != "regions_like" and a["값_수"] >= 2]
    if axes:
        parts = []
        for a in axes[:4]:
            ex = ", ".join(a["값"][:4])
            parts.append(f"{a['원래']}({ex}{' 등' if a['값_수'] > 4 else ''})" if ex else a["원래"])
        s.append(f"{', '.join(parts)} 기준으로 나뉜다.")
    lv = [x for x in p["지역수준"] if x != "전국"]
    if lv:
        s.append(f"지역은 {'·'.join(lv)} 단위로 볼 수 있다.")
    if (c.get("지역2") or {}).get("역할"):
        s.append(f"{c['지역2']['역할']}도 지역별로 나뉜다.")
    if p["모집단"]:
        s.append(f"대상 범위: {', '.join(p['모집단'][:4])}.")
    if diff:
        s.append(f"같은 주제의 다른 표와 달리 {', '.join(diff)}.")
    for d in p["정의"][:2]:
        s.append(f"{d['용어']}: {d['정의'][:90]}")
    return " ".join(s)


def check(text, f):
    """LLM 설명 금지 규칙: 연도 · 지역 이름 · 재료에 없는 숫자"""
    issues = []
    if R.SIDO_RE.search(text):
        issues.append("지역이름:" + ",".join(sorted(set(R.SIDO_RE.findall(text)))))
    if YEAR_RE.search(text):
        issues.append("연도:" + ",".join(sorted(set(YEAR_RE.findall(text)))))
    allowed = set(NUM_RE.findall(json.dumps(f, ensure_ascii=False)))
    extra = sorted(set(NUM_RE.findall(text)) - allowed)
    if extra:
        issues.append("재료에 없는 숫자:" + ",".join(extra[:5]))
    return issues


def facts_hash(f):
    return hashlib.sha1((PROMPT_VER + json.dumps(f, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]


def _llm(f):
    from backend.core.llm import chat
    res = chat([{"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(f, ensure_ascii=False, indent=1)}],
               schema=SCHEMA, temperature=0.2, max_tokens=600)
    if "_raw" in res:
        raise ValueError(f"LLM 형식 오류: {str(res['_raw'])[:120]}")
    return str(res.get("설명", "")).strip()


def run(P, C, out_dir, llm="template", workers=4, force=False, log=print):
    """→ {tbl_id: {설명, 설명_출처, 검사, 재료_해시}} (descriptions.jsonl 에 저장·재사용)"""
    path = out_dir / "descriptions.jsonl"
    old = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                old[r["tbl_id"]] = r
    diffs = siblings_diff(P)
    res, todo = {}, []
    for tid, p in P.items():
        f = facts(p, C[tid], diffs.get(tid, []))
        h = facts_hash(f)
        tpl = template_description(p, C[tid], diffs.get(tid, []))
        if llm == "template":
            res[tid] = {"tbl_id": tid, "설명": tpl, "설명_출처": "template", "검사": [], "재료_해시": h}
            continue
        o = old.get(tid)
        if o and not force and o.get("재료_해시") == h and o.get("설명_출처") == llm:
            res[tid] = o
            continue
        todo.append((tid, f, h, tpl))
    if todo:
        log(f"  LLM 설명 {len(todo)}개 (캐시 {len(P) - len(todo)})")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_llm, f): (tid, f, h, tpl) for tid, f, h, tpl in todo}
            for n, fu in enumerate(as_completed(futs), 1):
                tid, f, h, tpl = futs[fu]
                try:
                    text = fu.result()
                    iss = check(text, f)
                    res[tid] = ({"tbl_id": tid, "설명": text, "설명_출처": llm, "검사": [], "재료_해시": h} if not iss else
                                {"tbl_id": tid, "설명": tpl, "설명_출처": "template(LLM 검사 실패)", "검사": iss,
                                 "LLM_원문": text, "재료_해시": h})
                except Exception as e:  # noqa: BLE001  (실패한 표는 template 로)
                    res[tid] = {"tbl_id": tid, "설명": tpl, "설명_출처": "template(LLM 실패)",
                                "검사": [f"LLM 실패: {str(e)[:120]}"], "재료_해시": h}
                if n % 50 == 0:
                    log(f"    {n}/{len(todo)} ({time.time() - t0:.0f}초)")
    with path.open("w", encoding="utf-8") as fo:
        for tid in P:
            fo.write(json.dumps(res[tid], ensure_ascii=False) + "\n")
    return res
