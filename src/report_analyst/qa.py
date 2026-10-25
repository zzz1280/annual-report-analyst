"""带引用的年报问答：检索 → 依据材料作答 → 引用页码与证据页范围 → 数字审计。

两道自愈防线（各至多触发一次，成本可忽略）：
1. 拒答二次重读——首次回答"未找到"时，用 top-2 块的完整文本（不截断）复核一遍；
2. 审计驱动重答——数字审计发现不可溯源数字时，带着告警让模型重答，仅在告警减少时采纳。
"""

from __future__ import annotations

import re

from .index import best_excerpt
from .llm import chat
from .report import audit_numbers

NOT_FOUND = "年报材料中未找到相关依据"

SYSTEM = f"""你是严谨的年报问答助理。
规则：只依据提供的材料回答；每个事实性论断末尾用 (p.页码) 标注来源，
页码格式必须严格形如 (p.5)，禁止写成 (p.第5页) 或 (p.5-6页) 等变体，
页码只能取自材料中标注的页码；材料不足时明确回答"{NOT_FOUND}"，禁止编造。"""


def _ask(material: str, question: str, extra: str = "") -> str:
    user = f"== 年报材料 ==\n{material}\n\n== 问题 ==\n{question}"
    if extra:
        user += f"\n\n{extra}"
    return chat([{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": user}], temperature=0.2)


def _cited(text: str) -> list[int]:
    return sorted({int(p) for p in re.findall(r"p\.(\d+)", text)})


def _flags(audit: dict) -> int:
    return len(audit.get("bad_grouping") or []) + len(audit.get("untraced") or [])


def answer(index, question: str, k: int | None = None) -> dict:
    hits = index.search(question, k=k)
    # 材料截取用"查询相关窗口"而非头部截断，关键数字不会被埋没
    material = "\n\n".join(
        f"[{c['section']}｜第{c['page_start']}-{c['page_end']}页]\n{best_excerpt(c['text'], question, 800)}"
        for c in hits)
    text = _ask(material, question)
    refusal_retry = audit_retry = False

    # 防线一：拒答二次重读（top-2 块完整文本，不截断）
    if NOT_FOUND in text:
        full_material = "\n\n".join(f"[第{c['page_start']}页｜完整材料]\n{c['text']}"
                                    for c in hits[:2])
        retry = _ask(full_material, question,
                     "首次未定位到依据。请逐字仔细复核以上完整材料（未做任何截断）后再下结论。")
        if NOT_FOUND not in retry:
            text, refusal_retry = retry, True

    evidence = {p for c in hits for p in range(c["page_start"], c["page_end"] + 1)}
    audit = audit_numbers(text, [c["text"] for c in hits])

    # 防线二：审计驱动重答（仅在告警减少时采纳修正稿）
    if _flags(audit):
        flagged = "、".join((audit.get("bad_grouping") or []) + (audit.get("untraced") or []))
        revise = _ask(material, question,
                      f"你先前的回答包含材料中无法溯源的数字：{flagged}。请重新核对材料后回答："
                      f"数字必须逐字符复制自材料；若材料确实没有，回答\"{NOT_FOUND}\"。")
        audit2 = audit_numbers(revise, [c["text"] for c in hits])
        if _flags(audit2) < _flags(audit):
            text, audit, audit_retry = revise, audit2, True

    return {"answer": text, "cited_pages": _cited(text), "evidence_pages": sorted(evidence),
            "number_audit": audit, "refusal_retry": refusal_retry, "audit_retry": audit_retry}
