"""v2 평가 하네스 probe (J01~J14): 기준 문항의 정답 계산 결과를 고정하고 최종 답변만 바꿔 judge() 판정을 확인한다.

저장소 fixture(fixtures/v2_probes.json)로 돌아서 데이터셋이 없어도 항상 실행된다. 기계 관문(J11 외 13개)과 의미 관문(J11)을 따로 단언한다.
"""
import json

import pytest

from eval.generator import v2
from eval.generator.schema_v2 import Case, to_question
from eval.generator.verdict import judge

FX = json.loads(v2.FIXTURE.read_text(encoding="utf-8"))
PROBES = {p["id"]: p for p in FX["probes"]}
MECHANICAL = [p for p in sorted(PROBES) if p != "J11"]


def _verdict(pid: str):
    p = PROBES[pid]
    case = Case.model_validate(FX["cases"][p["base_case_id"]])
    q = to_question(case, version=FX["dataset_version"])
    return judge(q, v2.gold_run(case, FX["inputs"][p["base_case_id"]], p["candidate_answer"]))


def test_fixture_hash_matches_record():
    assert v2.fixture_hash(FX) == FX["fixture_sha256"]


def test_fixture_covers_all_probes():
    assert sorted(PROBES) == [f"J{i:02d}" for i in range(1, 15)]


@pytest.mark.parametrize("pid", MECHANICAL)
def test_mechanical_gate(pid):
    v = _verdict(pid)
    assert v2.probe_verdict_ok(pid, PROBES[pid]["expected_verdict"], v.verdict), \
        (pid, v.verdict, [f for f in v.findings if f["ok"] is False])


def test_semantic_gate_unsupported_causal():
    v = _verdict("J11")
    assert v.verdict == "미달" and any(f["code"] == "unsupported_causal" and f["ok"] is False for f in v.findings)


@pytest.mark.parametrize("pid,code", [("J04", "claim_unit"), ("J05", "claim_sign"), ("J06", "binding"), ("J07", "binding"),
                                      ("J08", "binding"), ("J10", "invisible_citation"), ("J12", "claim_unit"),
                                      ("J13", "required_digits")])
def test_failure_reason_is_the_intended_rule(pid, code):
    """우연한 실패가 아니라 그 probe 가 노린 규칙으로 실패한다"""
    v = _verdict(pid)
    assert any(f["code"] == code and f["ok"] is False for f in v.findings), [f for f in v.findings if f["ok"] is False]


@pytest.mark.parametrize("cid", sorted(FX["cases"]))
def test_reference_answer_passes(cid):
    """정상 답변 오탐 방지: 기준 문항의 reference_answer 는 같은 계산 결과에서 통과"""
    case = Case.model_validate(FX["cases"][cid])
    v = judge(to_question(case, version=FX["dataset_version"]), v2.gold_run(case, FX["inputs"][cid], case.reference_answer))
    assert v.verdict == "통과", [f for f in v.findings if f["ok"] is False]


@pytest.mark.parametrize("tail,ok", [
    (" 이 증가는 정책 효과 때문일 수 있습니다.", None),                     # 가능성 표현 → 수동 판정
    (" 세 지역 값을 더했기 때문에 합계가 커졌습니다.", "skip"),              # 산술 설명
    (" 사망자 자료가 없어 계산하지 못했습니다.", "skip"),                   # 보류 고지
    (" 출생아 증가는 정책 때문입니다.", False),
])
def test_causal_rule_scope(tail, ok):
    case = Case.model_validate(FX["cases"]["R01"])
    v = judge(to_question(case, version=FX["dataset_version"]),
              v2.gold_run(case, FX["inputs"]["R01"], "2024년 전국 출생아 수는 238,317명입니다." + tail))
    rows = [f for f in v.findings if f["code"] == "unsupported_causal"]
    assert (not rows) if ok == "skip" else [f["ok"] for f in rows] == [ok]


def test_dataset_check_fails_without_dataset(tmp_path, monkeypatch):
    monkeypatch.delenv(v2.ENV, raising=False)
    assert v2.main(["check"]) == 1
    assert v2.main(["check", "--dataset", str(tmp_path)]) == 1


def test_dataset_check_fails_on_hash_mismatch(tmp_path):
    (tmp_path / "cases.json").write_text(json.dumps({"cases": []}), encoding="utf-8")
    (tmp_path / "manifest.sha256.json").write_text(json.dumps({"cases.json": "0" * 64}), encoding="utf-8")
    assert v2.main(["check", "--dataset", str(tmp_path)]) == 1
