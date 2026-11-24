"""숫자 일치(numeric_match)와 의미적 정답(semantic_ok) 분리 (criteria.md 4.3)

claim 단위(claim.py)로 판정한다. 같은 숫자라도 단위 · 부호 · 항목 · 지역 · 연도가 기대와 다르면 다른 주장이다.
  numeric_match : 답변에 기대값과 크기가 같은 숫자가 있다
  unit_ok       : 그 숫자의 단위가 기대 단위와 같은 정규형이다 (명 ≠ 가구, % ≠ %p). 단위를 적지 않았으면 판정하지 않는다
  sign_ok       : 부호 또는 방향어(증가 · 감소 · 순유입 · 순유출)가 기대 부호와 맞는다
  semantic_ok   : 지역 · 연도 · 항목 레이블이 기대 binding 과 맞는다. binding 기대가 없으면 None (N/A)
지역은 숫자 앞의 가장 가까운 레이블을 쓰되, 분모 위치('전국 대비' · '전국 중')의 지역은 대상이 아니므로 건너뛴다.
구조 근거(그 값을 만든 계산의 원본 행 좌표)가 있으면 함께 대조하고, 복원이 모호하면 binding_unresolved(None).
"""
import re
from dataclasses import dataclass, field

from eval.generator import resolve as R
from eval.generator.checks.normalize import close, normalize
from eval.generator.claim import Claim, numeric_claims, period_key, region_key

# 항목 어휘: 같은 문장에 다른 항목이 붙어 있으면 항목 불일치로 본다 (예: 출생아 238,317 을 '혼인건수 238,317건' 으로 말함)
ITEM_VOCAB = ("출생아", "출생", "사망자", "사망", "혼인", "결혼", "이혼", "인구", "가구", "합계출산율", "출산율", "고령인구", "순이동",
              "전입", "전출", "매출", "사업체", "면적", "밀도")


@dataclass
class Bind:
    numeric_match: bool
    semantic_ok: bool | None
    detail: dict = field(default_factory=dict)
    unit_ok: bool | None = None
    sign_ok: bool | None = None
    item_ok: bool | None = None


def _as_list(v) -> list[str]:
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, (list, tuple, set)) else [str(v)]


def _item_tokens(item: str | None) -> list[str]:
    if not item:
        return []
    base = re.sub(r"\(.*?\)|수$|\s", "", str(item))
    toks = [t for t in ITEM_VOCAB if t in base]
    return toks or ([base] if base else [])


def _magnitude_ok(c: Claim, gold: float, unit: str | None, tol: float) -> bool:
    """크기 일치. 허용오차는 max(표시 허용오차, 그 숫자 표기의 정밀도). 정밀도 부족은 required_digits 가 따로 본다"""
    n = normalize(float(c.value), c.unit)
    if n.value is None:
        return False
    k = n.value / float(c.value) if c.value else 1.0          # 정규화 배율 (% → ratio 는 0.01, 천명 → 명 은 1000)
    cands = [(abs(n.value), abs(float(c.resolution) * k))]
    if c.unit is None and unit in ("ratio", "pp"):          # '17.5' 처럼 단위 없이 쓴 비율
        cands.append((abs(float(c.value)) / 100, float(c.resolution) / 100))
    return any(close(v, abs(gold), atol=max(tol, res) + 1e-12) for v, res in cands)


def _unit_ok(c: Claim, unit: str | None) -> bool | None:
    if c.unit is None or unit is None:
        return None
    return normalize(float(c.value), c.unit).unit == unit


def _sign_ok(c: Claim, gold: float) -> bool | None:
    """부호는 숫자 표기가 우선. 방향어는 음수 기대값(순이동 · 감소량)에만 쓴다:
    양수 수준값('640,089명 … 238,317명으로 감소')의 방향어는 추이를 말하는 것이라 부호 판정 근거가 아니다"""
    if gold == 0:
        return True
    want_neg = gold < 0
    if c.value < 0:
        return want_neg
    if not want_neg:
        return True
    if c.direction == "neg":
        return True
    if c.direction == "pos":
        return False
    return None                            # 음수 기대인데 부호 · 방향어가 없으면 판정하지 않는다


def structural_coord(calc: dict | None, records: list[dict], steps: list[dict]) -> tuple[dict | None, str | None]:
    """값을 만든 계산의 원본 행 좌표들을 합친 것"""
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
            "periods": {str(c.get("period")) for c in coords if c.get("period")}}, None


def check(text: str, gold: float, unit: str | None, binding: dict | None, *, tol: float = 0.0,
          calc: dict | None = None, records: list[dict] | None = None, steps: list[dict] | None = None,
          point_key: dict | None = None, extra_regions: tuple[str, ...] = (), other_items: tuple[str, ...] = ()) -> Bind:
    claims = [c for c in numeric_claims(text, extra_regions) if _magnitude_ok(c, gold, unit, tol)]
    if not claims:
        return Bind(False, False, {"why": "숫자를 찾지 못함"})
    b = binding or {}
    want_regions = {region_key(r, extra_regions) for r in _as_list(b.get("region"))}
    want_periods = set(_as_list(b.get("period")))
    want_items = _item_tokens(b.get("item"))
    structural, why = structural_coord(calc, records or [], steps or []) if calc is not None else (None, "no_calc")
    if structural is not None and point_key:
        if point_key.get("시점"):
            structural["periods"] = {str(point_key["시점"])}
        for k, v in point_key.items():
            if k != "시점" and any(h in k for h in R.REGION_HINTS):
                structural["regions"] = {region_key(v)}
    if structural:
        want_regions |= structural["regions"] if not want_regions else set()
    vocab = tuple(dict.fromkeys(ITEM_VOCAB + other_items))

    def judge(c: Claim) -> dict:
        r_ok = not want_regions or c.region is None or c.region in want_regions
        # [CHANGED] 이전: c.year in want_periods — 월 기간('2024-12')을 연도 '2024' 와 비교해 항상 불일치였다
        want_p = {period_key(x) or x for x in want_periods}
        if not want_periods or (c.period is None and c.year is None):
            p_ok = True
        elif c.period and "-" in c.period:
            p_ok = c.period in want_p or c.period[:4] in want_p
        else:
            p_ok = (c.period or c.year) in {x[:4] for x in want_p}
        if want_items:
            # 기대 항목 어휘가 문장에 있으면 일치. 없고 다른 항목 어휘만 있으면 불일치. 둘 다 없으면 판정하지 않는다
            if any(t in c.sentence for t in want_items):
                i_ok = True
            elif [t for t in vocab if t in c.sentence and not any(t in w or w in t for w in want_items)]:
                i_ok = False
            else:
                i_ok = None
        else:
            i_ok = None
        return {"claim": c, "r": r_ok, "p": p_ok, "i": i_ok, "u": _unit_ok(c, unit), "s": _sign_ok(c, gold)}

    scored = [judge(c) for c in claims]
    best = max(scored, key=lambda x: sum(1 for k in ("r", "p", "i", "u", "s") if x[k] is not False))   # 가장 잘 맞는 claim 하나로 판정
    c = best["claim"]
    k = abs(normalize(1.0, c.unit).value or 1.0)
    detail = {"text": c.text, "region": c.region, "year": c.year, "unit": c.unit, "direction": c.direction,
              "decimals": c.decimals, "resolution": float(c.resolution) * k,       # 정규형 단위의 표기 정밀도
              "structural": {k: sorted(v) for k, v in structural.items()} if structural else None, "structural_why": why}
    if not binding:
        return Bind(True, None, {**detail, "why": "binding 기대 없음"}, best["u"], best["s"], best["i"])
    if calc is not None and structural is None:
        return Bind(True, None, {**detail, "why": "binding_unresolved"}, best["u"], best["s"], best["i"])
    sem = best["r"] and best["p"] and best["i"] is not False
    return Bind(True, sem, detail, best["u"], best["s"], best["i"])
