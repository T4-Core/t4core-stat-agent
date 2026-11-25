"""[NEW 11-23 KOS-40] Generator(모듈 2 · 3 · 5 · 6 + QA) 평가 도구

평가 기준: eval/generator/docs/criteria.md · 방법: eval/generator/docs/method.md
"""
from pathlib import Path

from backend.core.config import ROOT

PKG_DIR = ROOT / "eval" / "generator"
QUESTIONS_DIR = PKG_DIR / "questions"
ORACLE_DIR = PKG_DIR / "oracle"
# [NEW] 판정 규칙 버전. 실행 기록(run.py record · manifest)에 남기고, 새 규칙은 이 버전 이상인 실행에만 적용한다
#   1 = 필드 없는 이전 실행, 2 = 차트 구조 판정(checks/chart_structure.py ①~④) 추가,
#   3 = 차트-답변 일관성(⑤a chart_answer_consistent) · 차트 금지 위반(⑤b chart_forbidden_drawn) 추가. 과거 실행은 다시 판정하지 않는다
JUDGE_RULES = 3
CHART_STRUCTURE_RULES = 2        # ①~④를 적용하는 최소 버전
CHART_CONSISTENCY_RULES = 3      # ⑤를 적용하는 최소 버전


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)
