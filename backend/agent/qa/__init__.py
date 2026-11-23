"""Generator QA — 에이전트(backend/agent) 입력과 모듈 2→3→5→6 사이 값의 형식(필드·타입·허용값)을 검사하고 대응한다

  run_modules_with_qa(vs, ...)   QA 를 끼운 run_modules (qa_runner.py)
  run_chat(question, ...)        질문 → ①·② (Retriever) → QA 를 끼운 Generator (qa_runner.py, 플러그인 입구:
                                 private/pipelines/qa.py → POST /api/v1/chat {"pipeline": "qa"})

설계: qa 설계.md
import: from backend.agent.qa import run_modules_with_qa
이 패키지 안에서는 상대 import 만 쓴다 → 폴더를 통째로 옮겨도 안쪽은 고칠 필요가 없다.
"""


def run_modules_with_qa(*args, **kwargs):
    from .qa_runner import run_modules_with_qa as _run
    return _run(*args, **kwargs)


def run_chat(*args, **kwargs):
    from .qa_runner import run_chat as _run
    return _run(*args, **kwargs)


__all__ = ["run_modules_with_qa", "run_chat"]
