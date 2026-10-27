"""
문맥 개선판 (실험용, 베이스라인 미수정) — 질문 조건을 적용한 단면·기간으로 facts 를 코드가 계산해 문맥에 넣는다

베이스라인 context_block 은 조건을 적용하면 조건 행만 넣고 facts 앞에서 반환한다 (G-5).
facts 자체도 기본 단면(전국·합계)·수록 전 기간으로만 미리 계산돼 있다 (B-9). 그래서 LLM 이 계산을 떠안고,
실제로는 계산하지 않거나(G-8) 단위를 섞는다(B-8).

여기서는 condition_rows 가 조건 적용 표(DataFrame)를 함께 넘기게 하고, context_block 이 그 표로
  · 시점 2개 이상      시리즈별 시작·끝·변화량(단위 % 면 %p)·변화율·구간 최대·최소
  · 시점 1개 + 시계열   직전 시점 대비 변화량·변화율 (기간 제한 없이 다시 읽은 시계열)
  · 시점 1개 + 범주들   1위·2위·최하위 (합계·묶음 구간은 빼고, 뺀 목록을 표시), 범주가 2개면 차이
를 계산해 "핵심 수치(질문 조건 기준·코드 계산)" 줄로 넣고, 블록 머리말에 적용 좌표를 적는다.

사용: e2e_eval.py --context v2 (qa.condition_rows · qa.context_block 을 바꿔 끼움)
"""
import copy
import math
import re

from profiling import baseline as b
from profiling import config
from profiling.check_facts import TOTAL_NAMES, age_range
import kosis_rag_qa as qa  # noqa: E402

BASE_CONDITION_ROWS = qa.condition_rows    # 바꿔 끼우기 전 원본 (재귀 방지)
BASE_CONTEXT_BLOCK = qa.context_block
MAX_SERIES = 8                             # kosis_views.MAX_LINES 와 같은 상한
FACTS_PREFIX = "핵심 수치(질문 조건 기준·코드 계산): "


class Rows(list):
    """condition_rows 의 텍스트 행 + 계산용 표. answer() 는 list 로만 쓰므로 기존 동작은 그대로다"""
    df = None
    series = None


def condition_rows_v2(src, max_rows):
    df, rows = BASE_CONDITION_ROWS(src, max_rows)
    out = Rows(rows)
    out.df = b.kv.load_view(src, config.VIEWS_DIR)
    if src.get("period"):                   # 직전 시점 대비용: 기간 제한을 뺀 같은 단면
        s2 = copy.deepcopy(src)
        s2["period"] = {}
        out.series = b.kv.load_view(s2, config.VIEWS_DIR)
    return df, out


def num(v, unit=""):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "자료없음"
    s = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.3f}".rstrip("0").rstrip(".")
    return f"{s}{unit}"


def signed(v, unit=""):
    return ("+" if v > 0 else "") + num(v, unit)


def aggregate_names(names):
    """다른 범주를 포함하는 묶음 이름 (합계류, 연령 구간 포함) — check_facts 와 같은 규칙"""
    rng = {n: age_range(n) for n in names}
    out = {n for n in names if str(n).strip() in TOTAL_NAMES}
    for n, r in rng.items():
        if r and any(o != n and ro and r[0] <= ro[0] and ro[1] <= r[1] and ro != r for o, ro in rng.items()):
            out.add(n)
    return out


def varying(df):
    cols = [c for c in df.columns if re.fullmatch(r"c\d_name", c)] + ["itm_nm"]
    return [c for c in cols if c in df and df[c].nunique() > 1]


def change_facts(df, var, unit):
    pp = "%p" if "%" in unit else unit
    out = []
    groups = list(df.groupby(var, sort=False)) if var else [("", df)]
    for key, g in groups[:MAX_SERIES]:
        d = g.dropna(subset=["value"]).sort_values("period_date")
        if len(d) < 2:
            continue
        a, z = d.iloc[0], d.iloc[-1]
        label = " ".join(map(str, key if isinstance(key, tuple) else (key,))).strip()
        diff = z.value - a.value
        pct = f"변화율 {signed(diff / a.value * 100, '%')}" if a.value > 0 else "변화율 계산 불가(기준값 0 이하)"
        mx, mn = d.loc[d.value.idxmax()], d.loc[d.value.idxmin()]
        out.append(f"{label + ' ' if label else ''}{a.period_label} {num(a.value, unit)} → {z.period_label} "
                   f"{num(z.value, unit)}, 변화량 {signed(diff, pp)}, {pct}, 구간 최대 {mx.period_label} "
                   f"{num(mx.value, unit)}, 최소 {mn.period_label} {num(mn.value, unit)}")
    return out


def prev_facts(series, var, unit):
    """시점 1개 질문: 같은 단면의 직전 시점 대비"""
    if series is None or var:
        return []
    d = series.dropna(subset=["value"]).sort_values("period_date")
    if len(d) < 2:
        return []
    p, z = d.iloc[-2], d.iloc[-1]
    pct = f", 변화율 {signed((z.value - p.value) / abs(p.value) * 100, '%')}" if p.value else ""
    pp = "%p" if "%" in unit else unit
    return [f"직전 시점 대비: {p.period_label} {num(p.value, unit)} → {z.period_label} {num(z.value, unit)}, "
            f"변화량 {signed(z.value - p.value, pp)}{pct}"]


def rank_facts(df, var, unit):
    col = max(var, key=lambda c: df[c].nunique())
    others = [c for c in var if c != col]
    out = []
    groups = list(df.groupby(others, sort=False)) if others else [("", df)]
    for key, g in groups[:4]:
        d = g.dropna(subset=["value"])
        excl = aggregate_names(d[col].astype(str).tolist())
        d = d[~d[col].astype(str).isin(excl)].sort_values("value", ascending=False)
        if len(d) < 2:
            continue
        label = " ".join(map(str, key if isinstance(key, tuple) else (key,))).strip()
        head = f"{label} " if label else ""
        parts = [f"{k + 1}위 {r[col]} {num(r.value, unit)}" for k, (_, r) in enumerate(d.head(2).iterrows())]
        if len(d) > 2:
            parts.append(f"최하위 {d.iloc[-1][col]} {num(d.iloc[-1].value, unit)}")
        if len(d) == 2:
            parts.append(f"차이({d.iloc[1][col]}→{d.iloc[0][col]}) {num(d.iloc[0].value - d.iloc[1].value, '%p' if '%' in unit else unit)}")
        note = f" (합계·묶음 구간 제외: {', '.join(sorted(excl))})" if excl else ""
        out.append(f"{head}{len(d)}개 범주 중 " + ", ".join(parts) + note)
    return out


def computed_facts(rows):
    df = rows.df
    if df is None or df.empty:
        return []
    unit = str(df["unit"].dropna().iloc[0]) if df["unit"].notna().any() else ""
    periods = df["period_date"].nunique()
    var = [c for c in varying(df)]
    if periods >= 2:
        return change_facts(df, var, unit)
    return prev_facts(rows.series, var, unit) + (rank_facts(df, var, unit) if var else [])


def context_block_v2(rec, max_rows, cond=None):
    text = BASE_CONTEXT_BLOCK(rec, max_rows, cond)
    if not cond or not isinstance(cond[2], Rows) or not cond[0]:
        return text
    lines = text.split("\n")
    coord = ", ".join(f"{k}={'·'.join(map(str, v)) if isinstance(v, list) else v}" for k, v in cond[0].items())
    lines.insert(2, f"적용 좌표: [{rec.get('tbl_nm', '')}] {coord}")
    facts = computed_facts(cond[2])
    if facts:
        at = next((i for i, l in enumerate(lines) if l.startswith("조건 적용 데이터")), len(lines))
        lines.insert(at, FACTS_PREFIX + " / ".join(facts))
    return "\n".join(lines)


def install():
    qa.condition_rows = condition_rows_v2
    qa.context_block = context_block_v2
