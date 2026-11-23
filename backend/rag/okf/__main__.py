"""
python -m backend.rag.okf <명령>

  tables    [--profiles DIR]                 프로필 → 표·분류 파일 (바뀐 것만 씀) + index.md · log.md
  lint      [--profiles DIR] [--all]         참조 무결성 검사 (오류면 종료 코드 1). --all 이면 info 까지
  build     [--profiles DIR] [--no-index] [--embed hcx] [--force] [--tables]
                                              검사 → 파생물 → CURRENT 교체 (--tables: 표 생성부터)
  show      [tbl_id | 개념 경로] [--text 질문]  지금 빌드 정보 · 표 · 질문에 걸린 개념
  use       <해시>                            CURRENT 를 이전 빌드로 (되돌리기)
  migrate   aliases | learned [--by 이름]     별칭 옮기기 (vocab_aliases.csv · 학습 사전 승인분 → 개념 파일)
  pending                                      학습 사전 '승인 대기' (벡터+HCX 제안 등) 와 맞을 개념
  approve   <표현> [--value 정규이름] [--by 이름]   승인 → 개념 별칭 (verified)
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
    ap.add_argument("cmd", choices=["tables", "lint", "build", "show", "use", "migrate", "pending", "approve"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--profiles", default=None, help="정규화 프로필 폴더 (기본 VIEW_OUT_DIR/profiles)")
    ap.add_argument("--bundle", default=None, help="번들 폴더 (기본 storage/okf)")
    ap.add_argument("--no-index", action="store_true", help="build: CSV 값 사전 없이 (프로필만으로 vocab)")
    ap.add_argument("--embed", default=None, help="build: 사전 벡터도 (hcx | bge-m3-ko | …)")
    ap.add_argument("--force", action="store_true", help="build: 검사 오류가 있어도 빌드")
    ap.add_argument("--tables", action="store_true", help="build: 표 생성부터")
    ap.add_argument("--all", action="store_true", help="lint: info 까지 출력")
    ap.add_argument("--text", default="", help="show: 질문 (걸리는 개념)")
    ap.add_argument("--by", default=None, help="승인한 사람 (기본 OS 사용자 → human:<이름>)")
    ap.add_argument("--value", default=None, help="approve: 정규 이름을 직접 (제안과 다르게)")
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
        m = B.build(bundle, B.build_root(s), prof if prof.exists() else None, idx, force=a.force, embed=a.embed, settings=s)
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
