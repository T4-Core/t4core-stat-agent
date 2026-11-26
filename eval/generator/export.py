"""평가 결과 정리본 내보내기: 질문 · 답변 · 만들어진 차트 이미지 · 판정을 md 와 PDF 로 정리한다 (HCX 없음)

  python -m eval.generator.export --runs <runs.jsonl.gz> [...] --v2 <데이터셋> [...] --out <폴더> [--png] [--md] [--html] [--pdf] [--limit N]

  --runs 와 --v2 는 같은 순서로 짝을 짓는다 (데이터셋마다 실행 기록 하나). 판정은 runs 옆 runs_report/verdicts.jsonl 을 읽는다
  (먼저 `report --v2` 를 돌려 둔다). 같은 문항이 여러 회차면 1회차만 쓴다.
  차트 그림은 실행 기록의 modules.drawn[].figure(모듈 5 출력, Plotly JSON)를 다시 그린 것이다. 앱 화면과 글꼴이 다를 수 있다.
  PDF 는 HTML 을 Chrome 헤드리스로 인쇄한다 (새 의존성 없음). A4 에 문항마다 위에 질문 · 답변, 아래에 차트 이미지(전부, 한 줄에 2개씩 줄바꿈)를 배치한다. 차트 크기는 82mm 폭 고정이다.
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from eval.generator import trace

CHROME = ("C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
          "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
FONT = "Malgun Gothic, NanumGothic, sans-serif"
FULL, SMALL = (760, 460), 520                       # md 용 원본 크기 · PDF 용 썸네일 폭(px)
VERDICT_CLASS = {"통과": "ok", "보류": "hold", "미달": "fail"}


@dataclass
class Chart:
    chart_id: str
    chart_type: str | None
    status: str
    title: str | None = None
    reason: str | None = None
    merged_from: list = field(default_factory=list)
    figure: dict | None = None
    png: str | None = None          # <out> 기준 상대 경로
    small: str | None = None
    source: str = "generator"       # "golden"(데이터셋 charts/<ID>.json 정답 차트) | "generator"(모듈 5가 그린 답변 차트)
    caption: str = ""


@dataclass
class Item:
    dataset: str
    version: str
    id: str
    group: str
    verdict: str
    first_failure: list
    tags: list
    question: str
    answer: str
    caveats: list
    charts: list


# ── 입력 ─────────────────────────────────────────────────────────
def chart_order(c: Chart):
    return (0 if c.source == "golden" else (2 if c.merged_from else 1), c.chart_id)


def _caption(c: Chart, sub_ids: dict) -> str:
    if c.merged_from:
        return f"답변 차트 · {c.chart_id} (두 차트 겹침)"
    subs = sub_ids.get(c.chart_id) or []
    n = ", ".join(str(x).rsplit("-", 1)[-1] for x in subs)
    return f"답변 차트 · {c.chart_id}" + (f" · 하위 질문 {n}" if n else "")


def golden_figure(spec: dict) -> dict | None:
    """데이터셋의 정답 차트 정의(points · chart_type)를 Plotly figure(JSON)로 그린다. 그릴 수 없는 유형이면 None"""
    import plotly.graph_objects as go
    pts = spec.get("points") or []
    kind = spec.get("chart_type")
    if not pts or kind not in ("line", "bar", "donut", "pie"):
        return None
    xs = [str(p["label"]) for p in pts]
    ys = [float(p["value"]) for p in pts]
    txt = [f"{y:,.0f}" if y == int(y) else f"{y:,.2f}" for y in ys]
    unit = spec.get("unit") or ""
    if kind == "line":
        tr = go.Scatter(x=xs, y=ys, mode="lines+markers+text", text=txt, textposition="top center", line=dict(color="#1565c0"))
    elif kind == "bar":
        tr = go.Bar(x=xs, y=ys, text=txt, textposition="outside", marker=dict(color="#1565c0"))
    else:
        tr = go.Pie(labels=xs, values=ys, hole=0.5 if kind == "donut" else 0, text=txt, textinfo="label+percent")
    fig = go.Figure(tr)
    fig.update_layout(title=f"골든 차트: {spec.get('y_axis') or ''}" + (f" ({unit})" if unit else ""), margin=dict(t=60, b=50, l=60, r=30),
                      xaxis_title=spec.get("x_axis"), yaxis_title=unit or None, showlegend=False)
    return json.loads(fig.to_json())


def golden_chart(root: Path, case_id: str) -> Chart:
    f = root / "charts" / f"{case_id}.json"
    if not f.exists():
        return Chart("golden", None, "none", reason="골든 차트 파일 없음", source="golden", caption="골든 차트")
    spec = json.loads(f.read_text(encoding="utf-8"))
    fig = golden_figure(spec) if spec.get("should_render") else None
    if fig:
        return Chart("golden", spec.get("chart_type"), "drawn", title=fig["layout"]["title"]["text"], figure=fig, source="golden",
                     caption=f"골든 차트 (정답 기준 · {spec.get('chart_type')})")
    why = spec.get("reason") or ("그리지 않는 것이 정답" if not spec.get("should_render") else "표현할 수 없는 유형")
    if spec.get("allowed_partial") and spec.get("partial_rules"):
        why += f" / 부분 차트 허용: {spec['partial_rules']}"
    return Chart("golden", spec.get("chart_type"), "none", reason=why, source="golden", caption="골든 차트 없음")


def charts_of(run: dict) -> list[Chart]:
    """modules.drawn 전부 + 그리지 못한 차트(render_status). 합친 차트(c1+c2)는 맨 뒤"""
    mods = trace.mods(run)
    sub_ids = {str(c.get("chart_id")): c.get("sub_question_ids") for c in mods.get("charts") or []}
    out = [Chart(str(d.get("chart_id")), d.get("chart_type"), d.get("status") or "?", d.get("title"), d.get("reason"),
                 list(d.get("merged_from") or []), d.get("figure")) for d in mods.get("drawn") or []]
    seen = {c.chart_id for c in out}
    for cid, st in (mods.get("render_status") or {}).items():
        if cid not in seen and st.get("state") != "drawn":
            out.append(Chart(str(cid), None, st.get("state") or "?", reason=st.get("reason") or st.get("error")))
    for c in out:
        c.caption = _caption(c, sub_ids)
    return sorted(out, key=chart_order)


def _caveat_texts(run: dict) -> list[str]:
    res = run.get("result") or {}
    return [(c.get("text") if isinstance(c, dict) else str(c)) for c in res.get("caveats") or [] if c]


def load_items(runs_path: Path, dataset_root: Path, limit: int | None = None) -> list[Item]:
    meta = json.loads((dataset_root / "cases.json").read_text(encoding="utf-8"))
    name, version = str(meta.get("name")), str(meta.get("version"))
    vpath = Path(runs_path).parent / "runs_report" / "verdicts.jsonl"
    verdicts = {}
    if vpath.exists():
        for x in trace.iter_jsonl(vpath):
            verdicts.setdefault(x["id"], x)
    items, seen = [], set()
    for r in trace.load(runs_path):
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        v = verdicts.get(r["id"]) or {}
        items.append(Item(
            dataset=name, version=version, id=r["id"], group=v.get("group") or "", verdict=v.get("verdict") or "판정 없음",
            first_failure=v.get("first_failure") or [], tags=[t for t in v.get("tags") or [] if t != "no_viewset"],
            question=r.get("question") or "", answer=((r.get("result") or {}).get("answer") or r.get("error") or ""),
            caveats=_caveat_texts(r), charts=sorted([golden_chart(dataset_root, r["id"])] + charts_of(r), key=chart_order)))
    items.sort(key=lambda i: i.id)
    return items[:limit] if limit else items


# ── 차트 이미지 ──────────────────────────────────────────────────
def _safe(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_.-]", "_", s)


def _render_batch(jobs: list[tuple[str, str, str]]) -> list[str]:
    """(원본 경로, 썸네일 경로, figure JSON) 목록 → 실패한 원본 경로. 브라우저를 한 번만 띄워 일괄 렌더한다"""
    import plotly.io as pio
    from PIL import Image
    failed = []
    figs = []
    for full, _, fj in jobs:
        f = pio.from_json(fj)
        f.update_layout(font=dict(family=FONT))
        figs.append(f)
    try:
        pio.write_images(fig=figs, file=[j[0] for j in jobs], width=FULL[0], height=FULL[1], scale=1)
    except Exception:  # noqa: BLE001  (일괄이 실패하면 한 장씩 다시 시도해 실패한 것만 가려낸다)
        for f, (full, _, _) in zip(figs, jobs):
            try:
                f.write_image(full, width=FULL[0], height=FULL[1], scale=1)
            except Exception:  # noqa: BLE001
                failed.append(full)
    for full, small, _ in jobs:
        if full in failed:
            continue
        im = Image.open(full).convert("RGB")
        im = im.resize((SMALL, round(im.height * SMALL / im.width)), Image.LANCZOS).quantize(colors=64)
        im.save(small, optimize=True)
    return failed


def render_pngs(items: list[Item], out: Path, workers: int = 4, force: bool = False, batch: int = 40) -> dict:
    """차트 PNG(원본 · 썸네일)를 만들고 Chart.png / Chart.small 을 채운다. 이미 있으면 건너뛴다"""
    jobs = []
    for it in items:
        d = out / "assets" / _safe(it.dataset)
        for c in it.charts:
            if c.status != "drawn" or not c.figure:
                continue
            base = f"{it.id}_{_safe(c.chart_id)}"
            full, small = d / f"{base}.png", d / f"{base}_s.png"
            c.png, c.small = full.relative_to(out).as_posix(), small.relative_to(out).as_posix()
            if force or not (full.exists() and small.exists()):
                d.mkdir(parents=True, exist_ok=True)
                jobs.append((str(full), str(small), json.dumps(c.figure)))
    failed: list[str] = []
    chunks = [jobs[i:i + batch] for i in range(0, len(jobs), batch)]
    if chunks:
        with ProcessPoolExecutor(max_workers=max(1, min(workers, len(chunks)))) as ex:
            for f in ex.map(_render_batch, chunks):
                failed += f
    bad = {Path(p).relative_to(out).as_posix() for p in failed}
    for it in items:
        for c in it.charts:
            if c.png in bad:
                c.png = c.small = None
                c.status, c.reason = "render_failed", "PNG 렌더 실패"
    return {"charts": sum(1 for it in items for c in it.charts if c.figure), "rendered": len(jobs), "failed": len(failed)}


# ── md ───────────────────────────────────────────────────────────
def _answer_md(a: str) -> str:
    return "\n".join("> " + ln if ln.strip() else ">" for ln in a.strip().splitlines()) or "> (답변 없음)"


def _summary(items: list[Item]) -> str:
    n = len(items)
    from collections import Counter
    cnt = Counter(i.verdict for i in items)
    nch = sum(1 for i in items for c in i.charts if c.status == "drawn" and c.source == "generator")
    ngold = sum(1 for i in items for c in i.charts if c.status == "drawn" and c.source == "golden")
    return f"문항 {n} · " + " · ".join(f"{k} {cnt[k]}" for k in ("통과", "보류", "미달", "판정 없음") if cnt[k]) + f" · 답변 차트 {nch} · 골든 차트 {ngold}"


def build_md(sections: list[tuple[str, str, list[Item]]], title: str) -> str:
    L = [f"# {title}", "", "질문 · 답변 · 차트와 자동 판정을 문항 ID 순으로 정리했다. 차트는 두 종류다: **골든 차트**(데이터셋 `charts/<ID>.json`의 정답 차트)와 **답변 차트**(Generator 모듈 5가 그린 것, 전부). 이미지는 모두 저장된 정의를 다시 그린 것이라 앱 화면과 글꼴이 다를 수 있다.", ""]
    for name, ver, items in sections:
        L += [f"- **{name}** v{ver}: {_summary(items)}"]
    for name, ver, items in sections:
        L += ["", f"## {name} v{ver}", ""]
        for it in items:
            tags = " · ".join(it.tags)
            L += [f"### {it.id} · {it.group} · {it.verdict}", "",
                  f"- 판정: **{it.verdict}** · First Failure: {' '.join(it.first_failure) or '-'}" + (f" · 태그: {tags}" if tags else ""), "",
                  f"**질문** {it.question}", "", "**답변**", "", _answer_md(it.answer), ""]
            if it.caveats:
                L += ["**주의사항** " + " / ".join(it.caveats), ""]
            for c in it.charts:
                if c.png:
                    L += [f"**{c.caption}**", "", f"![{c.caption}]({c.png})", ""]
                else:
                    L += [f"- {c.caption or '차트 ' + c.chart_id}: 없음 ({c.status}{', ' + c.reason if c.reason else ''})", ""]
    return "\n".join(L) + "\n"


# ── HTML · PDF ───────────────────────────────────────────────────
CSS = """
@page { size: A4; margin: 10mm; }
* { box-sizing: border-box; }
body { font-family: 'Malgun Gothic','NanumGothic',sans-serif; font-size: 8.5pt; line-height: 1.3; margin: 0; color: #111; }
h1 { font-size: 11pt; margin: 0 0 1mm; } h2 { font-size: 9pt; margin: 2mm 0 1mm; border-bottom: 0.6pt solid #444; }
.note { font-size: 6.5pt; color: #555; margin-bottom: 1.5mm; }
.case { border-bottom: 0.3pt solid #bbb; padding: 1.5mm 0 2mm; break-inside: avoid; }
.txt { min-width: 0; }
.head { font-weight: 700; font-size: 8.5pt; }
.badge { padding: 0 1.2mm; border-radius: 1mm; color: #fff; font-weight: 700; font-size: 7pt; }
.ok { background: #2e7d32; } .hold { background: #ef8f00; } .fail { background: #c62828; } .none { background: #777; }
.meta { color: #555; font-weight: 400; font-size: 6.5pt; }
.q { font-size: 9pt; font-weight: 600; margin: 0.5mm 0; }
.a { white-space: pre-wrap; margin: 0; }
.cv { color: #6a3d00; margin-top: 0.4mm; }
.charts { display: flex; flex-wrap: wrap; gap: 2mm; margin-top: 1.2mm; }
.charts .c { flex: 0 0 82mm; width: 82mm; }
.charts img { width: 82mm; height: auto; display: block; }
.charts .c.nochart { flex: 0 0 100%; width: auto; font-size: 6.5pt; color: #777; }
.cap { display: inline-block; font-size: 7pt; font-weight: 700; padding: 0 1.2mm; margin-bottom: 0.6mm; border-radius: 0.8mm; color: #fff; }
.cap.gold { background: #1565c0; } .cap.gen { background: #555; }
"""


def _e(s) -> str:
    return html.escape(str(s))


def _compact(a: str) -> str:
    return re.sub(r"\n\s*\n+", "\n", a.strip()) or "(답변 없음)"


def build_html(sections: list[tuple[str, str, list[Item]]], title: str) -> str:
    P = [f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{_e(title)}</title><style>{CSS}</style></head><body>",
         f"<h1>{_e(title)}</h1><div class='note'>질문 · 답변 · 차트와 자동 판정. 파란 라벨 [골든 차트]는 데이터셋의 정답 차트, 회색 라벨 [답변 차트]는 Generator(모듈 5)가 그린 차트이다. 이미지는 모두 저장된 정의를 다시 그린 것이며 답변의 연속 빈 줄은 줄여 표시했다.</div>"]
    for name, ver, items in sections:
        P.append(f"<h2>{_e(name)} v{_e(ver)} — {_e(_summary(items))}</h2>")
        for it in items:
            cls = VERDICT_CLASS.get(it.verdict, "none")
            meta = f"{it.group} · FF {' '.join(it.first_failure) or '-'}" + (f" · {' · '.join(it.tags)}" if it.tags else "")
            imgs = []
            for c in it.charts:
                kind = "gold" if c.source == "golden" else "gen"
                if c.small:
                    imgs.append(f"<div class='c'><div class='cap {kind}'>{_e(c.caption)}</div><img src='{_e(c.small)}'></div>")
                else:
                    imgs.append(f"<div class='c nochart'><span class='cap {kind}'>{_e(c.caption or c.chart_id)}</span> 없음: {_e(c.reason or c.status)}</div>")
            cv = f"<div class='cv'>주의: {_e(' / '.join(it.caveats))}</div>" if it.caveats else ""
            P.append(f"<div class='case'><div class='txt'><div class='head'>{_e(it.id)} <span class='badge {cls}'>{_e(it.verdict)}</span> "
                     f"<span class='meta'>{_e(meta)}</span></div><div class='q'>{_e(it.question)}</div>"
                     f"<div class='a'>{_e(_compact(it.answer))}</div>{cv}</div><div class='charts'>{''.join(imgs)}</div></div>")
    P.append("</body></html>")
    return "\n".join(P)


def find_chrome(arg: str | None = None) -> str:
    for p in ([arg] if arg else []) + list(CHROME):
        if p and Path(p).exists():
            return p
    raise SystemExit("Chrome(또는 Edge)를 찾지 못했다: --chrome 으로 경로를 준다")


def print_pdf(html_path: Path, pdf_path: Path, chrome: str, timeout: int = 7200) -> float:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as prof:
        t = time.time()
        r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={prof}",
                            f"--print-to-pdf={pdf_path.resolve()}", html_path.resolve().as_uri()], capture_output=True, timeout=timeout)
        if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
            raise SystemExit(f"PDF 인쇄 실패(rc={r.returncode}): {(r.stderr or b'').decode('utf-8', 'replace')[-300:]}")
        return time.time() - t


def pdf_pages(pdf_path: Path) -> int | None:
    """쪽 수 (Skia PDF 는 쪽마다 /Type /Page 개체를 둔다). 세지 못하면 None"""
    n = len(re.findall(rb"/Type\s*/Page[^s]", pdf_path.read_bytes()))
    return n or None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", type=Path, required=True)
    ap.add_argument("--v2", nargs="+", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", default="Generator_결과정리본")
    ap.add_argument("--title", default="Generator 평가 결과 정리본")
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--pdf", action="store_true", help="HTML 을 만들고 Chrome 으로 인쇄 (--png 가 먼저 돼 있어야 이미지가 나온다)")
    ap.add_argument("--limit", type=int, help="데이터셋마다 앞 N문항만 (시험용)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--chrome")
    a = ap.parse_args(argv)
    if len(a.runs) != len(a.v2):
        ap.error("--runs 와 --v2 의 개수가 같아야 한다")
    from eval.generator import v2 as V2
    sections = []
    for rp, dp in zip(a.runs, a.v2):
        items = load_items(rp, V2.dataset_dir(dp), a.limit)
        sections.append((items[0].dataset if items else str(dp), items[0].version if items else "", items))
        print(f"[export] {rp}: {_summary(items)}", flush=True)
    a.out.mkdir(parents=True, exist_ok=True)
    allitems = [i for _, _, its in sections for i in its]
    if a.png or a.pdf:
        t = time.time()
        stat = render_pngs(allitems, a.out, a.workers, a.force)
        print(f"[export] 차트 PNG {stat} ({time.time() - t:.0f}s)", flush=True)
    if a.md:
        (a.out / f"{a.name}.md").write_text(build_md(sections, a.title), encoding="utf-8")
        print("[export] md", a.out / f"{a.name}.md", flush=True)
    if a.html or a.pdf:
        hp = a.out / f"{a.name}.html"
        hp.write_text(build_html(sections, a.title), encoding="utf-8")
        print("[export] html", hp, flush=True)
    if a.pdf:
        pp = a.out / f"{a.name}.pdf"
        sec = print_pdf(hp, pp, find_chrome(a.chrome))
        pages = pdf_pages(pp)
        print(f"[export] pdf {pp} {pp.stat().st_size / 1048576:.1f}MB · {pages or '쪽수 미확인'}쪽 · "
              f"쪽당 {len(allitems) / pages:.1f}문항 · {sec:.0f}s" if pages else f"[export] pdf {pp} {pp.stat().st_size / 1048576:.1f}MB · 쪽수 미확인", flush=True)


if __name__ == "__main__":
    sys.exit(main())
