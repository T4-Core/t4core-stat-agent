"""
모듈 5 저장 (fan-in) — 그린 결과를 모아 json → PNG 일괄 → 질문 HTML 한 장

  - drawn 차트만 {chart_id}.json · {chart_id}.png 로 저장한다
  - PNG는 plotly.io.write_images로 한 번에 저장한다 (kaleido가 Chrome을 한 번만 띄운다). 실패하면 files.png에 이유만 남긴다
  - 질문 하나 = {query_id}.html 한 장. 그리지 못한 차트(skipped · failed · not_implemented) 자리에는 안내 박스
"""
import html as html_lib
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.io as pio

from .draw_chart_schema import BASE_DIR, DRAWN

PNG_SIZE = {"width": 900, "height": 520}
PLOTLYJS = "cdn"      # HTML에 plotly.js를 넣는 방식. "cdn" = 인터넷에서 받음(가벼움) / True = 파일 안에 넣음(약 4.8MB, 오프라인 가능)

PAGE_CSS = """
body{font-family:'Malgun Gothic',sans-serif;margin:24px auto;max-width:960px;padding:0 16px;color:#222;background:#fff}
h1{font-size:20px;margin:0 0 4px} .meta{color:#666;font-size:13px;margin-bottom:20px}
.chart{margin:0 0 28px} .warn{color:#8a6d3b;font-size:12px;margin:4px 0 0 8px}
.notice{border:1px dashed #bbb;border-radius:8px;background:#fafafa;padding:14px 16px;margin:0 0 28px;font-size:14px}
.notice b{margin-right:6px} .badge{display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;background:#eee;margin-left:6px}
.notice .why{color:#666;font-size:13px;margin-top:6px}
"""
# 노트북 출력용: body 규칙 없이 안내 박스에만 적용 (VS Code는 모든 셀 출력을 한 화면에 그려서 body 스타일이 전체 배경을 바꾼다)
NOTICE_CSS = """
.notice{border:1px dashed #bbb;border-radius:8px;padding:14px 16px;margin:8px 0;font-size:14px;font-family:'Malgun Gothic',sans-serif}
.notice b{margin-right:6px} .notice .badge{display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;border:1px solid #bbb;margin-left:6px}
.notice .why{opacity:.75;font-size:13px;margin-top:6px} .notice .warn{color:#b8860b;font-size:12px;margin-top:4px}
"""


def rel(p: Path) -> str:
    """저장 경로를 BASE_DIR(backend/agent/draw_chart) 기준 상대 경로로 (밖이면 절대 경로)"""
    return str(p.relative_to(BASE_DIR)) if p.is_relative_to(BASE_DIR) else str(p)


def save_json(results, out_dir: Path):
    """drawn 차트의 figure JSON → {chart_id}.json"""
    for r in results:
        if r.status == DRAWN:
            p = out_dir / f"{r.chart_id}.json"
            p.write_text(r.figure.to_json(), encoding="utf-8")
            r.files["json"] = rel(p)


def save_png_batch(results, out_dir: Path):
    """drawn 차트의 PNG를 한 번에 저장. 실패하면 files.png에 이유만 남기고 status는 그대로 둔다 (그리기와 별개)"""
    drawn = [r for r in results if r.status == DRAWN]
    if not drawn:
        return
    paths = [out_dir / f"{r.chart_id}.png" for r in drawn]
    try:
        pio.write_images([r.figure for r in drawn], paths, **PNG_SIZE)
        for r, p in zip(drawn, paths):
            r.files["png"] = rel(p)
    except Exception as e:   # noqa: BLE001
        for r in drawn:
            r.files["png"] = f"저장 실패: {type(e).__name__}: {e}"


def notice_box(r) -> str:
    """그리지 못한 차트 자리의 안내 박스"""
    e = html_lib.escape
    name = f"{r.chart_id}" + (f" · {e(r.title)}" if r.title else "")
    kind = r.chart_type or r.planned_type or "-"
    return (f'<div class="notice"><b>{name}</b><span class="badge">{r.status}</span>'
            f'<span class="badge">{e(kind)}</span><div class="why">{e(r.reason or "")}</div>'
            + "".join(f'<div class="warn">⚠ {e(w)}</div>' for w in r.warnings) + '</div>')


def save_html(results, out_dir: Path, query_id: str) -> Path:
    """질문 하나 = HTML 한 장. ChartPlan 순서대로 차트 또는 안내 박스를 놓는다 (plotly.js는 한 번만 넣는다)"""
    counts = Counter(r.status for r in results)
    parts, js_done = [], False
    for r in results:
        if r.status == DRAWN:
            div = r.figure.to_html(full_html=False, include_plotlyjs=PLOTLYJS if not js_done else False,
                                   config={"displaylogo": False})
            js_done = True
            warns = "".join(f'<div class="warn">⚠ {html_lib.escape(w)}</div>' for w in r.warnings)
            parts.append(f'<div class="chart">{div}{warns}</div>')
        else:
            parts.append(notice_box(r))
    summary = " · ".join(f"{k} {v}" for k, v in counts.items())
    page = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>차트 {html_lib.escape(query_id)}</title>'
            f'<style>{PAGE_CSS}</style></head><body><h1>질문 {html_lib.escape(query_id)}</h1>'
            f'<div class="meta">차트 {len(results)}개 · {summary}</div>{"".join(parts)}</body></html>')
    p = out_dir / f"{query_id}.html"
    p.write_text(page, encoding="utf-8")
    for r in results:
        r.files["html"] = rel(p)
    return p


def fan_in(results, out_dir: Path, query_id: str) -> Path:
    """결과 모으기 → json 저장 → PNG 일괄 저장 → 질문 HTML 1장. HTML 경로를 돌려준다"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_json(results, out_dir)
    save_png_batch(results, out_dir)
    return save_html(results, out_dir, query_id)


def results_table(results) -> pd.DataFrame:
    """결과 요약 표"""
    return pd.DataFrame([{
        "chart_id": r.chart_id,
        "계획 → 최종": f"{r.planned_type or '-'} → {r.chart_type or '-'}",
        "status": r.status,
        "이유": r.reason or "",
        "json": r.files.get("json", ""),
        "png": r.files.get("png", ""),
        "warnings": " / ".join(r.warnings),
    } for r in results])
