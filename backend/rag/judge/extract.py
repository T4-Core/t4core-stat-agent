"""
[NEW] Record(View) → ViewContents — "이 View 에 실제로 무엇이 담겼는가" 를 비교하기 쉬운 모양으로 정리

  입력  Record (dict 또는 backend.schemas.record.Record)
          table.columns = ["시점", <분류 열 …>, "항목", "값"]   ← build_view 가 붙이는 열 이름
          table.rows    = [["2023", "대구광역시", "남자", "20 - 24세", "인구", 61234], …]
  출력  ViewContents
          years {2023} · dims [지역 {대구광역시}, 성별 {남자}, 연령 [(20, 24)]] · items [인구] · n_points · is_empty

  분류 종류(kind)·지역 표준화·연령 해석은 View 를 만든 normalize.py 의 함수를 그대로 쓴다.
  → View 라벨을 만든 규칙과 '같은 규칙' 으로 다시 읽어야 판정이 어긋나지 않는다.
  메타 프로필 파일을 읽지 않는 순수 함수라서, 테스트에 데이터 파일이 필요 없다.
"""
import re
from dataclasses import dataclass, field

from backend.core.utils import norm_space
from backend.rag.ingestion.normalize import (STRONG_TOTAL, URBAN_RURAL, level_kind, level_role, parse_age,
                                             std_geo_name)

PERIOD_COL, ITEM_COL, VALUE_COL = "시점", "항목", "값"
FIXED_COLS = {PERIOD_COL, ITEM_COL, VALUE_COL}

# 시점 라벨 맨 앞 4자리 연도: "2023" "2023.01"(월) "2023 1분기" "2023 상반기" 모두 2023
YEAR_RE = re.compile(r"^\s*((?:19|20)\d{2})")


@dataclass
class DimContents:
    """분류 열 하나 (시점·항목·값을 뺀 나머지 열) 에 담긴 것"""
    column: str                         # 열 이름 그대로 (예: "행정구역(시군구)별")
    kind: str                           # 분류 종류: regions | ages | sex | nationality | cohort | scenario | other
    #   ⚠ level_kind 는 '특성별' 처럼 이름에 '성별' 글자가 든 열을 라벨과 관계없이 sex 로 분류한다
    #     (예: '특성별' + ['1인가구', '2인가구'] → sex). View 와 같은 규칙을 유지하려고 여기서는 고치지 않고,
    #     성별 판정은 slots.py 에서 라벨(남자·여자 …)로 다시 확인한다
    role: str = ""                      # 누구의 분류인가 ("가구주의 연령별" → "가구주"). 본인이면 ""
    labels: list[str] = field(default_factory=list)   # 표에 나온 값 (중복 제거, 처음 나온 순서 유지)
    std: set[str] = field(default_factory=set)        # 비교용 값 (합계 라벨 제외). 지역은 표준 이름으로 바꿈
    age_ranges: list[tuple[int, int | None]] = field(default_factory=list)   # 연령 열만: [(20, 24), (65, None)]
    has_total: bool = False             # "계"·"전국" 같은 합계 라벨이 들어 있는가
    label_points: dict[str, int] = field(default_factory=dict)
    #   라벨 → 그 라벨 행 중 값이 있는 칸 수. 예) {"계": 1, "20 - 24세": 1, "25 - 29세": 0}
    #   "라벨이 있다" 와 "값이 있다" 는 다른 정보다 → 0 이면 slots.py 가 "표에 있으나 값 없음(partial)" 으로 판정
    #   값 열이 없는 표는 빈 dict {} = "모름" (0 개와 구분)

@dataclass
class ViewContents:
    """View(Record) 하나에 실제로 담긴 조건 — slots.py 가 질문 슬롯과 비교할 재료"""
    record_id: str
    tbl_id: str
    prd_se: str | None                  # 수록 주기: Y(년) M(월) Q(분기) … 모르면 None
    years: set[int]                     # 표에 실제로 있는 연도
    period_labels: list[str]            # 시점 원본 라벨 ("2023.01" 등). 근거 문장(evidence)에 쓴다
    dims: list[DimContents]             # 분류 열들
    items: list[str]                    # 항목 이름들 (예: ["인구"], ["기대수명 - 남"])
    view_type: str                      # value | trend | breakdown (build_view 의 의도 → View 종류)
    n_points: int                       # 값이 들어 있는 칸 수
    is_empty: bool                      # 값이 하나도 없으면 True
    title: str = ""
    #   Record.lexical_text (표 이름·조사명·조건·항목·단위를 이어 붙인 문장).
    #   지표·대상이 항목에는 없고 표 이름에만 있는 경우를 slots.py 가 partial 로 구분할 때 쓴다
    year_points: dict[int, int] = field(default_factory=dict)
    #   연도 → 값이 있는 칸 수. 예) {2023: 2, 2024: 0}  ← 2024 행은 있지만 값이 모두 '-'(None)
    #   years 에는 2024 가 들어 있으므로, 둘을 함께 봐야 "요청 연도에 실제 값이 있는가" 를 알 수 있다
    #   기본값이 있는 필드는 dataclass 규칙상 기본값 없는 필드들 뒤에 와야 해서 맨 끝에 두었다

    def dims_of(self, kind: str) -> list[DimContents]:
        """특정 종류의 분류 열만 (예: dims_of("regions") → 지역 열들). 연령 열이 두 개인 표도 있어서 목록으로 돌려준다"""
        return [d for d in self.dims if d.kind == kind]


def _as_dict(record) -> dict:
    if hasattr(record, "model_dump"):            # pydantic 객체면 .model_dump() 로 dict 변환
        return record.model_dump(mode="json")   # mode="json" → Enum 도 "view" 같은 문자열로
    return dict(record)


def _unique(values) -> list[str]:
    return list(dict.fromkeys(str(v) for v in values if v is not None))


def is_total(label: str) -> bool:
    """합계 라벨인가 ("계", "전국", "합계" …). 공백 차이는 무시"""
    return norm_space(label) in STRONG_TOTAL


def region_std(label: str) -> str:
    """지역 라벨 → 표준 지역 이름.
    이름이 겹치는 코드는 정규화 때 상위 지역이 앞에 붙는다 (normalize.build_level_dims).
      "서울특별시 동부"  → 뒤가 동부·읍부·면부면 앞 단어가 지역 → "서울특별시"
      "부산광역시 중구"  → 그대로 (구 이름만으로는 어느 시의 중구인지 모르므로 앞을 떼지 않음)"""
    parts = norm_space(label).split(" ")
    if len(parts) == 2 and parts[1] in URBAN_RURAL:
        return std_geo_name(parts[0])
    return std_geo_name(label)


def _year_of(label) -> int | None:
    """시점 라벨 → 연도. 연도로 시작하지 않으면 None ("2023.01" → 2023, "1분기" → None)"""
    m = YEAR_RE.match(str(label))
    return int(m.group(1)) if m else None


def _count_points(rows, key_idx: int, value_idx: int, key=str) -> dict:
    """행을 한 번 돌면서 '열 key_idx 의 라벨별로 값이 있는 칸 수' 를 센다.
      key   : 라벨을 무엇으로 묶을지 정하는 함수. 기본 str (라벨 그대로), 연도는 _year_of 를 넘긴다
              → 함수를 인자로 넘기는 것. 자바의 Function<Object, K> 람다를 넘기는 것과 같다
    예) 행 [["2023", "20 - 24세", 61234], ["2023", "25 - 29세", None]], key_idx=1, value_idx=2
        → {"20 - 24세": 1, "25 - 29세": 0}   ← 값이 None 이어도 라벨은 0 으로 남긴다 (0 과 '없음' 을 구분)"""
    counts = {}
    for row in rows:
        if key_idx >= len(row) or value_idx >= len(row) or row[key_idx] is None:
            continue                                   # 깨진 행·라벨 없는 행은 건너뜀
        k = key(row[key_idx])
        if k is None:                                  # 연도로 읽을 수 없는 시점 라벨 등
            continue
        # counts.get(k, 0): 처음 보는 라벨이면 0 에서 시작 (자바 Map.getOrDefault 와 같음)
        # (row[value_idx] is not None) 은 True/False → 더하면 1/0
        counts[k] = counts.get(k, 0) + (row[value_idx] is not None)
    return counts


def _years_from_metadata(meta: dict) -> set[int]:
    """행이 없을 때(빈 View) 연도 대신 쓰기: metadata.prd_from ~ prd_to 범위"""
    try:
        lo, hi = int(str(meta.get("prd_from"))[:4]), int(str(meta.get("prd_to"))[:4])
    except (TypeError, ValueError):   # 값이 없거나("None") 숫자가 아니면 → 모른다
        return set()
    return set(range(lo, hi + 1))     # range 는 끝을 포함하지 않으므로 +1


def extract_contents(record) -> ViewContents:
    """Record 하나 → ViewContents.  예외를 내지 않는다: 모르는 것은 빈 값으로 둔다 (판정은 slots.py 가 unknown 으로)"""
    r = _as_dict(record)
    table = r.get("table") or {}
    meta = r.get("metadata") or {}
    source = r.get("source") or {}
    columns = list(table.get("columns") or [])
    rows = table.get("rows") or []

    col_index = {name: i for i, name in enumerate(columns)}

    def column_values(name: str) -> list:
        """열 이름 하나의 값을 모든 행에서 꺼낸다. 열이 없으면 []"""
        i = col_index.get(name)
        if i is None:
            return []
        return [row[i] for row in rows if i < len(row)]   # 행 길이가 짧은 깨진 행은 건너뜀

    # 값 열의 위치. 없으면 None → 라벨별 값 개수는 "모름"({}) 으로 둔다
    value_idx = col_index.get(VALUE_COL)

    period_labels = _unique(column_values(PERIOD_COL))
    years = {y for lb in period_labels if (y := _year_of(lb)) is not None}

    if not years:
        years = _years_from_metadata(meta)

    # 연도별 값 개수: 시점 열과 값 열이 둘 다 있을 때만 셀 수 있다
    year_points = {}
    if PERIOD_COL in col_index and value_idx is not None:
        year_points = _count_points(rows, col_index[PERIOD_COL], value_idx, key=_year_of)

    dims = []
    for name in columns:
        if name in FIXED_COLS:
            continue
        labels = _unique(column_values(name))
        kind = level_kind(name, labels)            # 열 이름 + 라벨로 종류 판정 (정규화와 같은 규칙)
        values = [lb for lb in labels if not is_total(lb)]
        dim = DimContents(column=name, kind=kind, role=level_role(name), labels=labels,
                          has_total=len(values) < len(labels))   # 합계 라벨을 뺐더니 줄었다 = 합계가 있었다
        if kind == "regions":
            dim.std = {region_std(lb) for lb in values}
        else:
            dim.std = {norm_space(lb) for lb in values}
        if kind == "ages":
            for lb in values:
                lo, hi = parse_age(lb)
                if lo is not None:                 # "미상" 처럼 나이로 읽을 수 없는 라벨은 건너뜀
                    dim.age_ranges.append((lo, hi))
        if value_idx is not None:
            dim.label_points = _count_points(rows, col_index[name], value_idx)
        dims.append(dim)

    items = _unique(column_values(ITEM_COL)) or [str(i) for i in meta.get("items") or []]

    if VALUE_COL in col_index:
        n_points = sum(v is not None for v in column_values(VALUE_COL))   # True 는 1, False 는 0 으로 더해진다
    else:
        n_points = int(meta.get("n_points") or 0)

    return ViewContents(
        record_id=str(r.get("id") or ""),
        tbl_id=str(source.get("tbl_id") or ""),
        prd_se=meta.get("prd_se") or source.get("prd_se"),
        years=years,
        period_labels=period_labels,
        dims=dims,
        items=items,
        view_type=str(meta.get("view_type") or "value"),
        n_points=n_points,
        is_empty=n_points == 0,
        title=str(r.get("lexical_text") or ""),
        year_points=year_points,
    )
