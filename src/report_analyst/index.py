"""结构感知分块与混合检索（向量 + 字符 bigram 关键词），带本地持久化。"""

from __future__ import annotations

import gzip
import json
import math
import re
from pathlib import Path

from .config import settings

# 年报章节标题，如 "第三节 管理层讨论与分析"、"一、主营业务分析"
_HEADING = re.compile(r"^\s*(第[一二三四五六七八九十百零]+节|[（(]?[一二三四五六七八九十]+[)）、])\s*\S+")
_TOKEN_OK = re.compile(r"[\w\u4e00-\u9fff]")
_PAGE_NO = re.compile(r"^\d{1,4}\s*/\s*\d{1,4}$")  # "30 / 143" 式页码
# 四大报表标题：表格分块必须知道自己属于哪张报表，否则"资产总计"无法区分合并/母公司口径
_STATEMENT = re.compile(r"^(合并|母公司)?(资产负债表|利润表|现金流量表|所有者权益变动表)\s*$")


def _bigrams(text: str) -> set[str]:
    """字符 bigram 集合——中文关键词匹配比按词分词更鲁棒（查询与原文用词常有差异）。"""
    chars = [c for c in text if _TOKEN_OK.search(c)]
    return {a + b for a, b in zip(chars, chars[1:])}


def _detect_furniture(pages: list[dict]) -> set[str]:
    """识别每页重复出现的页眉/页脚版面杂讯（如"2023年年度报告"、"公司简称"行）。

    出现在 30% 以上页面且长度 <=20 字的行视为杂讯——它们会稀释关键词检索的命中率。
    """
    from collections import Counter

    counter: Counter = Counter()
    for p in pages:
        lines = {(l or "").strip() for l in (p["text"] or "").splitlines() if l.strip()}
        counter.update(lines)
    threshold = max(3, int(0.3 * len(pages)))
    return {line for line, cnt in counter.items() if cnt >= threshold and len(line) <= 20}


TABLE_CHUNK_MAX = 1200


def _table_pieces(section: str, tbl: list[list[str]], max_chars: int = TABLE_CHUNK_MAX) -> list[str]:
    """表格转文本块：超长表格按行分组切成多块，首行（表头）随每块重复，
    避免关键行在下游截断中被埋没。"""
    prefix = f"[{section[:40]}] "
    rows = [" | ".join(str(c).strip() for c in row) for row in tbl]
    header = rows[0] if len(rows) > 2 else None
    body = rows[1:] if header else rows
    head_len = len(prefix) + (len(header) + 1 if header else 0)
    pieces: list[list[str]] = []
    cur: list[str] = []
    cur_len = head_len
    for r in body:
        if cur and cur_len + len(r) + 1 > max_chars:
            pieces.append(cur)
            cur, cur_len = [], head_len
        cur.append(r)
        cur_len += len(r) + 1
    if cur:
        pieces.append(cur)
    return [prefix + ((header + "\n") if header else "") + "\n".join(p) for p in pieces]


# 报表口径：加权幅度由 settings.scope_adjust 控制（默认 0=关闭，实测无可测收益）
_SCOPE_PARENT = ("母公司", "本行", "本公司")
_SCOPE_CONSOL = ("合并", "本集团", "集团")


def _query_scope(query: str) -> str | None:
    if any(k in query for k in _SCOPE_PARENT):
        return "母公司"
    if any(k in query for k in _SCOPE_CONSOL):
        return "合并"
    return None


def _chunk_scope(chunk: dict) -> str | None:
    """从分块的章节名/表格前缀推断口径；仅看头部，避免正文里"本行"等词的噪声。"""
    for s in (str(chunk.get("section", "")), str(chunk.get("text", ""))[:24]):
        if "母公司" in s:
            return "母公司"
        if "合并" in s:
            return "合并"
    return None


def best_excerpt(text: str, query: str, max_chars: int = 800) -> str:
    """超长分块的截取策略：取与查询 bigram 命中最密集的窗口，替代盲目的头部截断——
    关键数字常在分块中后段，头部截断会把它们埋掉。"""
    if len(text) <= max_chars:
        return text
    hits: list[int] = []
    for bg in _bigrams(query):
        pos = text.find(bg)
        while pos != -1 and len(hits) < 800:
            hits.append(pos)
            pos = text.find(bg, pos + 1)
    if not hits:
        return text[:max_chars] + "…"
    hits.sort()
    lo = 0
    best_cnt, best_start = 0, hits[0]
    for hi in range(len(hits)):
        while hits[hi] - hits[lo] > max_chars:
            lo += 1
        if hi - lo + 1 > best_cnt:
            best_cnt, best_start = hi - lo + 1, hits[lo]
    start = max(0, best_start - 120)
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + max_chars < len(text) else ""
    return f"{prefix}{text[start:start + max_chars]}{suffix}"


def chunk_doc(doc: dict, target_chars: int = 900) -> list[dict]:
    """按章节标题 + 段落分块（保留页码）；表格单独成块，避免被正文稀释。"""
    chunks: list[dict] = []
    section = "封面"
    buf: list[str] = []
    pages: list[int] = []

    def flush() -> None:
        nonlocal buf, pages
        text = "\n".join(buf).strip()
        if text:
            chunks.append({
                "chunk_id": len(chunks),
                "text": text,
                "section": section[:40],
                "page_start": min(pages),
                "page_end": max(pages),
            })
        buf, pages = [], []

    furniture = _detect_furniture(doc["pages"])
    for page in doc["pages"]:
        for line in (page["text"] or "").splitlines():
            line = line.strip()
            if not line or line in furniture or _PAGE_NO.match(line):
                continue
            if (_HEADING.match(line) or _STATEMENT.match(line)) and len(line) <= 30:
                flush()
                section = line
            buf.append(line)
            pages.append(page["page"])
            if sum(map(len, buf)) >= target_chars:
                flush()
        for tbl in page.get("tables") or []:
            if len(tbl) < 2:  # 单行"表格"多为版面切分残留
                continue
            flush()
            # 表格分块带上所属章节前缀（如 [母公司资产负债表]）保留归属上下文；
            # 超长表格按行分组切块，避免关键行在下游截断中被埋没
            for piece in _table_pieces(section, tbl):
                chunks.append({
                    "chunk_id": len(chunks),
                    "text": piece,
                    "section": section[:40],
                    "page_start": page["page"],
                    "page_end": page["page"],
                })
    flush()
    return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


class HybridIndex:
    """混合检索：语义向量 + 关键词重叠线性加权。千级分块内纯 Python 即可，无需向量库。"""

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.vectors: list[list[float]] | None = None
        self.embedding_meta: dict | None = None
        self._tokens = [_bigrams(c["text"]) for c in chunks]
        # bigram 文档频率 → idf 权重：稀有词（如"派息"）比套话（如"是什么"）更有区分度
        from collections import Counter

        df: Counter = Counter()
        for toks in self._tokens:
            df.update(toks)
        n = max(len(chunks), 1)
        default_idf = math.log(1 + n)
        self._idf = {t: math.log(1 + n / (1 + d)) for t, d in df.items()}
        self._default_idf = default_idf

    def _sparse_scores(self, q_tokens: set[str]) -> list[float]:
        idf = self._idf
        total = sum(idf.get(t, self._default_idf) for t in q_tokens) or 1.0
        return [sum(idf.get(t, self._default_idf) for t in q_tokens if t in toks) / total
                for toks in self._tokens]

    # ---------- 持久化 ----------

    def save(self, out_dir: Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        data = {"chunks": self.chunks,
                "vectors": [[round(x, 6) for x in v] for v in self.vectors] if self.vectors else None,
                "embedding_meta": self.embedding_meta}
        path = out_dir / "index.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, out_dir: Path) -> "HybridIndex | None":
        path = Path(out_dir) / "index.json.gz"
        if not path.exists():
            return None
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        obj = cls(data["chunks"])
        obj.vectors = data.get("vectors") or None
        obj.embedding_meta = data.get("embedding_meta")
        return obj

    # ---------- 检索 ----------

    def build(self, backend=None) -> None:
        if not self.chunks:
            raise ValueError("没有可索引的分块，请检查解析结果。")
        if backend is None:
            from .embeddings import get_backend

            backend = get_backend()
        self.embedding_meta = backend.meta
        self.vectors = backend.embed([c["text"] for c in self.chunks])

    def search(self, query: str, k: int | None = None) -> list[dict]:
        k = k or settings.retrieve_k
        q_tokens = _bigrams(query)
        sparse = self._sparse_scores(q_tokens)
        if self.vectors:
            # 混合检索：RRF 倒数排名融合（语义 + 关键词两个排序器话语权均衡），
            # 后端必须与建索引时一致
            from .embeddings import get_backend

            backend = get_backend()
            if self.embedding_meta and backend.meta != self.embedding_meta:
                raise RuntimeError(
                    f"嵌入后端与索引不一致：索引由 {self.embedding_meta} 构建，当前为 {backend.meta}。"
                    "请重建索引：python -m report_analyst parse <pdf>")
            qv = backend.embed_query(query)
            n = len(self.chunks)
            w = settings.dense_weight
            scores = [w * _cosine(qv, self.vectors[i]) + (1 - w) * sparse[i] for i in range(n)]
            # 报表口径：仅在查询显式指明"母公司/合并/本行"且幅度非零时调整
            if settings.scope_adjust:
                scope = _query_scope(query)
                if scope:
                    for i in range(n):
                        cs = _chunk_scope(self.chunks[i])
                        if cs:
                            scores[i] += settings.scope_adjust if cs == scope else -settings.scope_adjust
        else:
            # 未构建向量（无 embedding）时退化为纯关键词检索：零成本本地可用
            scores = sparse
        order = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)[:k]
        return [dict(self.chunks[i], score=round(scores[i], 4)) for i in order]
