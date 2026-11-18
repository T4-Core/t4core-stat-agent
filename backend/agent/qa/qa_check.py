"""형식 검사 — 필드 · 타입 · 허용값 + 스키마에 없는 키 (qa 설계.md 5·6장)

  check(point, raw) → Checked(ok, value, issues, error_locs, changed)
    raw        검사할 값 (dict · list · 그 안의 pydantic 객체). pydantic 객체는 미리 model_dump 해서 넘긴다
    ok=False   스키마 검사 실패. error_locs 에 틀린 위치 (대응은 qa_runner 가 정한다)
    ok=True    통과. 보정(B안)이 있었으면 changed=True 이고 value 는 보정한 사본, 없으면 value 는 raw 그대로

  보정 B안 (pydantic 수준만)
    · 손실 없는 타입 변환 ("2023" → 2023)      → pydantic 이 바꾼 값을 쓴다 (warning, fixed)
    · 빠진 선택 필드                           → 기록만 (info). 값에 넣지 않는다 — 받는 쪽 스키마가 같은 기본값을 채우고,
                                                 넣으면 setdefault · 'in' 처럼 키가 있는지 보는 코드의 동작이 바뀐다
    · 스키마에 없는 키                         → 지우지 않고 그대로 둔다 (warning)
"""
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from .qa_schemas import SCHEMAS

ERROR, WARNING, INFO = "error", "warning", "info"
MAX_ISSUES_PER_KIND = 30       # 같은 지점에서 같은 종류가 너무 많으면 앞의 것만 (나머지는 개수로)


@dataclass
class Issue:
    point: str
    path: str
    kind: str              # missing · type · enum · extra · fixed_type · default · exception
    severity: str          # error · warning · info
    message: str
    value: str | None = None
    fixed: bool = False
    action: str | None = None   # qa_runner 가 채운다: fixed · warn · retry · drop · stop · skip

    def as_dict(self):
        return asdict(self)


@dataclass
class Checked:
    ok: bool
    value: Any
    issues: list[Issue] = field(default_factory=list)
    error_locs: list[tuple] = field(default_factory=list)
    changed: bool = False


def path_str(loc) -> str:
    out = ""
    for p in loc:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


def _short(v, n=60) -> str | None:
    if v is None:
        return None
    s = repr(v)
    return s if len(s) <= n else s[:n] + "…"


_ENUM_TYPES = {"literal_error", "enum"}
_MISSING_TYPES = {"missing"}


def _kind(err_type: str) -> str:
    return "missing" if err_type in _MISSING_TYPES else "enum" if err_type in _ENUM_TYPES else "type"


def _clean_loc(loc) -> tuple:
    """pydantic 은 Union 의 갈래마다 오류를 내고 loc 에 갈래 이름('list[int]' · 'str' …)을 끼운다 → 경로에서 뺀다"""
    return tuple(p for p in loc if isinstance(p, int) or not (("[" in p and p.endswith("]")) or p in
                                                               {"int", "str", "float", "bool", "dict", "list", "none"}))


def _from_errors(point: str, e: ValidationError) -> tuple[list[Issue], list[tuple]]:
    issues, locs, seen = [], [], set()
    for er in e.errors():
        loc = _clean_loc(er["loc"])
        kind = _kind(er["type"])
        key = (loc, kind)
        if key in seen:              # Union 갈래마다 같은 위치 오류가 여러 번 나온다 → 한 번만
            continue
        seen.add(key)
        locs.append(loc)
        issues.append(Issue(point, path_str(loc), kind, ERROR, er["msg"],
                            None if kind == "missing" else _short(er.get("input"))))
    return issues, locs


def _field_map(model: BaseModel) -> dict[str, str]:
    """입력 키(이름 · alias) → 필드 이름"""
    out = {}
    for name, f in type(model).model_fields.items():
        out[name] = name
        if f.alias:
            out[f.alias] = name
    return out


def _dump(v):
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json", by_alias=True)
    if isinstance(v, list):
        return [_dump(x) for x in v]
    if isinstance(v, dict):
        return {k: _dump(x) for k, x in v.items()}
    if hasattr(v, "value") and type(v).__module__ != "builtins" and isinstance(getattr(v, "value"), (str, int)):
        return v.value               # Enum
    return v


def _same(raw, val) -> bool:
    if raw is val:
        return True
    try:
        if raw == val:
            return isinstance(raw, str) == isinstance(val, str)
    except Exception:  # noqa: BLE001  (비교할 수 없는 객체는 같다고 본다 — 예: plotly Figure)
        return True
    return False


class _Walk:
    """검사를 통과한 객체(inst)와 원래 값(raw)을 나란히 따라가며 보정 · 모르는 키를 찾는다"""

    def __init__(self, point):
        self.point, self.issues, self.changed = point, [], False
        self.counts: dict[str, int] = {}

    def add(self, issue: Issue):
        n = self.counts[issue.kind] = self.counts.get(issue.kind, 0) + 1
        if n <= MAX_ISSUES_PER_KIND:
            self.issues.append(issue)

    def walk(self, inst, raw, loc):
        if isinstance(inst, BaseModel) and isinstance(raw, dict):
            fmap, out = _field_map(inst), {}
            for k, v in raw.items():
                name = fmap.get(k)
                if name is None:
                    self.add(Issue(self.point, path_str(loc + (k,)), "extra", WARNING,
                                   "스키마에 없는 키 (그대로 둠)", _short(v)))
                    out[k] = v
                else:
                    out[k] = self.walk(getattr(inst, name), v, loc + (k,))
            given = {fmap[k] for k in raw if k in fmap}
            for name, f in type(inst).model_fields.items():
                if name not in given:      # 값에는 넣지 않는다: 받는 쪽 스키마가 같은 기본값을 채운다.
                    key = f.alias or name  # 넣으면 '키가 있는지' 를 보는 코드(setdefault · in)의 동작이 바뀐다
                    self.add(Issue(self.point, path_str(loc + (key,)), "default", INFO,
                                   "빠진 선택 필드 (받는 쪽에서 기본값)", _short(_dump(getattr(inst, name)))))
            return out
        if isinstance(inst, (list, tuple)) and isinstance(raw, (list, tuple)) and len(inst) == len(raw):
            return [self.walk(i, r, loc + (n,)) for n, (i, r) in enumerate(zip(inst, raw))]
        if isinstance(inst, dict) and isinstance(raw, dict) and inst.keys() == raw.keys():
            return {k: self.walk(inst[k], raw[k], loc + (k,)) for k in raw}
        val = _dump(inst)
        if isinstance(inst, BaseModel) or _same(raw, val):
            return raw
        self.changed = True
        self.add(Issue(self.point, path_str(loc), "fixed_type", WARNING, "타입을 바꿈 (손실 없는 변환)",
                       f"{_short(raw, 30)} → {_short(val, 30)}", fixed=True))
        return val


def check(point: str, raw, ctx: dict | None = None) -> Checked:
    """스키마 검사 → (통과하면) 규칙 검사 (qa_rules: 허용값 · 빈 값 · id 짝). ctx = id 짝을 볼 참조 목록"""
    from . import qa_policy
    from .qa_rules import rule_issues
    model = SCHEMAS[point]
    try:
        inst = model.model_validate(raw)
    except ValidationError as e:
        issues, locs = _from_errors(point, e)
        return Checked(False, raw, issues, locs)
    w = _Walk(point)
    value = w.walk(inst, raw, ())
    for kind, n in w.counts.items():
        if n > MAX_ISSUES_PER_KIND:
            w.issues.append(Issue(point, "", kind, INFO, f"같은 종류 {n - MAX_ISSUES_PER_KIND}건 더 (생략)"))
    checked_value = value if w.changed else raw
    found = rule_issues(point, checked_value, ctx)
    if not found:
        return Checked(True, checked_value, w.issues, [], w.changed)
    sev = ERROR if qa_policy.RULE_SEVERITY == "error" else WARNING
    rules = [Issue(point, path_str(loc), kind, sev, msg, None if v is None else _short(v)) for loc, kind, msg, v in found]
    if sev != ERROR:                                  # 기록만 (진단 모드)
        return Checked(True, checked_value, w.issues + rules, [], w.changed)
    return Checked(False, checked_value, w.issues + rules, [loc for loc, *_ in found], w.changed)


def drop_items(raw, locs, prefixes):
    """틀린 위치가 모두 '목록의 한 원소' 안이면 그 원소들을 뺀 사본과 뺀 위치를 돌려준다. 아니면 None
    prefixes: 뺄 수 있는 목록의 경로들 (예: (('chart_contents',), ('calc_results',)))"""
    import copy
    targets: dict[tuple, set[int]] = {}
    for loc in locs:
        hit = next((p for p in prefixes if tuple(loc[:len(p)]) == tuple(p) and len(loc) > len(p)
                    and isinstance(loc[len(p)], int)), None)
        if hit is None:
            return None
        targets.setdefault(tuple(hit), set()).add(loc[len(hit)])
    if not targets:
        return None
    out = copy.deepcopy(raw)
    dropped = []
    for prefix, idxs in targets.items():
        parent = out
        for p in prefix:
            parent = parent[p]
        for i in sorted(idxs, reverse=True):
            del parent[i]
            dropped.append(path_str(prefix + (i,)))
    return out, sorted(dropped)
