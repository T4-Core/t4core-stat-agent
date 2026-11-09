"""
[NEW v4] 검색 실험실 API — 검색 구성(configs/retrieval/*.yaml)을 바꿔 가며 같은 질의를 나란히 비교

  GET  /api/v1/retrieval-lab/configs                 구성 목록 (설명·필요 패키지·설치 여부)
  GET  /api/v1/retrieval-lab/configs/{name}          구성 펼친 모양 (extends 반영)
  POST /api/v1/retrieval-lab/search                  질의 하나 × 구성 하나 → 후보 + 단계별 순위·점수 + trace
  POST /api/v1/retrieval-lab/compare                 질의 묶음 × 구성 여러 개 → 나란히 비교 (+ 보고서·판정표 파일)
  GET  /api/v1/retrieval-lab/runs/{run_id}/report    비교 보고서 HTML (브라우저로 열기)
  GET  /api/v1/retrieval-lab/runs/{run_id}/review.csv  사람 판정표 (label 칸 채우기)
  POST /api/v1/retrieval-lab/runs/{run_id}/score     판정(JSON 또는 채운 review.csv) → 구성별 P@k·MRR·nDCG

정답셋 없이 쓰는 것이 기본: 보고서를 보고 판정표에 관련도(2/1/0)를 적으면 그걸로 점수를 낸다.
HCX 답변 호출은 없음 (구성에 hcx_bge_m3 임베딩이 있으면 임베딩만 호출, 캐시)
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from backend.api.deps import guard
from backend.core.config import ROOT, STORAGE_DIR
from backend.schemas.retrieval_v4 import (CompareRequest, CompareResponse, ConfigSummary, LabSearchRequest,
                                          LabSearchResponse, ScoreRequest)

PREFIX = "/api/v1/retrieval-lab"
router = APIRouter(prefix=PREFIX, tags=["② Retrieval 검색 실험실 v4"])


def _cfg_arg(c):
    return c.model_dump(exclude_unset=True, exclude_none=True) if hasattr(c, "model_dump") else c   # 안 쓴 칸이 extends 를 덮지 않게


def _safe_source(src):
    """질의 출처가 파일 경로면 저장소·storage 안의 파일만"""
    if src in (None, "bundles", "golden", "examples"):
        return src
    p = Path(src)
    p = (p if p.is_absolute() else ROOT / p).resolve()
    if not any(str(p).startswith(str(Path(b).resolve())) for b in (ROOT, STORAGE_DIR)):
        raise HTTPException(400, f"질의 파일은 저장소 또는 storage 안에 있어야 합니다: {src}")
    if not p.exists():
        raise HTTPException(404, f"질의 파일 없음: {src}")
    return str(p)


@router.get("/configs", response_model=list[ConfigSummary], summary="검색 구성 목록")
def configs():
    """`missing` 이 있으면 그 패키지를 설치해야 실행됨 (예: sentence-transformers)"""
    from backend.rag.retrieval.factory import list_configs
    return list_configs()


@router.get("/configs/{name}", summary="구성 펼친 모양 (extends 반영)")
def config(name: str):
    from backend.rag.retrieval.factory import load_config
    with guard("검색 구성: "):
        return load_config(name)


@router.post("/search", response_model=LabSearchResponse, summary="질의 하나 × 구성 하나 → 후보 + 단계별 순위")
def search(body: LabSearchRequest):
    """- `config`(이름) 또는 `config_inline`(구성 전체) + `overrides`(점 경로)
    - `prep: resolve` 면 `views.run_query` 처럼 지역·시점 단어를 빼고 지표를 더한 문장으로 검색
    - `hits[].stages` = 단계(검색기·재정렬)마다 몇 위였는지 → 어느 단계가 순위를 바꿨는지"""
    from backend.core.tracking import Tracer
    from backend.rag.retrieval.factory import get_pipeline
    over = dict(body.overrides or {})
    if body.prep:
        over["query.prep"] = body.prep
    with guard("검색 실험: "):
        p = get_pipeline(_cfg_arg(body.config_inline) if body.config_inline else (body.config or "baseline"), over)
        r = p.search(body.query, body.filters, body.top_k, tracer=Tracer(run_name="lab") if body.trace else None)
        info = p.info()
        info.pop("config", None)
        return {**r, "pipeline": info}


@router.post("/compare", response_model=CompareResponse, summary="질의 묶음 × 구성 여러 개 → 나란히 비교")
def compare(body: CompareRequest):
    """- 질의: `source`(bundles = 재작성 80문항 결과, HCX 호출 없음 | golden | examples | 파일) 또는 `queries`
    - 응답 `report_url` 을 브라우저로 열면 구성별 상위 k 가 나란히 (같은 표 = 같은 색)
    - `review_url` 판정표의 label 칸을 채워 `POST …/runs/{run_id}/score`
    - 모델·패키지가 없는 구성은 `configs[].error` 에만 남고 나머지는 비교됨"""
    from backend.rag.retrieval import lab
    with guard("검색 비교: "):
        if body.queries:
            qs = lab.load_queries([q.model_dump() for q in body.queries], analyze=body.analyze, today=body.today)
        else:
            qs = lab.load_queries(_safe_source(body.source), limit=body.limit, analyze=body.analyze, today=body.today)
        res = lab.run_compare(qs, [_cfg_arg(c) for c in body.configs], top_k=body.top_k, reference=body.reference,
                              save=body.save, blind=body.blind, trace=body.trace)
        if body.save:
            res["report_url"] = f"{PREFIX}/runs/{res['run_id']}/report"
            res["review_url"] = f"{PREFIX}/runs/{res['run_id']}/review.csv"
        return res


def _run_file(run_id, name):
    from backend.rag.retrieval.lab import run_dir
    try:
        p = run_dir(run_id) / name
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not p.exists():
        raise HTTPException(404, f"없음: {run_id}/{name}")
    return p


@router.get("/runs/{run_id}/report", response_class=HTMLResponse, summary="비교 보고서 (HTML)")
def report(run_id: str):
    return HTMLResponse(_run_file(run_id, "report.html").read_text(encoding="utf-8"))


@router.get("/runs/{run_id}/review.csv", summary="사람 판정표 (CSV, 엑셀에서 열림)")
def review_csv(run_id: str):
    return FileResponse(_run_file(run_id, "review.csv"), media_type="text/csv", filename=f"review_{run_id}.csv")


@router.post("/runs/{run_id}/score", summary="판정 → 구성별 P@k·MRR·nDCG·hit@1")
def score(run_id: str, body: ScoreRequest):
    """`judgments` 를 비우면 `storage/runs/<run_id>/review.csv` 의 label 칸(2/1/0 또는 O/△/X)을 읽음.
    같은 (질의, 표) 판정은 어느 구성이 냈든 공통으로 적용"""
    from backend.rag.retrieval.lab import score_review
    _run_file(run_id, "params.json")
    with guard("판정 점수: "):
        return score_review(run_id, [j.model_dump() for j in body.judgments] or None, k=body.k)
