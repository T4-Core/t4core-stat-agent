"""개발(dev) / 보류(heldout) 나누기 — 일상어 사전·개념 카탈로그를 정답에서 캐낼 때 쓰는 문항과
평가하는 문항을 가른다. 같은 레코드의 O·P 는 같은 쪽 (레코드 번호의 해시로 정함 — 실행마다 같음)

  split_of("SG-471627522189")  → "dev" | "heldout"
  python -m backend.rag.search.tuning.compare --golden … --split heldout     # 보류 문항만 평가
"""
import hashlib

HELDOUT = 0.2
SEED = "t4core-1116"


def split_of(record_id, heldout=HELDOUT, seed=SEED) -> str:
    h = int(hashlib.md5(f"{seed}:{record_id}".encode("utf-8")).hexdigest()[:8], 16)
    return "heldout" if (h % 1000) < heldout * 1000 else "dev"
