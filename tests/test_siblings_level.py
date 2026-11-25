from types import SimpleNamespace

import pytest

from backend.rag.search.siblings import build_groups, core_title, table_level


@pytest.mark.parametrize("level", ["전국", "시도", "시군구", "읍면동"])
def test_slash_suffix_sets_table_level(level):
    facet = SimpleNamespace(tbl_nm=f"성 및 연령별 추계인구 / {level}", geo={"시군구"})

    assert table_level(facet) == level


def test_slash_and_dash_editions_share_a_sibling_group():
    title = "성 및 연령별 추계인구(1세별, 5세별)"
    facets = {
        "national": SimpleNamespace(survey_nm="장래인구추계", tbl_nm=f"{title} / 전국"),
        "province": SimpleNamespace(survey_nm="장래인구추계", tbl_nm=f"{title}/시도"),
        "district": SimpleNamespace(survey_nm="장래인구추계", tbl_nm=f"{title}-시군구"),
        "other_survey": SimpleNamespace(survey_nm="다른 조사", tbl_nm=f"{title}/시도"),
    }

    membership, groups = build_groups(facets)

    assert list(groups.values()) == [["district", "national", "province"]]
    assert set(membership) == {"district", "national", "province"}


@pytest.mark.parametrize("title", ["추계인구/시도(행정구역)/성별", "추계인구/시도(행정구역)/연령(각세)"])
def test_slash_level_in_the_middle_is_not_a_suffix(title):
    facet = SimpleNamespace(tbl_nm=title, geo={"읍면동"})

    assert table_level(facet) == "읍면동"
    assert core_title(title) != core_title("추계인구")


def test_slash_suffix_allows_a_trailing_note():
    facet = SimpleNamespace(tbl_nm="추계인구 / 시도(시군구/읍면동), 최근판", geo=set())

    assert table_level(facet) == "시도"
    assert core_title(facet.tbl_nm) == core_title("추계인구")
