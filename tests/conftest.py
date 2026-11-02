import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent           # 저장소 루트
# [CHANGED] 이전: ROOT = Path(__file__).resolve().parent.parent  (Rewritten_fastapi) — 'rewriter' 패키지를 찾기 위함
sys.path.insert(0, str(ROOT))
