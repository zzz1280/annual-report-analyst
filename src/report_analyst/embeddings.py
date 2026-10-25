"""嵌入后端抽象：API（OpenAI 兼容 /embeddings）或本地 fastembed，两者向量不可混用。

索引会记录生成向量所用的后端标识（embedding_meta），检索时校验一致性——
防止用 A 后端建索引、用 B 后端编码查询导致的静默错误。
本地后端基于 fastembed（ONNX，无 torch、无 API），千级分块 CPU 数十秒可建完索引。
"""

from __future__ import annotations

from .config import settings


# bge 系列支持查询指令前缀；实测在本语料引入回归，默认关闭（机制保留，可按需启用）
QUERY_INSTRUCTIONS = {}


class ApiBackend:
    """OpenAI 兼容 /embeddings 接口（如智谱 embedding-3）。"""

    def __init__(self) -> None:
        self.meta = {"backend": "api", "model": settings.embedding_model}

    def embed(self, texts: list[str]) -> list[list[float]]:
        from .llm import embed  # 延迟导入：本地后端场景无需配置 API key

        return embed(texts)

    def embed_query(self, query: str) -> list[float]:
        return self.embed([query])[0]


class LocalBackend:
    """fastembed 本地推理（如 BAAI/bge-small-zh-v1.5，512 维）。"""

    def __init__(self, model: str) -> None:
        self.meta = {"backend": "local", "model": model}
        self._model = model
        self._instance = None

    def _get(self):
        if self._instance is None:
            from fastembed import TextEmbedding

            self._instance = TextEmbedding(self._model)
        return self._instance

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._get().embed(texts)]

    def _query_text(self, query: str) -> str:
        return QUERY_INSTRUCTIONS.get(self._model, "") + query

    def embed_query(self, query: str) -> list[float]:
        return [v.tolist() for v in self._get().embed([self._query_text(query)])][0]


def get_backend() -> ApiBackend | LocalBackend:
    """按配置选择后端：LLM_EMBEDDING_BACKEND=auto|api|local（缺省 auto：装了 fastembed 用本地）。"""
    choice = settings.embedding_backend
    if choice in ("auto", "local"):
        try:
            import fastembed  # noqa: F401
        except ImportError:
            if choice == "local":
                raise RuntimeError("本地嵌入未安装：pip install '.[local-embedding]'")
        else:
            return LocalBackend(settings.local_embedding_model)
    return ApiBackend()
