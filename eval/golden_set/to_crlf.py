# to_crlf.py : 파일 내용은 그대로 두고 줄바꿈(LF)만 CRLF로 변환
from pathlib import Path

FILES = [
    "kosis_query_debug.ipynb",
    "kosis_fast_human_review_accum.ipynb",
]

for name in FILES:
    p = Path(name)
    raw = p.read_bytes()                       # 바이트 그대로 읽기 (인코딩 변환 없음)
    lf_only = raw.replace(b"\r\n", b"\n")      # 이미 CRLF인 줄이 CRCRLF가 되지 않도록 먼저 정규화
    crlf = lf_only.replace(b"\n", b"\r\n")     # 모든 LF → CRLF
    p.write_bytes(crlf)

    # 검증: 줄바꿈을 제외한 내용이 원본과 완전히 같은지 확인
    assert crlf.replace(b"\r\n", b"\n") == lf_only, f"{name}: 내용 불일치!"
    print(f"✅ {name}: {crlf.count(b'\r\n')}줄 CRLF 변환 완료 (내용 동일 검증 통과)")