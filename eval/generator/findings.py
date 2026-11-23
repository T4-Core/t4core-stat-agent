"""점검 결과 한 건. 판정(verdict.py)은 Finding 목록만 보고 정한다"""
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Stage = Literal["scope", "stage1", "stage2", "metric", "info"]
Module = Literal["M1+R", "M2", "M3", "M5", "M6", "QA", "data", "E2E"]


@dataclass
class Finding:
    code: str                         # 예: value_mismatch, unit_mismatch, silent_omission
    stage: Stage                      # stage1 실패 = 미달, stage2 = 완전성, metric = 지표용 기록
    module: Module                    # First Failure 후보
    ok: bool | None                   # None = 판정 보류(수동)
    message: str = ""
    sub_key: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    source: Literal["schema", "adapter", "text", "manual"] = "schema"

    def as_dict(self) -> dict:
        return asdict(self)


def failed(fs: list[Finding], stage: str | None = None) -> list[Finding]:
    return [f for f in fs if f.ok is False and (stage is None or f.stage == stage)]


def unresolved(fs: list[Finding]) -> list[Finding]:
    return [f for f in fs if f.ok is None]
