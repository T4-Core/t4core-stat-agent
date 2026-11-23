"""숫자 일치(numeric_match)와 의미적 정답(semantic_ok) 분리 (계획 2.2, D-5 · D-25)

numeric_match: 문장의 숫자가 기대값과 같은가. 숫자 추출은 synthetic_gold_pipeline 의 extract_numbers 를 재사용한다
semantic_ok  : 그 숫자가 기대한 지역 · 기간 · 지표에 연결되는가
  (1) 구조 근거: 그 값을 만든 CalcResult.inputs → resolve_input(record_id + item + key + select) → 원본 행의 전체 좌표
  (2) 텍스트 근거: 숫자가 있는 문장의 지역 · 연도 레이블
  (1)이 있으면 (1)을 우선하고, (2)에서 다른 지역 · 연도가 그 숫자에 붙어 있으면 불일치. 복원이 모호하면 None (binding_unresolved)
"""
import re
from dataclasses import dataclass, field

from eval.generator import resolve as R
from eval.generator.checks.normalize import close, normalize
from synthetic_gold_pipeline.tools.evaluation_tool import extract_numbers, split_sentences

REGIONS = ("전국", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "충청북도",
           "충청남도", "전북", "전남", "전라북도", "전라남도", "경북", "경남", "경상북도", "경상남도", "제주")
YEAR = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
SHORT = {"충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남"}


def region_key(name: str | None) -> str | None:
    if not name:
        return None
    n = R.norm(name)
    for full, short in SHORT.items():
        if n.startswith(full) or n.startswith(short):
            return short
    for r in REGIONS:
        if n.startswith(r):
            return r
    return n


@dataclass
class Bind:
    numeric_match: bool
    semantic_ok: bool | None
    detail: dict = field(default_factory=dict)


def _mentions(text: str, gold: float, unit: str | None, tol: float):
    out = []
    for m in extract_numbers(text):
        if m.is_period_token:
            continue
        n = normalize(float(m.value), m.unit)
        if n.value is None:
            continue
        cands = [n.value]
        if m.unit is None and unit in ("ratio", "pp"):        # '17.5' 처럼 단위 없이 쓴 비율
            cands.append(float(m.value) / 100)
        if any(close(v, gold, atol=tol) or close(-v, gold, atol=tol) for v in cands):
            out.append(m)
    return out


def text_labels(text: str, start: int, sentence: tuple[int, int]) -> dict:
    """숫자 앞쪽(같은 문장)에서 가장 가까운 지역 · 연도"""
    a, _ = sentence
    before = text[a:start]
    regs = [(mm.start(), region_key(mm.group(0))) for mm in re.finditer("|".join(REGIONS), before)]
    yrs = [(mm.start(), mm.group(1)) for mm in YEAR.finditer(before)]
    return {"region": regs[-1][1] if regs else None, "period": yrs[-1][1] if yrs else None,
            "regions_in_sentence": {r for _, r in regs}, "years_in_sentence": {y for _, y in yrs}}


def structural_coord(calc: dict | None, records: list[dict], steps: list[dict]) -> tuple[dict | None, str | None]:
    """값을 만든 계산의 원본 행 좌표들을 합친 것. 지역 · 시점이 여럿이면 집합"""
    if not calc:
        return None, "no_calc"
    coords = []
    for inp in calc.get("inputs") or []:
        row, why = R.resolve_input(records, inp, R.select_of(steps, calc.get("step_id"), inp.get("record_id")))
        if row is None:
            return None, why or "missing"
        coords.append(row.coord())
    if not coords:
        return None, "no_inputs"
    return {"regions": {region_key(c.get("region")) for c in coords if c.get("region")},
            "periods": {str(c.get("period")) for c in coords if c.get("period")},
            "items": {R.norm(c.get("item")) for c in coords if c.get("item")}}, None


def check(text: str, gold: float, unit: str | None, binding: dict | None, *, tol: float = 0.0,
          calc: dict | None = None, records: list[dict] | None = None, steps: list[dict] | None = None,
          point_key: dict | None = None) -> Bind:
    hits = _mentions(text, gold, unit, tol)
    if not hits:
        return Bind(False, False, {"why": "숫자를 찾지 못함"})
    if not binding:
        return Bind(True, True, {"why": "binding 기대 없음"})
    want_r, want_p = region_key(binding.get("region")), binding.get("period")
    sents = split_sentences(text)
    structural, why = (structural_coord(calc, records or [], steps or []) if calc is not None else (None, "no_calc"))
    if structural is not None and point_key:
        if point_key.get("시점"):
            structural["periods"] = {str(point_key["시점"])}
        for k, v in point_key.items():
            if k != "시점" and any(h in k for h in R.REGION_HINTS):
                structural["regions"] = {region_key(v)}
    s_ok = None
    if structural is not None:
        s_ok = (not want_r or want_r in structural["regions"] or not structural["regions"]) and \
               (not want_p or str(want_p) in structural["periods"] or not structural["periods"])
        if want_r and not structural["regions"]:
            s_ok = None if calc is not None else s_ok      # 고정 차원을 select 로도 복원 못 함
    best = None
    ok_regions = {want_r} | (structural["regions"] if structural else set())
    ok_periods = {str(want_p)} | (structural["periods"] if structural else set())
    for m in hits:
        lab = text_labels(text, m.start, sents[m.sentence])
        # 숫자 앞 레이블이 기대 대상이거나 그 계산의 입력(분모 '전국 대비' 등)이면 일치. 기대 지역이 문장에 아예 없고 다른 지역이 붙으면 불일치
        r_ok = not want_r or lab["region"] in ok_regions | {None} or want_r in lab["regions_in_sentence"]
        p_ok = not want_p or lab["period"] in ok_periods | {None} or str(want_p) in lab["years_in_sentence"]
        best = best or (m, lab, r_ok and p_ok)
        if r_ok and p_ok:
            best = (m, lab, True)
            break
    t_ok = best[2]
    detail = {"structural": {k: sorted(v) for k, v in structural.items()} if structural else None,
              "structural_why": why, "text": {k: v for k, v in best[1].items() if not isinstance(v, set)}}
    if structural is None and calc is not None:
        return Bind(True, None, {**detail, "why": "binding_unresolved"})
    if s_ok is None and structural is not None:
        return Bind(True, None, {**detail, "why": "binding_unresolved"})
    ok = t_ok if s_ok is None else (s_ok and t_ok)
    return Bind(True, ok, detail)
