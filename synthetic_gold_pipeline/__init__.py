"""KOSIS Multi-View Synthetic Golden Set 생성 파이프라인.

기존 RAG 파이프라인(backend/, eval/ ...)과 독립적으로 동작한다.
기존 저장소의 데이터(storage/kosis_data)는 읽기 전용으로만 사용하고,
모든 산출물은 synthetic_gold_pipeline/outputs/ 아래에 저장한다.
"""

__version__ = "0.1.0"
PACKAGE_NAME = "synthetic_gold_pipeline"
