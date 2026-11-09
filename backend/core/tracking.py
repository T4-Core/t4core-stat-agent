"""
[NEW v4] 단계별 실행 기록 — 파라미터(모수)·입력 요약·출력·소요 시간을 남겨 평가 파이프라인이 그대로 읽게 함

  tr = Tracer(run_name="analyze")                       # 저장하지 않으려면 save=False (기본: 저장 안 함)
  with tr.step("lexicon", fuzzy_cutoff=0.8) as s:       # params 는 키워드 인자로
      hits = lookup(...)
      s.output = {"n_hits": len(hits)}                  # 출력 요약 (JSON 가능 값)
      s.notes.append("…")
  tr.traces        → [StepTrace, …]  (API 응답 trace 에 그대로)
  tr.save()        → RUNS_DIR/<run_id>/params.json · steps.jsonl

노트북에서는 단계 함수를 직접 부르고 Tracer 없이도 됨 (모든 단계 함수는 tracer=None 을 받음)
"""
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class StepTrace:
    step: str                                     # 단계 이름 (예: "1-2 lexicon")
    params: dict[str, Any] = field(default_factory=dict)
    output: Any = None                            # 출력 요약
    notes: list[str] = field(default_factory=list)
    seconds: float = 0.0
    error: str | None = None

    def as_dict(self):
        return asdict(self)


class Tracer:
    def __init__(self, run_name="run", params=None, save=False, runs_dir=None):
        self.run_id = f"{datetime.now():%Y%m%d_%H%M%S}_{run_name}_{uuid.uuid4().hex[:6]}"
        self.params = dict(params or {})          # 실행 전체 설정 (settings 등)
        self.traces: list[StepTrace] = []
        self._save = save
        self._dir = Path(runs_dir) if runs_dir else None

    @contextmanager
    def step(self, name, **params):
        s = StepTrace(step=name, params=_jsonable(params))
        t0 = time.time()
        try:
            yield s
        except Exception as e:  # noqa: BLE001  (기록 후 다시 올림)
            s.error = f"{e.__class__.__name__}: {str(e)[:300]}"
            raise
        finally:
            s.seconds = round(time.time() - t0, 3)
            s.output = _jsonable(s.output)
            self.traces.append(s)

    def as_list(self):
        return [t.as_dict() for t in self.traces]

    def save(self, result=None):
        if not self._save:
            return None
        from backend.core.config import RUNS_DIR
        d = (self._dir or RUNS_DIR) / self.run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "params.json").write_text(json.dumps(_jsonable(self.params), ensure_ascii=False, indent=1), encoding="utf-8")
        with (d / "steps.jsonl").open("w", encoding="utf-8") as f:
            for t in self.traces:
                f.write(json.dumps(t.as_dict(), ensure_ascii=False, default=str) + "\n")
        if result is not None:
            (d / "result.json").write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=1, default=str),
                                           encoding="utf-8")
        return d


@contextmanager
def maybe_step(tracer, name, **params):
    """tracer 가 None 이면 기록 없이 실행 (노트북에서 단계 함수를 단독으로 부를 때)"""
    if tracer is None:
        yield StepTrace(step=name, params=params)
    else:
        with tracer.step(name, **params) as s:
            yield s


def _jsonable(x):
    try:
        json.dumps(x, ensure_ascii=False)
        return x
    except TypeError:
        if hasattr(x, "model_dump"):
            return x.model_dump()
        if hasattr(x, "__dataclass_fields__"):
            return asdict(x)
        if isinstance(x, dict):
            return {str(k): _jsonable(v) for k, v in x.items()}
        if isinstance(x, (list, tuple, set)):
            return [_jsonable(v) for v in x]
        return str(x)
