"""대규모 실행 인프라: 샤딩 · 재개 · ID 파일 (HCX 없음)"""
import gzip
import json

import pytest

from eval.generator import trace, v2

IDS = [f"G{n:04d}-{r}" for n in range(1, 497) for r in "VAH"]          # generator_eval1484 와 같은 모양(짝 496 × V · A · H)


@pytest.mark.parametrize("n", [1, 2, 4, 6])
def test_shards_partition_ids(n):
    parts = [{i for i in IDS if v2.shard_of(i, n) == k} for k in range(n)]
    assert sum(len(p) for p in parts) == len(IDS) and set().union(*parts) == set(IDS)
    sizes = [len(p) for p in parts]
    assert max(sizes) - min(sizes) <= 0.2 * len(IDS) / n                # 균등 (편차 20% 이내: 해시 분포의 정상 범위)


def test_slow_cases_are_spread_over_shards():
    """H(느린 문항)가 한 샤드에 몰리지 않는다"""
    h = [i for i in IDS if i.endswith("-H")]
    cnt = [sum(v2.shard_of(i, 4) == k for i in h) for k in range(4)]
    assert min(cnt) > 0.6 * len(h) / 4


def test_shard_is_stable():
    assert v2.shard_of("G0235-H", 4) == v2.shard_of("G0235-H", 4) == 0 or v2.shard_of("G0235-H", 4) in (1, 2, 3)
    assert [v2.shard_of(i, 4) for i in IDS[:5]] == [v2.shard_of(i, 4) for i in IDS[:5]]


@pytest.mark.parametrize("arg,want", [("1/4", (0, 4)), ("4/4", (3, 4)), (None, None), ("", None)])
def test_parse_shard(arg, want):
    assert v2.parse_shard(arg) == want


@pytest.mark.parametrize("arg", ["0/4", "5/4", "a/b", "3"])
def test_parse_shard_rejects(arg):
    with pytest.raises(v2.DatasetError):
        v2.parse_shard(arg)


def test_read_ids(tmp_path):
    p = tmp_path / "ids.txt"
    p.write_text("G0001-V\n\n# 주석\nG0002-A  # 뒤 주석\n", encoding="utf-8")
    assert v2.read_ids(p) == {"G0001-V", "G0002-A"}


def _rows(n, start=0):
    return [json.dumps({"id": f"X{i}", "run": 1, "ok": True}, ensure_ascii=False) for i in range(start, start + n)]


def _killed_gz(path, lines):
    """프로세스가 죽은 상태: 줄마다 flush 했지만 gzip 이 닫히지 않았다"""
    f = gzip.open(path.with_name("live.gz"), "wt", encoding="utf-8")
    for x in lines:
        f.write(x + "\n")
        f.flush()
    data = path.with_name("live.gz").read_bytes()
    f.close()
    path.write_bytes(data)


def test_done_keys_reads_unterminated_gzip(tmp_path):
    p = tmp_path / "runs.jsonl.gz"
    _killed_gz(p, _rows(5))
    with pytest.raises(EOFError):
        gzip.open(p, "rt").read()                                        # 평범한 읽기는 실패한다 (전제)
    assert v2.done_keys(p) == {(f"X{i}", 1) for i in range(5)}


def test_salvage_rewrites_valid_gzip_and_append_is_safe(tmp_path):
    p = tmp_path / "runs.jsonl.gz"
    _killed_gz(p, _rows(3))
    assert v2.salvage(p) == 3
    with gzip.open(p, "at", encoding="utf-8") as f:                      # 재개: 이어 쓴다
        for x in _rows(2, start=3):
            f.write(x + "\n")
    assert [r["id"] for r in trace.load(p)] == [f"X{i}" for i in range(5)]


def test_done_keys_missing_file(tmp_path):
    assert v2.done_keys(tmp_path / "none.gz") == set() and v2.salvage(tmp_path / "none.gz") == 0


def test_concatenated_shards_load_as_one(tmp_path):
    """샤드별 gz 를 cat 으로 합친 파일을 평가기가 한 파일로 읽는다"""
    parts = []
    for k in range(3):
        p = tmp_path / f"s{k}.gz"
        with gzip.open(p, "wt", encoding="utf-8") as f:
            for x in _rows(2, start=k * 2):
                f.write(x + "\n")
        parts.append(p.read_bytes())
    merged = tmp_path / "merged.jsonl.gz"
    merged.write_bytes(b"".join(parts))
    assert [r["id"] for r in trace.load(merged)] == [f"X{i}" for i in range(6)]
