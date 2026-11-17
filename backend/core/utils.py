"""공용 문자열 함수"""
import re


def safe(name):
    # 폴더·파일 이름에 쓸 수 없는 문자 치환 (collector 가 raw 폴더를 만들 때와 같은 규칙이어야 경로가 맞음)
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name)).strip("_")[:80]


def sql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


def norm_space(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()
