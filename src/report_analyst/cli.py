"""命令行入口：parse / analyze / ask。

示例:
    python -m report_analyst parse data/raw/600519_2023.pdf
    python -m report_analyst analyze data/raw/600519_2023.pdf
    python -m report_analyst ask data/raw/600519_2023.pdf "本期研发投入是多少？"
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import settings
from .index import HybridIndex, chunk_doc
from .metrics import compute_metrics, extract_figures
from .parse import load_doc, parse_pdf
from .qa import answer
from .report import audit_citations, audit_numbers, generate_report
from .risk import extract_risks

app = typer.Typer(add_completion=False,
                  help="AI 年报解读：解析 PDF → 指标计算 → 带引用的分析报告与问答")
console = Console()


def _parsed_dir(pdf_stem: str) -> Path:
    return settings.parsed_dir / pdf_stem


def _load_index(d: Path, doc: dict) -> HybridIndex:
    index = HybridIndex.load(d)
    if index is None:
        console.print("⚙️ 未找到索引，现场构建（调用 embedding 接口）…")
        index = HybridIndex(chunk_doc(doc))
        index.build()
        index.save(d)
    return index


def _fmt_metric(name: str, value: float) -> str:
    if "同比" in name:
        return f"{value:+.2%}"
    if "率" in name:
        return f"{value:.2%}"
    return f"{value:.2f}"


@app.command()
def parse(pdf: Path):
    """解析年报 PDF：逐页提取文本与表格，并构建检索索引。"""
    doc_json = parse_pdf(pdf)
    doc = load_doc(_parsed_dir(pdf.stem))
    console.print(f"📄 解析完成：{doc['n_pages']} 页，开始构建索引…")
    index = HybridIndex(chunk_doc(doc))
    index.build()
    index.save(_parsed_dir(pdf.stem))
    console.print(f"✅ 索引完成：{len(index.chunks)} 个分块 → {_parsed_dir(pdf.stem) / 'index.json.gz'}")
    console.print(f"[dim]{doc_json}[/dim]")


@app.command()
def analyze(pdf: Path):
    """生成带页码引用的分析报告与财务指标。"""
    d = _parsed_dir(pdf.stem)
    doc = load_doc(d)
    index = _load_index(d, doc)

    console.print("🧮 抽取主要会计数据（LLM 读数）…")
    figures = extract_figures(doc)
    metrics = compute_metrics(figures)

    console.print("⚠️ 扫描风险章节…")
    risks = extract_risks(doc)

    console.print("✍️ 生成分析报告…")
    report = generate_report(doc, index, figures, metrics, risks)
    out = settings.data_dir / "reports" / f"{pdf.stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    table = Table(title="核心指标")
    table.add_column("指标")
    table.add_column("数值", justify="right")
    table.add_column("口径")
    for name, m in metrics.items():
        table.add_row(name, _fmt_metric(name, m["value"]), m["formula"])
    console.print(table)

    audit = audit_citations(report, doc["n_pages"])
    sources = [json.dumps(figures, ensure_ascii=False), json.dumps(metrics, ensure_ascii=False),
               json.dumps(risks, ensure_ascii=False)] + [p["text"] or "" for p in doc["pages"]]
    nums = audit_numbers(report, sources)
    console.print(Panel(
        f"报告: {out}\n"
        f"引用审计: {audit['n_citations']} 处引用，无效 {len(audit['invalid_pages'])} 处 {audit['invalid_pages'] or ''}\n"
        f"数字审计: {nums['n_numbers']} 个数字，千分位异常 {nums['bad_grouping'] or '无'}，"
        f"不可溯源 {nums['untraced'] or '无'}",
        title="analyze 完成", border_style="green"))


@app.command()
def ask(pdf: Path, question: str):
    """针对年报问答（自动检索并附页码引用）。"""
    d = _parsed_dir(pdf.stem)
    doc = load_doc(d)
    index = _load_index(d, doc)
    result = answer(index, question)
    console.print(Panel(result["answer"], title=f"Q: {question}", border_style="cyan"))
    console.print(f"[dim]引用页: {result['cited_pages'] or '（回答未含引用）'}｜"
                  f"证据页范围: {result['evidence_pages']}[/dim]")


if __name__ == "__main__":
    app()
