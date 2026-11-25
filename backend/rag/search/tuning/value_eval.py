"""검색 실행의 상위 표가 정답 교차점 값을 제공하는지 기록한다.

단순 조회는 최종 값, 계산형 질문은 골든셋에 기록된 계산 입력 교차점을 모두 비교한다.
캐시의 검색 단위만 읽고, 검색 임베딩은 로컬 캐시에서만 가져온다.
View와 정규화의 임시 파일은 작업 폴더에 둔다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.rag.ingestion.normalize import level_kind
from backend.rag.judge.extract import is_total, region_std
from backend.rag.view.points import age_key, item_core, period_key, sex_of
from synthetic_gold_pipeline.tools.units import UnitIncompatible, canonical_unit, convert_value


@dataclass(frozen=True)
class Cell:
    coordinate: tuple
    value: Decimal
    unit: str


@dataclass
class Gold:
    kind: str
    cells: frozenset[Cell]


@dataclass
class ViewValues:
    cells: list[Cell]
    reason: str = ""


def json_lines(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def number(value):
    try:
        result = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def coordinate(period, item, labels):
    if not period or not item:
        return None
    parts = []
    for key, label in labels.items():
        if label is None or not str(label).strip():
            continue
        label = str(label).strip()
        kind = level_kind(key, [label])
        if kind == "regions":
            # 동부·읍부·면부는 같은 지역 안의 다른 좌표다.
            suffix = re.search(r"(?:^|\s)(동부|읍부|면부)$", label)
            if is_total(label):
                continue
            label = (region_std(label), suffix[1] if suffix else "")
            name = "지역"
        elif is_total(label):
            continue
        elif kind == "sex":
            name, label = "성별", sex_of(label) or label
        elif kind == "ages":
            name, label = "연령", age_key(label) or label
        else:
            name = re.sub(r"[\s_/·()]+|별$", "", key)
        if isinstance(label, str):
            label = re.sub(r"\s+", "", label)
        parts.append((name, label))
    sex = sex_of(item) or next((sex_of(word) for word in ("남자", "여자", "남성", "여성") if word in item), None)
    if sex and not any(key == "성별" for key, _ in parts):
        parts.append(("성별", sex))
    return period_key(period), item_core(item) or item, tuple(sorted(parts, key=repr))


def make_cell(period, item, labels, value, unit):
    key = coordinate(period, item, labels)
    numeric = number(value)
    unit = canonical_unit(unit)
    if key is None or numeric is None or not unit:
        return None
    return Cell(key, numeric, unit)


def equal_value(expected, observed):
    candidate = observed.value
    if expected.unit != observed.unit:
        try:
            candidate, _ = convert_value(candidate, observed.unit, expected.unit)
        except UnitIncompatible:
            return False
    return abs(expected.value - candidate) <= max(Decimal("1e-9"), abs(expected.value) * Decimal("1e-14"))


def parse_gold(m2, numeric, reasoning=""):
    evidence = m2.get("expected_values") or []
    simple = reasoning == "SIMPLE_LOOKUP"
    if not evidence:
        return Gold("no_gold_coordinates", frozenset())
    if simple:
        if len(evidence) != 1 or not isinstance(numeric, dict):
            return Gold("no_gold_value", frozenset())
        numeric_value = numeric.get("exact_decimal") or numeric.get("raw")
        if numeric_value is None:
            return Gold("no_gold_value", frozenset())
    cells = set()
    for entry in evidence:
        stored = make_cell(entry.get("period"), entry.get("item"), entry.get("labels") or {},
                           entry.get("value"), entry.get("unit"))
        if stored is None:
            return Gold("no_gold_value", frozenset())
        if simple:
            final = make_cell(entry.get("period"), entry.get("item"), entry.get("labels") or {},
                              numeric_value, numeric.get("unit"))
            if final is None or not equal_value(final, stored):
                return Gold("gold_value_conflict", frozenset())
            cells.add(final)
        else:
            cells.add(stored)
    return Gold("direct" if simple else "evidence", frozenset(cells))


def load_gold(path):
    if Path(path).suffix.lower() == ".csv":
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            out = {}
            for row in csv.DictReader(stream):
                if row.get("answerability") != "ANSWERABLE":
                    continue
                modules = json.loads(row.get("module_eval") or "{}")
                reason = (modules.get("M1") or {}).get("expected_intent", "").split(":", 1)[0]
                if not reason and (row.get("executed_formula") or "").startswith("s1: A = "):
                    reason = "SIMPLE_LOOKUP"
                out[row["id"]] = parse_gold(modules.get("M2") or {},
                                            json.loads(row.get("numeric_ground_truth") or "null"), reason)
            return out
    out = {}
    for row in json_lines(path):
        if row.get("answerability_type") != "ANSWERABLE":
            continue
        gen = row.get("generation_eval") or {}
        gold = parse_gold((row.get("module_eval") or {}).get("M2") or {},
                          gen.get("exact_numeric_ground_truth") or gen.get("final_answer"), row.get("reasoning_type"))
        ids = row.get("question_ids") or {
            "original": f'{row["dataset_id"]}-O', "paraphrased": f'{row["dataset_id"]}-P',
        }
        out.update({qid: gold for qid in ids.values()})
    return out


def evaluate_cells(gold, views):
    """모든 근거 교차점이 같은 값을 갖는지 평가하고 판정 못 한 이유를 구분한다."""
    if not gold.cells:
        return gold.kind, 0
    observed = defaultdict(list)
    reasons = set()
    for view in views:
        if view.reason:
            reasons.add(view.reason)
        for cell in view.cells:
            observed[cell.coordinate].append(cell)
    matched = sum(any(equal_value(c, got) for got in observed[c.coordinate]) for c in gold.cells)
    if matched == len(gold.cells):
        return "match", matched
    for reason in ("view_error", "incomplete_view", "no_slots", "embedding_cache_miss", "ranking_changed"):
        if reason in reasons:
            return reason, matched
    if not any(observed.values()):
        return "no_value" if views else "no_candidates", matched
    return "mismatch", matched


def read_view(path):
    cells = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            period, item = row.pop("시점"), row.pop("항목")
            value, unit = row.pop("값"), row.pop("단위")
            row.pop("부호", None)
            cell = make_cell(period, item, row, value, unit)
            if cell is not None:
                cells.append(cell)
    return cells


@contextmanager
def view_builder(directory):
    from duckdb import Error as DuckError

    from backend.data_engine.duckdb_client import connect
    from backend.rag.ingestion import normalize
    from backend.rag.view import build

    old_root, old_normalized, old_ensure = build.VIEW_OUT_DIR, normalize.VIEW_OUT_DIR, build.ensure_normalized
    profiles = defaultdict(list)
    for profile in (old_root / "profiles").glob("*.json"):
        _, _, table = profile.stem.partition("_")
        profiles[table].append(profile)
    directory = Path(directory)
    (directory / "processed").mkdir(parents=True)
    (directory / "profiles").mkdir()

    def ensure(con, tid):
        if len(profiles[tid]) == 1:
            prof = json.loads(profiles[tid][0].read_text(encoding="utf-8-sig"))
            raw_file = old_root / prof["file"]
            local_file = directory / prof["file"]
            compatible = prof.get("kind_rules") == normalize.KIND_RULES_VERSION or not normalize.stale_kinds(prof)
            if raw_file.is_file() and compatible:
                if not local_file.exists():
                    try:
                        os.link(raw_file, local_file)
                    except OSError:
                        return old_ensure(con, tid)
                return prof
        return old_ensure(con, tid)

    cache = {}
    with closing(connect()) as con:
        build.VIEW_OUT_DIR = normalize.VIEW_OUT_DIR = directory
        build.ensure_normalized = ensure
        try:
            def fetch(tid, filters):
                if filters is None:
                    return ViewValues([], "no_slots")
                key = (tid, json.dumps(filters, ensure_ascii=False, sort_keys=True))
                if key not in cache:
                    try:
                        rec, notes = build.build_view(tid, filters, f"eval-{len(cache)}", con)
                        stem = re.sub(r"[^\w\-]+", "_", rec["id"])
                        cells = read_view(directory / "views" / f"{stem}.csv")
                        if rec.get("metadata", {}).get("indicator_missing"):
                            cells = []
                        reason = "incomplete_view" if any(n.get("type") == "truncated" for n in notes) else ""
                        cache[key] = ViewValues(cells, reason)
                    except (DuckError, OSError, ValueError, KeyError, RuntimeError) as exc:
                        print(f"  View 실패 {tid} ({type(exc).__name__}): {str(exc)[:160]}", file=sys.stderr)
                        cache[key] = ViewValues([], "view_error")
                return cache[key]
            yield fetch
        finally:
            build.VIEW_OUT_DIR, normalize.VIEW_OUT_DIR = old_root, old_normalized
            build.ensure_normalized = old_ensure


class CacheMiss(RuntimeError):
    pass


@contextmanager
def cached_search(dense, settings, work_dir):
    from backend.core import llm
    from backend.rag.search import index
    from backend.rag.search.tuning.compare import get_search_for

    original_embed, original_many = llm.embed_one, llm.embed_many
    original_cache_file = index._cache_file

    def local_cache(kind, *keys):
        source = original_cache_file(kind, *keys)
        return source if source.exists() else work_dir / kind / source.name

    index._cache_file = local_cache
    try:
        if dense != "hcx":
            yield get_search_for(dense, False, settings)
            return
        cache = llm._EmbedCache.__new__(llm._EmbedCache)
        cache.lock = threading.Lock()
        with closing(sqlite3.connect(llm.EMBED_CACHE.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)) as db:
            cache.db = db

            def embed(text):
                value = cache.get((text or "")[:llm.EMBED_MAX_CHARS])
                if value is None:
                    raise CacheMiss("로컬 질의 임베딩 없음")
                return value

            llm.embed_one = embed
            llm.embed_many = lambda texts, **kwargs: [embed(text) for text in texts]
            yield get_search_for(dense, False, settings)
    finally:
        llm.embed_one, llm.embed_many = original_embed, original_many
        index._cache_file = original_cache_file


def load_run(run, config_name=None):
    with (run / "per_query.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r["method"] == "search"]
    configs = {r["config"] for r in rows}
    if config_name is None and len(configs) == 1:
        config_name = next(iter(configs))
    if config_name not in configs:
        raise ValueError(f"--config로 search 구성 선택 필요: {sorted(configs)}")
    rows = [r for r in rows if r["config"] == config_name]
    cfg = json.loads((run / "config.json").read_text(encoding="utf-8-sig"))
    meta = json.loads((run / "summary.json").read_text(encoding="utf-8-sig"))["meta"]
    return rows, cfg, meta


def read_analysis(run, rows, cfg, prune):
    from backend.rag.search.tuning.compare import prune_analysis

    by_key = {row["key"]: row["units"] for row in json_lines(run / "analysis_cache.jsonl")}
    mode, today = cfg.get("analyze", "analyze"), cfg["today"]
    matched = {}
    for row in rows:
        question = row["question"]
        key = hashlib.sha1(f"{mode}|{today}|{question}".encode()).hexdigest()[:16]
        if key in by_key:
            matched[row["qid"]] = by_key[key]
    return prune_analysis(rows, matched, log=lambda *_: None)[0] if prune else matched


def candidate_views(row, units, pipe, app, top_k, fetch):
    from backend.rag.search.tuning.compare import app_status
    from backend.rag.view.run import main_copy

    if not units:
        missing = [ViewValues([], "no_slots")]
        return missing, missing
    top = row.get("top1")
    main = next((u for u in units if u.get("unit") == "main"), units[0])
    top_view = [fetch(top, main.get("filters"))] if top else []
    if app_status(units) != "ok":
        return top_view, [ViewValues([], "no_slots")]
    def rank(u, mode):
        return [hit["tbl_id"] for hit in pipe.search(
            u["search_query"], u.get("filters"), top_k, question=row["question"], unit=mode,
        )["hits"]]

    try:
        ranks = [rank(u, u.get("unit") or "main") for u in units]
    except CacheMiss:
        return top_view, [ViewValues([], "embedding_cache_miss")]
    merged = list(dict.fromkeys(r[depth] for depth in range(top_k) for r in ranks if depth < len(r)))
    evidence = (row.get("top5") or "").split()
    if merged[:1] != ([top] if top else []) or (evidence and merged[:len(evidence)] != evidence):
        return top_view, [ViewValues([], "ranking_changed")]
    winner = next((i for i, rank in enumerate(ranks) if rank), None)
    if winner is not None and units[winner] is not main:
        top_view = [fetch(top, units[winner].get("filters"))]
    copy = main_copy([(u.get("unit"), u.get("text") or u["search_query"], u.get("filters")) for u in units])
    if copy is not None:
        try:
            ranks[copy] = ranks[units.index(main)] if all(
                units[copy].get(k) == main.get(k) for k in ("search_query", "filters")
            ) else rank(units[copy], "main")
        except CacheMiss:
            return top_view, [ViewValues([], "embedding_cache_miss")]
    include_main = app["main_with_subs"] or len(units) == 1
    return top_view, [
        fetch(tid, u.get("filters"))
        for u, candidates in zip(units, ranks)
        if include_main or u is not main
        for tid in candidates[:app["n_rec"]]
    ]


def metric(result):
    status, _ = result
    return 1 if status == "match" else 0 if status == "mismatch" else ""


def evaluate(rows, gold, analysis, pipe, app, top_k, fetch):
    for row in rows:
        qid = row["qid"]
        target = gold.get(qid, Gold("no_gold_value", frozenset()))
        if target.cells:
            top, app_views = candidate_views(row, analysis.get(qid), pipe, app, top_k, fetch)
        else:
            top = app_views = []
        results = [evaluate_cells(target, top), evaluate_cells(target, app_views)]
        yield {
            "qid": qid, "hit@1_aud": row.get("hit@1_aud"), "top1": row.get("top1"),
            "target": target.kind, "target_cells": len(target.cells),
            "hit@1_value": metric(results[0]), "app_value": metric(results[1]),
            "hit@1_status": results[0][0], "app_status": results[1][0],
            "hit@1_matched_cells": results[0][1], "app_matched_cells": results[1][1],
        }


def main(argv=None):
    from backend.rag.search.tuning import compare

    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="캐시 검색 결과의 정답 교차점 값 평가")
    parser.add_argument("run", help="compare 실행 폴더 또는 전체 이름")
    parser.add_argument("--gold", type=Path, help="골든 JSONL 또는 정답 참조 CSV (기본: 실행의 골든셋)")
    parser.add_argument("--config", help="per_query.csv의 search 구성 이름")
    parser.add_argument("--out", type=Path, required=True, help="문항별 결과 CSV")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다")
    run = compare.find_run(args.run)
    rows, cfg, meta = load_run(run, args.config)
    rows = rows[:args.limit]
    system = meta["configs"][rows[0]["config"]]
    dense = rows[0]["dense"].split("|")[0].rstrip("*")
    if dense not in {"hcx", "none"}:
        raise ValueError("값 평가는 HCX 로컬 캐시 또는 dense 없는 search 구성을 지원합니다")
    settings = dict(system.get("tuned") or {})
    if system.get("dense_docs") != "rule":
        settings.update(dense_docs=system.get("dense_docs"), dense_cards=cfg.get("cards"), kos14_cards=cfg.get("kos14"))
    if "|okf-" in rows[0]["dense"]:
        settings["okf"] = {"enabled": "|okf-on" in rows[0]["dense"]}
    if system.get("feas"):
        settings["feas"] = {**(settings.get("feas") or {}), **system["feas"]}
    analysis = read_analysis(run, rows, cfg, system.get("prune_units", meta.get("prune_units", True)))
    gold = load_gold(args.gold or Path(cfg["golden"]))
    top_k = cfg["top_k"]
    app = meta.get("app") or compare.app_settings()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.out.parent, prefix="value-") as name:
        work = Path(name)
        with cached_search(dense, settings, work / "index") as pipe, view_builder(work / "view") as fetch:
            results = list(evaluate(rows, gold, analysis, pipe, app, top_k, fetch))
    with args.out.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    for key in ("hit@1", "app"):
        print(f"{key}: {dict(Counter(row[key + '_status'] for row in results))}")
    failed = [r for r in results if r["hit@1_aud"] == "0"]
    print(f"hit@1_aud 실패 {len(failed)}건 중 값 일치: "
          f"1위 {sum(r['hit@1_value'] == 1 for r in failed)}, 앱 {sum(r['app_value'] == 1 for r in failed)}")
    print(args.out)


if __name__ == "__main__":
    main()
