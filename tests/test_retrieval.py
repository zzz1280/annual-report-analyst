"""嵌入后端一致性与本地后端的测试。"""

import pytest

from report_analyst.index import HybridIndex


def _idx_with_vectors() -> HybridIndex:
    idx = HybridIndex([{"chunk_id": 0, "text": "营业收入 147,693,604,994.14 元",
                        "section": "主要会计数据", "page_start": 5, "page_end": 5}])
    idx.vectors = [[0.1, 0.2, 0.3]]
    idx.embedding_meta = {"backend": "fake", "model": "m1"}
    return idx


def test_backend_mismatch_raises(monkeypatch):
    idx = _idx_with_vectors()

    class OtherBackend:
        meta = {"backend": "fake", "model": "m2"}

        def embed(self, texts):
            return [[0.1, 0.2, 0.3]]

    import report_analyst.embeddings as emb
    monkeypatch.setattr(emb, "get_backend", lambda: OtherBackend())
    with pytest.raises(RuntimeError, match="不一致"):
        idx.search("营业收入", k=1)


def test_backend_match_searches(monkeypatch):
    idx = _idx_with_vectors()

    class SameBackend:
        meta = {"backend": "fake", "model": "m1"}

        def embed(self, texts):
            return [[0.1, 0.2, 0.3]]

    import report_analyst.embeddings as emb
    monkeypatch.setattr(emb, "get_backend", lambda: SameBackend())
    assert idx.search("营业收入", k=1)[0]["chunk_id"] == 0


def test_sparse_fallback_still_works_without_vectors():
    idx = HybridIndex([{"chunk_id": 0, "text": "营业收入 147,693,604,994.14 元",
                        "section": "主要会计数据", "page_start": 5, "page_end": 5}])
    assert idx.vectors is None
    hits = idx.search("营业收入", k=1)
    assert hits and hits[0]["chunk_id"] == 0


def test_local_backend_dim():
    pytest.importorskip("fastembed")
    from report_analyst.embeddings import LocalBackend

    be = LocalBackend("BAAI/bge-small-zh-v1.5")
    assert be.meta["backend"] == "local"
    vecs = be.embed(["营业收入", "研发投入"])
    assert len(vecs) == 2 and len(vecs[0]) == 512
