"""python -m backend.rag.csv_index {build|summary|find|values|table} …"""
import argparse
import json

from backend.rag.csv_index import build_index, load_index


def main():
    ap = argparse.ArgumentParser(prog="python -m backend.rag.csv_index")
    ap.add_argument("cmd", choices=["build", "summary", "find", "values", "table"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--scope", default=None, help="build 기본 all(raw 전체) / 조회 기본 selected (지금 검색 대상과 같음)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.cmd == "build":
        build_index(scope=a.scope or "all", workers=a.workers, force=a.force, limit=a.limit)
        return
    idx = load_index()
    scope = a.scope or "selected"
    if a.cmd == "summary":
        print(json.dumps(idx.summary, ensure_ascii=False, indent=1))
    elif a.cmd == "find":
        q = " ".join(a.args)
        rows = idx.find(q, scope=scope) or idx.contains(q, scope=scope)
        for r in rows[:a.limit or 30]:
            print(f"  [{r['match']:8s}] {r['slot']:4s} {r['name']:<24} {r['tbl_id']:<14} {r['obj_nm']}")
        print(f"총 {len(rows)}개")
    elif a.cmd == "values":
        for v in idx.values(a.args[0], scope=scope, limit=a.limit or 40):
            print(f"  {v['value']:<20} 표 {v['n_tables']}개  {v['example_tables']}")
    elif a.cmd == "table":
        print(json.dumps(idx.table(a.args[0]), ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
