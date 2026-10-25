"""生成带页码引用的分析报告，并做引用审计。"""

from __future__ import annotations

import json
import re

from .llm import chat

CITE_RULE = """硬性规则：
1. 所有数字只能来自给定的 JSON 或年报材料原文，禁止编造。
2. 每个事实性论断末尾用 (p.页码) 标注来源，页码只能取自材料中 [第N页] 的 N。
3. 材料不足处写"年报中未找到相关依据"，不要猜测。
4. 正文中金额用亿元/万元并保留两位小数（如 1,476.94 亿元），禁止逐位抄写全精度数字；
   百分比写成 +19.01% 形式，比率保留两位小数。"""

_NUM = re.compile(r"\d[\d,，]*(?:\.\d+)?")
_GROUPING = re.compile(r"^\d{1,3}(,\d{3})*(?:\.\d+)?$")


def audit_numbers(report_md: str, sources: list[str]) -> dict:
    """数字审计：报告中每个数字都应能在来源中溯源（允许亿元/万元换算与四舍五入）。

    含千分位的数字必须分组合法——用于捕获 LLM 抄错数字
    （如把 74,734,071,550.75 抄成 747,340,71550.75：数字相同但逗号错位）。
    """
    text = re.sub(r"\(p\.\d+\)", "", report_md)  # 引用页码不参与审计
    values: set[float] = set()
    for src in sources:
        for t in _NUM.findall(src):
            try:
                values.add(float(t.replace("，", "").replace(",", "")))
            except ValueError:
                pass
    bad_grouping: list[str] = []
    untraced: list[str] = []
    seen: set[str] = set()
    for t in _NUM.findall(text):
        if t in seen:
            continue
        seen.add(t)
        if ("," in t or "，" in t) and not _GROUPING.match(t):
            bad_grouping.append(t)
            continue
        try:
            val = float(t.replace("，", "").replace(",", ""))
        except ValueError:
            continue
        traceable = val in values or any(
            abs(val * k - s) <= max(abs(s) * 0.005, 0.005)
            for s in values for k in (1, 1e4, 1e8, 1e12, 0.01))
        if not traceable:
            untraced.append(t)
    return {"n_numbers": len(seen), "bad_grouping": bad_grouping, "untraced": untraced}


def _fmt(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def generate_report(doc: dict, index, figures: dict, metrics: dict, risks: list[dict]) -> str:
    hits = index.search("主营业务 经营模式 行业格局 报告期经营情况讨论", k=6)
    material = "\n\n".join(
        f"[第{c['page_start']}-{c['page_end']}页｜{c['section']}]\n{c['text'][:700]}" for c in hits)

    blocks = [
        ("一、公司概览", "概述公司主营业务、经营模式与报告期整体表现（150-300 字）。"),
        ("二、财务表现", "基于 figures 与 metrics JSON 分析：成长性（各项同比）、盈利质量"
                    "（归母净利率、净现比）、偿债压力（资产负债率）。数字必须与 JSON 完全一致，并解释指标含义。"),
        ("三、风险提示", "逐条展开 risks JSON 中的风险，引用其 evidence 与页码，并简述可能影响。"),
    ]

    parts = [f"# {doc['source']} 年报分析报告",
             "> AI 生成，供学习研究使用，不构成投资建议。所有数字来自年报原文并附页码引用。\n"]
    for title, task in blocks:
        prompt = (f"{task}\n\n{CITE_RULE}\n\n"
                  f"== figures JSON ==\n{_fmt(figures)}\n\n"
                  f"== metrics JSON ==\n{_fmt(metrics)}\n\n"
                  f"== risks JSON ==\n{_fmt(risks)}\n\n"
                  f"== 年报材料 ==\n{material}\n\n"
                  f"只输出本小节的 markdown 正文。")
        parts.append(f"## {title}\n")
        parts.append(chat([{"role": "user", "content": prompt}], temperature=0.3))
    return "\n\n".join(parts)


def audit_citations(report_md: str, n_pages: int) -> dict:
    """统计报告中 (p.N) 引用，并找出超出页码范围的无效引用。"""
    pages = [int(p) for p in re.findall(r"\(p\.(\d+)\)", report_md)]
    invalid = sorted({p for p in pages if not (1 <= p <= n_pages)})
    return {"n_citations": len(pages), "invalid_pages": invalid}
