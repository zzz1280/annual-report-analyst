"""带引用的年报问答：检索 → 依据材料作答 → 引用页码与证据页范围 → 数字审计。"""

from __future__ import annotations

import re

from .index import best_excerpt
from .llm import chat
from .report import audit_numbers

SYSTEM = """你是严谨的年报问答助理。
规则：只依据提供的材料回答；每个事实性论断末尾用 (p.页码) 标注来源，
页码格式必须严格形如 (p.5)，禁止写成 (p.第5页) 或 (p.5-6页) 等变体，
页码只能取自材料中标注的页码；材料不足时明确回答"年报材料中未找到相关依据"，禁止编造。"""


def answer(index, question: str, k: int | None = None) -> dict:
    hits = index.search(question, k=k)
    # 材料截取用"查询相关窗口"而非头部截断，关键数字不会被埋没
    material = "\n\n".join(
        f"[{c['section']}｜第{c['page_start']}-{c['page_end']}页]\n{best_excerpt(c['text'], question, 800)}"
        for c in hits)
    prompt = f"== 年报材料 ==\n{material}\n\n== 问题 ==\n{question}"
    text = chat([{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": prompt}], temperature=0.2)
    cited = sorted({int(p) for p in re.findall(r"p\.(\d+)", text)})
    evidence = {p for c in hits for p in range(c["page_start"], c["page_end"] + 1)}
    # 数字审计：回答中的每个数字都必须能在检索到的材料中溯源
    audit = audit_numbers(text, [c["text"] for c in hits])
    return {"answer": text, "cited_pages": cited, "evidence_pages": sorted(evidence),
            "number_audit": audit}
