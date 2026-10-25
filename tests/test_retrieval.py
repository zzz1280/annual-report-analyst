"""嵌入后端一致性、报表口径加权与本地后端的测试。"""

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

        def embed_query(self, query):
            return [0.1, 0.2, 0.3]

    import report_analyst.embeddings as emb
    monkeypatch.setattr(emb, "get_backend", lambda: OtherBackend())
    with pytest.raises(RuntimeError, match="不一致"):
        idx.search("营业收入", k=1)


def test_backend_match_searches(monkeypatch):
    idx = _idx_with_vectors()

    class SameBackend:
        meta = {"backend": "fake", "model": "m1"}

        def embed_query(self, query):
            return [0.1, 0.2, 0.3]

    import report_analyst.embeddings as emb
    monkeypatch.setattr(emb, "get_backend", lambda: SameBackend())
    assert idx.search("营业收入", k=1)[0]["chunk_id"] == 0


def test_sparse_fallback_still_works_without_vectors():
    idx = HybridIndex([{"chunk_id": 0, "text": "营业收入 147,693,604,994.14 元",
                        "section": "主要会计数据", "page_start": 5, "page_end": 5}])
    assert idx.vectors is None
    hits = idx.search("营业收入", k=1)
    assert hits and hits[0]["chunk_id"] == 0


def test_query_scope_detection():
    from report_analyst.index import _query_scope

    assert _query_scope("母公司资产负债表中，资产总计是多少") == "母公司"
    assert _query_scope("本行发行债券的金额是多少") == "母公司"
    assert _query_scope("合并现金流量表中支付给职工的现金") == "合并"
    assert _query_scope("营业收入是多少") is None  # 未指明时不做口径加权，由生成端默认合并口径


def test_chunk_scope_detection():
    from report_analyst.index import _chunk_scope

    assert _chunk_scope({"section": "母公司资产负债表", "text": "项目 | 金额"}) == "母公司"
    assert _chunk_scope({"section": "表格", "text": "[合并现金流量表] 项目 | 金额"}) == "合并"
    assert _chunk_scope({"section": "重要会计政策", "text": "正文内容"}) is None


def test_scope_adjusts_ranking(monkeypatch):
    """口径加权（默认关闭，显式开启后生效）：指明"母公司"时母公司块排前；未指明不干预。"""
    from report_analyst.config import settings

    chunks = [
        {"chunk_id": 0, "text": "[合并资产负债表] 资产总计 | 100", "section": "合并资产负债表",
         "page_start": 1, "page_end": 1},
        {"chunk_id": 1, "text": "[母公司资产负债表] 资产总计 | 50", "section": "母公司资产负债表",
         "page_start": 2, "page_end": 2},
    ]
    idx = HybridIndex(chunks)
    idx.vectors = [[1.0, 0.0], [0.0, 1.0]]
    idx.embedding_meta = {"backend": "fake", "model": "m"}

    class FakeBackend:
        meta = {"backend": "fake", "model": "m"}

        def embed_query(self, query):
            return [0.6, 0.4] if "合并" in query else [0.2, 0.8]  # 语义默认偏好母公司块

    import report_analyst.embeddings as emb
    monkeypatch.setattr(emb, "get_backend", lambda: FakeBackend())

    # 默认关闭：即使查询指明"母公司"，语义偏好不受加权干扰
    assert idx.search("母公司资产负债表中资产总计", k=2)[0]["chunk_id"] == 1
    # 显式开启后：加权足以翻转语义偏好（合并查询 → 合并块排前）
    monkeypatch.setattr(settings, "scope_adjust", 0.15)
    assert idx.search("合并口径下的资产总计", k=2)[0]["chunk_id"] == 0


def test_bge_query_instruction_prefix():
    """前缀机制默认关闭（实测在本语料引入回归）；登记条目后即启用。"""
    from report_analyst.embeddings import QUERY_INSTRUCTIONS, LocalBackend

    be = LocalBackend("BAAI/bge-small-zh-v1.5")
    assert be._query_text("营业收入") == "营业收入"  # 默认无前缀
    QUERY_INSTRUCTIONS["BAAI/bge-small-zh-v1.5"] = "为这个句子生成表示以用于检索相关文章："
    try:
        assert be._query_text("营业收入").startswith("为这个句子")
    finally:
        del QUERY_INSTRUCTIONS["BAAI/bge-small-zh-v1.5"]
    unknown = LocalBackend("unknown/model")
    assert unknown._query_text("营业收入") == "营业收入"


def test_local_backend_dim():
    pytest.importorskip("fastembed")
    from report_analyst.embeddings import LocalBackend

    be = LocalBackend("BAAI/bge-small-zh-v1.5")
    assert be.meta["backend"] == "local"
    vecs = be.embed(["营业收入", "研发投入"])
    assert len(vecs) == 2 and len(vecs[0]) == 512
