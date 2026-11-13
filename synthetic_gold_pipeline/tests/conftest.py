"""공용 fixture: 가상 KOSIS 데이터 → MetadataIndex → CompatibilityGraph (모듈마다 한 번)."""
from __future__ import annotations

import pytest

from synthetic_gold_pipeline.demo_data import build_demo_dataset
from synthetic_gold_pipeline.sampler.compatibility_graph import CompatibilityGraph
from synthetic_gold_pipeline.sampler.metadata_index import MetadataIndex
from synthetic_gold_pipeline.utils import load_config


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def demo_env(tmp_path_factory, cfg):
    root = tmp_path_factory.mktemp("sgp")
    build_demo_dataset(root / "kosis")
    index = MetadataIndex.build(root / "kosis", root / "generated_views", root, cfg)
    graph = CompatibilityGraph(index, cfg["compatibility"])
    return {"root": root, "index": index, "graph": graph, "cfg": cfg}


def find_view(index, table, item, period, split=None, mode="GENERATED_FROM_RAW"):
    for v in index.views.values():
        if (v.parent_table_id == table and v.source_coordinates.itm_ids == [item] and v.available_periods == [period]
                and v.input_mode.value == mode and (split is None or v.source_coordinates.dim_filters == split)):
            return v.view_id
    raise KeyError((table, item, period, split))
