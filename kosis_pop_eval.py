"""
kosis_pop_qa.py 답변(answers/*.json) → 5대 핵심 지표 자동 판정 + 근거 자료 대조 리포트(HTML)

  python kosis_pop_eval.py                          # answers/*.json 전부
  python kosis_pop_eval.py --since 20261027_112113  # 이 시각(파일 이름) 이후 답변만
  python kosis_pop_eval.py --since 20261027_112113 --serve   # 브라우저 검수 페이지: HUMAN 판정 고르면 CSV 에 바로 저장
  → kosis_data/pop_qa/eval/report_<시각>.html   근거 자료·수치 대조·5대 지표 (파일로 열면 'CSV 내보내기'로 저장)
  → kosis_data/pop_qa/eval/human_review.csv     HUMAN 판정 (엑셀로 직접 채워도 됨)

5대 지표 (PASS / PARTIAL / FAIL, 계산 질문이 아니면 4번은 N/A)
  1. 검색 적합성        질문의 조사·개념(예: 인구밀도)·연도에 맞는 표를 골랐는가
  2. 원본 수치 추출      답변의 숫자가 근거 데이터의 값과 일치하는가
  3. Context 충분성     조회한 데이터에 질문 조건(연도·지역·항목)이 다 들어 있는가
  4. 변화율 응답 완성도   차이·증감률을 묻는 질문에 계산값을 바르게 제시했는가
  5. 자동 환각 검증      근거·계산으로 설명되지 않는 숫자(한글 단위 오류 포함)가 없는가
"""
import argparse
import csv
import html
import json
import re
import sys
from datetime import datetime
from functools import lru_cache
from itertools import permutations

from kosis_pop_qa import OUT, tables
from kosis_rag_qa import NUM_RE, SIDO, fmt_v, short_name

EVAL = OUT / "eval"
METRICS = ["검색 적합성", "원본 수치 추출", "Context 충분성", "변화율 응답 완성도", "자동 환각 검증"]
CALC_RE = re.compile(r"차이|증가|감소|증감|늘었|줄었|%|퍼센트|비율|비중|몇 배|합계|합이|일치|대비")
PCT_RE = re.compile(r"%|퍼센트|비율|비중|증가율|감소율|증감률")
META_RE = re.compile(r"단위|존재|왜|설명|어떤 (통계|항목)|의미")
YEAR_RE = re.compile(r"(?<![\d,])(1[89]\d{2}|20\d{2})(?![\d,])")
SURVEY_KW = {"주민등록인구현황": r"주민등록", "인구총조사": r"인구총조사|총조사|센서스", "장래가구추계": r"장래가구|추계"}
KOR_RE = re.compile(r"\d[\d,.]*\s*억(?:\s*\d[\d,.]*\s*(?:천|백|십)?)*(?:\s*만)?|(?:\d[\d,.]*\s*(?:천|백|십)?\s*)+만")
ROW_RE = re.compile(r"^  (\S+) \| (.+?) \| (.+?) \| (\S+) \| (.*)$")
JOSA = sorted("으로 에서 까지 부터 이나 에는 와 과 은 는 이 가 을 를 의 에 도 로 만 별".split(), key=len, reverse=True)
STOP = set("전국 기준 대한민국 데이터 수치 통계 자료 최근 현재 변화 추이 각각 얼마 정도 전체 서로 조사 연도".split())
SYN = {"남성": "남자", "여성": "여자"}
SYN_ALT = {"남자": ["남"], "여자": ["여"]}
KOSIS_URL = "https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId={}"
CRITERIA = {"VALUE": "질문 조건(연도·지역·항목)에 맞는 원본 값을 정확히 제시",
            "CALC": "동일 정의·단위로 두 값을 추출하고 차이·증감률을 바르게 계산",
            "TREND": "질문 기간의 시작·끝 값과 변화량(률)을 제시",
            "RANK": "비교 범위 안의 순위·값을 정확히 제시",
            "META": "자료에 있는 정보만으로 사실대로 설명 (없으면 없다고 답변)"}


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


# 근거(context) 파싱
def parse_context(ctx):
    """kosis_pop_qa.context_block 텍스트 → 표별 {tbl_id, title, cond, missing, rows, more, facts, notes}"""
    blocks = []
    for part in re.split(r"\n\n(?=\[자료 id=)", ctx or ""):
        m = re.match(r"\[자료 id=(\S+)\]", part)
        if not m:
            continue
        b = {"tbl_id": m[1], "title": "", "cond": "", "missing": "", "rows": [], "more": "", "facts": "", "notes": ""}
        for line in part.splitlines()[1:]:
            r = ROW_RE.match(line)
            if r:
                b["rows"].append({"prd": r[1], "region": r[2], "item": r[3], "raw": r[4], "value": num(r[4]), "unit": r[5]})
            elif line.startswith("제목: "):
                b["title"] = line[4:]
            elif line.startswith("조회 조건: "):
                b["cond"] = line[7:]
            elif line.startswith("⚠"):
                b["missing"] = line.split(": ", 1)[-1].split(" → ")[0]
            elif line.strip().startswith("… 외"):
                b["more"] = line.strip()
            elif line.startswith("핵심 수치: "):
                b["facts"] = line[7:]
            elif line.startswith("주의: "):
                b["notes"] = line[4:]
        blocks.append(b)
    return blocks


# 수치 대조
def tol(tok):
    d = len(tok.split(".")[1]) if "." in tok else 0
    return 0.5 * 10 ** -d + 1e-9


def derive(x, t, vals):
    """x 가 근거 값 그대로·단위 환산·두 값의 합/차/비율로 설명되면 (판정, 식, 사용한 값, 정확값), 아니면 None"""
    for v in vals:
        if abs(x - v) <= t:
            return "원본", fmt_v(v), [v], v
    for k, nm in ((1e3, "천"), (1e4, "만"), (1e6, "백만"), (1e8, "억")):
        for v in vals:
            if v >= k and abs(x - v / k) <= max(t, 0.5):
                return "환산", f"{fmt_v(v)} ÷ {nm}", [v], v / k
    pt = max(t, 0.051)                                 # 비율은 반올림 방식 차이 허용
    for a, b in permutations(vals, 2):
        if a >= b and abs(x - (a + b)) <= t:
            return "계산", f"{fmt_v(a)} + {fmt_v(b)}", [a, b], a + b
        if abs(x - (a - b)) <= t:
            return "계산", f"{fmt_v(a)} − {fmt_v(b)}", [a, b], a - b
        if b:
            if abs(x - a / b * 100) <= pt:
                return "계산", f"{fmt_v(a)} ÷ {fmt_v(b)} × 100", [a, b], a / b * 100
            if abs(x - abs(a - b) / b * 100) <= pt:
                return "계산", f"({fmt_v(a)} − {fmt_v(b)}) ÷ {fmt_v(b)} × 100", [a, b], abs(a - b) / b * 100
    return None


def kor_value(s):
    """'21억 7천만' → 2,170,000,000 / '2,177만' → 21,770,000"""
    m = re.match(r"(\d[\d,.]*)\s*억(.*)", s)
    total, rest = (num(m[1]) * 1e8, m[2]) if m else (0, s)
    unit = {"천": 1e3, "백": 1e2, "십": 10, "": 1}
    man = sum((num(n) or 0) * unit[u] for n, u in re.findall(r"(\d[\d,.]*)\s*(천|백|십)?", rest.replace("만", "")))
    return total + man * 1e4


def check_numbers(text, vals):
    """답변 속 숫자 → [{tok, kind, expr, used}]  kind: 원본 / 환산 / 계산 / 단위오류 / 계산오류 / 근거없음"""
    out, seen = [], set()
    for m in KOR_RE.finditer(text):                    # 한글 단위 금액('21억 7천만')은 값으로 바꿔 상대오차 1% 로 대조
        s = m[0].strip()
        x = kor_value(s)
        if s in seen or not x:
            continue
        seen.add(s)
        hit = derive(x, 0.01 * x, vals)
        if not hit:
            for f in (100, 0.01, 10, 0.1):
                r = derive(x / f, 0.01 * x / f, vals)
                if r:
                    hit = ("단위오류", f"근거 {r[1]} 의 {f:g}배로 표기", r[2])
                    break
        out.append(dict(zip(("kind", "expr", "used"), hit or ("근거없음", "", [])), tok=s))
    for m in re.finditer(NUM_RE.pattern + r"(\s*%)?", KOR_RE.sub(" ", text)):
        tok, v = m[0].replace(" ", ""), num(m[0].rstrip(" %"))
        short = len(tok.rstrip("%").replace(",", "").replace(".", "")) <= 2 and not m[1]
        if v is None or tok in seen or short or YEAR_RE.fullmatch(tok):
            continue                                   # 1~2자리(순위·개수, % 제외)·연도 제외
        seen.add(tok)
        hit = derive(v, tol(tok), vals)
        near = None if hit else derive(v, max(tol(tok), 0.001 * v), vals)   # 0.1% 안에서만 맞으면 계산 실수
        if near and near[0] == "계산":
            hit = ("계산오류", f"정확값 {fmt_v(near[3])} = {near[1]}", near[2])
        out.append(dict(zip(("kind", "expr", "used"), hit or ("근거없음", "", [])), tok=tok))
    return out


# 질문 조건
@lru_cache(maxsize=None)
def table_text(tid):
    t = tables()[tid]
    return " ".join([t["tbl_nm"], t["survey"], *(i["nm"] for i in t["items"])])


@lru_cache(maxsize=1)
def catalog_words():
    return " ".join(table_text(tid) for tid in tables())


def concepts(question):
    """질문 속 통계 개념어 (카탈로그의 표 이름·조사명·항목에 실제로 나오는 단어만)"""
    out = []
    for w in re.findall(r"\d+(?:인|세)|[가-힣]{2,}", question):      # '1인', '65세' 같은 숫자 개념어 포함
        for j in JOSA if w not in catalog_words() else ():   # '인구밀도' 의 '도' 는 조사가 아님
            if w.endswith(j) and len(w) - len(j) >= 2:
                w = w[: -len(j)]
                break
        w = SYN.get(w, w)
        if w in STOP or any(w in s or short_name(s) == w for s in SIDO):
            continue
        if w in catalog_words() and w not in out:
            out.append(w)
    return out


def has_word(w, text):
    """표기 차이 허용: 인구수 ↔ 인구, 남자 ↔ 남·남성"""
    vs = [w, *SYN_ALT.get(w, [])] + ([w[:-1]] if w.endswith("수") and len(w) > 2 else [])
    return any(v in text for v in vs)


def q_type(question, plans, calc):
    if calc:
        return "CALC"
    mode = plans[0]["mode"] if plans else "value"
    if mode in ("trend", "rank"):
        return mode.upper()
    return "META" if META_RE.search(question) else "VALUE"


# 5대 지표
def evaluate(r):
    q = r["question"]
    blocks = parse_context(r.get("context", ""))
    rows = [x for b in blocks for x in b["rows"]]
    vals = sorted({x["value"] for x in rows if x["value"] is not None})
    text = " ".join([str(r.get("answer", "")), str(r.get("summary", "")), *map(str, r.get("key_points") or [])])
    checks = check_numbers(text, vals)
    plans = r.get("plans") or []
    tids = [p["tbl_id"] for p in plans if p["tbl_id"] in tables()]
    calc, pct = bool(CALC_RE.search(q)), bool(PCT_RE.search(q))
    typ = q_type(q, plans, calc)
    q_years = YEAR_RE.findall(q)
    cs = concepts(q)
    by_kind = lambda *ks: [c for c in checks if c["kind"] in ks]
    orig, bad = by_kind("원본"), by_kind("근거없음", "단위오류", "계산오류")
    res = []

    # 1. 검색 적합성: 조건이 맞는 표가 있는지 + 질문의 조사·개념어가 고른 표에 있는지
    ok_plans = [p for p in plans if not p.get("missing") and p.get("n_rows")]
    chosen = " ".join(table_text(t) for t in tids)
    sv = [s for s, kw in SURVEY_KW.items() if re.search(kw, q)]
    sv_miss = [s for s in sv if not any(tables()[t]["survey"] == s for t in tids)]
    fits = lambda t: ((not sv or tables()[t]["survey"] in sv)                 # 대안 표: 질문의 조사·연도도 맞아야 인정
                      and all(y in tables()[t]["years"] for y in q_years))
    alt = {w: [t for t in tables() if t not in tids and has_word(w, table_text(t)) and fits(t)][:3]
           for w in cs if not has_word(w, chosen)}
    alt = {w: a for w, a in alt.items() if a}
    why = []
    if not ok_plans:
        why.append("조건에 맞는 표 없음 (" + " / ".join(
            f"{p['tbl_id']}: {', '.join(p.get('missing') or []) or '조회 0행'}" for p in plans) + ")")
    why += [f"'{w}'은(는) {', '.join(a)} 에 있으나 선택 안 됨" for w, a in alt.items()]
    if sv_miss:
        why.append(f"질문의 조사({', '.join(sv_miss)}) 표를 고르지 않음")
    res.append(("FAIL", "; ".join(why)) if why else
               ("PASS", f"{', '.join(tids)} — 질문의 조사·연도·개념어와 일치"))

    # 2. 원본 수치 추출: 답변 숫자가 근거 값과 일치하는지, 인용 값의 시점이 질문 연도와 맞는지
    cited_rows = [x for c in orig for x in rows if x["value"] in c["used"]]
    off_year = sorted({x["prd"] for x in cited_rows if q_years and x["prd"] not in q_years})
    if not rows:
        res.append(("FAIL", "근거 데이터 0행"))
    elif not checks:
        res.append(("N/A", "답변에 수치 없음 (설명형)") if typ == "META" else ("FAIL", "수치를 제시하지 않음"))
    elif not orig and not by_kind("환산", "계산"):
        res.append(("FAIL", f"근거 값과 일치하는 수치 없음 ({', '.join(c['tok'] for c in bad)})"))
    elif off_year:
        res.append(("PARTIAL", f"인용 값의 시점({', '.join(off_year)})이 질문 연도({', '.join(q_years)})와 다름"))
    elif bad:
        res.append(("PARTIAL", f"원본 일치 {len(orig)}개, 근거 없는 수치 {len(bad)}개"))
    else:
        res.append(("PASS", f"원본 값 {len(orig)}개 일치 (" + ", ".join(c["tok"] for c in orig[:4]) + ")"))

    # 3. Context 충분성: 질문 조건(연도·시도·개념어)이 조회 데이터에 들어 있는지
    got = " ".join([*(b["title"] for b in blocks), *(f"{x['prd']} {x['region']} {x['item']}" for x in rows)])
    sido = [s for s in SIDO if s in q or (len(short_name(s)) >= 2 and short_name(s) in q)]
    need = [*q_years, *dict.fromkeys(short_name(s) for s in sido), *cs]
    miss = [w for w in need if not has_word(w, got)]
    if not rows:
        res.append(("FAIL", "조회된 데이터 없음"))
    elif not miss:
        res.append(("PASS", "질문 조건 모두 포함" + (f" ({', '.join(need)})" if need else "")))
    else:
        res.append(("FAIL" if len(miss) == len(need) else "PARTIAL", f"데이터에 없는 조건: {', '.join(miss)}"))

    # 4. 변화율 응답 완성도: 계산 질문일 때만
    calcs = by_kind("계산")
    has_pct = any("× 100" in c["expr"] for c in calcs)
    if not calc:
        res.append(("N/A", "차이·증감률을 묻는 질문 아님"))
    elif by_kind("계산오류"):
        res.append(("FAIL", "계산 오류: " + "; ".join(f"{c['tok']} → {c['expr']}" for c in by_kind("계산오류"))))
    elif not calcs:
        res.append(("FAIL", "계산값(차이·증감률)을 제시하지 않음"))
    elif pct and not has_pct:
        res.append(("PARTIAL", "차이는 제시했으나 변화율(%) 누락 또는 검증 불가"))
    elif bad:
        res.append(("PARTIAL", f"계산값 {len(calcs)}개 검증, 근거 없는 수치 {len(bad)}개"))
    else:
        res.append(("PASS", "계산값 검증: " + "; ".join(f"{c['tok']} = {c['expr']}" for c in calcs[:3])))

    # 5. 자동 환각 검증
    if bad:
        res.append(("FAIL", "; ".join(f"{c['tok']} ({c['kind'] + ': ' + c['expr'] if c['expr'] else '근거·계산으로 설명 안 됨'})"
                                      for c in bad)))
    else:
        res.append(("PASS", f"수치 {len(checks)}개 모두 근거·계산으로 확인" if checks else "답변에 수치 없음"))

    levels = [lv for lv, _ in res]
    final = "FAIL" if "FAIL" in levels else "PARTIAL" if "PARTIAL" in levels else "PASS"
    cited = {v for c in checks if c["kind"] != "근거없음" for v in c["used"]}
    return {"type": typ, "criteria": CRITERIA[typ], "metrics": res, "final": final,
            "checks": checks, "blocks": blocks, "cited": cited}


# 콘솔·Markdown 출력 (kosis_pop_qa.print_result / qa_log.md 에서 사용)
MARK = {"원본": "✓ 원본 일치", "환산": "✓ 단위 환산", "계산": "✓ 계산 검증", "단위오류": "✗ 단위 오류", "계산오류": "✗ 계산 오류", "근거없음": "✗ 근거 없음"}


def evidence_text(r, ev=None, max_rows=20):
    ev = ev or evaluate(r)
    out = ["■ 근거 자료 (LLM 답변과 대조)"]
    for k, b in enumerate(ev["blocks"], 1):
        out.append(f"[근거 #{k}] {b['tbl_id']} {b['title']}")
        out.append(f"  조회 조건: {b['cond']}")
        if b["missing"]:
            out.append(f"  ⚠ 누락/불일치 조건: {b['missing']}")
        rows = b["rows"]
        shown = [x for x in rows if x["value"] in ev["cited"]][:max_rows]   # 답변이 인용한 행 우선
        shown += [x for x in rows if x not in shown][: max_rows - len(shown)]
        shown.sort(key=rows.index)
        if shown:
            out.append("  시점 | 지역/분류 | 항목 | 값 | 단위")
            out += [f"  {x['prd']} | {x['region']} | {x['item']} | {x['raw']} | {x['unit']}"
                    + ("   ◀ 답변 인용" if x["value"] in ev["cited"] else "") for x in shown]
        else:
            out.append("  데이터: 조건에 맞는 값 없음")
        if len(rows) > len(shown) or b["more"]:
            out.append(f"  … 외 {len(rows) - len(shown)}행 표시 생략" + (f" ({b['more']})" if b["more"] else ""))
        out.append(f"  KOSIS: {KOSIS_URL.format(b['tbl_id'])}")
    if ev["checks"]:
        out.append("\n■ 수치 대조 (답변 숫자 → 근거)")
        out += [f"  {MARK[c['kind']]:<9} {c['tok']}" + (f"  ← {c['expr']}" if c["expr"] else "") for c in ev["checks"]]
    out.append(f"\n■ 5대 지표 자동 판정 [{ev['type']}] → 최종 {ev['final']}")
    out += [f"  {i}. {m:<12} {lv:<7} {why}" for i, (m, (lv, why)) in enumerate(zip(METRICS, ev["metrics"]), 1)]
    return "\n".join(out)


# HTML 리포트 (HUMAN 판정은 드롭다운으로 바로 입력)
CSS = """
body{font-family:'Malgun Gothic',sans-serif;margin:0 24px 24px;color:#222;background:#fff}
h1{font-size:22px} .card{border:1px solid #ddd;border-radius:8px;padding:18px;margin:22px 0}
.head{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #222;padding-bottom:8px}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;background:#eef2f7;margin-left:6px}
.q{background:#f6f8fa;border-radius:6px;padding:12px;margin:12px 0}.ans{border-left:4px solid #2f6fdf;background:#f3f7ff;padding:12px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:13px} th{background:#1f2a3a;color:#fff;padding:7px}
td{border-bottom:1px solid #e3e3e3;padding:6px;vertical-align:top}
.PASS{background:#e3f5e8;color:#1b7a3a}.PARTIAL{background:#fff4d6;color:#8a6200}.FAIL{background:#fde3e3;color:#b42318}
.NA{background:#eee;color:#666}.TODO{background:#f1f1f1;color:#999}
.pill{display:inline-block;padding:2px 9px;border-radius:4px;font-weight:bold;font-size:12px}
.hsel{padding:2px 4px;border-radius:4px;border:1px solid #bbb;font-weight:bold;font-size:12px;cursor:pointer}
.memo{width:100%;min-height:38px;box-sizing:border-box;font-family:inherit}
.ev{border:1px solid #e3e3e3;border-radius:6px;padding:12px;margin:12px 0;background:#fcfcfc}
.warn{background:#fde3e3;padding:6px 10px;border-radius:4px;margin:6px 0}.cited td{background:#fff3b0;font-weight:bold}
.small{font-size:12px;color:#555}
#bar{position:sticky;top:0;background:#fff;padding:10px 0;border-bottom:1px solid #ddd;z-index:9;display:flex;gap:12px;align-items:center}
#bar button{padding:5px 12px;border-radius:4px;border:1px solid #2f6fdf;background:#2f6fdf;color:#fff;cursor:pointer}
@media print{#bar{display:none} .card{break-inside:avoid-page} details{display:block} .hsel{-webkit-appearance:none;appearance:none;border:none} *{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""

# 브라우저 쪽: 드롭다운·메모 변경 → (--serve) /save 로 CSV 즉시 저장 / (파일로 열면) 브라우저 임시 저장 + CSV 내보내기
JS = r"""
const HUMAN = __HUMAN__, COLS = __COLS__;
const live = location.protocol.startsWith('http'), LS = 'kosis_human_review';
const cls = v => v === 'N/A' ? 'NA' : (v || 'TODO');
const st = m => document.getElementById('st').textContent = m;
function paintFinal(key) {
  const v = (HUMAN[key] || {})['HUMAN_최종'] || '';
  document.querySelectorAll(`[data-final="${key}"]`).forEach(e => { e.textContent = v || '미검수'; e.className = 'pill ' + cls(v); });
}
async function save(key, col, v) {
  (HUMAN[key] = HUMAN[key] || {key})[col] = v;
  if (live) {
    const r = await fetch('/save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key, col, value: v})});
    st(r.ok ? `✅ 저장됨 (${key} ${col} = ${v || '미검수'})` : '⚠ 저장 실패 — 서버 창을 확인하세요');
  } else {
    try { localStorage.setItem(LS, JSON.stringify(HUMAN)); } catch (e) {}
    st('💾 브라우저에 임시 저장됨 — 다 채운 뒤 "CSV 내보내기"로 파일 저장');
  }
}
function autoFinal(key) {                       // 1~5 를 다 채웠고 최종이 비어 있으면 자동 계산 (N/A 는 제외)
  const h = HUMAN[key], vs = [1, 2, 3, 4, 5].map(i => h['HUMAN_' + i] || '');
  if (vs.includes('') || h['HUMAN_최종']) return;
  const f = vs.includes('FAIL') ? 'FAIL' : vs.includes('PARTIAL') ? 'PARTIAL' : 'PASS';
  const s = document.querySelector(`select[data-key="${key}"][data-col="HUMAN_최종"]`);
  s.value = f; s.className = 'hsel ' + cls(f);
  save(key, 'HUMAN_최종', f).then(() => paintFinal(key));
}
document.addEventListener('change', e => {
  const t = e.target, {key, col} = t.dataset;
  if (!col) return;
  if (t.tagName === 'SELECT') t.className = 'hsel ' + cls(t.value);
  save(key, col, t.value).then(() => col === 'HUMAN_최종' ? paintFinal(key) : col.startsWith('HUMAN_') && autoFinal(key));
});
if (!live) {                                    // 파일 모드: 이전에 임시 저장한 값 복원
  try {
    const s = JSON.parse(localStorage.getItem(LS) || 'null');
    if (s) {
      for (const k in s) HUMAN[k] = {...HUMAN[k], ...s[k]};
      document.querySelectorAll('[data-col]').forEach(el => {
        const v = (HUMAN[el.dataset.key] || {})[el.dataset.col];
        if (v !== undefined) { el.value = v; if (el.tagName === 'SELECT') el.className = 'hsel ' + cls(v); }
      });
      Object.keys(HUMAN).forEach(paintFinal);
    }
  } catch (e) {}
}
function exportCsv() {
  const q = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
  const rows = Object.values(HUMAN).sort((a, b) => a.key < b.key ? -1 : 1).map(h => COLS.map(c => q(h[c])).join(','));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['﻿' + [COLS.join(','), ...rows].join('\r\n')], {type: 'text/csv'}));
  a.download = 'human_review.csv';
  a.click();
}
st(live ? '🟢 자동 저장 모드 — 고르는 즉시 human_review.csv 에 저장됩니다'
        : '📄 파일 모드 — 바꾼 값은 이 브라우저에만 임시 저장됩니다. "CSV 내보내기" 후 eval 폴더의 human_review.csv 를 교체하세요');
"""

LEVELS = ["", "PASS", "PARTIAL", "FAIL", "N/A"]
HR_COLS = ["key", "id", "question", "자동_최종", *(f"HUMAN_{i}" for i in range(1, 6)), "HUMAN_최종", "메모"]
HR_PATH = EVAL / "human_review.csv"


def norm(v):
    v = str(v or "").strip().upper()
    return "N/A" if v in ("NA", "N/A") else v


def pill(lv, key=None):
    lv = lv or "미검수"
    cls = {"N/A": "NA", "미검수": "TODO"}.get(lv, lv)
    return f'<span class="pill {cls}"' + (f' data-final="{key}"' if key else "") + f">{html.escape(lv)}</span>"


def hsel(key, col, val):
    val = norm(val)
    opts = [*LEVELS, *([val] if val not in LEVELS else [])]
    cls = {"N/A": "NA", "": "TODO"}.get(val, val)
    return (f'<select class="hsel {html.escape(cls)}" data-key="{key}" data-col="{col}">'
            + "".join(f'<option value="{html.escape(o)}"{" selected" if o == val else ""}>{html.escape(o) or "미검수"}</option>'
                      for o in opts) + "</select>")


def render_card(qid, r, ev, hr):
    e, key = html.escape, r["_file"]
    o = [f'<div class="card" id="{qid}"><div class="head"><div><b style="font-size:18px">[{qid}]</b>'
         f'<span class="tag">유형: {ev["type"]}</span><span class="tag">표: {e(", ".join(r.get("tables") or []))}</span>'
         f'<span class="tag">{e(key)}</span></div>'
         f'<div>자동 판정 {pill(ev["final"])} &nbsp; 최종 HUMAN 판정 {hsel(key, "HUMAN_최종", hr.get("HUMAN_최종"))}</div></div>',
         f'<div class="q"><b>❓ 입력 질문: {e(r["question"])}</b><br>'
         f'<span class="small">🎯 채점 통과 기준: {e(ev["criteria"])}</span></div>',
         f'<div class="ans"><b>🤖 AI 출력 답변</b><br>{e(str(r.get("answer", "")))}'
         + (f'<br><span class="small">요약: {e(str(r.get("summary", "")))}</span>' if r.get("summary") else "")
         + f'<br><span class="small">• 핵심 수치: {e(" / ".join(map(str, r.get("key_points") or [])) or "없음")}'
         f' | 자료부족(insufficient): {r.get("insufficient")}</span></div>',
         "<table><tr><th>5대 핵심 지표</th><th>자동 판정</th><th>HUMAN 판정</th><th>자동 진단 근거</th></tr>"]
    for i, (m, (lv, why)) in enumerate(zip(METRICS, ev["metrics"]), 1):
        o.append(f"<tr><td><b>{i}. {m}</b></td><td>{pill(lv)}</td><td>{hsel(key, f'HUMAN_{i}', hr.get(f'HUMAN_{i}'))}</td>"
                 f"<td>{e(why)}</td></tr>")
    o.append("</table>")
    o.append(f'<div class="q">📝 검수 메모<br><textarea class="memo" data-key="{key}" data-col="메모" '
             f'placeholder="자동 판정이 틀린 이유, 원본과 다른 점 등">{e(hr.get("메모", ""))}</textarea></div>')
    if ev["checks"]:
        o.append('<div class="ev"><b>🔢 수치 대조 (답변 숫자 → 근거)</b><table><tr><th>답변 숫자</th><th>판정</th><th>근거·계산식</th></tr>')
        o += [f"<tr><td>{e(c['tok'])}</td><td>{pill('PASS' if c['kind'] in ('원본', '환산', '계산') else 'FAIL')} "
              f"{e(c['kind'])}</td><td>{e(c['expr'])}</td></tr>" for c in ev["checks"]]
        o.append("</table></div>")
    for k, b in enumerate(ev["blocks"], 1):
        o.append(f'<div class="ev"><b>📁 [근거 자료 #{k}] {e(b["title"])}</b> <span class="small">({b["tbl_id"]})</span><br>'
                 f'<span class="small">• 조회 조건: {e(b["cond"])}<br>• 원본 대조 링크: '
                 f'<a href="{KOSIS_URL.format(b["tbl_id"])}" target="_blank">KOSIS 웹 통계표 바로가기</a></span>')
        if b["missing"]:
            o.append(f'<div class="warn">⚠ 누락/불일치 조건: {e(b["missing"])}</div>')
        if b["facts"]:
            o.append(f'<div class="small">📊 핵심 수치(Facts): {e(b["facts"])}</div>')
        if b["notes"]:
            o.append(f'<div class="small">📝 주의: {e(b["notes"])}</div>')
        if b["rows"]:
            o.append("<table><tr><th>시점</th><th>지역/분류</th><th>항목</th><th>값</th><th>단위</th></tr>")
            o += [f'<tr{" class=cited" if x["value"] in ev["cited"] else ""}><td>{e(x["prd"])}</td><td>{e(x["region"])}</td>'
                  f'<td>{e(x["item"])}</td><td style="text-align:right">{e(x["raw"])}</td><td>{e(x["unit"])}</td></tr>'
                  for x in b["rows"]]
            o.append("</table>" + (f'<div class="small">{e(b["more"])}</div>' if b["more"] else ""))
        else:
            o.append('<div class="small">데이터: 조건에 맞는 값 없음</div>')
        o.append("</div>")
    return "\n".join(o) + "</div>"


def load_answers(since=None):
    files = sorted(p for p in (OUT / "answers").glob("*.json") if not since or p.stem >= since)
    out = []
    for p in files:
        r = json.loads(p.read_text(encoding="utf-8"))
        if r.get("question") and r.get("context") is not None:
            r["_file"] = p.stem
            out.append(r)
    return out


def load_human():
    if not HR_PATH.exists():
        return {}
    with HR_PATH.open(encoding="utf-8-sig") as f:
        return {row["key"]: {c: (norm(v) if c.startswith("HUMAN_") else v or "") for c, v in row.items() if c in HR_COLS}
                for row in csv.DictReader(f)}


def save_human(human):
    with HR_PATH.open("w", encoding="utf-8-sig", newline="") as f:   # 엑셀에서 한글 안 깨지게 BOM
        w = csv.DictWriter(f, fieldnames=HR_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(human.values(), key=lambda x: x["key"]))


def build(answers, evs):
    """현재 human_review.csv 를 반영한 리포트 HTML (기존 HUMAN 입력은 key=답변 파일 이름 기준으로 유지)"""
    EVAL.mkdir(parents=True, exist_ok=True)
    human = load_human()
    for n, (r, ev) in enumerate(zip(answers, evs), 1):
        human[r["_file"]] = {**{c: "" for c in HR_COLS}, **human.get(r["_file"], {}), "key": r["_file"],
                             "id": f"Q{n:03d}", "question": r["question"], "자동_최종": ev["final"]}
    save_human(human)
    e = html.escape
    rows, cards = [], []
    for n, (r, ev) in enumerate(zip(answers, evs), 1):
        qid, hr = f"Q{n:03d}", human[r["_file"]]
        cards.append(render_card(qid, r, ev, hr))
        rows.append(f'<tr><td><a href="#{qid}">{qid}</a></td><td>{e(r["question"])}</td><td>{ev["type"]}</td>'
                    + "".join(f"<td>{pill(lv)}</td>" for lv, _ in ev["metrics"])
                    + f"<td>{pill(ev['final'])}</td><td>{pill(hr.get('HUMAN_최종'), r['_file'])}</td></tr>")
    cnt = {lv: sum(ev["final"] == lv for ev in evs) for lv in ("PASS", "PARTIAL", "FAIL")}
    js = JS.replace("__HUMAN__", json.dumps(human, ensure_ascii=False).replace("</", "<\\/")) \
           .replace("__COLS__", json.dumps(HR_COLS, ensure_ascii=False))
    page = (f"<!doctype html><html lang=ko><head><meta charset=utf-8><title>KOSIS QA 평가</title><style>{CSS}</style></head><body>"
            '<div id="bar"><button onclick="exportCsv()">CSV 내보내기</button><span id="st" class="small"></span></div>'
            f"<h1>KOSIS 인구통계 QA — 5대 핵심 지표 평가</h1>"
            f"<p class=small>생성 {datetime.now():%Y-%m-%d %H:%M} · 답변 {len(answers)}개 · 자동 최종 "
            f"PASS {cnt['PASS']} / PARTIAL {cnt['PARTIAL']} / FAIL {cnt['FAIL']} · HUMAN 판정은 각 카드의 드롭다운으로 입력</p>"
            "<table><tr><th>ID</th><th>질문</th><th>유형</th>" + "".join(f"<th>{i}. {m}</th>" for i, m in enumerate(METRICS, 1))
            + f"<th>자동 최종</th><th>HUMAN 최종</th></tr>{''.join(rows)}</table>" + "\n".join(cards)
            + f"<script>{js}</script></body></html>")
    return page, cnt


def serve(answers, evs, port):
    """localhost 검수 페이지: 드롭다운·메모를 바꾸면 human_review.csv 에 바로 저장 (새로고침 = CSV 최신 내용으로 다시 그림)"""
    import threading
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    lock = threading.Lock()
    keys = {r["_file"] for r in answers}

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, ctype="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html"):
                return self.reply(404, b"not found")
            with lock:
                page, _ = build(answers, evs)
            self.reply(200, page.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            if self.path != "/save":
                return self.reply(404, b"not found")
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            col, key = d.get("col"), d.get("key")
            if key not in keys or col not in HR_COLS[4:]:          # HUMAN_1~5, HUMAN_최종, 메모 만 수정 허용
                return self.reply(400, b"bad request")
            with lock:
                human = load_human()
                human[key][col] = norm(d.get("value")) if col.startswith("HUMAN_") else str(d.get("value", ""))
                save_human(human)
            print(f"  저장: {key} {col} = {d.get('value') or '(빈칸)'}", flush=True)
            self.reply(200, b"ok")

        def log_message(self, *a):                                 # 요청마다 찍히는 기본 로그 끔
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n검수 페이지: {url}  (내 컴퓨터에서만 접속 가능 · 종료: Ctrl+C)", flush=True)
    webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("종료합니다.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="이 파일 이름(YYYYMMDD_HHMMSS) 이후 답변만")
    ap.add_argument("--serve", action="store_true", help="브라우저에서 HUMAN 판정을 입력하면 CSV 에 바로 저장")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    answers = load_answers(args.since)
    if not answers:
        raise SystemExit("평가할 답변(answers/*.json)이 없습니다.")
    evs = [evaluate(r) for r in answers]
    for n, (r, ev) in enumerate(zip(answers, evs), 1):
        print(f"[Q{n:03d}] {ev['final']:<7} " + " ".join(lv for lv, _ in ev["metrics"]) + f"  {r['question'][:50]}")
    page, cnt = build(answers, evs)
    rp = EVAL / f"report_{datetime.now():%Y%m%d_%H%M%S}.html"
    rp.write_text(page, encoding="utf-8")
    print(f"\n자동 최종: PASS {cnt['PASS']} / PARTIAL {cnt['PARTIAL']} / FAIL {cnt['FAIL']}")
    print(f"리포트: {rp}\nHUMAN 판정 CSV: {HR_PATH}")
    if args.serve:
        serve(answers, evs, args.port)


if __name__ == "__main__":
    main()
