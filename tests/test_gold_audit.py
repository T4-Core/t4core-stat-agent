"""골든셋 정답 표시 검토 (search/tuning/gold_audit.py) · compare --audit · alt_gold 의 '계' 항목 (Kiwi 형태소는 실제)

  1) SEX       성별로 나뉜 정답 표 + 질문에 성별 없음 → (계) 형제 표를 대체 정답 (기본 반영)
  2) UNIVERSE  '(15세이상)' 정답 표 + 질문에 '15세' 없음 → 그 변형은 뺌 (O 에 있으면 O 는 그대로)
  3) P_DRIFT   O 에 있던 '당해연도' 가 P 에 없고 P 가 형제 쪽 말('누적')도 안 씀 → 검토 제안 (human accept 해야 반영)
               형제 표에 정답 시점이 없으면 후보가 아님
  4) load_audit human 판단 (accept · exclude · strict) · 다시 돌려도 human 이 남음 · report
  5) compare   검토 반영 지표 (rank_aud · 뺀 변형은 None · n_aud) — 엄격·완화는 그대로
  6) alt_gold  정답 항목이 '계' 뿐이면 loose 확인을 자동으로 (총괄 표의 '주택수')
"""
import json
from decimal import Decimal
from typing import ClassVar

from backend.rag.search.tuning import gold_audit as G
from tests.test_okf import env  # noqa: F401 (pytest 픽스처)

TABLES = {
    "TX_M": {"title": "한국국적을 취득한 자-기타(남)(2007~2015)", "survey": "외국인주민", "periods": {"2010", "2013"},
             "names": {"한국국적을 취득한 자"}, "dims": ["행정구역(시군구)별", "국적별"]},
    "TX_T": {"title": "한국국적을 취득한 자-기타(계)(2007~2015)", "survey": "외국인주민", "periods": {"2010", "2013"},
             "names": {"한국국적을 취득한 자"}, "dims": ["행정구역(시군구)별", "국적별"]},
    "IN15": {"title": "행정구역/성/연령/혼인상태별 인구(15세이상)", "survey": "인구총조사", "periods": {"1985"},
             "names": {"인구"}, "dims": ["행정구역별", "연령별", "혼인상태별"]},
    "A004": {"title": "당해연도 혼인 비율", "survey": "인구동태패널통계", "periods": {"2016", "2018"}, "names": {"비율"},
             "dims": ["성별", "년생별"]},
    "A001": {"title": "누적 혼인 비율", "survey": "인구동태패널통계", "periods": {"2016", "2018"}, "names": {"비율"},
             "dims": ["성별", "년생별"]},
    "OLD": {"title": "누적 혼인 비율(구)", "survey": "인구동태패널통계", "periods": {"2010"}, "names": {"비율"},
            "dims": ["성별", "년생별"]},
}


def rec(rid, gold, o, p, facts):
    return {"dataset_id": rid, "answerability_type": "ANSWERABLE", "question_original": o, "question_paraphrased": p,
            "retrieval_eval": {"golden_table_ids": gold},
            "generation_eval": {"intermediate_facts": [{"parent_table_id": f"101_{t}", "coordinate": {"PRD_DE": y, "ITM_NM": i}}
                                                       for t, y, i in facts]}}


def _codes(x, v):
    return [f["code"] for f in x[v]["flags"]]


def test_sex_and_universe():
    t = G.Tables(docs=TABLES)
    x = G.audit_record(rec("R1", ["TX_M"], "진안군의 한국 국적을 취득한 자의 수가 2010년에 비해 2013년에 얼마나 변화했는가?",
                           "진안군에서 한국 국적을 취득한 사람 수는 2010년과 비교해 2013년에 어떻게 달라졌나요?",
                           [("TX_M", "2010", "한국국적을 취득한 자"), ("TX_M", "2013", "한국국적을 취득한 자")]), t)
    assert _codes(x, "O") == ["SEX"] and x["O"]["alt"] == ["TX_T"] and x["P"]["alt"] == ["TX_T"] and not x["P"]["exclude"]
    x = G.audit_record(rec("R2", ["TX_M"], "진안군 남자 귀화자 수는?", "진안군 남성 귀화자는 몇 명?", [("TX_M", "2010", "한국국적을 취득한 자")]), t)
    assert x["O"]["flags"] == [] and x["P"]["flags"] == []
    x = G.audit_record(rec("R3", ["IN15"], "1985년 행정구역/성/연령/혼인상태별 인구(15세 이상) 안동군 인구는?",
                           "1985년 안동군 인구 천 명당 주택은?", [("IN15", "1985", "인구")]), t)
    assert x["O"]["flags"] == [] and _codes(x, "P") == ["UNIVERSE"] and x["P"]["exclude"]


def test_p_drift_review():
    t = G.Tables(docs=TABLES)
    o = "2018년의 당해연도 혼인 비율 중 생년 1983년에 비해 2016년의 비율은 몇 %p 감소했는가?"
    facts = [("A004", "2016", "비율"), ("A004", "2018", "비율")]
    x = G.audit_record(rec("R4", ["A004"], o, "1983년생 사람들의 결혼 비율이 2016년과 비교해 2018년에는 얼마나 줄었나요?", facts), t)
    f = x["P"]["flags"][0]
    assert f["code"] == "P_DRIFT" and f["review"] and f["alt"] == ["A001"] and "당해" in f["lost"]   # 'OLD' 는 2016 이 없음
    assert x["O"]["flags"] == []
    x = G.audit_record(rec("R5", ["A004"], o, "1983년생이 당해연도에 혼인한 비율은 2016년보다 2018년에 얼마나 줄었나요?", facts), t)
    assert x["P"]["flags"] == []
    x = G.audit_record(rec("R6", ["A004"], o, "1983년생 누적 결혼 비율은 2016년보다 2018년에 얼마나 줄었나요?", facts), t)
    assert x["P"]["flags"] == []                               # P 가 형제 쪽 말을 직접 씀 → 다른 표를 물은 것


def test_load_audit_human(tmp_path):
    t = G.Tables(docs=TABLES)
    o = "2018년의 당해연도 혼인 비율 중 생년 1983년에 비해 2016년의 비율은 몇 %p 감소했는가?"
    rows = [G.audit_record(rec("R4", ["A004"], o, "1983년생 사람들의 결혼 비율이 2016년과 비교해 2018년에는 얼마나 줄었나요?",
                               [("A004", "2016", "비율")]), t),
            G.audit_record(rec("R1", ["TX_M"], "진안군 귀화자 수는?", "진안군 귀화자는?", [("TX_M", "2010", "한국국적을 취득한 자")]), t)]
    f = tmp_path / "gold_audit.jsonl"

    def write(rs):
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs), encoding="utf-8")
        return G.load_audit(f)
    a = write(rows)
    assert a[("R4", "P")]["alt"] == [] and a[("R4", "P")]["pending"] == ["P_DRIFT"]   # 검토 제안은 기본 반영 안 함
    assert a[("R1", "O")]["alt"] == ["TX_T"] and not a[("R1", "O")]["exclude"]
    rows[0]["human"], rows[1]["human"] = {"P": "accept"}, {"O": "strict", "P": "exclude"}
    a = write(rows)
    assert a[("R4", "P")]["alt"] == ["A001"] and a[("R4", "P")]["pending"] == []
    assert a[("R1", "O")]["alt"] == [] and not a[("R1", "O")]["exclude"] and a[("R1", "P")]["exclude"]
    md = G.report_md(rows, "g.jsonl")
    assert "| P | P_DRIFT | 1 |" in md and "human" in md


def test_main_keeps_human(env, tmp_path):  # noqa: F811
    golden = tmp_path / "synthetic_gold_dataset.jsonl"
    r = rec("SG-1", ["DT_POP_M"], "2024년 서울특별시 인구는?", "2024년 서울 사람 수는?", [("DT_POP_M", "2024", "인구")])
    golden.write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")
    out = G.main(["--golden", str(golden), "--bundle", str(env["bundle"])])
    x = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert _codes(x, "O") == ["SEX"] and x["O"]["alt"] == ["DT_POP_T"] and out.with_suffix(".md").exists()
    x["human"] = {"O": "strict"}
    out.write_text(json.dumps(x, ensure_ascii=False) + "\n", encoding="utf-8")
    G.main(["--golden", str(golden), "--bundle", str(env["bundle"])])
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0])["human"] == {"O": "strict"}


def test_compare_audit_metrics(monkeypatch):
    from backend.rag.search.engine import TableSearch
    from backend.rag.search.tuning import compare as CMP
    from tests.test_okf_search import Corpus
    monkeypatch.setattr(CMP, "get_search_for", lambda d, l, s: TableSearch(Corpus(), facets_source="meta", llm_rerank=False,
                                                                           settings=s))
    q = "2020년 세종 모+미혼자녀 가구 수"
    base = {"record_id": "R", "hop_type": "", "reasoning_type": "", "subtype": "", "survey": "", "difficulty": "",
            "question": q, "gold": ["DT_1GA0002"], "groups": {"G1": ["DT_1GA0002"]}, "alt_groups": {}}
    rows = [{**base, "qid": "R-O", "variant": "O", "audit": {"alt": ["DT_1JC1516", "DT_1JC1517"], "exclude": False, "flags": ["SEX"]}},
            {**base, "qid": "R-P", "variant": "P", "audit": {"alt": [], "exclude": True, "flags": ["UNIVERSE"]}}]
    analysis = {r["qid"]: [{"unit": "main", "text": q, "search_query": q, "filters": None, "status": "ok"}] for r in rows}
    per, _ = CMP.run(rows, analysis, ["none"], False, 5, 20, log=lambda *_: None)
    o, p = per
    assert o["rank_aud"] == 1 and o["hit@1_aud"] == 1 and (o["rank"] or 99) > 1 and o["audit_flags"] == "SEX"
    assert p["audit_excluded"] == 1 and p.get("mrr_aud") is None and p["rank"] == o["rank"]   # 엄격 지표는 그대로
    agg = CMP.aggregate(per)
    assert agg["n_aud"] == 1 and agg["hit@1_aud"] == 1.0 and agg["n"] == 2
    table, fails, wins = CMP.summarize(per)
    meta = {"created": "-", "golden": "g", "n_rows": 2, "variants": ["O", "P"], "analyze": "analyze", "analysis_status": {},
            "top_k": 5, "pool": 20, "dense": ["none"], "configs": {}, "audit": "a.jsonl"}
    md = CMP.report_md(meta, table, fails, wins, per)
    assert "## 검토 반영" in md and "SEX 1 · UNIVERSE 1" in md and "평가에서 뺀 변형 1" in md


def test_alt_gold_total_item_is_loose_automatically():
    from backend.rag.search.tuning.alt_gold import Judge

    class Idx:
        v: ClassVar = {"name": ["안동군", "계", "주택수"], "std": [None] * 3, "slot": ["지역", "지표", "지표"],
                       "kind": ["dim", "item", "item"], "tbl_id": ["JU8504", "JU8504", "JU0001"]}
        tables: ClassVar = {
            "JU8504": {"tbl_nm": "행정구역/주택의종류/주택의편익시설별 주택", "survey_nm": "주택총조사", "periods": {"Y": ["1985"]},
                       "dims": [{"obj_nm": "행정구역별", "kind": "regions", "level": 1}]},
            "JU0001": {"tbl_nm": "총조사 주택총괄", "survey_nm": "주택총조사", "periods": {"Y": ["1985"]},
                       "dims": [{"obj_nm": "행정구역별", "kind": "regions", "level": 1}]},
        }

        def table(self, t):
            return self.tables.get(t)

    rows = {"JU0001": [{"PRD_DE": "1985", "C1_NM": "전국", "ITM_NM": "주택수", "UNIT_NM": "호", "DT": "4719671"}]}
    j = Judge(Idx(), log=lambda *a: None)          # --loose-items 없이
    j._rows = lambda t, periods: rows.get(t, [])
    r = {"dataset_id": "SG-H", "answerability_type": "ANSWERABLE",
         "retrieval_eval": {"golden_table_ids": ["JU8504"], "required_evidence_groups": {"R1": {"required_fact_ids": ["F1"]}}},
         "generation_eval": {"intermediate_facts": [{"fact_id": "F1", "parent_table_id": "101_JU8504", "item_name": "계",
                                                     "coordinate_labels": {"행정구역별": "전국"},
                                                     "coordinate": {"PRD_DE": "1985", "ITM_NM": "계", "normalized_value": "4719671",
                                                                    "normalized_unit": "호"}, "value": {"display_digits": 0}}]}}
    alts = j.judge(r)["groups"]["R1"]["alternatives"]
    assert [(a["tbl_id"], a["match"], a.get("why")) for a in alts] == [("JU0001", "loose", "total_item")]
    assert Decimal(4719671) == Decimal(rows["JU0001"][0]["DT"])
