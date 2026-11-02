"""공용 문자열 함수 (구 view_model/config.py 에서 분리. 내용은 그대로)"""
import re


def safe(name):
    # 폴더/파일명에 쓸 수 없는 문자 치환 (kosis_rag_builder 가 raw 폴더를 만들 때 쓴 규칙과 같아야 경로가 맞음)
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name)).strip("_")[:80]


def sql_str(s):
    # SQL 문자열 리터럴 (작은따옴표 이스케이프)
    return "'" + str(s).replace("'", "''") + "'"


def norm_space(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()
