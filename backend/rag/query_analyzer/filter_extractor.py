"""[NEW] 구조안의 filter_extractor.py — 의도(intent)·지역/연도 등 메타 필터 추출 진입점

  extract.py   2-2 코드(정규식 + rule_dict.json)로 확실한 값: 시점·지역·성별·연령·국적·출생연도   rule_extract
  validate.py  2-4 HCX 슬롯 검증·보정 (의도는 정해진 9개 값만, 원 질문은 목록)                    validate_slots
  bundle.py    to_filters: 검증된 슬롯 → filters (값 있는 슬롯만, 의도 제외)
  adapter.py   filters → View 모듈 Filters (시점 int, 연령 {from,to}, 의도 포함)  to_view_bundle
"""
from .adapter import to_view_bundle, to_view_filters  # noqa: F401
from .bundle import to_filters  # noqa: F401
from .extract import norm_age, norm_sido, rule_extract  # noqa: F401
from .slots import INTENTS, SLOT_KEYS  # noqa: F401
from .validate import validate_slots  # noqa: F401
