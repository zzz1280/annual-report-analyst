"""从已解析年报自动出题，构建 QA 评测集（LLM 辅助出题 + 人工复核）。

用法:
    python scripts/build_eval.py <pdf_stem> --n 30

输出:
    data/eval/qa_<pdf_stem>.jsonl（每行一条，reviewed=false；人工核对后改为 true）
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from report_analyst.config import settings  # noqa: E402
from report_analyst.index import HybridIndex, chunk_doc  # noqa: E402
from report_analyst.llm import chat_json  # noqa: E402
from report_analyst.parse import load_doc  # noqa: E402

QUIZ_PROMPT = """你是年报评测集出题人。基于以下年报片段出一道"有唯一明确答案"的问题（优先数字题）。
要求：问题自包含（不依赖本片段以外的上下文）；答案能从片段中直接找到。
只输出 JSON：{{"question": "...", "reference_answer": "...", "evidence_page": 页码, "type": "数字/事实"}}
片段不包含可出题的实质信息时输出 {{"skip": true}}。

[片段｜第{page_start}-{page_end}页]
{chunk}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem", help="已解析年报的文件名去后缀，如 600519_2023")
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()

    d = settings.parsed_dir / args.stem
    doc = load_doc(d)
    index = HybridIndex.load(d) or HybridIndex(chunk_doc(doc))
    chunks = [c for c in index.chunks if len(c["text"]) > 200 and c["section"] != "封面"]
    step = max(1, len(chunks) // args.n)
    sampled = chunks[::step][: args.n]

    out_path = settings.eval_dir / f"qa_{args.stem}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    with out_path.open("w", encoding="utf-8") as f:
        for c in sampled:
            try:
                item = chat_json([{"role": "user", "content": QUIZ_PROMPT.format(
                    chunk=c["text"][:1200], page_start=c["page_start"], page_end=c["page_end"])}])
            except Exception as exc:
                print(f"skip chunk {c['chunk_id']}: {exc}")
                continue
            if not item or item.get("skip"):
                continue
            record = {"id": f"{args.stem}-{n_ok:03d}",
                      "question": item["question"],
                      "reference_answer": item["reference_answer"],
                      "evidence_page": item.get("evidence_page"),
                      "type": item.get("type", ""),
                      "source_chunk": c["chunk_id"],
                      "reviewed": False}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_ok += 1
            print(f"[{n_ok}] {item['question'][:50]}")
    print(f"✅ 共 {n_ok} 题 → {out_path}\n⚠️ 请人工复核后将 reviewed 改为 true，run_eval 默认只跑复核过的题。")


if __name__ == "__main__":
    main()
