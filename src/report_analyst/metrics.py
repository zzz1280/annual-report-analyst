"""财务指标：LLM 只负责从原文"读数"，所有计算在本地确定性完成——可审计、可单测。"""

from __future__ import annotations

from .llm import chat_json

# 标准科目名（LLM 必须用这些 key 返回），后面是年报中可能出现的别名
KEY_ITEMS: dict[str, list[str]] = {
    "营业收入": ["营业总收入"],
    "归属于上市公司股东的净利润": ["归母净利润"],
    "扣除非经常性损益的净利润": ["扣非后净利润", "扣非净利润"],
    "经营活动产生的现金流量净额": [],
    "总资产": ["资产总计"],
    "归属于上市公司股东的净资产": ["归母净资产"],
    "总负债": ["负债合计"],
}

EXTRACT_PROMPT = """下面是某上市公司年报中"主要会计数据"相关页面的原文（含表格）。
请抽取以下科目的本期（本年度）与上期数值，统一换算成"元"：

{items}

规则：
1. 只输出 JSON，key 必须使用上面的标准科目名，结构：
   {{"科目名": {{"current": 数值, "prior": 数值, "page": 页码}}}}
2. 数值一律换算为元（原文单位为万元/亿元时乘以对应倍数），以数字类型输出，不要字符串。
3. 原文中找不到的科目直接省略，禁止估算或编造。
4. page 为该科目数值所在页码（原文方括号中标注）。

== 原文 ==
{material}
"""


def _tables_text(tables: list) -> str:
    return "\n".join(" | ".join(str(c) for c in row) for t in tables for row in t)


def extract_figures(doc: dict) -> dict:
    """定位"主要会计数据"段落，用 LLM 抽取本期/上期数值（单位：元）。"""
    hits = [p for p in doc["pages"] if "主要会计数据" in (p["text"] or "")]
    if not hits:
        raise RuntimeError("未定位到'主要会计数据'章节：请确认 PDF 为文本型（扫描件需先 OCR）。")
    parts = []
    for p in hits[:3]:
        parts.append(f"[第{p['page']}页]\n{p['text']}\n{_tables_text(p.get('tables') or [])}")
    material = "\n\n".join(parts)
    items = "\n".join(f"- {k}（别名：{'、'.join(v) if v else '无'}）" for k, v in KEY_ITEMS.items())
    data = chat_json(
        [{"role": "user", "content": EXTRACT_PROMPT.format(items=items, material=material)}],
        temperature=0.1,
    )
    # 只保留标准科目，防止模型自创 key
    return {k: v for k, v in data.items() if k in KEY_ITEMS}


def _get(figures: dict, item: str, key: str):
    v = (figures.get(item) or {}).get(key)
    return v if isinstance(v, (int, float)) else None


def compute_metrics(figures: dict) -> dict:
    """由科目数值计算衍生指标。

    figures 结构: {"科目名": {"current": 元, "prior": 元, "page": int}}；单位只需内部一致。
    返回: {"指标名": {"value", "formula", "basis", "note"?}}
    """
    out: dict[str, dict] = {}

    def yoy(name: str, item: str) -> None:
        cur, prior = _get(figures, item, "current"), _get(figures, item, "prior")
        if cur is None or not prior:
            return
        out[name] = {"value": (cur - prior) / abs(prior),
                     "formula": f"({item} 本期−上期)/|上期|", "basis": [item]}

    yoy("营业收入同比", "营业收入")
    yoy("归母净利润同比", "归属于上市公司股东的净利润")
    yoy("扣非净利润同比", "扣除非经常性损益的净利润")
    yoy("经营现金流净额同比", "经营活动产生的现金流量净额")

    rev = _get(figures, "营业收入", "current")
    profit = _get(figures, "归属于上市公司股东的净利润", "current")
    if rev and profit is not None:
        out["归母净利率"] = {"value": profit / rev, "formula": "归母净利润/营业收入",
                          "basis": ["归属于上市公司股东的净利润", "营业收入"]}

    ta = _get(figures, "总资产", "current")
    tl = _get(figures, "总负债", "current")
    nav = _get(figures, "归属于上市公司股东的净资产", "current")
    if ta and tl:
        out["资产负债率"] = {"value": tl / ta, "formula": "总负债/总资产",
                         "basis": ["总负债", "总资产"]}
    elif ta and nav is not None:
        out["资产负债率(估算)"] = {"value": (ta - nav) / ta,
                              "formula": "(总资产−归母净资产)/总资产",
                              "basis": ["总资产", "归属于上市公司股东的净资产"],
                              "note": "未抽取到总负债，按归母净资产估算（忽略少数股东权益，结果略偏高）"}

    ocf = _get(figures, "经营活动产生的现金流量净额", "current")
    if ocf is not None and profit:
        out["净现比"] = {"value": ocf / profit,
                      "formula": "经营现金流净额/归母净利润",
                      "basis": ["经营活动产生的现金流量净额", "归属于上市公司股东的净利润"],
                      "note": "长期明显小于 1 提示利润含金量不足"}

    return out
