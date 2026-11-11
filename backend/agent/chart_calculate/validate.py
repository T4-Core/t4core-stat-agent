"""
[NEW] 차트 검증 (명세 7장 ①·②) — 완성한 ChartContent 가 그 차트로 그릴 만한지 코드로 확인한다

  check_chart(content, requirements, data_errors) → CheckResult(passed, checked, failed, reasons)
    ① data_present    계산 단계에서 넘어온 오류가 없고 행이 있다. 실패하면 ② 로 가지 않는다
    ② required_roles  차트별 필수 역할이 encoding 에 있고, 가리키는 열이 실제로 있다
       requirements    코드별 판정 (아래 _CHECKS)

  검증 ③(단위 호환, 분모 0)은 계산할 때 calculate.py 가 한다.

  TODO(후속 명세): requirements 코드별 판정 기준은 팀 합의 전이다. 아래 기준은 임시값이고,
                   바뀌면 이 파일의 _CHECKS 함수와 PARTS_TOLERANCE 만 고친다.
"""
import re
from typing import Any, Callable

from backend.agent.chart_calculate.specs import SPECS, ChartSpec
from backend.schemas.chart import ChartContent, CheckResult

PARTS_TOLERANCE = 0.005                              # parts_sum_to_total: 총계 대비 상대 오차 0.5% 까지 허용
TOTAL_LABELS = {"계", "합계", "총계", "전체", "소계"}   # 구성 항목에 섞이면 안 되는 총계 이름
_COUNT = re.compile(r"^(min|max)_(points|categories)_(\d+)$")


class _Data:
    """ChartContent 를 역할 이름으로 읽는다"""

    def __init__(self, content: ChartContent, spec: ChartSpec, totals: dict[Any, float] | None):
        self.content, self.spec, self.totals = content, spec, totals
        self.enc = content.encoding

    def has(self, *roles: str) -> bool:
        return all(r in self.enc for r in roles)

    def values(self, role: str) -> list:
        if role not in self.enc:
            return []
        i = self.content.columns.index(self.enc[role])
        return [r[i] for r in self.content.rows]

    def distinct(self, role: str) -> list:
        return list(dict.fromkeys(self.values(role)))

    def axis_type(self, role: str) -> str | None:
        ax = self.content.axis.get(role)
        return ax.type if ax else None

    def distinct_columns(self, *roles: str) -> bool:
        return self.has(*roles) and len({self.enc[r] for r in roles}) == len(roles)


def _count(d: _Data, kind: str, what: str, n: int) -> str | None:
    if what == "points":      # long = 가로축의 서로 다른 값 수 / joined = 점(행) 수
        got = len(d.distinct("x")) if d.spec.rows == "long" and d.has("x") else len(d.content.rows)
        label = "점"
    else:
        role = d.spec.category or ("label" if d.has("label") else "x")
        got, label = len(d.distinct(role)), "항목"
    if kind == "min" and got < n:
        return f"{label} {got}개 (최소 {n}개)"
    if kind == "max" and got > n:
        return f"{label} {got}개 (최대 {n}개)"
    return None


def _time_axis(d: _Data) -> str | None:
    return None if d.axis_type("x") == "time" else "가로축이 시점이 아님"


def _category_axis(d: _Data) -> str | None:
    return None if "category" in (d.axis_type("x"), d.axis_type("y")) else "범주 축이 없음"


def _non_negative(d: _Data) -> str | None:
    roles = d.spec.non_negative or tuple(r for r in ("y", "value") if d.has(r))
    for role in roles:
        if neg := [v for v in d.values(role) if isinstance(v, (int, float)) and v < 0]:
            return f"{role}에 음수 {len(neg)}개"
    return None


def _two_series(d: _Data) -> str | None:
    if d.has("group"):                       # 피라미드: 좌우 두 집단
        n = len(d.distinct("group"))
        return None if n == 2 else f"group 이 {n}개 (2개여야 함)"
    if "y2" in d.spec.required:              # 복합: long 형식이라 y·y2 가 같은 '값' 열 → series 로 지표 2개를 구분
        return None if len(d.distinct("series")) >= 2 else "y 와 y2 에 올릴 지표 2개가 필요"
    n = len(d.distinct("series"))
    return None if n >= 2 else f"series 가 {n}개 (2개 이상이어야 함)"


def _measures(*roles: str):
    def check(d: _Data) -> str | None:
        return None if d.distinct_columns(*roles) else f"서로 다른 지표 {len(roles)}개가 필요 ({', '.join(roles)})"
    return check


def _region(d: _Data) -> str | None:
    return None if d.has("region") and d.distinct("region") else "지역 열이 없음"


def _two_points(d: _Data) -> str | None:
    lack = sum(1 for a, b in zip(d.values("start"), d.values("end")) if a is None or b is None)
    return f"두 값이 모두 있지 않은 범주 {lack}개" if lack or not d.has("start", "end") else None


def _parts(d: _Data) -> str | None:
    """명세 7장 'parts_sum_to_total 의 확인 방법': 1) 구성 항목 중복 없음 2) 총계가 있으면 합과 비교"""
    part = "series" if d.has("series") and d.spec.category is None else (d.spec.category or "label")
    group = "x" if part == "series" else None         # 누적 막대는 같은 x 안에서, 원형·트리맵은 전체에서
    value = "y" if d.has("y") and not d.has("value") else "value"
    groups, parts, values = (d.values(group) if group else [None] * len(d.content.rows)), d.values(part), d.values(value)
    seen, sums = set(), {}
    for g, p, v in zip(groups, parts, values):
        if (g, p) in seen:
            return f"구성 항목 중복: {p}"
        seen.add((g, p))
        sums[g] = sums.get(g, 0) + (v or 0)
    if len(set(parts)) > 1 and (mixed := TOTAL_LABELS & {str(p) for p in parts}):
        return f"구성 항목에 총계가 섞임: {sorted(mixed)}"
    for g, total in (d.totals or {}).items():      # totals 없음 = scope=selected → 합이 정의상 100%
        if g in sums and total and abs(sums[g] - total) / abs(total) > PARTS_TOLERANCE:
            return f"구성 항목의 합 {sums[g]:g} ≠ 총계 {total:g}" + (f" ({g})" if g is not None else "")
    return None


_CHECKS: dict[str, Callable[[_Data], str | None]] = {
    "time_axis_required": _time_axis,
    "category_axis_required": _category_axis,
    "non_negative": _non_negative,
    "parts_sum_to_total": _parts,
    "two_series_required": _two_series,
    "two_measures_required": _measures("x", "y"),
    "three_measures_required": _measures("x", "y", "size"),
    "two_dimensions_required": _measures("x", "y"),
    "region_dimension_required": _region,
    "two_points_per_category": _two_points,
}


def check_chart(content: ChartContent, requirements: list[str], data_errors: list[str] | None = None,
                totals: dict[Any, float] | None = None) -> CheckResult:
    """
    data_errors  계산 단계의 오류 (truncated, 없는 시점 …). 있으면 ① 실패
    totals       parts_sum_to_total 에서 비교할 총계 {묶음 값: 총계}. 원형·트리맵은 묶음이 없어 키가 None
    """
    spec = SPECS[content.chart_type]
    out = CheckResult(chart_type=content.chart_type, passed=False, checked=["data_present"])

    def fail(code: str, why: list[str]) -> CheckResult:
        out.failed.append(code)
        out.reasons += why
        return out

    if data_errors or not content.rows:
        return fail("data_present", list(data_errors or []) or ["행이 없음"])

    out.checked.append("required_roles")
    missing = [r for r in spec.required if r not in content.encoding]
    unknown = [f"{r}→{c}" for r, c in content.encoding.items() if c not in content.columns]
    if missing or unknown:   # 역할이 없으면 아래 조건들은 판정할 수 없다
        return fail("required_roles", ([f"필수 역할 없음: {missing}"] if missing else [])
                    + ([f"없는 열을 가리킴: {unknown}"] if unknown else []))

    data = _Data(content, spec, totals)
    for code in dict.fromkeys(requirements):
        m = _COUNT.match(code)
        check = (lambda d, m=m: _count(d, m[1], m[2], int(m[3]))) if m else _CHECKS.get(code)
        if check is None:
            # 모듈 2 가 새 코드를 보내도 차트를 버리지는 않는다. 판정하지 않았다는 사실만 남긴다
            out.reasons.append(f"알 수 없는 조건: {code} (판정하지 않음)")
            continue
        out.checked.append(code)
        if why := check(data):
            fail(code, [why])
    out.passed = not out.failed
    return out
