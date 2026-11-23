"""2번 차트 유형 판단 서브그래프의 노드 (세부 단계 하나 = 노드 하나)

각 노드는 10번에서 옮긴 함수를 부르기만 하고, 자기가 바꾼 State 키만 돌려준다.
결과는 노트북 9번 decide_charts와 같아야 한다.
"""
import copy
from pathlib import Path

from .chart_type_chart_picker import attach_requirements, pick_chart
from .chart_type_loader import load_json, slim_query_bundle, slim_view_input
from .chart_type_matcher import match_units
from .chart_type_measure import decide_measure
from .chart_type_profiler import profile_data
from .chart_type_reason import make_reason
from .chart_type_rules import MEASURE_TO_CHARTS, OUT_OF_SCOPE, USER_WARNING_NODES
from .chart_type_overlay import find_overlays
from .chart_type_preference import parse_chart_request, record_selection, requested_chart, requested_codes
from .chart_type_schema import validate_plan
from .chart_type_view_check import block_reason, check_view, fit_warnings
from .chart_type_view_filter import filter_view

CHART_KEYS = ["chart_id", "sub_question_ids", "view_ids", "chart_type",
              "requirements", "fallback_charts", "measure", "reason", "warnings",
              "request"]       # README 4장 출력 필드 순서 + [NEW 11-20 KOS-41] 차트 지정 요청


def chart_warnings(errors, chart_ids):
    """errors 중 그 차트(들)의 사용자용 경고 문장 (USER_WARNING_NODES 의 level=warning, 순서 유지 · 중복 제거, 고도화 4단계)
    combo 처럼 하위질문 둘을 묶은 차트는 두 짝의 chart_id 경고를 모두 담는다"""
    ids = set(chart_ids)
    return list(dict.fromkeys(e["reason"] for e in errors or []
                              if e.get("level") == "warning" and e.get("node") in USER_WARNING_NODES
                              and e.get("chart_id") in ids))


INPUT_DIR = Path(__file__).resolve().parents[2] / "input_data"      # chart_type_decision/input_data


def _empty_plan(state):
    return {"query_id": (state.get("view_input") or {}).get("query_id"), "charts": [], "overlays": []}


def _scenario_files(name):
    """시나리오 이름 → (QueryBundle 파일, Views 파일, 설명)
    - 이름 없음: input_data/ 바로 아래 파일 (기본 시나리오)
    - 이름 있음: input_data/<이름>/ 폴더. 폴더가 없으면 input_data/ 바로 아래 파일의 query_id가 같을 때 그 파일
    """
    root_qb, root_vi = INPUT_DIR / "QueryBundle.json", INPUT_DIR / "Views.json"
    if not name:
        return root_qb, root_vi, "기본 시나리오 (input_data/)"
    folder = INPUT_DIR / name
    if (folder / "QueryBundle.json").exists() and (folder / "Views.json").exists():
        return folder / "QueryBundle.json", folder / "Views.json", f"시나리오 {name} (input_data/{name}/)"
    if root_vi.exists() and load_json(root_vi).get("query_id") == name:
        return root_qb, root_vi, f"시나리오 {name} (input_data/)"
    return None, None, f"시나리오 {name}를 찾을 수 없음"


def _unwrap(qb, vi):
    """Studio에서 파일 전체를 한 칸에 넣은 경우 안쪽 값을 꺼낸다"""
    for box in (qb, vi):
        if isinstance(box, dict) and ("query_bundle" in box or "view_input" in box):
            qb = box.get("query_bundle", qb if box is not qb else None)
            vi = box.get("view_input", vi if box is not vi else None)
    if isinstance(qb, dict) and "units" in qb and not isinstance(vi, dict):     # Views를 query_bundle 칸에 넣음
        qb, vi = None, qb
    return qb, vi


def _read_if_path(x):
    """입력이 파일 경로 문자열이면 파일을 읽어 돌려준다 (실행 위치 → input_data/ 순서로 찾음)"""
    if isinstance(x, str):
        for cand in (Path(x), INPUT_DIR / x, INPUT_DIR / Path(x).name):
            if cand.exists():
                return load_json(cand)
    return x


# ⓪ 입력 준비: 비어 있으면 시나리오에서 불러오고, 원본·감싼 입력은 1번 전처리 모양으로 정리
def load_input_node(state):
    qb, vi = _unwrap(_read_if_path(state.get("query_bundle")), _read_if_path(state.get("view_input")))
    scenario = state.get("scenario")
    errors = []
    if isinstance(qb, str) or isinstance(vi, str):                        # 경로인데 파일이 없음
        bad = [k for k, v in (("query_bundle", qb), ("view_input", vi)) if isinstance(v, str)]
        return {"errors": [{"node": "load_input", "reason": f"{bad} 파일을 찾을 수 없음"}],
                "chart_plan": _empty_plan({}), "input_source": "파일 없음"}

    if scenario:                                                          # 시나리오 이름 → 그 데이터만
        f_qb, f_vi, source = _scenario_files(scenario)
        if f_qb is None:
            return {"errors": [{"node": "load_input", "reason": source}], "chart_plan": _empty_plan({}),
                    "input_source": source}
        qb, vi = load_json(f_qb), load_json(f_vi)
    elif not qb and not vi:                                               # 둘 다 비면 기본 시나리오
        f_qb, f_vi, source = _scenario_files(None)
        qb, vi = load_json(f_qb), load_json(f_vi)
    elif not qb or not vi:                                                # 하나만 있으면 채우지 않고 오류
        missing = "query_bundle" if not qb else "view_input"
        return {"errors": [{"node": "load_input", "reason": f"입력에 {missing} 없음 (다른 하나만 들어옴)"}],
                "chart_plan": _empty_plan({"view_input": vi if isinstance(vi, dict) else {}}),
                "input_source": "입력값 (일부 없음)"}
    else:
        source = "입력값"

    if isinstance(qb, list) and len(qb) > 1:                              # 질문 여러 개 → 첫 번째만
        errors.append({"node": "load_input", "level": "warning",
                       "reason": f"QueryBundle 질문 {len(qb)}개 중 첫 번째만 사용"})
    try:
        qb = slim_query_bundle(qb)                          # 리스트면 첫 질문, 모양 맞추기
        vi = slim_view_input(copy.deepcopy(vi))             # candidates 제거, unit마다 rank 1만
    except Exception as e:
        errors.append({"node": "load_input", "reason": f"입력 정리 실패: {type(e).__name__}: {e}"})
    for key, need in (("query_bundle", ["sub_questions", "filters"]), ("view_input", ["query_id", "units"])):
        box = qb if key == "query_bundle" else vi
        missing = [k for k in need if not isinstance(box, dict) or k not in box]
        if missing:
            errors.append({"node": "load_input", "reason": f"입력 {key}에 {missing} 없음"})
    out = {"query_bundle": qb, "view_input": vi, "input_source": source, "errors": errors}
    if any(e.get("level") != "warning" for e in errors):
        out["chart_plan"] = _empty_plan(out)
    return out


def _use_llm(state):
    return state.get("use_llm", True)


# ① 하위질문 ↔ View 짝짓기
def match_node(state):
    matches, errors = match_units(state["query_bundle"], state["view_input"])
    out = {"matches": matches, "errors": errors}
    if not matches:                                         # 짝 없음 → 바로 END
        out["chart_plan"] = _empty_plan(state)
    return out


# ①-1 View 필터링
def filter_node(state):
    qb = state["query_bundle"]
    kept, filtered, errors = [], [], []
    for m in copy.copy(state["matches"]):
        m = dict(m)
        fv = filter_view(m["view"], m["sub_filter"], qb["filters"])
        if not fv["record"]["table"]["rows"]:
            errors.append({"chart_id": m["chart_id"], "unit_id": m["unit_id"], "reason": "필터 결과 0행"})
            continue
        m["filtered_view"] = fv
        kept.append(m)
        filtered.append(fv)
    out = {"matches": kept, "filtered_views": filtered, "errors": errors}
    if not kept:                                            # 모두 0행 → 바로 END
        out["chart_plan"] = _empty_plan(state)
    return out


# ①-2 View 적합도: View 메모(record.notes)로 시점·나눔·지표가 요청대로인지 (고도화 1단계)
def view_check_node(state):
    matches, errors = [], []
    for m in state["matches"]:
        m = dict(m)
        m["view_fit"] = check_view(m["view"])
        errors += [{"node": "view_check", "chart_id": m["chart_id"], "level": "warning", "reason": w}
                   for w in fit_warnings(m["view_fit"])]
        matches.append(m)
    return {"matches": matches, "errors": errors}


# ② measure 판단 (규칙만, LLM 안 부름)
def measure_rule_node(state):
    qb = state["query_bundle"]
    matches = []
    for m in state["matches"]:
        m = dict(m)
        m["measure_info"] = decide_measure(m["sub_question"], qb, use_llm=False)
        m["measure"] = m["measure_info"]["measure"]
        matches.append(m)
    return {"matches": matches}


# ② measure 판단 (규칙이 확신하지 못한 하위질문만 LLM)
def measure_llm_node(state):
    qb = state["query_bundle"]
    matches = []
    for m in state["matches"]:
        m = dict(m)
        if not m["measure_info"]["confident"]:
            m["measure_info"] = decide_measure(m["sub_question"], qb, use_llm=True)
            m["measure"] = m["measure_info"]["measure"]
        matches.append(m)
    return {"matches": matches}


# ③ 데이터 모양 파악
def profile_node(state):
    qb = state["query_bundle"]
    matches = []
    errors = []
    for m in state["matches"]:
        m = dict(m)
        m["profile"] = profile_data(m["filtered_view"], m["sub_filter"], qb["filters"], qb.get("intent"))
        errors += [{"node": "profile", "chart_id": m["chart_id"], "level": "warning", "reason": t}
                   for t in m["profile"].get("axis_notes") or []]          # 범주에서 뺀 열 (고도화 2단계)
        matches.append(m)
    return {"matches": matches, "errors": errors}


def _requested(m, qb):
    """질문에서 이름으로 요청한 차트 (원 질문 → 하위질문 → 재작성 순서로 찾음, 고도화 3단계). 이전 호출 호환용 — 노드는 _request_info 를 쓴다"""
    return requested_chart([qb.get("original"), m.get("sub_question"), qb.get("rewritten")])[0]


def _request_info(m, qb):
    """[NEW 11-20 KOS-41] 하위 질문 → 원 질문 → 재작성 순서로 차트 지정 요청을 해석한다 (없으면 None).
    차단 판정보다 먼저 부른다 — View 적합도로 막히는 차트도 요청과 사유를 남겨야 최종 안내가 나온다"""
    info = parse_chart_request(m.get("sub_question"), qb.get("original"), qb.get("rewritten"))
    if info is not None:
        info["scope"] = [m["chart_id"]]
    return info


def _request_warning(chart_id, r):
    """요청한 차트를 못 그렸으면 경고 하나 (없으면 [])"""
    req = r.get("request")
    if not req or req["ok"]:
        return []
    return [{"node": "chart_select", "chart_id": chart_id, "level": "warning",
             "reason": f"요청한 {req['chart']} 차트를 그릴 수 없음: {req['why']} → {r['chart_type'] or '표만'}"}]


def _needs_llm(chart):
    """후보는 있었는데 모두 소거돼 규칙으로 못 정한 차트인가"""
    measure = chart["measure"]
    return (chart["chart_type"] is None and measure not in (None, OUT_OF_SCOPE)
            and bool(MEASURE_TO_CHARTS.get(measure)) and not chart.get("blocked"))     # View 적합도로 막은 차트는 LLM 도 안 씀


# ④ combo 묶음 판단 + chart_type 소거법 (규칙만)
def chart_select_node(state):
    ms, qb = state["matches"], state["query_bundle"]
    blocks = {m["chart_id"]: block_reason(m, qb) for m in ms}          # (막을 이유, 뺄 차트, 뺀 이유)
    # [고도화 5단계] 하위질문 둘을 combo 차트 하나로 묶지 않는다 (3번이 서로 다른 표의 둘을 한 차트로 계산하지 못함)
    #  → 차트는 하위질문마다 1개, 겹쳐 그리기는 reason 노드가 chart_plan.overlays 로 표시 (5번만 읽음)
    charts, errors = [], []
    for m in ms:
        block, exclude, why = blocks[m["chart_id"]]
        info = _request_info(m, qb)
        base = {"chart_id": m["chart_id"], "sub_question_ids": [m["sub_question_id"]],
                "view_ids": [m["filtered_view"]["record"]["id"]], "measure": m["measure"], "request": info}
        if block:                                                   # View 가 질문에 맞지 않음 → 차트 없음 (표만)
            record_selection(info, None, block=block)               # [NEW] 차단돼도 요청과 사유(view_blocked)를 남긴다
            charts.append({**base, "chart_type": None, "fallback_charts": [], "source": "rule", "blocked": True,
                           "log": [{"후보": "-", "결과": "막음", "이유": block}]})
            errors.append({"node": "chart_select", "chart_id": m["chart_id"], "level": "warning",
                           "reason": f"차트 없음(표만): {block}"})
            continue
        codes, excl = requested_codes(info)
        r = pick_chart(m["measure"], m["profile"], use_llm=False, exclude=exclude, exclude_why=why,
                       requested=codes, excluded=excl)
        record_selection(info, r)
        charts.append({**base, "chart_type": r["chart_type"], "fallback_charts": r["fallback_charts"],
                       "source": r["source"], "log": r["log"]})
        errors += _request_warning(m["chart_id"], r)
    for c in charts:
        c["needs_llm"] = _needs_llm(c)
    return {"charts": charts, "errors": errors}


# ④ 규칙 실패(모두 소거) 차트만 LLM (지금은 pick_chart_llm이 자리만 있어 None)
def chart_llm_node(state):
    by_sq = {m["sub_question_id"]: m for m in state["matches"]}
    charts = []
    for c in state["charts"]:
        c = dict(c)
        if c.get("needs_llm"):
            m = by_sq[c["sub_question_ids"][0]]
            _, exclude, why = block_reason(m, state["query_bundle"])
            codes, excl = requested_codes(c.get("request"))
            r = pick_chart(c["measure"], m["profile"], use_llm=True, exclude=exclude, exclude_why=why,
                           requested=codes, excluded=excl)
            record_selection(c.get("request"), r)
            c.update(chart_type=r["chart_type"], fallback_charts=r["fallback_charts"], source=r["source"], log=r["log"])
        charts.append(c)
    return {"charts": charts}


# ⑤ requirements · fallback
def requirements_node(state):
    return {"charts": [attach_requirements(dict(c)) for c in state["charts"]]}


# ⑥ reason → 최종 chart_plan
def reason_node(state):
    qb = state["query_bundle"]
    by_sq = {m["sub_question_id"]: m for m in state["matches"]}
    charts, plan_charts = [], []
    for c in state["charts"]:
        c = dict(c)
        ms = [by_sq[s] for s in c["sub_question_ids"]]
        c["reason"] = make_reason([m["sub_filter"] for m in ms], qb, [m["sub_question"] for m in ms])
        c["warnings"] = chart_warnings(state.get("errors"), [m["chart_id"] for m in ms])
        charts.append(c)
        plan_charts.append({k: c[k] for k in CHART_KEYS})
    # [고도화 5단계] 겹쳐 그리기 표시 (조건을 모두 만족할 때만) + 출력 스키마 검증
    ordered = [by_sq[c["sub_question_ids"][0]] for c in charts]
    overlays, notes = find_overlays(ordered, plan_charts, qb)
    plan, schema_errors = validate_plan({"query_id": state["view_input"]["query_id"], "charts": plan_charts,
                                         "overlays": overlays})
    errors = [{"node": "reason", "level": "info", "reason": t} for t in notes] + schema_errors
    return {"charts": charts, "chart_plan": plan, "errors": errors}


# ── 조건부 엣지 ──
def route_after_load(state):
    ok = isinstance(state.get("query_bundle"), dict) and isinstance(state.get("view_input"), dict) \
        and "sub_questions" in state["query_bundle"] and "units" in state["view_input"]
    return "match" if ok else "end"


def route_after_match(state):
    return "filter" if state.get("matches") else "end"


def route_after_filter(state):
    return "view_check" if state.get("matches") else "end"


def route_after_measure_rule(state):
    unsure = any(not m["measure_info"]["confident"] for m in state["matches"])
    return "measure_llm" if unsure and _use_llm(state) else "profile"


def route_after_chart_select(state):
    return "chart_llm" if any(c.get("needs_llm") for c in state["charts"]) and _use_llm(state) else "requirements"
