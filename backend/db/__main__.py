"""python -m backend.db <명령>

  migrate [main|vector|all]            스키마 적용 (기본 all = 설정된 DB 모두)
  check                                연결 확인 (PostgreSQL · pgvector · Redis)

  stats normalize --all | --catalog-all | --tables T…   원본 CSV → 정규화 parquet (원본이 있는 PC 에서)
  stats estimate                       PostgreSQL 크기 미리 보기
  stats load [--all | --tables T…] [--force] [--max-rows N]
  stats verify [--tables T…] [--sample 200]
  stats status
  stats drop --tables T…

  vectors import-sqlite [경로]         sqlite 임베딩 캐시 → pgvector
  vectors sync                         dense 문서 묶음 올리기 (검색기 한 번 만들기)
  vectors status | prune [--keep 1] | nearest "질문" [-k 10]

  bundle create [--out 파일] [--parts indices,profiles,parquet,meta,embed] [--no-compress]
"""
import argparse
import json
import sys


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="python -m backend.db", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("migrate")
    m.add_argument("target", nargs="?", default="all", choices=["main", "vector", "all"])
    sub.add_parser("check")

    st = sub.add_parser("stats")
    st.add_argument("action", choices=["normalize", "estimate", "load", "verify", "status", "drop"])
    st.add_argument("--tables", nargs="*", default=None)
    st.add_argument("--all", action="store_true")
    st.add_argument("--catalog-all", action="store_true", help="normalize: selected 가 아닌 catalog 표까지")
    st.add_argument("--force", action="store_true")
    st.add_argument("--sample", type=int, default=200)
    st.add_argument("--max-rows", type=int, default=None, help="load: 이보다 큰 표는 올리지 않음 (parquet 로 남김)")

    ve = sub.add_parser("vectors")
    ve.add_argument("action", choices=["import-sqlite", "sync", "status", "prune", "nearest"])
    ve.add_argument("arg", nargs="?", default=None, help="import-sqlite: 경로 · nearest: 질문")
    ve.add_argument("--keep", type=int, default=1)
    ve.add_argument("-k", type=int, default=10)

    bu = sub.add_parser("bundle")
    bu.add_argument("action", choices=["create"])
    bu.add_argument("--out", default="t4core_bundle.tar.gz")
    bu.add_argument("--parts", default="indices,profiles,parquet,meta,embed")
    bu.add_argument("--no-compress", action="store_true")

    a = ap.parse_args(argv)
    if a.cmd == "migrate":
        from backend.db import migrate
        out = migrate.migrate_configured() if a.target == "all" else migrate.migrate(a.target)
    elif a.cmd == "check":
        from backend.db.conn import ping_all
        out = ping_all()
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        bad = [k for k, v in out.items() if isinstance(v, dict) and not v.get("ok")]
        return 1 if bad else 0
    elif a.cmd == "stats":
        from backend.db import stats
        if a.action == "normalize":
            out = stats.normalize(a.tables, all_selected=a.all, force=a.force, catalog_all=a.catalog_all)
        elif a.action == "estimate":
            out = stats.estimate()
        elif a.action == "load":
            if not a.all and not a.tables:
                raise SystemExit("--all 또는 --tables 가 필요합니다")
            out = stats.load(None if a.all else a.tables, force=a.force, max_rows=a.max_rows)
            return 1 if out["failed"] else 0
        elif a.action == "verify":
            out = stats.verify(a.tables, sample=a.sample)
            return 1 if out["different"] else 0
        elif a.action == "status":
            out = stats.status()
        else:
            if not a.tables:
                raise SystemExit("--tables 가 필요합니다")
            out = stats.drop(a.tables)
    elif a.cmd == "vectors":
        from backend.db import vectors
        if a.action == "import-sqlite":
            out = vectors.import_sqlite(a.arg)
        elif a.action == "sync":
            out = vectors.sync()
        elif a.action == "status":
            out = vectors.status()
        elif a.action == "prune":
            out = vectors.prune(a.keep)
        else:
            if not a.arg:
                raise SystemExit("nearest \"질문\"")
            out = vectors.nearest(a.arg, a.k)
    else:
        from backend.db import bundle
        out = bundle.create(a.out, a.parts.split(","), compress=not a.no_compress)
    return 0 if out is not None else 0


if __name__ == "__main__":
    sys.exit(main())
