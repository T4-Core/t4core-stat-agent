"""
차트 데이터 가공

  chart_spec / render        : 구 kosis_views.py (backend/rag/ingestion/view_builder.py) — 다시 내보냄
  chart_from_record  [NEW]   : View 모듈 Record(table{columns, rows} + metadata.view_type) → 프론트엔드 차트 형식
                               Record 에는 차트 스펙이 없어서(kosis_views 레코드에는 rec["chart"] 가 있음) 여기서 만든다
"""
from backend.rag.ingestion.view_builder import chart_spec, render  # noqa: F401  (다시 내보냄)

FIXED = {"시점", "항목", "값"}


def chart_from_record(rec, title=None, max_rows=500):
    """Record(dict) → {record_id, type, title, x, y, series, unit, columns, rows}"""
    t = rec.get("table") or {}
    cols, rows = list(t.get("columns") or []), list(t.get("rows") or [])[:max_rows]
    md = rec.get("metadata") or {}
    dims = [c for c in cols if c not in FIXED]
    varying = [c for c in dims if len({r[cols.index(c)] for r in rows}) > 1]
    n_periods = len({r[cols.index("시점")] for r in rows}) if "시점" in cols else 0
    n_items = len({r[cols.index("항목")] for r in rows}) if "항목" in cols else 0
    if md.get("view_type") == "trend" or n_periods > 2:
        typ, x = "line", "시점"
        series = varying[0] if varying else ("항목" if n_items > 1 else None)
    elif varying:
        typ, x = "bar", varying[0]
        series = varying[1] if len(varying) > 1 else ("항목" if n_items > 1 else None)
    elif n_items > 1:
        typ, x, series = "bar", "항목", None
    else:
        typ, x, series = "table", None, None
    return {"record_id": rec.get("id"), "type": typ,
            "title": title or (rec.get("lexical_text") or "")[:60], "x": x, "y": "값", "series": series,
            "unit": md.get("unit") or None, "columns": cols, "rows": rows}
