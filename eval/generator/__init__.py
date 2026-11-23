"""[NEW 11-23 KOS-40] Generator(모듈 2 · 3 · 5 · 6 + QA) 평가 도구

평가 기준: eval/generator/docs/criteria.md · 방법: docs/method.md · 계획: docs/plans/2026-11-20-generator-평가-체계.md
"""
from pathlib import Path

from backend.core.config import ROOT

PKG_DIR = ROOT / "eval" / "generator"
QUESTIONS_DIR = PKG_DIR / "questions"
ORACLE_DIR = PKG_DIR / "oracle"


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)
