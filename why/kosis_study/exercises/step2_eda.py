"""
STEP 2 (학습용) — 간단한 EDA(탐색적 데이터 분석)

STEP 1 에서 고른 주택 표 하나로
  ① 값(DT)을 숫자로 바꾸고 결측을 확인하고
  ② 시점별 추이(전체)와 최신 시점의 지역(분류)별 비교를 뽑고
  ③ 숫자에서 읽을 수 있는 사실 몇 줄을 문장으로 정리하고
  ④ 그래프 2개를 그려 저장합니다.

KOSIS 표는 분류가 여러 개(예: 행정구역 × 주택종류)일 수 있습니다.
이번 단계에서는 단순하게 '첫 번째 항목' + 'C2 이후 분류는 첫 코드(보통 합계)로 고정'해서
C1(첫 번째 분류)만 비교합니다.

※ STEP 1 의 함수를 가져다 씁니다. STEP 1 을 먼저 완성하세요.
실행: python step2_eda.py      → study_out/eda_*.png
막히면: ../solutions/step2_eda.py
"""
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                     # 창을 띄우지 않고 파일로만 저장
import matplotlib.pyplot as plt
import pandas as pd

from step1_load_data import find_tables, load_catalog, load_raw, with_raw


OUT_DIR = Path("study_out")
TOTAL_NAMES = {"계", "합계", "총계", "소계", "전체", "전국"}


def set_korean_font():
    """그래프에 한글이 □□로 깨지지 않게 (완성되어 있음)"""
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"):
        if name in have:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


# ─────────────── 2-1. 값 숫자화 + 기본 정보 ───────────────
def add_value(raw):
    df = raw.copy()
    # TODO(2-1): DT 컬럼(문자열 "1,234" / "-" / "X")을 숫자로 바꿔 VALUE 컬럼을 만드세요.
    # 힌트: 쉼표 제거 → df["DT"].astype(str).str.replace(",", "")
    #       pd.to_numeric(..., errors="coerce")  → 숫자가 아니면 NaN 이 됩니다
    raise NotImplementedError("TODO 2-1")
    return df


def basic_info(df):
    print(f"행 {len(df):,}개, 컬럼 {df.shape[1]}개")
    print(f"값 결측(숫자가 아닌 값): {df['VALUE'].isna().sum():,}개 ({df['VALUE'].isna().mean():.1%})")
    for c in ("PRD_DE", "C1_NM", "ITM_NM"):
        if c in df.columns:
            print(f"{c:7s} 고유값 {df[c].nunique():4d}개  예: {df[c].dropna().unique()[:5].tolist()}")
    print(df["VALUE"].describe().round(1).to_string())


# ─────────────── 2-2. 비교하기 쉬운 모양으로 자르기 ───────────────
def fix_other_dims(df):
    """첫 번째 항목만 + C2~C8 분류는 첫 코드로 고정 → C1 × 시점 만 남음"""
    d = df[df["ITM_ID"] == df["ITM_ID"].iloc[0]]
    # TODO(2-2a): C2 ~ C8 컬럼이 있으면, 각 컬럼을 그 컬럼의 첫 번째 값으로만 남기세요.
    # 힌트: for i in range(2, 9):  c = f"C{i}"
    #       if c in d.columns:  d = d[d[c] == d[c].iloc[0]]
    raise NotImplementedError("TODO 2-2a")
    return d


def trend(base):
    """C1 의 첫 코드(보통 전국/합계)의 시점별 값 → Series (index=PRD_DE)"""
    # TODO(2-2b): C1 이 첫 번째 코드인 행만 고르고, PRD_DE 별 VALUE 합계를 시점 순으로 반환
    # 힌트: base[base["C1"] == base["C1"].iloc[0]].groupby("PRD_DE")["VALUE"].sum().sort_index()
    raise NotImplementedError("TODO 2-2b")


def snapshot(base):
    """최신 시점의 C1 분류별 값 (합계 행 제외, 큰 순) → Series (index=C1_NM)"""
    # TODO(2-2c):
    #   1) PRD_DE 가 가장 큰(최신) 행만 고르기       → base["PRD_DE"].max()
    #   2) C1_NM 을 index 로, VALUE 만 남기고 결측 제거 → .set_index("C1_NM")["VALUE"].dropna()
    #   3) TOTAL_NAMES(전국·계 …)에 해당하는 행 빼기   → s[~s.index.isin(TOTAL_NAMES)]
    #   4) 큰 순서로 정렬                             → .sort_values(ascending=False)
    raise NotImplementedError("TODO 2-2c")


# ─────────────── 2-3. 숫자로 사실 정리 ───────────────
def findings(tr, snap, unit):
    out = []
    if len(tr) >= 2:
        first, last = tr.iloc[0], tr.iloc[-1]
        # TODO(2-3): 처음 대비 마지막 변화율(%)을 계산하세요.  (first 가 0 이면 0)
        pct = None
        raise NotImplementedError("TODO 2-3")
        out.append(f"{tr.index[0]} {first:,.0f}{unit} → {tr.index[-1]} {last:,.0f}{unit} ({pct:+.1f}%)")
        out.append(f"가장 컸던 시점: {tr.idxmax()} ({tr.max():,.0f}{unit})")
    if len(snap) >= 1:
        top = ", ".join(f"{k} {v:,.0f}" for k, v in snap.head(3).items())
        out.append(f"최신 시점 상위 3개: {top}")
        out.append(f"최신 시점 최하위: {snap.index[-1]} {snap.iloc[-1]:,.0f}{unit}")
    return out


# ─────────────── 2-4. 그래프 ───────────────
def plot(tr, snap, title):
    set_korean_font()
    OUT_DIR.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    # TODO(2-4a): tr 을 선 그래프로 그리세요. (점 표시 marker="o", 제목 포함)
    # 힌트: tr.plot(ax=ax, marker="o", title=...)
    raise NotImplementedError("TODO 2-4a")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "eda_trend.png")

    fig, ax = plt.subplots(figsize=(8, 5))
    # TODO(2-4b): snap 상위 15개를 가로 막대 그래프로 그리세요.
    # 힌트: snap.head(15).plot.barh(ax=ax, title=...)   그 다음 ax.invert_yaxis() 로 1위를 위로
    raise NotImplementedError("TODO 2-4b")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "eda_snapshot.png")
    plt.close("all")


def main():
    tables = with_raw(find_tables(load_catalog()))
    row = tables.iloc[int(os.getenv("TABLE_INDEX", 0))]
    df = add_value(load_raw(row))
    print(f"=== {row['tbl_nm']} ===")
    basic_info(df)

    base = fix_other_dims(df)
    unit = str(base["UNIT_NM"].iloc[0]) if "UNIT_NM" in base.columns else ""
    item = base["ITM_NM"].iloc[0]
    tr, snap = trend(base), snapshot(base)

    print(f"\n[분석 대상] 항목: {item} / 단위: {unit}")
    print("[발견한 점]")
    for line in findings(tr, snap, unit):
        print(" -", line)
    plot(tr, snap, f"{item}")
    print(f"\n그래프 저장 → {OUT_DIR / 'eda_trend.png'}, {OUT_DIR / 'eda_snapshot.png'}")
    # 🤔 생각해 보기: 결측(NaN)은 어떤 시점·지역에 몰려 있나요? 0 으로 채워도 될까요?
    # 🤔 (선택) 2-2a 에서 C2 를 '계' 대신 '아파트' 로 고정하면 결과가 어떻게 달라질까요?


if __name__ == "__main__":
    main()
