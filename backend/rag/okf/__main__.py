"""
python -m backend.rag.okf <명령>

  tables    [--profiles DIR]                 프로필 → 표·분류 파일 (바뀐 것만 씀) + index.md · log.md
  lint      [--profiles DIR] [--all]         참조 무결성 검사 (오류면 종료 코드 1). --all 이면 info 까지
  build     [--profiles DIR] [--no-index] [--embed hcx] [--force] [--tables] [--gate <compare 실행>]
                                              검사 → 파생물 → CURRENT 교체 (--tables: 표 생성부터)
                                              --gate: 바꾸기 전에 그 실행의 질문으로 지금·새 빌드 검색을 비교 (gate.py)
  show      [tbl_id | 개념 경로] [--text 질문]  지금 빌드 정보 · 표 · 질문에 걸린 개념
  use       <해시>                            CURRENT 를 이전 빌드로 (되돌리기)
  migrate   aliases | learned [--by 이름]     별칭 옮기기 (vocab_aliases.csv · 학습 사전 승인분 → 개념 파일)
  pending                                      학습 사전 '승인 대기' (벡터+HCX 제안 등) 와 맞을 개념
  approve   <표현> [--value 정규이름] [--by 이름]   승인 → 개념 별칭 (verified)
  drafts    --runs <compare 폴더|per_query.csv> [더…] [--split dev|heldout|all] [--write [--hcx]] [--min-support N] [--gold-only]
                                              일상어(P)라서 못 찾은 문항 → 개념 초안 보고서 (--write: concepts/_inbox/draft-*.md
                                              + 표에서 정의를 채움 · --hcx: 정의 다듬기 · 별칭 판정 · 헷갈리는 말 제안)
  assist    [개념 경로 …] [--no-hcx] [--force]  _inbox 초안(경로 없으면 전부)에 정의 채우기 + HCX 제안
  verify    <개념 경로> [--to 영역/영어-이름] [--alias 표현 …] [--by 이름]
                                              사람이 확인 → status stable + 승인 (draft 별칭 포함) · --to: _inbox 에서 옮김
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="python -m backend.rag.okf")
    ap.add_argument("cmd", choices=["tables", "lint", "build", "show", "use", "migrate", "pending", "approve", "drafts",
                                    "verify", "assist"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--profiles", default=None, help="정규화 프로필 폴더 (기본 VIEW_OUT_DIR/profiles)")
    ap.add_argument("--bundle", default=None, help="번들 폴더 (기본 storage/okf)")
    ap.add_argument("--no-index", action="store_true", help="build: CSV 값 사전 없이 (프로필만으로 vocab)")
    ap.add_argument("--embed", default=None, help="build: 사전 벡터도 (hcx | bge-m3-ko | …)")
    ap.add_argument("--tables", action="store_true", help="build: 표 생성부터")
    ap.add_argument("--gate", default=None, metavar="실행",
                    help="build: 이 compare 실행(이름 일부·폴더)의 질문으로 지금·새 빌드를 비교해 나빠지면 바꾸지 않음")
    ap.add_argument("--gate-max-loss", type=int, default=0, help="build --gate: 허용하는 hit@5 순손실 질문 수 (기본 0)")
    ap.add_argument("--gate-mrr-drop", type=float, default=0.01, help="build --gate: 허용하는 mrr 하락 (기본 0.01)")
    ap.add_argument("--all", action="store_true", help="lint: info 까지 출력")
    ap.add_argument("--text", default="", help="show: 질문 (걸리는 개념)")
    ap.add_argument("--by", default=None, help="승인한 사람 (기본 OS 사용자 → human:<이름>)")
    ap.add_argument("--value", default=None, help="approve: 정규 이름을 직접 (제안과 다르게)")
    ap.add_argument("--runs", nargs="*", default=[], help="drafts: compare 결과 폴더 또는 per_query.csv (여러 개)")
    ap.add_argument("--split", default="dev", choices=["dev", "heldout", "all"], help="drafts: 초안을 만들 문항 (기본 dev)")
    ap.add_argument("--config", default=None, help="drafts: per_query 의 구성 이름 (기본 첫 구성)")
    ap.add_argument("--write", action="store_true", help="drafts: concepts/_inbox/ 에 초안 파일을 씀 (없으면 보고서만)")
    ap.add_argument("--min-support", type=int, default=1, help="drafts --write: 이 레코드 수 이상인 일상어만")
    ap.add_argument("--out", default=None, help="drafts: 보고서 폴더 (기본 storage/runs/okf_drafts/<시각>)")
    ap.add_argument("--gold-only", action="store_true", help="drafts: 묶을 표를 정답 표로만 (기본: 같은 이름이 있는 표 모두)")
    ap.add_argument("--alias", nargs="*", default=None, help="verify: 승인할 별칭 (없으면 미승인 전부)")
    ap.add_argument("--hcx", action="store_true", help="drafts --write: HCX 제안까지 (정의 · 별칭 판정 · 헷갈리는 말)")
    ap.add_argument("--no-hcx", action="store_true", help="assist: 표에서 정의만 채움 (HCX 안 부름)")
    ap.add_argument("--force", action="store_true", help="build: 검사 오류가 있어도 빌드 · assist: 판정한 것도 다시")
    ap.add_argument("--to", default=None, help="verify: 옮길 자리 concepts/<영역>/<영어-이름> (예: population/birth)")
    a = ap.parse_args(argv)

    from backend.core.config import VIEW_OUT_DIR
    from backend.core.settings import get_settings
    from backend.rag.okf import build as B
    from backend.rag.okf import tables as T
    s = get_settings()
    bundle = Path(a.bundle) if a.bundle else B.bundle_dir(s)
    prof = Path(a.profiles) if a.profiles else Path(VIEW_OUT_DIR) / "profiles"
    out = lambda o: print(json.dumps(o, ensure_ascii=False, indent=1, default=str))

    if a.cmd == "tables" or (a.cmd == "build" and a.tables):
        if not prof.exists():
            sys.exit(f"프로필 폴더 없음: {prof} (python -m backend.rag.ingestion … 로 정규화 먼저)")
        T.generate(bundle, prof)
        if a.cmd == "tables":
            return
    if a.cmd == "lint":
        from backend.rag.okf.lint import lint
        recs = T.load_profiles(prof) if prof.exists() else []
        rep = lint(bundle, B.codebooks_from(recs) or None)
        print("\n".join(rep.lines(("error", "warn", "info") if a.all else ("error", "warn"))) or "문제 없음")
        print(json.dumps(rep.summary(), ensure_ascii=False))
        sys.exit(0 if rep.ok else 1)
    if a.cmd == "build":
        idx = None
        if not a.no_index:
            from backend.rag.csv_index.store import load_index
            try:
                idx = load_index()
            except FileNotFoundError as e:
                print(f"CSV 값 사전 없음 → 프로필만: {e}")
        gate = None
        if a.gate:
            from backend.rag.okf import gate as G
            gate = lambda new, base: G.gate(B.build_root(s), new, base, a.gate, a.gate_max_loss, a.gate_mrr_drop)
        m = B.build(bundle, B.build_root(s), prof if prof.exists() else None, idx, force=a.force, embed=a.embed, settings=s,
                    gate=gate)
        if m.get("gate"):
            gf = B.build_root(s) / m.get("hash", "") / "gate.json"
            if gf.parent.exists():
                gf.write_text(json.dumps(m["gate"], ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"검사 결과 → {gf}")
        sys.exit(0 if m.get("ok") else 1)
    if a.cmd == "use":
        h = (a.args or [""])[0]
        root = B.build_root(s)
        if not (root / h / "manifest.json").exists():
            sys.exit(f"빌드 없음: {root / h}")
        B.set_current(root, h)
        print(f"CURRENT = {h}")
        return
    if a.cmd == "show":
        from backend.rag.okf.catalog import Catalog
        cat = Catalog.current(s)
        if cat is None:
            sys.exit("빌드 없음 → python -m backend.rag.okf build")
        if not a.args:
            out(cat.manifest)
            return
        for x in a.args:
            t = cat.table(x)
            out(t if t else cat.concept(x) or f"'{x}' 없음")
            if t and a.text:
                out({"concepts_for": cat.concepts_for([x], a.text)})
        return
    if a.cmd == "drafts":
        from collections import Counter
        from datetime import datetime

        from backend.core.config import RUNS_DIR
        from backend.rag.okf import drafts as D
        from backend.rag.okf.catalog import Catalog
        if not a.runs:
            sys.exit("drafts --runs <compare 폴더 또는 per_query.csv> …")
        cat = Catalog.current(s)
        cbs = cat._j("codebooks.json") if cat is not None else None
        recs, drafts, terms, used = D.collect(a.runs, bundle, a.split, a.config, cbs, gold_only=a.gold_only)
        if not used:
            sys.exit(f"per_query.csv 를 찾지 못함: {a.runs}")
        out_dir = Path(a.out) if a.out else Path(RUNS_DIR) / "okf_drafts" / f"{datetime.now():%Y%m%d_%H%M%S}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "drafts.md").write_text(D.report_md(recs, drafts, used, a.split, terms), encoding="utf-8")
        (out_dir / "drafts.json").write_text(json.dumps({"used": used, "split": a.split, "records": recs, "drafts": drafts,
                                                         "terms": terms}, ensure_ascii=False, indent=1, default=str),
                                             encoding="utf-8")
        print(f"문항 {len(recs)}: " + " · ".join(f"{k} {n}" for k, n in Counter(r['kind'] for r in recs).most_common()))
        print(f"개념 초안 {sum(1 for d in drafts if d['aliases'])}개 (일상어 후보가 있는 것) · 용어 후보 {len(terms)}개")
        print(f"보고서 → {out_dir / 'drafts.md'}")
        if a.write:
            for cid, text, st in D.write_drafts(bundle, drafts, a.min_support, hcx=a.hcx):
                print(f"  {cid} · {text} · {st}")
            print("→ 초안을 고친 뒤 python -m backend.rag.okf verify <개념 경로> --to <영역/영어-이름> → lint → build")
        return
    if a.cmd == "assist":
        from backend.rag.okf import assist as A
        paths = [Path(x) if Path(x).exists() else bundle / x.lstrip("/") for x in a.args] or A.inbox(bundle)
        if not paths:
            sys.exit("초안이 없음 (concepts/_inbox 에 status draft 파일) — drafts --write 로 먼저 만드세요")
        for p in paths:
            r = A.refresh(bundle, p, force=a.force) if a.no_hcx else A.assist(bundle, p, force=a.force)
            print(f"{r['concept']} · 정의 {r['definition']}" + ("" if a.no_hcx else f" · HCX {r.get('hcx', '-')}"))
            for t, v in (r.get("verdicts") or {}).items():
                print(f"    별칭 '{t}': {v}")
            for t in r.get("suggested") or []:
                print(f"    + 제안 별칭 '{t}' (미승인)")
            for t in r.get("not") or []:
                print(f"    + 헷갈리는 말 '{t}'")
        T.write_dir_indexes(bundle)
        print("→ 파일을 보고 틀린 별칭을 지운 뒤 verify <경로> --to <영역/영어-이름>")
        return
    if a.cmd == "verify":
        from backend.rag.okf import drafts as D
        if not a.args:
            sys.exit("verify <개념 경로> [--alias 표현 …]")
        try:
            r = D.verify(bundle, a.args[0], a.alias, a.by, a.to)
        except (ValueError, FileExistsError) as e:
            sys.exit(str(e))
        out(r)
        for x in r.get("skipped_aliases") or []:
            print(f"  - 승인 안 함 (HCX 판정): {x} — 맞으면 --alias 로 직접 고르세요")
        for w in r["warnings"]:
            print(f"  ! {w}")
        print("→ python -m backend.rag.okf lint · build 로 반영")
        return
    from backend.rag.okf import curate as C
    from backend.rag.query_analyzer.lexicon import get_lexicon
    recs = T.load_profiles(prof) if prof.exists() else []
    if a.cmd == "migrate":
        what = (a.args or ["aliases"])[0]
        res = C.migrate_aliases(bundle, recs) if what == "aliases" else C.migrate_learned(bundle, recs, get_lexicon(settings=s), a.by)
        for r in res:
            print(" · ".join(map(str, r)))
        return
    if a.cmd == "pending":
        out(C.pending(bundle, get_lexicon(settings=s)))
        return
    if a.cmd == "approve":
        if not a.args:
            sys.exit("approve <표현> [--value 정규이름]")
        out(C.approve(bundle, recs, get_lexicon(settings=s), a.args[0], a.by, a.value))
        print("→ python -m backend.rag.okf build 로 반영")


if __name__ == "__main__":
    main()
