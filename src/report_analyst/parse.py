"""年报 PDF 解析：逐页提取文本与表格，落盘为 JSON 中间产物。

扫描件（无文本层的 PDF）无法提取文本，需先 OCR（Roadmap：PaddleOCR 预处理）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pdfplumber

from .config import settings


def parse_pdf(pdf_path: Path) -> Path:
    """解析 PDF，返回解析产物目录下的 doc.json 路径（data/parsed/<stem>/doc.json）。"""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    out_dir = settings.parsed_dir / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables = [[[cell or "" for cell in (row or [])] for row in tbl]
                      for tbl in (page.extract_tables() or [])]
            pages.append({"page": i, "text": text, "tables": tables})

    doc = {"source": pdf_path.name, "n_pages": len(pages), "pages": pages}
    out = out_dir / "doc.json"
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return out


def load_doc(parsed_dir: Path) -> dict:
    parsed_dir = Path(parsed_dir)
    return json.loads((parsed_dir / "doc.json").read_text(encoding="utf-8"))
