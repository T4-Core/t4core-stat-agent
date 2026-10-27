# profiling/

KOSIS 데이터와 베이스라인 RAG(`kosis_*.py`)의 한계를 진단하고 평가하는 코드. 베이스라인 파일은 수정하지 않고 가져다 쓰기만 한다.

## 공통
| 파일 | 역할 |
|---|---|
| `config.py` | 경로, 담당 범위, 임계값을 한곳에서 관리 |
| `io_utils.py` | DuckDB 연결, raw CSV 읽기, 표별 결과 캐시, 결과 저장 |
| `baseline.py` | 베이스라인(`kosis_views.py`)의 메타 해석·파일명 규칙을 가져오는 어댑터 |

## 데이터 진단 (LLM 호출 없음)
| 파일 | 역할 |
|---|---|
| `check_records.py` | `rag_views` 결과(tables/views)가 RAG에 쓸 수 있는 상태인지 검사 (8개 항목) |
| `check_facts.py` | 뷰의 facts 수치를 raw에서 다시 계산해 대조 (소계 혼입, 순위, %p 표기 등) |
| `diagnose.py` | 질문 조건 무시, 반올림, 단위 혼재, BM25 형태소 어긋남 등 D1~D6 한계를 표 전체 규모로 측정 |
| `checks/` | 진단 체크 모음용 패키지 (현재는 비어 있음) |

## 평가
| 파일 | 역할 |
|---|---|
| `golden/build_gold.py` | 골든셋 질문의 정답을 raw CSV에서 직접 계산해 채움 |
| `e2e_eval.py` | 질문 → 답변 전체를 돌리고 실패 지점(검색 / 문맥 / 답변)을 판정 |
| `criteria.py` | 팀 평가 기준 C1~C5 채점기 |
| `test_criteria.py` | `criteria.py` 채점기의 회귀 테스트 |

## 개선 실험 (베이스라인에 끼워 넣는 방식)
| 파일 | 역할 |
|---|---|
| `conditions_v2.py` | `apply_conditions` 개선판. 지역·성별·연도 외의 분류 조건도 처리 |
| `context_v2.py` | 질문 조건에 맞춰 변화량·순위 등을 코드로 계산해 LLM 문맥에 넣는 개선판 |

## 실행
프로젝트 루트(`t4core-stat-agent/`)에서 `python -m profiling.<모듈명>`으로 실행한다.
