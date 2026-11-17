"""
파이프라인 플러그인 — 기본 파이프라인 + 개인 폴더(private/pipelines/*.py)의 파이프라인을 이름으로 고른다

  private/pipelines/<이름>.py
    def run_chat(question, today=None, top_k=None, n_views=None, **kw) -> dict   # ChatResponse 와 같은 키 권장
    DESCRIPTION = "한 줄 설명"   (선택)

  POST /api/v1/chat {"pipeline": "<이름>"} 로 호출 (응답 모양은 검사하지 않고 그대로 돌려줌)
  개인 폴더 위치: config.PRIVATE_DIR — 없으면 기본만
"""
import importlib
import importlib.util
import sys

from backend.core.config import PRIVATE_DIR

DEFAULT = "default"
_loaded = {}


def _private_files():
    d = PRIVATE_DIR / "pipelines" if PRIVATE_DIR else None
    return sorted(f for f in d.glob("*.py") if not f.name.startswith("_")) if d and d.is_dir() else []


def available():
    """{이름: 설명}"""
    out = {DEFAULT: "기본: 질의 분석 → 표 검색 → View·충돌 판정 → 답변  (backend.agent.pipeline)"}
    for f in _private_files():
        try:
            out[f.stem] = getattr(_load(f.stem), "DESCRIPTION", "") or f"private/pipelines/{f.name}"
        except Exception as e:  # noqa: BLE001  (불러오기 실패해도 목록은 보여 줌)
            out[f.stem] = f"(불러오기 실패: {e.__class__.__name__}: {str(e)[:120]})"
    return out


def _load(name):
    if name in _loaded:
        return _loaded[name]
    f = next((x for x in _private_files() if x.stem == name), None)
    if f is None:
        raise KeyError(f"파이프라인 '{name}' 없음. 사용 가능: {list(available())}  (개인 폴더: {PRIVATE_DIR})")
    if str(PRIVATE_DIR) not in sys.path:
        sys.path.insert(0, str(PRIVATE_DIR))  # private 안의 패키지(예: stat_rag)를 import 할 수 있게
    spec = importlib.util.spec_from_file_location(f"private_pipeline_{name}", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "run_chat", None)):
        raise TypeError(f"{f} 에 run_chat(question, today, top_k, n_views, **kw) 가 없습니다")
    _loaded[name] = mod
    return mod


def get(name=None):
    """이름 → run_chat 함수"""
    if not name or name == DEFAULT:
        from backend.agent.pipeline import run_chat
        return run_chat
    return _load(name).run_chat
