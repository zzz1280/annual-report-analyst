"""风险章节扫描：抽取结构化风险条目（含页码证据）。"""

from __future__ import annotations

from .llm import chat_json

_HINTS = ("可能面对的风险", "公司面临的主要风险", "风险因素", "风险管理")
# 只有当"风险"以标题形式出现时才是真章节；正文顺带提及"风险管理"的页是噪声
_HEADING_HINTS = ("可能面对的风险", "风险因素", "重大风险提示")

RISK_PROMPT = """以下是年报中与风险相关的页面原文。请抽取具体的风险条目（不要泛泛的套话）。
只输出 JSON 数组，每条格式：
{{"risk": "风险名称", "category": "经营/财务/行业/政策/其他", "evidence": "原文关键句(<=60字)", "page": 页码}}

最多 8 条；没有实质风险内容则输出 []。

== 原文 ==
{material}
"""


def _has_risk_heading(page: dict) -> bool:
    return any(h in line for line in (page["text"] or "").splitlines()
               if len(line.strip()) <= 20 for h in _HEADING_HINTS)


def extract_risks(doc: dict, max_pages: int = 6) -> list[dict]:
    pages = [p for p in doc["pages"] if _has_risk_heading(p)]
    if not pages:  # 无明确标题页时退回全文匹配
        pages = [p for p in doc["pages"] if any(h in (p["text"] or "") for h in _HINTS)]
    if not pages:
        return []
    parts = [f"[第{p['page']}页]\n{(p['text'] or '')[:1500]}" for p in pages[:max_pages]]
    data = chat_json(
        [{"role": "user", "content": RISK_PROMPT.format(material="\n\n".join(parts))}],
        temperature=0.2,
    )
    return [r for r in data if isinstance(r, dict) and r.get("risk")]
