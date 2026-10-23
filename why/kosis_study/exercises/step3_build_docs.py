"""
STEP 3 (학습용) — 나만의 RAG 문서 만들기

RAG 는 '검색해서 가져온 글'을 LLM 에게 보여 주고 답하게 하는 방식입니다.
그래서 먼저 '검색될 글(문서)'을 만들어야 합니다. 표 1개당 문서 2개를 만듭니다.

  meta 문서  : 메타데이터를 자연어로 풀어 쓴 설명  (이 표가 무엇을 담고 있나?)
  table 문서 : 최신 시점 숫자를 몇 줄로 적은 표   (실제 값은 얼마인가?)

문서 1개 = {"id", "doc_type", "tbl_id", "title", "text"}
결과: study_out/docs.jsonl  (한 줄에 문서 1개, JSON)

💡 설계는 자유입니다. 정답 코드와 똑같을 필요 없어요.
   "질문하는 사람이 쓸 법한 단어가 text 안에 들어 있는가?" 가 좋은 문서의 기준입니다.

※ STEP 1, 2 의 함수를 가져다 씁니다.
실행: python step3_build_docs.py        (표 개수 제한: MAX_TABLES=10 python step3_build_docs.py)
막히면: ../solutions/step3_build_docs.py
"""
import json
import os
from pathlib import Path

from step1_load_data import find_tables, load_catalog, load_meta, load_raw, meta_path, summarize_meta, with_raw
from step2_eda import add_value, fix_other_dims

OUT_DIR = Path("study_out")
DOCS_PATH = OUT_DIR / "docs.jsonl"
MAX_TABLES = int(os.getenv("MAX_TABLES", 30))


# ─────────────── 3-1. 메타 → 자연어 문서 ───────────────
def dims_text(summary, max_codes=10):
    """분류를 '- 행정구역별(18개): 전국, 서울특별시, ... 외 8개' 형태의 줄들로 (완성되어 있음)"""
    lines = []
    for obj_nm, codes in summary["dims"].items():
        names = ", ".join(str(c["name"]) for c in codes[:max_codes])
        more = f" 외 {len(codes) - max_codes}개" if len(codes) > max_codes else ""
        lines.append(f"- {obj_nm}({len(codes)}개): {names}{more}")
    return "\n".join(lines)


def make_meta_doc(row, summary):
    items = ", ".join(f"{it['name']}({it['unit']})" if it["unit"] else str(it["name"])
                      for it in summary["items"][:15])
    # TODO(3-1): 표 설명 text 를 여러 줄 문자열로 만드세요. 최소한 아래 정보를 넣어 보세요.
    #   표 이름(row["tbl_nm"]), 조사(row["category"]), 분류 경로(row["path"]),
    #   분류(dims_text(summary)), 항목(items), 수록기간(summary["period"]), 주석(summary["comment"] 앞 300자)
    # 예)
    #   [통계표 설명] 시도별 주택종류별 주택
    #   조사: 주택총조사
    #   분류:
    #   - 행정구역별(18개): 전국, 서울특별시, ...
    #   항목: 주택수(호)
    #   ...
    text = None
    raise NotImplementedError("TODO 3-1")
    return {"id": f"meta::{row['tbl_id']}", "doc_type": "meta", "tbl_id": row["tbl_id"],
            "title": row["tbl_nm"], "text": text}


# ─────────────── 3-2. 숫자 → 표 문서 ───────────────
def make_table_doc(row, raw, max_rows=20):
    base = fix_other_dims(add_value(raw))
    # TODO(3-2a): 최신 시점(latest)을 구하고, 그 시점의 행만 max_rows 개까지 snap 에 담으세요.
    latest = None
    snap = None
    raise NotImplementedError("TODO 3-2a")
    item = snap["ITM_NM"].iloc[0]
    unit = str(snap["UNIT_NM"].iloc[0]) if "UNIT_NM" in snap.columns else ""

    fixed = []                                           # 고정한 다른 분류도 적어 두기 (예: 주택종류별: 계)
    for i in range(2, 9):
        if f"C{i}_NM" in snap.columns:
            obj = snap[f"C{i}_OBJ_NM"].iloc[0] if f"C{i}_OBJ_NM" in snap.columns else f"분류{i}"
            fixed.append(f"{obj}: {snap[f'C{i}_NM'].iloc[0]}")

    # TODO(3-2b): snap 의 각 행을 "- 서울특별시: 3,000,000 호" 형태의 줄로 만드세요. (값이 NaN 이면 '자료없음')
    # 힌트: for r in snap.itertuples():  r.C1_NM, r.VALUE
    #       NaN 확인: pd.isna(r.VALUE)  또는  r.VALUE != r.VALUE
    lines = []
    raise NotImplementedError("TODO 3-2b")
    text = (f"[통계표 데이터] {row['tbl_nm']}\n"
            f"항목: {item} / 단위: {unit} / 시점: {latest}"
            + (f" / 조건: {', '.join(fixed)}" if fixed else "") + "\n"
            + "\n".join(lines))
    return {"id": f"table::{row['tbl_id']}", "doc_type": "table", "tbl_id": row["tbl_id"],
            "title": f"{row['tbl_nm']} ({latest})", "text": text}


# ─────────────── 3-3. 전체 표 → docs.jsonl ───────────────
def build_docs():
    tables = with_raw(find_tables(load_catalog())).head(MAX_TABLES)
    docs = []
    for row in tables.to_dict("records"):
        try:
            # TODO(3-3a): meta 파일이 있으면 meta 문서를, 그리고 table 문서를 docs 에 추가하세요.
            # 힌트: meta_path(row).exists(), make_meta_doc(row, summarize_meta(load_meta(row))),
            #       make_table_doc(row, load_raw(row))
            raise NotImplementedError("TODO 3-3a")
        except NotImplementedError:
            raise
        except Exception as e:                            # 표 하나가 이상해도 전체는 계속
            print(f"  ✗ {row['tbl_nm']}: {e}")
    return docs


def save_docs(docs, path=DOCS_PATH):
    path.parent.mkdir(exist_ok=True)
    # TODO(3-3b): docs 를 JSONL 로 저장하세요. (한 줄 = 문서 1개)
    # 힌트: with path.open("w", encoding="utf-8") as f:
    #           f.write(json.dumps(d, ensure_ascii=False) + "\n")     ← ensure_ascii=False: 한글 그대로
    raise NotImplementedError("TODO 3-3b")


def main():
    docs = build_docs()
    save_docs(docs)
    n_meta = sum(d["doc_type"] == "meta" for d in docs)
    print(f"문서 {len(docs)}개 (meta {n_meta}, table {len(docs) - n_meta}) → {DOCS_PATH}")
    for d in docs[:2]:
        print("\n" + "-" * 60 + f"\n{d['id']}\n{d['text'][:500]}")
    # 🤔 (선택 과제) 질문에 자주 나올 단어(예: '집', '아파트 몇 채')를 text 에 추가하면
    #    STEP 4 검색 결과가 어떻게 달라지는지 비교해 보세요.


if __name__ == "__main__":
    main()
