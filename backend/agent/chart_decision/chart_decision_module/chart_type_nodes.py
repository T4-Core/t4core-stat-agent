"""2번 차트 유형 판단 서브그래프의 노드 (세부 단계 하나 = 노드 하나)

각 노드는 10번에서 옮긴 함수를 부르기만 하고, 자기가 바꾼 State 키만 돌려준다.
결과는 노트북 9번 decide_charts와 같아야 한다.
"""
import copy
from pathlib import Path

from .chart_type_chart_picker import attach_requirements, pick_chart, try_combo
from .chart_type_loader import load_json, slim_query_bundle, slim_view_input
from .chart_type_matcher import match_units
from .chart_type_measure import decide_measure
from .chart_type_profiler import profile_data
from .chart_type_reason import make_reason
from .chart_type_rules import MEASURE_TO_CHARTS, OUT_OF_SCOPE
from .chart_type_view_filter import filter_view

CHART_KEYS = ["chart_id", "sub_question_ids", "view_ids", "chart_type",
              "requirements", "fallback_charts", "measure", "reason"]       # README 4장 출력 필드 순서


INPUT_DIR = Path(__file__).resolve().parents[2] / "input_data"      # chart_type_decision/input_data


def _empty_plan(state):
    return {"query_id": (state.get("view_input") or {}).get("query_id"), "charts": []}


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
    for m in state["matches"]:
        m = dict(m)
        m["profile"] = profile_data(m["filtered_view"], m["sub_filter"], qb["filters"])
        matches.append(m)
    return {"matches": matches}


def _needs_llm(chart):
    """후보는 있었는데 모두 소거돼 규칙으로 못 정한 차트인가"""
    measure = chart["measure"]
    return (chart["chart_type"] is None and measure not in (None, OUT_OF_SCOPE)
            and bool(MEASURE_TO_CHARTS.get(measure)))


# ④ combo 묶음 판단 + chart_type 소거법 (규칙만)
def chart_select_node(state):
    ms = state["matches"]
    ok, reasons, _ = try_combo(ms, state["query_bundle"])
    charts = []
    if ok:
        a, b = ms
        charts.append({"chart_id": a["chart_id"], "sub_question_ids": [a["sub_question_id"], b["sub_question_id"]],
                       "view_ids": [a["filtered_view"]["record"]["id"], b["filtered_view"]["record"]["id"]],
                       "measure": a["measure"], "chart_type": "combo", "fallback_charts": [], "source": "rule",
                       "log": [{"후보": "combo", "결과": "남음", "이유": ", ".join(reasons)}]})
    else:
        for m in ms:
            r = pick_chart(m["measure"], m["profile"], use_llm=False)
            charts.append({"chart_id": m["chart_id"], "sub_question_ids": [m["sub_question_id"]],
                           "view_ids": [m["filtered_view"]["record"]["id"]], "measure": m["measure"],
                           "chart_type": r["chart_type"], "fallback_charts": r["fallback_charts"],
                           "source": r["source"], "log": r["log"]})
    for c in charts:
        c["needs_llm"] = _needs_llm(c)
    return {"charts": charts}


# ④ 규칙 실패(모두 소거) 차트만 LLM (지금은 pick_chart_llm이 자리만 있어 None)
def chart_llm_node(state):
    by_sq = {m["sub_question_id"]: m for m in state["matches"]}
    charts = []
    for c in state["charts"]:
        c = dict(c)
        if c.get("needs_llm"):
            m = by_sq[c["sub_question_ids"][0]]
            r = pick_chart(c["measure"], m["profile"], use_llm=True)
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
        charts.append(c)
        plan_charts.append({k: c[k] for k in CHART_KEYS})
    return {"charts": charts, "chart_plan": {"query_id": state["view_input"]["query_id"], "charts": plan_charts}}


# ── 조건부 엣지 ──
def route_after_load(state):
    ok = isinstance(state.get("query_bundle"), dict) and isinstance(state.get("view_input"), dict) \
        and "sub_questions" in state["query_bundle"] and "units" in state["view_input"]
    return "match" if ok else "end"


def route_after_match(state):
    return "filter" if state.get("matches") else "end"


def route_after_filter(state):
    return "measure_rule" if state.get("matches") else "end"


def route_after_measure_rule(state):
    unsure = any(not m["measure_info"]["confident"] for m in state["matches"])
    return "measure_llm" if unsure and _use_llm(state) else "profile"


def route_after_chart_select(state):
    return "chart_llm" if any(c.get("needs_llm") for c in state["charts"]) and _use_llm(state) else "requirements"
